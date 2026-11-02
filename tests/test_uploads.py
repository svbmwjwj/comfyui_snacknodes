"""Background upload queue (cloud_drive/uploads.py) and resumable uploads."""

import json
import os

import pytest
from local_provider import LocalProvider
from test_s3 import ENDPOINT, FakeS3, _configure

from cloud_drive import google_drive as gd
from cloud_drive import s3 as s3mod
from cloud_drive import uploads as up
from cloud_drive.base import CloudDriveError
from cloud_drive.config import CredentialStore
from cloud_drive.s3 import R2
from cloud_drive.vault import CryptomatorVault
from fake_http import FakeResponse, FakeSession


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Flaky(LocalProvider):
    """Fails the first `fail` uploads with the given error."""

    def __init__(self, root, fail=0, error=None):
        super().__init__(root)
        self.fail, self.error, self.calls = fail, error, 0

    def upload_file(self, *a, **kw):
        self.calls += 1
        if self.fail:
            self.fail -= 1
            raise self.error
        return super().upload_file(*a, **kw)


def _files(tmp_path, *names, size=10):
    out = []
    for n in names:
        p = tmp_path / "src" / n
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(os.urandom(size))
        out.append({"path": str(p)})
    return out


def _queue(tmp_path, provider, clock=None, events=None):
    return up.UploadQueue(tmp_path / "q.json", providers={"local": lambda: provider},
                          notify=(events.append if events is not None else None), clock=clock or Clock())


def _add(q, files, **kw):
    return q.add(provider="local", provider_label="Local", remote_folder="out", encrypt=False, files=files, **kw)


