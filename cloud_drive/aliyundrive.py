"""Aliyun Drive (阿里云盘) provider, official Open Platform API.

Auth uses the Open Platform QR-code flow: the user scans a QR code with the
Aliyun Drive app. The user registers their own app on the Open Platform
(https://www.alipan.com/developer) to get a client_id / client_secret.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Callable, Optional

import requests

from .base import AuthRequired, CloudDriveError, Provider, request
from .config import CredentialStore

NAME = "aliyundrive"
DISPLAY_NAME = "Aliyun Drive"

API = "https://openapi.alipan.com"
SCOPES = ["user:base", "file:all:read", "file:all:write"]
PART_SIZE = 20 * 1024 * 1024
URL_MAX_AGE = 50 * 60  # signed part URLs expire after ~1h; refresh early
MAX_PARTS = 10000

AUTH_HINT = "Run: python custom_nodes/comfyui_snacknodes/auth.py aliyundrive"


class AliyunDrive(Provider):
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
        self._drive_id: Optional[str] = None

    # ---------------------------------------------------------------- auth
    def _creds(self) -> dict[str, Any]:
        creds = self.store.get(NAME)
        for key, env in (
            ("client_id", "SNACK_ALIYUNDRIVE_CLIENT_ID"),
            ("client_secret", "SNACK_ALIYUNDRIVE_CLIENT_SECRET"),
            ("refresh_token", "SNACK_ALIYUNDRIVE_REFRESH_TOKEN"),
        ):
            if os.environ.get(env):
                creds[key] = os.environ[env]
        return creds

    def start_qr_flow(self, client_id: str, client_secret: str) -> dict[str, Any]:
        """Returns {"qrCodeUrl": ..., "sid": ...}."""
        return request(self.session, "POST", f"{API}/oauth/authorize/qrcode", sleep=self.sleep, json={
            "client_id": client_id, "client_secret": client_secret,
            "scopes": SCOPES, "width": 430, "height": 430,
        }).json()

    def import_refresh_token(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        """Manual fallback: exchange an existing refresh token and store the result."""
        token = self._token_request({"client_id": client_id, "client_secret": client_secret,
                                     "grant_type": "refresh_token", "refresh_token": refresh_token})
        self._save_token(token, client_id=client_id, client_secret=client_secret)

    def finish_qr_flow(self, client_id: str, client_secret: str, sid: str,
                       on_status: Callable[[str], None] = lambda s: None, max_wait: float = 600) -> None:
        deadline = self.clock() + max_wait
        last = None
        while self.clock() < deadline:
            body = request(self.session, "GET", f"{API}/oauth/qrcode/{sid}/status", sleep=self.sleep).json()
            status = body.get("status")
            if status != last:
                on_status(status)
                last = status
            if status == "LoginSuccess":
                token = self._token_request({
                    "client_id": client_id, "client_secret": client_secret,
                    "grant_type": "authorization_code", "code": body["authCode"],
                })
                self._save_token(token, client_id=client_id, client_secret=client_secret)
                return
            if status == "QRCodeExpired":
                raise CloudDriveError("QR code expired, please run the auth command again")
            self.sleep(2)
        raise CloudDriveError("Aliyun Drive authorization timed out")

    def _token_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self.session.post(f"{API}/oauth/access_token", json=payload, timeout=30)
        if resp.status_code != 200:
            raise AuthRequired(f"Aliyun Drive token request failed ({resp.text[:200]}). {AUTH_HINT}")
        return resp.json()

    def _save_token(self, body: dict[str, Any], **extra: Any) -> None:
        values = dict(extra)
        values["access_token"] = body["access_token"]
        values["expires_at"] = self.clock() + int(body.get("expires_in", 7200))
        if body.get("refresh_token"):
            # refresh tokens rotate: always persist the newest one
            values["refresh_token"] = body["refresh_token"]
        self.store.update(NAME, values)

    def access_token(self) -> str:
        creds = self._creds()
        if creds.get("access_token") and creds.get("expires_at", 0) > self.clock() + 60:
            return creds["access_token"]
        if not (creds.get("refresh_token") and creds.get("client_id") and creds.get("client_secret")):
            raise AuthRequired(f"Aliyun Drive is not authorized. {AUTH_HINT}")
        token = self._token_request({
            "client_id": creds["client_id"], "client_secret": creds["client_secret"],
            "grant_type": "refresh_token", "refresh_token": creds["refresh_token"],
        })
        self._save_token(token)
        return token["access_token"]

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return request(self.session, "POST", f"{API}{path}", sleep=self.sleep, json=payload,
                       headers={"Authorization": f"Bearer {self.access_token()}"}).json()

    # --------------------------------------------------------------- drive
    def drive_id(self) -> str:
        """Upload target. Default: the resource drive (资源库); set
        "drive": "backup" in the credential file for the backup drive (备份盘)."""
        if self._drive_id is None:
            info = self._post("/adrive/v1.0/user/getDriveInfo", {})
            prefer_backup = self._creds().get("drive") == "backup"
            if prefer_backup:
                self._drive_id = info.get("backup_drive_id") or info["default_drive_id"]
            else:
                self._drive_id = info.get("resource_drive_id") or info["default_drive_id"]
        return self._drive_id

    # ---------------------------------------------------------- primitives
    def find_child(self, parent_id: str, name: str) -> Optional[str]:
        marker = ""
        while True:
            body = self._post("/adrive/v1.0/openFile/list", {
                "drive_id": self.drive_id(), "parent_file_id": parent_id,
                "limit": 100, "marker": marker,
            })
            for item in body.get("items", []):
                if item.get("name") == name:
                    return item["file_id"]
            marker = body.get("next_marker") or ""
            if not marker:
                return None

    def create_folder(self, parent_id: str, name: str) -> str:
        # check_name_mode=refuse returns the existing folder if one already exists
        return self._post("/adrive/v1.0/openFile/create", {
            "drive_id": self.drive_id(), "parent_file_id": parent_id,
            "name": name, "type": "folder", "check_name_mode": "refuse",
        })["file_id"]

    def download(self, file_id: str) -> bytes:
        url = self._post("/adrive/v1.0/openFile/getDownloadUrl",
                         {"drive_id": self.drive_id(), "file_id": file_id, "expire_sec": 14400})["url"]
        return request(self.session, "GET", url, sleep=self.sleep).content

    def upload_file(self, parent_id: str, name: str, local_path: str,
                    mime_type: str = "application/octet-stream",
                    allow_rename: bool = True) -> tuple[str, str, Optional[str]]:
        size = os.path.getsize(local_path)
        part_size = max(PART_SIZE, math.ceil(size / MAX_PARTS))
        n_parts = max(1, math.ceil(size / part_size))
        drive_id = self.drive_id()
        created = self._post("/adrive/v1.0/openFile/create", {
            "drive_id": drive_id, "parent_file_id": parent_id, "name": name, "type": "file",
            "check_name_mode": "auto_rename" if allow_rename else "refuse", "size": size,
            "part_info_list": [{"part_number": i + 1} for i in range(n_parts)],
        })
        if created.get("exist"):
            raise CloudDriveError(f"'{name}' already exists in the target folder")
        file_id, upload_id = created["file_id"], created.get("upload_id")
        if not created.get("rapid_upload"):
            urls = {p["part_number"]: p["upload_url"] for p in created.get("part_info_list", [])}
            issued = self.clock()
            with open(local_path, "rb") as f:
                for number in range(1, n_parts + 1):
                    if self.clock() - issued > URL_MAX_AGE:
                        urls.clear()  # forces fresh URLs for the remaining parts
                        issued = self.clock()
                    f.seek((number - 1) * part_size)
                    self._put_part(drive_id, file_id, upload_id, number, urls, f.read(part_size))
        done = self._post("/adrive/v1.0/openFile/complete",
                          {"drive_id": drive_id, "file_id": file_id, "upload_id": upload_id})
        return file_id, done.get("name", created.get("file_name", name)), None

    def _put_part(self, drive_id: str, file_id: str, upload_id: str, number: int,
                  urls: dict[int, str], chunk: bytes) -> None:
        for attempt in range(2):
            url = urls.get(number)
            if url:
                # No Content-Type header: the signed URL rejects it.
                resp = self.session.put(url, data=chunk, timeout=(15, 600))
                if resp.status_code in (200, 409):  # 409: part already uploaded
                    return
                if resp.status_code != 403 or attempt == 1:
                    raise CloudDriveError(f"Aliyun Drive part {number} upload failed: "
                                          f"HTTP {resp.status_code} {resp.text[:300]}")
            # missing or expired (403) signed URL: ask for a fresh one
            fresh = self._post("/adrive/v1.0/openFile/getUploadUrl", {
                "drive_id": drive_id, "file_id": file_id, "upload_id": upload_id,
                "part_info_list": [{"part_number": number}],
            })
            urls[number] = fresh["part_info_list"][0]["upload_url"]
