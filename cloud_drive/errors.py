"""Turn upload failures into short, actionable messages in Chinese and English.

classify() maps an exception to a code using the HTTP status, the response body
and the exception type; explain() fills in the text. The original technical
message is always kept as `detail` so nothing is lost for debugging.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests

from .base import AuthRequired, CloudDriveError
from .paths import AUTH_SCRIPT

AUTH_COMMANDS = {
    "google_drive": "{auth} google_drive",
    "webdav": "{auth} webdav --url URL --username USER",
    "aliyundrive": "{auth} aliyundrive",
    "r2": "{auth} r2 --url S3_API_URL",
    "s3": "{auth} s3 --endpoint URL --bucket BUCKET",
}
KEY_PROVIDERS = ("r2", "s3")

# code -> (zh title, zh hint, en title, en hint). {provider}, {cmd}, {name} are filled in.
MESSAGES: dict[str, tuple[str, str, str, str]] = {
    "not_authorized": (
        "{provider} 尚未授权，或授权已失效。",
        "在顶部 SnackNodes →「网盘设置」里重新连接 {provider}；或在终端执行：{cmd}",
        "{provider} is not authorized, or the authorization has expired.",
        "Connect {provider} again in SnackNodes > Cloud drives (top bar), or run: {cmd}"),
    "wrong_password": (
        "{provider} 用户名或密码错误。",
        "在顶部 SnackNodes →「网盘设置」里重新填写（或执行：{cmd}）。坚果云等服务要用「应用密码」，不是登录密码。",
        "Wrong {provider} username or password.",
        "Enter them again in SnackNodes > Cloud drives (top bar) (or run: {cmd}). Services such as Nutstore need an "
        "app password, not your login password."),
    "wrong_keys": (
        "{provider} 的 Access Key ID 或 Secret Access Key 错误，或密钥已被删除。",
        "重新创建 API 令牌，在顶部 SnackNodes →「网盘设置」里重新填写（或执行：{cmd}）",
        "Wrong {provider} Access Key ID or Secret Access Key, or the key was deleted.",
        "Create a new API token and enter it in SnackNodes > Cloud drives (top bar) (or run: {cmd})"),
    "storage_limit": (
        "再上传就会超过你给 {provider} 设的容量上限（Cloudflare R2 免费额度为 10 GB）。",
        "清理存储桶里的旧文件；或在顶部 SnackNodes →「网盘设置」里修改容量上限（0 = 不限制，超出免费额度会产生费用）。",
        "This upload would take {provider} over the storage limit you set (R2's free tier is 10 GB).",
        "Delete old files from the bucket, or change the limit in SnackNodes > Cloud drives (top bar) "
        "(0 = no limit; storage over the free tier is billed)."),
    "forbidden": (
        "没有权限写入这个网盘目录。",
        "检查「网盘目录」是否正确，以及账号是否有写入权限。",
        "No permission to write to this folder on the drive.",
        "Check remote_folder and that the account may write there."),
    "conflict": (
        "网盘目录不可写：路径里有同名文件，或上级目录不存在。",
        "换一个「网盘目录」，或在网盘上删除/改名与目录同名的文件。",
        "The folder cannot be created: a file has the same name as a folder in the path, "
        "or a parent folder is missing.",
        "Use another remote_folder, or rename/delete the conflicting file on the drive."),
    "not_found": (
        "在网盘上找不到目标位置。",
        "检查「网盘目录」、WebDAV 地址或 S3/R2 存储桶名是否正确。",
        "The target location was not found on the drive.",
        "Check remote_folder and, for WebDAV, the server URL, for S3/R2, the bucket name."),
    "quota": (
        "网盘空间不足。",
        "清理网盘空间或扩容后重试。",
        "The drive is full.",
        "Free up space or upgrade the storage, then try again."),
    "too_large": (
        "文件超过了网盘允许的单个文件大小。",
        "换一个网盘，或减小文件（例如降低视频码率）。",
        "The file is larger than the drive allows for a single file.",
        "Use another drive, or make the file smaller (e.g. a lower video bitrate)."),
    "rate_limited": (
        "网盘限流或服务繁忙，自动重试后仍然失败。",
        "稍后再试；坚果云免费版有请求频率限制。",
        "The drive is rate limiting or busy, and retries did not help.",
        "Try again later. Nutstore's free plan limits the request rate."),
    "server_error": (
        "网盘服务器出错。",
        "通常是临时问题，稍后再试。",
        "The drive's server returned an error.",
        "Usually temporary; try again later."),
    "network": (
        "无法连接到网盘。",
        "检查网络；需要代理时，设置 HTTPS_PROXY 环境变量后重启 ComfyUI。",
        "Could not reach the drive.",
        "Check the network. If you need a proxy, set HTTPS_PROXY and restart ComfyUI."),
    "vault_not_configured": (
        "已开启加密，但这个网盘还没有设置保险库。",
        "在顶部 SnackNodes →「网盘设置」里新建或打开保险库；或在终端执行：{auth} vault-create {name}",
        "Encryption is on, but no vault is set up for this drive.",
        "Create or open a vault in SnackNodes > Cloud drives (top bar), or run: "
        "{auth} vault-create {name}"),
    "local_file": (
        "本地文件不存在或无法读取。",
        "检查「额外上传文件」里的路径（相对于 ComfyUI 的 output 目录）。",
        "A local file is missing or cannot be read.",
        "Check the paths given in file_paths (relative to ComfyUI's output folder)."),
    "unknown": (
        "上传失败。",
        "详细信息见下方。",
        "Upload failed.",
        "See the details below."),
}

QUOTA_HINTS = ("storagequotaexceeded", "quotaexceeded", "quotaexhausted", "insufficient storage",
               "not enough space", "space not enough", "insufficientstorage")
RATE_HINTS = ("ratelimitexceeded", "userratelimitexceeded", "too many requests", "toomanyrequests")
TOO_LARGE_HINTS = ("filesizeexceed", "file too large", "file_size_exceed", "entity too large", "entitytoolarge")


@dataclass
class Explanation:
    code: str
    zh: str
    en: str
    detail: str

    def text(self, locale: Optional[str]) -> str:
        """Message for the UI language; both languages when it is unknown."""
        if locale and locale.lower().startswith("zh"):
            return self.zh
        if locale:
            return self.en
        return f"{self.zh}\n{self.en}"


def _chain(exc: BaseException):
    while exc is not None:
        yield exc
        exc = exc.__cause__ or exc.__context__


def classify(exc: BaseException, provider_name: str = "") -> str:
    for e in _chain(exc):
        if type(e).__name__ == "VaultNotConfigured":
            return "vault_not_configured"
        if isinstance(e, (FileNotFoundError, PermissionError, IsADirectoryError)):
            return "local_file"
        if type(e).__name__ == "StorageLimitReached":
            return "storage_limit"
        if isinstance(e, requests.RequestException):
            return "network"
        if isinstance(e, CloudDriveError):
            status, body = e.status, (e.body or str(e)).lower()
            if any(h in body for h in QUOTA_HINTS) or status == 507:
                return "quota"
            if any(h in body for h in RATE_HINTS) or status == 429:
                return "rate_limited"
            if status == 413 or any(h in body for h in TOO_LARGE_HINTS):
                return "too_large"
            if provider_name in KEY_PROVIDERS and isinstance(e, AuthRequired) and status:
                return "wrong_keys"
            if status == 401:
                # WebDAV uses a password; for OAuth drives a 401 means the token is no longer valid
                return "wrong_password" if provider_name == "webdav" else "not_authorized"
            if isinstance(e, AuthRequired):
                return "not_authorized"
            if status == 403:
                return "forbidden"
            if status == 409:
                return "conflict"
            if status in (404, 410):
                return "not_found"
            if status in (500, 502, 503, 504):
                return "rate_limited" if status == 503 else "server_error"
            if e.network:
                return "network"
    return "unknown"


def explain(exc: BaseException, provider_name: str, provider_label: str, file_name: str = "",
            local_copy: str = "") -> Explanation:
    code = classify(exc, provider_name)
    zh_title, zh_hint, en_title, en_hint = MESSAGES[code]
    cmd = AUTH_COMMANDS.get(provider_name, "{auth}").format(auth=AUTH_SCRIPT)
    fill = {"provider": provider_label, "cmd": cmd, "name": provider_name, "auth": AUTH_SCRIPT}
    zh = [zh_title.format(**fill), zh_hint.format(**fill)]
    en = [en_title.format(**fill), en_hint.format(**fill)]
    if file_name:
        zh.append(f"文件：{file_name}" + (f"（本地副本已保存在 {local_copy}）" if local_copy else ""))
        en.append(f"File: {file_name}" + (f" (local copy kept at {local_copy})" if local_copy else ""))
    return Explanation(code, "\n".join(zh), "\n".join(en), str(exc))


def ui_locale() -> Optional[str]:
    """ComfyUI's interface language (Comfy.Locale in the default user's settings), if set."""
    try:
        import json
        import os

        import folder_paths
        path = os.path.join(folder_paths.get_user_directory(), "default", "comfy.settings.json")
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("Comfy.Locale") or None
    except Exception:
        return None
