"""Background upload queue: the node saves its files and returns at once; uploads run here.

ComfyUI runs one workflow node after another, so an upload done inside the node holds up the
whole queue (a big video can take many minutes). Instead the node adds a job here and the
worker thread uploads it while ComfyUI moves on.

- Jobs are kept in a JSON file next to the credentials, so a restart continues them. Resumable
  uploads (Google Drive sessions, S3/R2 multipart parts, the encrypted copy for vaults) store
  their state in each file's "resume" dict and pick up where they stopped.
- Progress, completion and failures are reported through `notify` (ComfyUI: a websocket event).
- `auth.py uploads --wait` reads the same file to wait until everything is uploaded, e.g. before
  shutting down a rented GPU machine. The worker writes a heartbeat so it can tell when ComfyUI
  is no longer running.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from .config import config_dir
from .errors import explain

logger = logging.getLogger(__name__)

QUEUE_FILE = "uploads.json"
HEARTBEAT_SECONDS = 5.0
STALE_SECONDS = 60.0          # no heartbeat for this long: ComfyUI is not running
KEEP_FINISHED = 50            # finished jobs kept for display
AUTO_RETRIES = 3              # automatic retries for temporary failures
RETRY_DELAYS = (30.0, 120.0, 600.0)
TEMPORARY = {"network", "server_error", "rate_limited"}
NOTIFY_EVERY = 0.5            # seconds between progress events
SAVE_EVERY = 3.0              # seconds between progress writes to the queue file

ACTIVE = ("queued", "running", "waiting")


def queue_path() -> Path:
    return config_dir() / QUEUE_FILE


class ResumeState(dict):
    """A file's resume dict. Providers call save_resume() after changing it."""

    def __init__(self, data: Optional[dict] = None, saver: Optional[Callable[[], None]] = None):
        super().__init__(data or {})
        self._saver = saver

    def save(self) -> None:
        if self._saver:
            self._saver()


def read_queue(path: Optional[Path] = None) -> dict[str, Any]:
    path = path or queue_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault("jobs", [])
    data.setdefault("worker", {})
    return data


def summarize(data: dict[str, Any], now: Optional[float] = None) -> dict[str, Any]:
    """Counts for the CLI and the UI: active / failed / done jobs and remaining bytes."""
    now = time.time() if now is None else now
    jobs = data.get("jobs", [])
    active = [j for j in jobs if j["state"] in ACTIVE]
    remaining = sum(f["size"] - f.get("sent", 0) for j in active for f in j["files"] if f["state"] != "done")
    beat = data.get("worker", {}).get("heartbeat", 0)
    return {"active": len(active), "failed": sum(j["state"] == "failed" for j in jobs),
            "done": sum(j["state"] == "done" for j in jobs), "remaining_bytes": max(remaining, 0),
            "files_left": sum(f["state"] != "done" for j in active for f in j["files"]),
            "worker_alive": bool(beat) and now - beat < STALE_SECONDS}