def test_jobs_persist_and_continue_after_restart(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    q = _queue(tmp_path, LocalProvider(drive))
    job = _add(q, _files(tmp_path, "a.png", "b.mp4"), node_id=3)
    data = json.loads((tmp_path / "q.json").read_text())
    data["jobs"][0]["state"] = "running"  # ComfyUI stopped in the middle of it
    (tmp_path / "q.json").write_text(json.dumps(data))

    q2 = _queue(tmp_path, LocalProvider(drive))
    assert q2.jobs()[0]["state"] == "queued" and q2.jobs()[0]["id"] == job["id"]
    assert q2.run_once()
    assert sorted(os.listdir(drive / "out")) == ["a.png", "b.mp4"]
    snap = q2.jobs()[0]
    assert snap["state"] == "done" and snap["sent"] == snap["total"] == 20
    assert "path" not in snap["files"][0] and "resume" not in snap["files"][0]  # nothing local leaks to the page
    assert up.summarize(up.read_queue(tmp_path / "q.json"), now=1000.0)["active"] == 0


def test_temporary_failures_retry_later_and_others_wait_for_the_user(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    clock, events = Clock(), []
    provider = Flaky(drive, fail=1, error=CloudDriveError("offline", network=True))
    q = _queue(tmp_path, provider, clock, events)
    job = _add(q, _files(tmp_path, "a.png"))
    assert q.run_once()
    snap = q.jobs()[0]
    assert snap["state"] == "waiting" and snap["attempts"] == 1 and snap["error"]["code"] == "network"
    assert not q.run_once()          # not due yet
    clock.now += up.RETRY_DELAYS[0]
    assert q.run_once() and q.jobs()[0]["state"] == "done"

    provider.fail, provider.error = 1, CloudDriveError("denied", status=403)
    job = _add(q, _files(tmp_path, "b.png"))
    q.run_once()
    assert q._job(job["id"])["state"] == "failed" and events[-1]["type"] == "failed"
    assert events[-1]["job"]["error"]["code"] == "forbidden"
    q.retry(job["id"])
    assert q.run_once() and q._job(job["id"])["state"] == "done"


def test_cancel_deletes_pending_copies_and_frees_parts(tmp_path):
    class Provider(Flaky):
        discarded = []

        def discard_resume(self, resume):
            self.discarded.append(dict(resume))

    drive = tmp_path / "drive"
    drive.mkdir()
    provider = Provider(drive, fail=1, error=CloudDriveError("denied", status=403))
    q = _queue(tmp_path, provider)
    pending = tmp_path / "pending" / "job1"
    pending.mkdir(parents=True)
    copy = pending / "v.mp4"
    copy.write_bytes(b"x" * 5)
    job = _add(q, [{"path": str(copy), "cleanup": True}], pending_dir=str(pending))
    q._job(job["id"])["files"][0]["resume"] = {"upload_id": "U9", "key": "out/v.mp4"}
    q.run_once()
    q._job(job["id"])["files"][0]["resume"] = {"upload_id": "U9", "key": "out/v.mp4"}
    assert q.cancel(job["id"])["state"] == "cancelled"
    assert not pending.exists() and q.jobs() == [] and provider.discarded == [{"upload_id": "U9", "key": "out/v.mp4"}]


def test_summary_tells_whether_comfyui_is_still_running(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    clock = Clock()
    q = _queue(tmp_path, LocalProvider(drive), clock)
    _add(q, _files(tmp_path, "a.png", size=100))
    data = up.read_queue(tmp_path / "q.json")
    s = up.summarize(data, now=clock.now + 10)
    assert s["active"] == 1 and s["files_left"] == 1 and s["remaining_bytes"] == 100 and s["worker_alive"]
    assert not up.summarize(data, now=clock.now + up.STALE_SECONDS + 1)["worker_alive"]


@pytest.fixture
def r2(tmp_path, monkeypatch):
    for prefix in ("SNACK_R2_", "SNACK_S3_"):
        for f in s3mod.S3.FIELDS + ("account_id",):
            monkeypatch.delenv(prefix + f.upper(), raising=False)
    monkeypatch.setattr(s3mod, "PART_SIZE", 4)
    monkeypatch.setattr(s3mod, "MULTIPART_THRESHOLD", 5)
    fake = FakeS3()
    drive = R2(CredentialStore(tmp_path / "c.json"), fake, sleep=lambda s: None)
    _configure(drive, limit_gb=0)
    return fake, drive


def test_s3_parts_go_in_parallel(r2, tmp_path):
    fake, drive = r2
    data = os.urandom(4 * 25 + 3)
    src = tmp_path / "big.mp4"
    src.write_bytes(data)
    seen = []
    drive.upload(str(src), "v", progress=lambda a, b: seen.append((a, b)))
    assert fake.objects["v/big.mp4"] == data and not fake.uploads
    assert seen[-1] == (len(data), len(data))


def test_s3_upload_continues_with_the_parts_already_sent(r2, tmp_path, monkeypatch):
    fake, drive = r2
    monkeypatch.setattr(s3mod, "PARALLEL_PARTS", 1)
    data = b"0123456789ab"  # 3 parts
    src = tmp_path / "big.mp4"
    src.write_bytes(data)
    original = fake.routes
    put = next(h for m, _, h in original if m == "PUT")
    state = {"n": 0}

    def put_failing_third(url, **kw):
        if "partNumber=3" in url and not state["n"]:
            state["n"] += 1
            return FakeResponse(400, content=b"<Error><Code>BadDigest</Code></Error>")
        return put(url, **kw)
    fake.routes = [r if r[0] != "PUT" else ("PUT", ENDPOINT, put_failing_third) for r in original]
    saves = []
    resume = up.ResumeState(saver=lambda: saves.append(dict(resume)))
    with pytest.raises(CloudDriveError):
        drive.upload(str(src), "v", resume=resume)
    assert resume["upload_id"] == "U1" and sorted(resume["etags"]) == ["1", "2"] and fake.uploads["U1"]

    sent_before = sum(1 for m, u, _ in fake.calls if m == "PUT" and "partNumber" in u)
    drive.upload(str(src), "v", resume=resume)
    parts_after = [u for m, u, _ in fake.calls[len(fake.calls) - 3:] if m == "PUT" and "partNumber" in u]
    assert fake.objects["v/big.mp4"] == data
    assert sum(1 for m, u, _ in fake.calls if m == "PUT" and "partNumber" in u) == sent_before + 1
    assert all("partNumber=3" in u for u in parts_after) and saves


def test_s3_starts_over_when_the_saved_upload_is_gone(r2, tmp_path):
    fake, drive = r2
    src = tmp_path / "big.mp4"
    src.write_bytes(b"0123456789")
    resume = up.ResumeState({"key": "v/big.mp4", "size": 10, "upload_id": "GONE", "etags": {"1": '"x"'}})
    drive.upload(str(src), "v", resume=resume)
    assert fake.objects["v/big.mp4"] == b"0123456789" and resume["upload_id"] == "U1"


def test_google_upload_continues_its_session(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "CHUNK_SIZE", 4)
    store = CredentialStore(tmp_path / "c.json")
    store.update("google_drive", {"client_id": "cid", "client_secret": "sec", "refresh_token": "rt"})
    data = b"0123456789"
    src = tmp_path / "v.mp4"
    src.write_bytes(data)
    session = FakeSession()
    session.route("POST", gd.TOKEN_URL, lambda **kw: FakeResponse(200, {"access_token": "at", "expires_in": 3600}))
    session.route("POST", gd.UPLOAD_URL, lambda **kw: FakeResponse(200, {}, {"Location": "https://up/s1"}))
    got = bytearray()
    state = {"broken": True}

    def put(data, headers, **kw):
        rng = headers["Content-Range"]
        if rng.startswith("bytes */"):
            return FakeResponse(308, {}, {"Range": f"bytes=0-{len(got) - 1}"} if got else {})
        if len(got) == 4 and state["broken"]:
            state["broken"] = False
            return FakeResponse(400, {"error": "boom"})
        got.extend(data)
        if len(got) == 10:
            return FakeResponse(200, {"id": "f1", "name": "v.mp4"})
        return FakeResponse(308, {}, {"Range": f"bytes=0-{len(got) - 1}"})
    session.route("PUT", "https://up/s1", put)
    drive = gd.GoogleDrive(store, session, clock=lambda: 1000.0, sleep=lambda s: None)
    resume = up.ResumeState()
    with pytest.raises(CloudDriveError):
        drive.upload_file("root", "v.mp4", str(src), resume=resume)
    assert resume == {"session_url": "https://up/s1", "size": 10}
    assert drive.upload_file("root", "v.mp4", str(src), resume=resume)[0] == "f1"
    assert bytes(got) == data
    assert sum(1 for m, u, _ in session.calls if u.startswith(gd.UPLOAD_URL)) == 1  # no second session


def test_vault_upload_keeps_its_ciphertext_until_done(tmp_path, monkeypatch):
    monkeypatch.setenv("SNACKNODES_CONFIG_DIR", str(tmp_path / "cfg"))
    drive = tmp_path / "drive"
    drive.mkdir()
    class BigFails(Flaky):
        def upload_file(self, parent_id, name, local_path, *a, **kw):
            if self.fail and os.path.getsize(local_path) > 1000:
                self.fail -= 1
                raise self.error
            return LocalProvider.upload_file(self, parent_id, name, local_path, *a, **kw)
    provider = BigFails(drive)
    vault = CryptomatorVault.create(provider, "Vault", "pw123456")
    src = tmp_path / "v.mp4"
    src.write_bytes(os.urandom(5000))
    provider.fail, provider.error = 1, CloudDriveError("offline", network=True)
    resume = up.ResumeState({"cipher_dir": str(tmp_path / "enc")})
    with pytest.raises(CloudDriveError):
        vault.upload(str(src), "c", resume=resume)
    cipher = resume["cipher"]
    assert os.path.exists(cipher) and resume["vault_name"] == "v.mp4"
    before = open(cipher, "rb").read()
    result = vault.upload(str(src), "c", resume=resume)
    assert not os.path.exists(cipher) and result.remote_path == "Vault/c/v.mp4"
    uploaded = [p for p in drive.rglob("*.c9r") if p.is_file()]
    assert any(p.read_bytes() == before for p in uploaded)  # the same ciphertext, not a new one


def test_wait_for_uploads(tmp_path):
    path = tmp_path / "q.json"
    clock, out = Clock(), []
    assert up.wait_for_uploads(path, out=out.append, clock=clock) == up.WAIT_OK  # nothing queued

    drive = tmp_path / "drive"
    drive.mkdir()
    q = _queue(tmp_path, LocalProvider(drive), clock)
    _add(q, _files(tmp_path, "a.png", size=2048))

    def run_when_asked_to_sleep(seconds):
        clock.now += seconds
        q.run_once()
    assert up.wait_for_uploads(path, out=out.append, sleep=run_when_asked_to_sleep, clock=clock) == up.WAIT_OK
    assert out[-2].startswith("Uploading: 1 file(s) left") and out[-1] == "All uploads are done."

    _add(q, _files(tmp_path, "b.png"))
    clock.now += up.STALE_SECONDS + 1   # ComfyUI stopped: no heartbeat
    assert up.wait_for_uploads(path, out=out.append, clock=clock) == up.WAIT_NOT_RUNNING
    assert "ComfyUI is not running: 1 file(s)" in out[-1]
    assert up.wait_for_uploads(path, out=out.append, clock=clock, timeout=1,
                               sleep=lambda s: None) == up.WAIT_NOT_RUNNING

    q2 = _queue(tmp_path, Flaky(drive, fail=1, error=CloudDriveError("denied", status=403)), clock)
    q2.run_once()
    assert up.wait_for_uploads(path, out=out.append, clock=clock) == up.WAIT_FAILED
    assert out[-1] == "Retry or cancel them on the node in ComfyUI." and "[failed] Local / out" in out[-2]


def test_auth_uploads_command(tmp_path, monkeypatch, capsys):
    import subprocess
    import sys
    env = {**os.environ, "SNACKNODES_CONFIG_DIR": str(tmp_path)}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, os.path.join(root, "auth.py"), "uploads", "--wait"], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0 and "All uploads are done." in r.stdout


def test_worker_thread_uploads_in_the_background(tmp_path):
    import threading
    drive = tmp_path / "drive"
    drive.mkdir()
    done = threading.Event()
    events = []

    def notify(e):
        events.append(e["type"])
        if e["type"] == "done":
            done.set()
    q = up.UploadQueue(tmp_path / "q.json", providers={"local": lambda: LocalProvider(drive)}, notify=notify)
    q.start()
    try:
        _add(q, _files(tmp_path, "a.png", "b.png"))
        assert done.wait(5)
    finally:
        q.stop()
    assert sorted(os.listdir(drive / "out")) == ["a.png", "b.png"] and events[:2] == ["queued", "running"]


def test_clear_finished_keeps_unfinished_jobs(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    q = _queue(tmp_path, Flaky(drive))
    _add(q, _files(tmp_path, "a.png"))
    q.run_once()
    q.providers["local"]().fail = 0
    pending = _add(q, _files(tmp_path, "b.png"))
    assert q.clear_finished() == 1 and [j["id"] for j in q.jobs()] == [pending["id"]]
    assert up.read_queue(tmp_path / "q.json")["jobs"][0]["id"] == pending["id"]
