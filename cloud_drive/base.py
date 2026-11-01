"""Shared types for cloud drive providers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests

DEFAULT_TIMEOUT = (15, 120)  # (connect, read) seconds
RETRY_STATUS = {429, 500, 502, 503, 504}

# progress(bytes_sent, total_bytes) for the payload of one upload
Progress = Callable[[int, int], None]


class CloudDriveError(RuntimeError):
    """Raised when a cloud drive operation fails."""


class AuthRequired(CloudDriveError):
    """Raised when a provider has no usable credentials."""


@dataclass
class UploadResult:
    provider: str
    remote_path: str
    file_id: str
    url: Optional[str] = None
    encrypted: bool = False

    def describe(self) -> str:
        if self.encrypted:
            return f"{self.provider}:{self.remote_path} [encrypted]"
        return self.url or f"{self.provider}:{self.remote_path}"


def request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    ok: tuple[int, ...] = (200, 201),
    **kwargs: Any,
) -> requests.Response:
    """Send a request, retrying on network errors, 429 and 5xx.

    Proxies come from the standard HTTP(S)_PROXY environment variables, so users
    on restricted networks configure them the usual way.
    """
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = session.request(method, url, **kwargs)
        except requests.RequestException as e:
            last_error = e
        else:
            if resp.status_code in ok:
                return resp
            if resp.status_code not in RETRY_STATUS or attempt == retries:
                raise CloudDriveError(
                    f"{method} {url} failed: HTTP {resp.status_code} {resp.text[:500]}"
                )
            last_error = CloudDriveError(f"HTTP {resp.status_code}")
        if attempt < retries:
            sleep(backoff * (2**attempt))
    raise CloudDriveError(f"{method} {url} failed after {retries + 1} attempts: {last_error}")


def split_folder(path: str) -> list[str]:
    """'/a//b/ ' -> ['a', 'b']"""
    return [p.strip() for p in (path or "").replace("\\", "/").split("/") if p.strip()]


class Provider:
    """A cloud drive. Subclasses implement the primitive operations; folder
    walking and uploads by path are shared (and reused by the encrypted vault)."""

    name = ""
    display_name = ""
    root_id = "root"

    def __init__(self) -> None:
        self._folder_cache: dict[tuple[str, str], str] = {}

    # primitives -----------------------------------------------------------
    def find_child(self, parent_id: str, name: str) -> Optional[str]:
        """Id of the child (file or folder) with exactly this name, or None."""
        raise NotImplementedError

    def create_folder(self, parent_id: str, name: str) -> str:
        raise NotImplementedError

    def upload_file(self, parent_id: str, name: str, local_path: str,
                    mime_type: str = "application/octet-stream",
                    allow_rename: bool = True,
                    progress: Optional[Progress] = None) -> tuple[str, str, Optional[str]]:
        """Upload; returns (file_id, final_name, share_url_or_None).
        allow_rename=False must fail rather than store under a different name.
        progress, if given, is called with (bytes_sent, total_bytes) as the upload advances."""
        raise NotImplementedError

    def download(self, file_id: str) -> bytes:
        raise NotImplementedError

    def _creds(self) -> dict[str, Any]:
        return {}

    def is_authorized(self) -> bool:
        return bool(self._creds().get("refresh_token"))

    # shared ---------------------------------------------------------------
    def ensure_child_folder(self, parent_id: str, name: str) -> str:
        key = (parent_id, name)
        if key not in self._folder_cache:
            self._folder_cache[key] = self.find_child(parent_id, name) or self.create_folder(parent_id, name)
        return self._folder_cache[key]

    def ensure_folder(self, path: str, parent_id: Optional[str] = None) -> str:
        current = parent_id or self.root_id
        for part in split_folder(path):
            current = self.ensure_child_folder(current, part)
        return current

    def find_path(self, path: str) -> Optional[str]:
        current: Optional[str] = self.root_id
        for part in split_folder(path):
            current = self.find_child(current, part)
            if current is None:
                return None
        return current

    def upload(self, local_path: str, remote_folder: str, remote_name: Optional[str] = None,
               mime_type: str = "application/octet-stream", progress: Optional[Progress] = None) -> UploadResult:
        import os
        parent = self.ensure_folder(remote_folder)
        file_id, final_name, url = self.upload_file(
            parent, remote_name or os.path.basename(local_path), local_path, mime_type, progress=progress)
        return UploadResult(self.name, "/".join(split_folder(remote_folder) + [final_name]), file_id, url)
