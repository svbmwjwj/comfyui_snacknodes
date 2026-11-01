"""Credential storage for cloud drive providers.

Credentials live outside workflows so that sharing a workflow never leaks them.
Location: $SNACKNODES_CONFIG_DIR/cloud_drive.json, default
~/.config/comfyui_snacknodes/cloud_drive.json. The file is written with mode 600.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def config_dir() -> Path:
    env = os.environ.get("SNACKNODES_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".config" / "comfyui_snacknodes"


class CredentialStore:
    """Small JSON store: {provider_name: {key: value}}."""

    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "cloud_drive.json")

    def _read_all(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Credential file is corrupt: {self.path} ({e})") from e

    def get(self, provider: str) -> dict[str, Any]:
        with _LOCK:
            return dict(self._read_all().get(provider, {}))

    def update(self, provider: str, values: dict[str, Any]) -> None:
        with _LOCK:
            data = self._read_all()
            data.setdefault(provider, {}).update(values)
            self._write_all(data)

    def clear(self, provider: str) -> None:
        with _LOCK:
            data = self._read_all()
            if data.pop(provider, None) is not None:
                self._write_all(data)

    def _write_all(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".cloud_drive.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
