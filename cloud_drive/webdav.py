"""WebDAV provider (RFC 4918): Nutstore/坚果云, Nextcloud/ownCloud, NAS boxes,
OpenList/AList, rclone serve webdav, ...

Ids are paths relative to the configured base URL. Credentials (URL, username,
password; use an app password where the service offers one) come from auth.py
or SNACK_WEBDAV_URL / SNACK_WEBDAV_USERNAME / SNACK_WEBDAV_PASSWORD.
Files are never overwritten: a name that already exists gets _1, _2, ... (as in the vault).
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Optional
from urllib.parse import quote, urlsplit

import requests

from .base import DEFAULT_TIMEOUT, RETRY_STATUS, AuthRequired, CloudDriveError, Provider, request
from .config import CredentialStore

NAME = "webdav"
DISPLAY_NAME = "WebDAV"
AUTH_HINT = "Run: python custom_nodes/comfyui_snacknodes/auth.py webdav --url URL --username USER"
PROPFIND_BODY = ('<?xml version="1.0" encoding="utf-8"?>'
                 '<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>')


def _join(parent_id: str, name: str) -> str:
    return f"{parent_id}/{name}" if parent_id else name


def is_insecure_url(url: str) -> bool:
    """Plain http to anything but the local machine sends the password in clear text."""
    parts = urlsplit(url)
    return parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1")


class WebDAV(Provider):
    name = NAME
    display_name = DISPLAY_NAME
    root_id = ""

    def __init__(
        self,
        store: Optional[CredentialStore] = None,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        super().__init__()
        self.store = store or CredentialStore()
        self.session = session or requests.Session()
        self.sleep = sleep

    # ---------------------------------------------------------------- auth
    def _creds(self) -> dict[str, Any]:
        creds = self.store.get(NAME)
        for key, env in (("url", "SNACK_WEBDAV_URL"), ("username", "SNACK_WEBDAV_USERNAME"),
                         ("password", "SNACK_WEBDAV_PASSWORD")):
            if os.environ.get(env):
                creds[key] = os.environ[env]
        return creds

    def is_authorized(self) -> bool:
        return bool(self._creds().get("url"))

    def _conn(self) -> tuple[str, Optional[tuple[str, str]]]:
        creds = self._creds()
        if not creds.get("url"):
            raise AuthRequired(f"WebDAV is not configured. {AUTH_HINT}")
        auth = (creds["username"], creds.get("password", "")) if creds.get("username") else None
        return creds["url"].rstrip("/") + "/", auth

    def _url(self, path: str) -> str:
        base, _ = self._conn()
        return base + "/".join(quote(p, safe="") for p in path.split("/") if p)

    def _send(self, method: str, path: str, ok: tuple[int, ...], **kw: Any) -> requests.Response:
        _, auth = self._conn()
        try:
            return request(self.session, method, self._url(path), auth=auth, ok=ok, sleep=self.sleep, **kw)
        except CloudDriveError as e:
            if " 401 " in str(e) or " 403 " in str(e):
                raise AuthRequired(f"WebDAV rejected the credentials or path ({e}). {AUTH_HINT}") from e
            raise

    def configure(self, url: str, username: str, password: str) -> None:
        """Check the server answers with these credentials, then store them."""
        if not url.startswith(("http://", "https://")):
            raise CloudDriveError("The WebDAV URL must start with https:// (or http://)")
        try:
            request(self.session, "PROPFIND", url.rstrip("/") + "/", ok=(207,), sleep=self.sleep, retries=1,
                    auth=(username, password) if username else None,
                    headers={"Depth": "0", "Content-Type": "application/xml"}, data=PROPFIND_BODY)
        except CloudDriveError as e:
            if " 401 " in str(e):
                raise CloudDriveError(f"{url}: wrong username or password (HTTP 401). Services such as "
                                      f"Nutstore/坚果云 need an app password, not your login password.") from e
            raise CloudDriveError(f"Could not open {url}: {e}") from e
        self.store.update(NAME, {"url": url, "username": username, "password": password})

    # ---------------------------------------------------------- primitives
    def find_child(self, parent_id: str, name: str) -> Optional[str]:
        path = _join(parent_id, name)
        resp = self._send("PROPFIND", path, ok=(207, 200, 404),
                          headers={"Depth": "0", "Content-Type": "application/xml"}, data=PROPFIND_BODY)
        return None if resp.status_code == 404 else path

    def create_folder(self, parent_id: str, name: str) -> str:
        path = _join(parent_id, name)
        # 405: it already exists (e.g. created concurrently), which is fine for a folder
        self._send("MKCOL", path, ok=(201, 200, 204, 405))
        return path

    def download(self, file_id: str) -> bytes:
        return self._send("GET", file_id, ok=(200,)).content

    def upload_file(self, parent_id: str, name: str, local_path: str,
                    mime_type: str = "application/octet-stream",
                    allow_rename: bool = True) -> tuple[str, str, Optional[str]]:
        final = name
        if self.find_child(parent_id, name):
            if not allow_rename:
                raise CloudDriveError(f"{_join(parent_id, name)} already exists")
            stem, ext = os.path.splitext(name)
            n = 1
            while self.find_child(parent_id, final := f"{stem}_{n}{ext}"):
                n += 1
        path = _join(parent_id, final)
        url, (_, auth) = self._url(path), self._conn()
        size = os.path.getsize(local_path)
        # Streamed PUT; the file is reopened on each attempt so retries resend it whole.
        last: Optional[Exception] = None
        for attempt in range(4):
            try:
                with open(local_path, "rb") as f:
                    resp = self.session.request(
                        "PUT", url, data=f, auth=auth, timeout=DEFAULT_TIMEOUT,
                        headers={"Content-Type": mime_type, "Content-Length": str(size)})
            except requests.RequestException as e:
                last = e
            else:
                if resp.status_code in (200, 201, 204):
                    return path, final, None
                if resp.status_code in (401, 403):
                    raise AuthRequired(f"WebDAV refused the upload: HTTP {resp.status_code}. {AUTH_HINT}")
                if resp.status_code not in RETRY_STATUS:
                    raise CloudDriveError(f"PUT {url} failed: HTTP {resp.status_code} {resp.text[:300]}")
                last = CloudDriveError(f"HTTP {resp.status_code}")
            if attempt < 3:
                self.sleep(2.0 * (2 ** attempt))
        raise CloudDriveError(f"PUT {url} failed after 4 attempts: {last}")