class UploadQueue:
    def __init__(self, path: Optional[Path] = None, providers: Optional[dict[str, Callable[[], Any]]] = None,
                 notify: Optional[Callable[[dict[str, Any]], None]] = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time,
                 vault_loader: Optional[Callable[[Any], Any]] = None):
        if providers is None:
            from . import PROVIDERS
            providers = PROVIDERS
        if vault_loader is None:
            from .vault import CryptomatorVault
            vault_loader = CryptomatorVault.load
        self.path = path or queue_path()
        self.providers = providers
        self.notify = notify or (lambda event: None)
        self.sleep = sleep
        self.clock = clock
        self.vault_loader = vault_loader
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stopping = False
        self.thread: Optional[threading.Thread] = None
        self.data = read_queue(self.path)
        for job in self.data["jobs"]:  # interrupted by a restart: run again (resume state is kept)
            if job["state"] == "running":
                job["state"] = "queued"
        self._last_save = 0.0
        self._last_notify: dict[str, float] = {}

    # ---- persistence -------------------------------------------------------------------------
    def _save(self) -> None:
        with self.lock:
            self.data["worker"] = {"pid": os.getpid(), "heartbeat": self.clock()}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".uploads.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
                raise
            self._last_save = self.clock()

    # ---- public API --------------------------------------------------------------------------
    def add(self, *, provider: str, provider_label: str, remote_folder: str, encrypt: bool,
            files: list[dict[str, Any]], node_id: Any = None, prompt_id: Any = None,
            pending_dir: Optional[str] = None) -> dict[str, Any]:
        """files: [{"path": local path, "cleanup": delete it after a successful upload}]."""
        job = {
            "id": uuid.uuid4().hex[:12], "created": self.clock(), "state": "queued",
            "provider": provider, "provider_label": provider_label, "remote_folder": remote_folder,
            "encrypt": bool(encrypt), "node_id": None if node_id is None else str(node_id),
            "prompt_id": prompt_id, "pending_dir": pending_dir, "attempts": 0, "next_try": 0, "error": None,
            "files": [{"path": f["path"], "name": os.path.basename(f["path"]),
                       "size": os.path.getsize(f["path"]), "sent": 0, "state": "queued",
                       "cleanup": bool(f.get("cleanup")), "result": None, "resume": {}} for f in files],
        }
        with self.lock:
            self.data["jobs"].append(job)
            self._save()
        self._emit("queued", job, force=True)
        self.wake.set()
        return self.snapshot(job)

    def jobs(self) -> list[dict[str, Any]]:
        with self.lock:
            return [self.snapshot(j) for j in self.data["jobs"]]

    def summary(self) -> dict[str, Any]:
        with self.lock:
            return summarize(self.data, self.clock())

    def retry(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self._job(job_id)
            if job["state"] == "failed":
                job.update(state="queued", attempts=0, next_try=0, error=None)
                for f in job["files"]:
                    if f["state"] == "failed":
                        f["state"] = "queued"
                self._save()
        self._emit("queued", job, force=True)
        self.wake.set()
        return self.snapshot(job)

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Forget a job that is not running; its pending copies are deleted (kept local copies stay)."""
        with self.lock:
            job = self._job(job_id)
            if job["state"] == "running":
                raise ValueError("This upload is running; wait for it to finish or fail")
            self.data["jobs"].remove(job)
            self._save()
        for f in job["files"]:
            if f["state"] != "done" and f.get("resume"):
                self._discard_resume(job, f)
        self._cleanup(job, everything=True)
        job["state"] = "cancelled"
        self._emit("cancelled", job, force=True)
        return self.snapshot(job)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stopping = False
        self.thread = threading.Thread(target=self._loop, name="snacknodes-uploads", daemon=True)
        self.thread.start()
        threading.Thread(target=self._heartbeat, name="snacknodes-uploads-heartbeat", daemon=True).start()

    def stop(self) -> None:
        self.stopping = True
        self.wake.set()

    @staticmethod
    def snapshot(job: dict[str, Any]) -> dict[str, Any]:
        """What the page needs: no local paths beyond file names, no resume state."""
        files = [{"name": f["name"], "size": f["size"], "sent": f.get("sent", 0), "state": f["state"],
                  "result": f.get("result")} for f in job["files"]]
        return {k: job.get(k) for k in ("id", "state", "provider", "provider_label", "remote_folder", "encrypt",
                                         "node_id", "prompt_id", "error", "attempts", "next_try", "created")} \
            | {"files": files, "total": sum(f["size"] for f in files),
               "sent": sum(f["size"] if f["state"] == "done" else f["sent"] for f in files)}

    # ---- worker ------------------------------------------------------------------------------
    def _job(self, job_id: str) -> dict[str, Any]:
        for job in self.data["jobs"]:
            if job["id"] == job_id:
                return job
        raise KeyError(job_id)

    def _next_job(self) -> Optional[dict[str, Any]]:
        now = self.clock()
        with self.lock:
            for job in self.data["jobs"]:
                if job["state"] == "queued" or (job["state"] == "waiting" and job["next_try"] <= now):
                    return job
        return None

    def _loop(self) -> None:
        while not self.stopping:
            job = self._next_job()
            if job is None:
                self.wake.wait(HEARTBEAT_SECONDS)
                self.wake.clear()
                continue
            try:
                self.run_job(job)
            except Exception:  # noqa: BLE001 - never let the worker die
                logger.exception("SnackNodes: upload worker error")

    def _heartbeat(self) -> None:
        """While uploads are pending, rewrite the queue file every few seconds (even during a long
        encryption or a slow chunk), so `uploads --wait` can tell that ComfyUI is still running."""
        while not self.stopping:
            time.sleep(HEARTBEAT_SECONDS)
            try:
                with self.lock:
                    if any(j["state"] in ACTIVE for j in self.data["jobs"]):
                        self._save()
            except Exception:  # noqa: BLE001 - e.g. disk full; uploads go on
                logger.debug("SnackNodes: heartbeat failed", exc_info=True)

    def run_once(self) -> bool:
        """Run the next due job in this thread (tests, and the CLI fallback). False when idle."""
        job = self._next_job()
        if job is None:
            return False
        self.run_job(job)
        return True

    def run_job(self, job: dict[str, Any]) -> None:
        with self.lock:
            job["state"] = "running"
            job["error"] = None
            self._save()
        self._emit("running", job, force=True)
        current: Optional[dict[str, Any]] = None
        try:
            client = self.providers[job["provider"]]()
            vault = self.vault_loader(client) if job["encrypt"] else None
            for f in job["files"]:
                if f["state"] == "done":
                    continue
                current = f
                f["state"] = "running"
                if not os.path.isfile(f["path"]):
                    raise FileNotFoundError(f"Local file is gone: {f['path']}")
                resume = ResumeState(f.setdefault("resume", {}), saver=lambda: self._save())
                f["resume"] = resume
                if vault is not None and job.get("pending_dir"):
                    resume.setdefault("cipher_dir", os.path.join(job["pending_dir"], ".encrypted"))

                def on_progress(sent: int, total: int, f=f) -> None:
                    f["sent"] = int(f["size"] * (sent / total)) if total else f["size"]
                    self._emit("progress", job)
                    if self.clock() - self._last_save >= SAVE_EVERY:
                        self._save()

                if vault is not None:
                    result = vault.upload(f["path"], job["remote_folder"], progress=on_progress, resume=resume)
                else:
                    mime = mimetypes.guess_type(f["path"])[0] or "application/octet-stream"
                    result = client.upload(f["path"], job["remote_folder"], mime_type=mime,
                                           progress=on_progress, resume=resume)
                with self.lock:
                    f.update(state="done", sent=f["size"], result=result.describe(), resume={})
                    self._save()
                logger.info("SnackNodes: uploaded %s -> %s", f["path"], f["result"])
                self._emit("progress", job, force=True)
            with self.lock:
                job["state"] = "done"
                self._prune()
                self._save()
            self._cleanup(job)
            self._emit("done", job, force=True)
        except Exception as e:  # noqa: BLE001 - explained to the user
            failure = explain(e, job["provider"], job["provider_label"],
                              file_name=current["name"] if current else "")
            with self.lock:
                if current is not None:
                    current["state"] = "failed"
                job["error"] = {"code": failure.code, "zh": failure.zh, "en": failure.en, "detail": failure.detail}
                if failure.code in TEMPORARY and job["attempts"] < AUTO_RETRIES:
                    delay = RETRY_DELAYS[min(job["attempts"], len(RETRY_DELAYS) - 1)]
                    job.update(state="waiting", attempts=job["attempts"] + 1, next_try=self.clock() + delay)
                    if current is not None:
                        current["state"] = "queued"
                else:
                    job["state"] = "failed"
                self._save()
            logger.warning("SnackNodes: upload to %s failed [%s]: %s", job["provider_label"], failure.code,
                           failure.detail)
            self._emit("waiting" if job["state"] == "waiting" else "failed", job, force=True)

    def _emit(self, kind: str, job: dict[str, Any], force: bool = False) -> None:
        now = self.clock()
        if not force and now - self._last_notify.get(job["id"], 0) < NOTIFY_EVERY:
            return
        self._last_notify[job["id"]] = now
        try:
            self.notify({"type": kind, "job": self.snapshot(job), "summary": summarize(self.data, now)})
        except Exception:  # noqa: BLE001 - the page being away must not break uploads
            logger.debug("SnackNodes: notify failed", exc_info=True)

    def _prune(self) -> None:
        finished = [j for j in self.data["jobs"] if j["state"] == "done"]
        for job in finished[:-KEEP_FINISHED]:
            self.data["jobs"].remove(job)

    def _discard_resume(self, job: dict[str, Any], f: dict[str, Any]) -> None:
        try:
            client = self.providers[job["provider"]]()
            discard = getattr(client, "discard_resume", None)
            if discard:
                discard(f["resume"])
        except Exception:  # noqa: BLE001 - best effort
            logger.debug("SnackNodes: could not discard resume state", exc_info=True)
        cipher = f["resume"].get("cipher") if f.get("resume") else None
        if cipher and os.path.exists(cipher):
            os.unlink(cipher)

    def _cleanup(self, job: dict[str, Any], everything: bool = False) -> None:
        """Delete the copies made only for uploading (keep_local_copy off) once they are uploaded."""
        for f in job["files"]:
            if f["cleanup"] and (everything or f["state"] == "done"):
                try:
                    os.unlink(f["path"])
                except FileNotFoundError:
                    pass
        pending = job.get("pending_dir")
        if pending and os.path.isdir(pending) and (everything or job["state"] == "done"):
            shutil.rmtree(pending, ignore_errors=True)


# The queue of the running ComfyUI (one per process).
_QUEUE: Optional[UploadQueue] = None


def get_queue() -> UploadQueue:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = UploadQueue()
    return _QUEUE


def set_queue(queue: Optional[UploadQueue]) -> None:
    global _QUEUE
    _QUEUE = queue


def _mb(n: float) -> str:
    return f"{n / 1048576:.1f} MB"


def describe(data: dict[str, Any], now: Optional[float] = None) -> list[str]:
    """Lines for `auth.py uploads`: one per unfinished or failed job."""
    lines = []
    for job in data.get("jobs", []):
        if job["state"] == "done":
            continue
        left = [f for f in job["files"] if f["state"] != "done"]
        sent = sum(f["size"] if f["state"] == "done" else f.get("sent", 0) for f in job["files"])
        total = sum(f["size"] for f in job["files"])
        line = (f"[{job['state']}] {job['provider_label']} / {job['remote_folder']}: "
                f"{len(left)} file(s) left, {_mb(sent)} / {_mb(total)}")
        if job.get("error"):
            line += f" - {job['error'].get('en', '')}".rstrip()
        lines.append(line)
    return lines


# exit codes of `auth.py uploads --wait`
WAIT_OK, WAIT_FAILED, WAIT_NOT_RUNNING, WAIT_TIMEOUT = 0, 1, 2, 3


def wait_for_uploads(path: Optional[Path] = None, *, interval: float = 5.0, timeout: float = 0,
                     out: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
                     clock: Callable[[], float] = time.time) -> int:
    """Block until no upload is queued or running. Returns WAIT_OK when everything was uploaded,
    WAIT_FAILED when some uploads failed (retry them on the node), WAIT_NOT_RUNNING when uploads
    are left but ComfyUI is not running, WAIT_TIMEOUT after `timeout` seconds (0 = no limit)."""
    start = clock()
    last = ""
    while True:
        data = read_queue(path)
        s = summarize(data, clock())
        if s["active"] == 0:
            if s["failed"]:
                out(f"{s['failed']} upload(s) failed:")
                for line in describe(data):
                    out("  " + line)
                out("Retry or cancel them on the node in ComfyUI.")
                return WAIT_FAILED
            out("All uploads are done.")
            return WAIT_OK
        if not s["worker_alive"]:
            out(f"ComfyUI is not running: {s['files_left']} file(s) not uploaded yet "
                f"({_mb(s['remaining_bytes'])}). Start ComfyUI and they continue where they stopped.")
            return WAIT_NOT_RUNNING
        line = f"Uploading: {s['files_left']} file(s) left, {_mb(s['remaining_bytes'])} to go"
        if line != last:
            out(line)
            last = line
        if timeout and clock() - start >= timeout:
            out("Timed out; uploads are still running.")
            return WAIT_TIMEOUT
        sleep(interval)
