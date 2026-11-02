"""Google Drive provider (official Drive API v3).

Auth uses the OAuth 2.0 device flow, which works on headless GPU servers: the
user opens a URL on any device and types a short code. The scope is
``drive.file``, so the tool can only see files and folders it created itself.
A published, project-wide OAuth client is built in, so users only approve access
for their own Google account; files always go to that user's own Drive. Users can
still bring their own client (type "TVs and Limited Input devices").
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Optional

import requests

from .base import AuthRequired, CloudDriveError, Progress, Provider, request, save_resume
from .config import CredentialStore
from .paths import AUTH_SCRIPT

NAME = "google_drive"
DISPLAY_NAME = "Google Drive"

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_MIME = "application/vnd.google-apps.folder"
CHUNK_SIZE = 32 * 256 * 1024  # 8 MiB, must be a multiple of 256 KiB

# Built-in OAuth client ("TVs and Limited Input devices", published to production).
# For installed/device apps Google does not treat the client secret as confidential:
# it only identifies the app and grants no access to anyone's Drive by itself.
BUILTIN_CLIENT_ID = "394500357791-5lu827rsdh8d83his7jnpulgcgt0930f.apps.googleusercontent.com"
BUILTIN_CLIENT_SECRET = "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"


def resolve_client(client_id: Optional[str] = None,
                   client_secret: Optional[str] = None) -> tuple[Optional[str], Optional[str], str]:
    """Pick the OAuth client: command-line args, then env vars, then the built-in one.

    Returns (client_id, client_secret, source); ids are None when nothing is configured.
    """
    for cid, sec, source in (
        (client_id, client_secret, "command line"),
        (os.environ.get("SNACK_GDRIVE_CLIENT_ID"), os.environ.get("SNACK_GDRIVE_CLIENT_SECRET"), "environment"),
        (BUILTIN_CLIENT_ID, BUILTIN_CLIENT_SECRET, "built-in"),
    ):
        if cid and sec:
            return cid, sec, source
        if cid or sec:
            raise CloudDriveError(f"Google OAuth client from {source} needs both a client ID and a secret.")
    return None, None, "none"


AUTH_HINT = f"Run: {AUTH_SCRIPT} google_drive"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDrive(Provider):
    name = NAME
    display_name = DISPLAY_NAME

    def __init__(
        self,
        store: Optional[CredentialStore] = None,
        session: Optional[requests.Session] = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        super().__init__()
        self.store = store or CredentialStore()
        self.session = session or requests.Session()
        self.clock = clock
        self.sleep = sleep

    # ---------------------------------------------------------------- auth
    def _creds(self) -> dict[str, Any]:
        creds = self.store.get(NAME)
        for key, env in (
            ("client_id", "SNACK_GDRIVE_CLIENT_ID"),
            ("client_secret", "SNACK_GDRIVE_CLIENT_SECRET"),
            ("refresh_token", "SNACK_GDRIVE_REFRESH_TOKEN"),
        ):
            if os.environ.get(env):
                creds[key] = os.environ[env]
        return creds

    def start_device_flow(self, client_id: str) -> dict[str, Any]:
        resp = request(self.session, "POST", DEVICE_CODE_URL,
                       data={"client_id": client_id, "scope": SCOPE}, sleep=self.sleep)
        return resp.json()

    def finish_device_flow(self, client_id: str, client_secret: str, flow: dict[str, Any],
                           max_wait: float = 900) -> None:
        interval = float(flow.get("interval", 5))
        deadline = self.clock() + min(float(flow.get("expires_in", max_wait)), max_wait)
        while self.clock() < deadline:
            self.sleep(interval)
            resp = self.session.post(TOKEN_URL, data={
                "client_id": client_id,
                "client_secret": client_secret,
                "device_code": flow["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }, timeout=30)
            body = resp.json()
            if resp.status_code == 200:
                self._save_token(body, client_id=client_id, client_secret=client_secret)
                return
            error = body.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            raise CloudDriveError(f"Google authorization failed: {error} {body.get('error_description', '')}")
        raise CloudDriveError("Google authorization timed out")

    def _save_token(self, body: dict[str, Any], **extra: Any) -> None:
        values = dict(extra)
        values["access_token"] = body["access_token"]
        values["expires_at"] = self.clock() + int(body.get("expires_in", 3600))
        if body.get("refresh_token"):
            values["refresh_token"] = body["refresh_token"]
        self.store.update(NAME, values)

    def access_token(self) -> str:
        creds = self._creds()
        if creds.get("access_token") and creds.get("expires_at", 0) > self.clock() + 60:
            return creds["access_token"]
        if not (creds.get("refresh_token") and creds.get("client_id") and creds.get("client_secret")):
            raise AuthRequired(f"Google Drive is not authorized. {AUTH_HINT}")
        resp = self.session.post(TOKEN_URL, data={
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": creds["refresh_token"],
            "grant_type": "refresh_token",
        }, timeout=30)
        if resp.status_code != 200:
            raise AuthRequired(f"Google token refresh failed ({resp.text[:200]}). {AUTH_HINT}")
        self._save_token(resp.json())
        return resp.json()["access_token"]

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token()}"}

    # ---------------------------------------------------------- primitives
    def find_child(self, parent_id: str, name: str) -> Optional[str]:
        q = f"name = '{_escape(name)}' and '{parent_id}' in parents and trashed = false"
        found = request(self.session, "GET", FILES_URL, headers=self._headers(), sleep=self.sleep,
                        params={"q": q, "fields": "files(id)", "pageSize": 1}).json()["files"]
        return found[0]["id"] if found else None

    def create_folder(self, parent_id: str, name: str) -> str:
        return request(self.session, "POST", FILES_URL, headers=self._headers(), sleep=self.sleep,
                       params={"fields": "id"},
                       json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}).json()["id"]

    def download(self, file_id: str) -> bytes:
        return request(self.session, "GET", f"{FILES_URL}/{file_id}", headers=self._headers(),
                       params={"alt": "media"}, sleep=self.sleep).content

    def upload_file(self, parent_id: str, name: str, local_path: str,
                    mime_type: str = "application/octet-stream",
                    allow_rename: bool = True,
                    progress: Optional[Progress] = None,
                    resume: Optional[dict[str, Any]] = None) -> tuple[str, str, Optional[str]]:
        # Drive allows duplicate names, so the name is always kept as given.
        size = os.path.getsize(local_path)
        session_url, offset = None, 0
        if resume is not None and resume.get("session_url") and resume.get("size") == size:
            # An earlier try was interrupted: ask Google how much it already has (sessions last ~1 week).
            try:
                resp = request(self.session, "PUT", resume["session_url"], data=b"", ok=(200, 201, 308),
                               headers={"Content-Range": f"bytes */{size}"}, sleep=self.sleep)
            except CloudDriveError as e:
                if e.status not in (404, 410):
                    raise
            else:
                if resp.status_code in (200, 201):
                    body = resp.json()
                    return body["id"], body.get("name", name), body.get("webViewLink")
                session_url = resume["session_url"]
                received = resp.headers.get("Range")
                offset = int(received.rsplit("-", 1)[1]) + 1 if received else 0
        if session_url is None:
            init = request(
                self.session, "POST", UPLOAD_URL, sleep=self.sleep,
                params={"uploadType": "resumable", "fields": "id,name,webViewLink"},
                headers={**self._headers(), "X-Upload-Content-Type": mime_type,
                         "X-Upload-Content-Length": str(size)},
                json={"name": name, "parents": [parent_id]},
            )
            session_url = init.headers["Location"]
            if resume is not None:
                resume.update(session_url=session_url, size=size)
                save_resume(resume)
        with open(local_path, "rb") as f:
            while True:
                f.seek(offset)
                chunk = f.read(CHUNK_SIZE)
                end = offset + len(chunk) - 1
                content_range = f"bytes {offset}-{end}/{size}" if chunk else f"bytes */{size}"
                resp = request(self.session, "PUT", session_url, data=chunk, ok=(200, 201, 308),
                               headers={"Content-Range": content_range}, sleep=self.sleep)
                if resp.status_code in (200, 201):
                    if progress:
                        progress(size, size)
                    body = resp.json()
                    return body["id"], body.get("name", name), body.get("webViewLink")
                if not chunk:
                    raise CloudDriveError("Google upload stalled")
                # 308: the server reports how much it has; resume from there
                received = resp.headers.get("Range")
                offset = int(received.rsplit("-", 1)[1]) + 1 if received else 0
                if progress:
                    progress(offset, size)
