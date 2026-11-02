"""Connect a drive from inside ComfyUI: what the node's setup panel shows and does.

The frontend asks for a drive's status and form fields, then posts what the user typed.
Credentials go to the same credential file as auth.py and are never sent back: status
only reports non-secret facts (bucket, server, user name). Nothing here touches the workflow.

Kept free of aiohttp so it can be tested; nodes/routes.py wires it to ComfyUI's server.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from .base import CloudDriveError
from .config import CredentialStore
from .errors import explain
from .google_drive import GoogleDrive, resolve_client
from .cryptomator import VaultError
from .s3 import GB, R2, parse_r2_url
from .vault import CryptomatorVault
from .webdav import WebDAV, is_insecure_url

README = "https://github.com/svbmwjwj/SnackNodes#-授权"
DEFAULT_VAULT = "ComfyUI-Vault"
MIN_VAULT_PASSWORD = 8


def _field(key: str, zh: str, en: str, *, secret: bool = False, placeholder: str = "", default: str = "",
           optional: bool = False, hint_zh: str = "", hint_en: str = "") -> dict[str, Any]:
    return {"key": key, "label": {"zh": zh, "en": en}, "secret": secret, "placeholder": placeholder,
            "default": default, "optional": optional, "hint": {"zh": hint_zh, "en": hint_en}}


# What each drive asks for. "oauth" drives show one button instead of fields.
FORMS: dict[str, dict[str, Any]] = {
    "google_drive": {
        "kind": "oauth",
        "intro": {"zh": "点「连接」后，用任意设备打开显示的网址、输入验证码并登录你的 Google 账号。"
                        "本工具只能访问它自己创建的文件。",
                  "en": "Click Connect, then open the link on any device, enter the code and sign in to your "
                        "Google account. The tool can only access files it created."},
    },
    "webdav": {
        "kind": "form",
        "intro": {"zh": "坚果云、Nextcloud、NAS、OpenList 等。坚果云要用「应用密码」，不是登录密码。",
                  "en": "Nutstore, Nextcloud, NAS, OpenList... Nutstore needs an app password, "
                        "not your login password."},
        "fields": [
            _field("url", "WebDAV 地址", "WebDAV URL", placeholder="https://dav.jianguoyun.com/dav/"),
            _field("username", "用户名", "Username"),
            _field("password", "密码", "Password", secret=True),
        ],
    },
    "r2": {
        "kind": "form",
        "intro": {"zh": "免费 10 GB、下载不收费。在 Cloudflare 控制台建好存储桶和 API 令牌后，把下面三项粘贴进来。",
                  "en": "10 GB free, no egress fees. Create a bucket and an API token in the Cloudflare "
                        "dashboard, then paste these three values."},
        "help": README,
        "fields": [
            _field("s3_url", "S3 API 地址", "S3 API URL",
                   placeholder="https://<账户ID>.r2.cloudflarestorage.com/<桶名>",
                   hint_zh="存储桶 → 设置 → S3 API", hint_en="Bucket → Settings → S3 API"),
            _field("access_key_id", "访问密钥 ID", "Access Key ID"),
            _field("secret_access_key", "机密访问密钥", "Secret Access Key", secret=True),
            _field("limit_gb", "容量上限（GB）", "Storage limit (GB)", default="10", optional=True,
                   hint_zh="超过就停止上传，避免产生费用；0 = 不限制",
                   hint_en="Uploads stop before going over, so nothing is billed; 0 = no limit"),
        ],
    },
}

PROVIDER_CLASSES = {"google_drive": GoogleDrive, "webdav": WebDAV, "r2": R2}


def _summary(name: str, provider: Any) -> dict[str, str]:
    creds = provider._creds()
    if name == "webdav":
        text = f"{creds.get('username') or ''} @ {creds.get('url', '')}".strip(" @")
        return {"zh": text, "en": text}
    if name == "r2":
        limit = provider.limit_bytes()
        zh = f"存储桶 {creds.get('bucket')}" + (f"，上限 {limit / GB:g} GB" if limit else "，不限容量")
        en = f"bucket {creds.get('bucket')}" + (f", limit {limit / GB:g} GB" if limit else ", no limit")
        return {"zh": zh, "en": en}
    return {"zh": "", "en": ""}


class Connector:
    def __init__(self, store: Optional[CredentialStore] = None, providers: Optional[dict[str, type]] = None):
        self.store = store or CredentialStore()
        self.providers = providers or PROVIDER_CLASSES
        self._oauth: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _provider(self, name: str):
        if name not in self.providers:
            raise KeyError(name)
        return self.providers[name](self.store)

    def status(self, name: str) -> dict[str, Any]:
        provider = self._provider(name)
        connected = provider.is_authorized()
        out: dict[str, Any] = {"provider": name, "connected": connected, "form": FORMS[name],
                               "summary": _summary(name, provider) if connected else {"zh": "", "en": ""}}
        flow = self._oauth.get(name)
        if flow:
            out["oauth"] = {k: flow[k] for k in ("state", "url", "code", "error") if k in flow}
        return out

    def connect(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        """Check and store what the user typed. Returns status plus an optional note."""
        provider = self._provider(name)
        values = {k: str(v).strip() for k, v in (values or {}).items() if v is not None}
        note: dict[str, str] = {}
        try:
            if name == "webdav":
                if is_insecure_url(values.get("url", "")):
                    note = {"zh": "注意：http:// 会明文传输密码，服务器支持的话请改用 https://",
                            "en": "Note: http:// sends the password unencrypted; use https:// if you can."}
                provider.configure(values.get("url", ""), values.get("username", ""), values.get("password", ""))
            elif name == "r2":
                conf = parse_r2_url(values.get("s3_url", ""))
                if "bucket" not in conf:
                    raise CloudDriveError("The URL has no bucket name. Copy the S3 API URL from the bucket's "
                                          "settings page (it ends with /<bucket>).")
                conf.update(access_key_id=values.get("access_key_id"),
                            secret_access_key=values.get("secret_access_key"))
                limit = values.get("limit_gb", "")
                conf["limit_gb"] = float(limit) if limit else 10.0
                provider.configure(conf)
                used = provider.used_bytes()
                note = {"zh": f"已用 {used / GB:.2f} GB", "en": f"{used / GB:.2f} GB used"}
            else:
                raise CloudDriveError(f"{name} is connected with the Connect button")
        except ValueError as e:
            raise CloudDriveError(f"Not a number: {e}") from e
        return {**self.status(name), "note": note}

    def error(self, name: str, exc: BaseException) -> dict[str, Any]:
        """Friendly text for a failed connect, in both languages, with the raw detail."""
        cls = self.providers.get(name)
        failure = explain(exc, name, getattr(cls, "display_name", name))
        if failure.code == "unknown":
            return {"zh": "连接失败。", "en": "Could not connect.", "detail": str(exc)}
        # first line only: the second line of explain() is a terminal hint, not useful in the panel
        return {"zh": failure.zh.split("\n")[0], "en": failure.en.split("\n")[0], "detail": str(exc)}

    def disconnect(self, name: str) -> dict[str, Any]:
        self._provider(name)
        self.store.clear(name)
        self.store.clear(f"vault:{name}")
        self._oauth.pop(name, None)
        return self.status(name)

    # Google device flow: start returns the link and code at once; a thread waits for approval.
    def oauth_start(self, name: str) -> dict[str, Any]:
        if name != "google_drive":
            raise CloudDriveError(f"{name} does not use a sign-in link")
        with self._lock:
            flow = self._oauth.get(name)
            if flow and flow["state"] == "pending" and flow["expires"] > time.time():
                return self.status(name)
            drive = self._provider(name)
            client_id, client_secret, _ = resolve_client()
            if not client_id:
                raise CloudDriveError("No Google OAuth client configured")
            started = drive.start_device_flow(client_id)
            flow = {"state": "pending", "url": started["verification_url"], "code": started["user_code"],
                    "expires": time.time() + float(started.get("expires_in", 900))}
            self._oauth[name] = flow

        def wait() -> None:
            try:
                drive.finish_device_flow(client_id, client_secret, started)
                flow["state"] = "done"
            except Exception as e:  # noqa: BLE001 - shown on the node
                failure = explain(e, name, drive.display_name)
                flow.update(state="error", error={"zh": failure.zh, "en": failure.en, "detail": failure.detail})

        threading.Thread(target=wait, daemon=True, name="snack-google-auth").start()
        return self.status(name)

    # ---- vault (encryption): created or unlocked from the node; only the unlocked keys are stored
    def vault_status(self, name: str) -> dict[str, Any]:
        provider = self._provider(name)
        data = self.store.get(f"vault:{name}")
        vault = {"path": data.get("path", "")} if data.get("enc_key") else None
        return {"provider": name, "connected": provider.is_authorized(), "vault": vault,
                "default_path": DEFAULT_VAULT, "min_password": MIN_VAULT_PASSWORD}

    def _vault_args(self, name: str, values: dict[str, Any]):
        provider = self._provider(name)
        if not provider.is_authorized():
            raise CloudDriveError(f"{getattr(provider, 'display_name', name)} is not connected yet")
        path = "/".join(p for p in str((values or {}).get("path") or DEFAULT_VAULT).strip().split("/") if p)
        password = str((values or {}).get("password") or "")
        if not path:
            raise CloudDriveError("Empty vault location")
        return provider, path, password

    def vault_create(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        provider, path, password = self._vault_args(name, values)
        if len(password) < MIN_VAULT_PASSWORD:
            raise VaultInputError("short_password")
        CryptomatorVault.create(provider, path, password).save(self.store)
        return self.vault_status(name)

    def vault_unlock(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        provider, path, password = self._vault_args(name, values)
        if not password:
            raise VaultInputError("short_password")
        CryptomatorVault.unlock(provider, path, password).save(self.store)
        return self.vault_status(name)

    def vault_forget(self, name: str) -> dict[str, Any]:
        self._provider(name)
        self.store.clear(f"vault:{name}")
        return self.vault_status(name)

    def vault_error(self, name: str, exc: BaseException) -> dict[str, Any]:
        detail = str(exc)
        if isinstance(exc, VaultInputError):
            return {"zh": f"保险库密码至少 {MIN_VAULT_PASSWORD} 个字符。",
                    "en": f"Use at least {MIN_VAULT_PASSWORD} characters for the vault password.", "detail": ""}
        if isinstance(exc, VaultError) and "Wrong vault password" in detail:
            return {"zh": "保险库密码错误。", "en": "Wrong vault password.", "detail": ""}
        if "already exists" in detail:
            return {"zh": "这个位置已经有一个保险库了：请改用「打开已有保险库」，或换一个位置。",
                    "en": "There is already a vault here: use Open existing vault, or pick another location.",
                    "detail": detail}
        if "No Cryptomator vault found" in detail:
            google = name == "google_drive"
            return {"zh": "这个位置没有保险库。" + ("Google Drive 上只能打开本工具创建的保险库。" if google
                                                   else "请检查位置（区分大小写）。"),
                    "en": "No vault at this location." + (" On Google Drive only vaults created by this tool "
                                                          "can be opened." if google else
                                                          " Check the location (it is case-sensitive)."),
                    "detail": detail}
        if "is not connected yet" in detail:
            return {"zh": "请先在上面连接网盘。", "en": "Connect the drive above first.", "detail": ""}
        return self.error(name, exc)


class VaultInputError(CloudDriveError):
    """The vault password typed in the node is too short (or empty)."""
