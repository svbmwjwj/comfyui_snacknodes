"""Save to Cloud Drive: save images / video / files and upload them to a personal cloud drive."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
from datetime import datetime

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from ..cloud_drive import NODE_PROVIDERS, PROVIDERS, CloudDriveError  # noqa: F401 - re-exported for tests
from ..cloud_drive.errors import explain, ui_locale
from ..cloud_drive.vault import CryptomatorVault

logger = logging.getLogger(__name__)

PROVIDER_LABELS = {PROVIDERS[name].display_name: name for name in NODE_PROVIDERS}


_DATE_TOKEN = re.compile(r"%date:([^%]+)%")
_DATE_PARTS = re.compile(r"yyyy|yy|MM|M|dd|d|hh|h|mm|m|ss|s")
_SIMPLE_TOKENS = {"year": "%Y", "month": "%m", "day": "%d", "hour": "%H", "minute": "%M", "second": "%S"}


def expand_date_tokens(text: str, now: datetime | None = None) -> str:
    """Expand %date:yyyy-MM-dd% (the Save Image syntax) and %year% %month% %day%
    %hour% %minute% %second%, using the server's local time."""
    now = now or datetime.now()
    parts = {"yyyy": f"{now.year:04}", "yy": f"{now.year % 100:02}", "MM": f"{now.month:02}",
             "M": str(now.month), "dd": f"{now.day:02}", "d": str(now.day), "hh": f"{now.hour:02}",
             "h": str(now.hour), "mm": f"{now.minute:02}", "m": str(now.minute),
             "ss": f"{now.second:02}", "s": str(now.second)}
    text = _DATE_TOKEN.sub(lambda m: _DATE_PARTS.sub(lambda p: parts[p.group(0)], m.group(1)), text or "")
    for name, fmt in _SIMPLE_TOKENS.items():
        text = text.replace(f"%{name}%", now.strftime(fmt))
    return text


def _metadata_disabled() -> bool:
    try:
        from comfy.cli_args import args
        return bool(args.disable_metadata)
    except Exception:
        return False


def _folder_paths():
    # Imported lazily: folder_paths only exists inside a running ComfyUI.
    import folder_paths
    return folder_paths


def _resolve_local_file(path: str) -> str:
    """Resolve a user-supplied path, only allowing files under ComfyUI's output/input/temp dirs."""
    folder_paths = _folder_paths()
    roots = [os.path.realpath(d) for d in (folder_paths.get_output_directory(),
                                           folder_paths.get_input_directory(),
                                           folder_paths.get_temp_directory())]
    candidate = path if os.path.isabs(path) else os.path.join(roots[0], path)
    real = os.path.realpath(candidate)
    if not any(real == r or real.startswith(r + os.sep) for r in roots):
        raise ValueError(f"Refusing to upload '{path}': only files inside ComfyUI's output, input "
                         f"or temp directories can be uploaded.")
    if not os.path.isfile(real):
        raise FileNotFoundError(f"File not found: {path}")
    return real


def _mb(n: int) -> str:
    return f"{n / 1048576:.1f} MB"


class _ProgressReporter:
    """Node progress bar (bytes over all files) plus a short language-neutral status line,
    e.g. "2/3 · video.mp4 · 12.0/15.2 MB". Silent outside a running ComfyUI (tests)."""

    def __init__(self, paths: list[str], node_id):
        self.names = [os.path.basename(p) for p in paths]
        self.sizes = [max(os.path.getsize(p), 1) for p in paths]
        self.total = sum(self.sizes)
        self.node_id = node_id
        self.bar = self.server = None
        try:
            import comfy.utils
            self.bar = comfy.utils.ProgressBar(self.total, node_id=node_id)
        except Exception:
            pass
        try:
            from server import PromptServer
            self.server = PromptServer.instance
        except Exception:
            pass

    def _report(self, index: int, fraction: float) -> None:
        file_bytes = int(self.sizes[index] * min(max(fraction, 0.0), 1.0))
        done = sum(self.sizes[:index]) + file_bytes
        if self.bar is not None:
            self.bar.update_absolute(done, self.total)
        if self.server is not None and self.node_id is not None:
            try:
                self.server.send_progress_text(
                    f"{index + 1}/{len(self.names)} · {self.names[index]} · "
                    f"{_mb(file_bytes)}/{_mb(self.sizes[index])}", self.node_id)
            except Exception:
                pass

    def for_file(self, index: int):
        # The payload may differ in size from the local file (encryption adds overhead): use the ratio.
        def on_progress(sent: int, total: int) -> None:
            self._report(index, sent / total if total else 1.0)
        self._report(index, 0.0)
        return on_progress

    def file_done(self, index: int) -> None:
        self._report(index, 1.0)


class SaveToCloudDrive:
    """Save outputs locally, then upload them to Google Drive, a WebDAV server or Cloudflare R2,
    optionally end-to-end encrypted into a Cryptomator vault."""

    CATEGORY = "SnackNodes"
    FUNCTION = "save_and_upload"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING", "BOOLEAN")
    RETURN_NAMES = ("remote_paths", "success")
    OUTPUT_TOOLTIPS = ("One line per uploaded file: a share link when the drive provides one, "
                       "otherwise provider:path.",
                       "True when every file was uploaded. With stop_on_error off, a failed upload gives False "
                       "instead of stopping the workflow, so you can branch on it.")
    # English texts live here; other languages in locales/<lang>/nodeDefs.json.
    DESCRIPTION = ("Upload images and videos to your own cloud drive (Google Drive, WebDAV, Cloudflare R2), "
                   "optionally end-to-end encrypted. Hover over each option for details.")
    SEARCH_ALIASES = ["upload", "google drive", "aliyun", "alipan", "cloud", "export", "backup",
                      "encrypt", "cryptomator", "webdav", "nutstore", "jianguoyun", "nextcloud",
                      "s3", "r2", "cloudflare", "object storage", "minio", "backblaze",
                      "上传", "网盘", "云盘", "备份", "加密", "坚果云", "对象存储"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "provider": (list(PROVIDER_LABELS), {
                    "tooltip": "Which cloud drive to upload to. Connect it once in the rows that appear below it.",
                }),
                "remote_folder": ("STRING", {
                    "default": "ComfyUI/%date:yyyy-MM-dd%",
                    "tooltip": "Folder on the drive (inside the vault when encrypting); created if missing. "
                               "Date tokens: %date:yyyy-MM-dd%, %year%, %month%, %day%, %hour%, %minute%, "
                               "%second% (server local time). Example: ComfyUI/%date:yyyy-MM%. "
                               "Existing files are never overwritten (name_1, name_2 ...).",
                }),
                "encrypt": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Encrypt file contents and names before upload (Cryptomator vault format); open "
                               "them with the Cryptomator app. Set up the vault in the rows that appear below.",
                }),
                "preview": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Show the saved images on the node after the run.",
                }),
                "keep_local_copy": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "On: also keep the files in ComfyUI's output folder. Off: use the temp folder "
                               "(cleared when ComfyUI restarts).",
                }),
                "filename_prefix": ("STRING", {
                    "default": "ComfyUI", "advanced": True,
                    "tooltip": "Name prefix for saved images/videos, same as Save Image. A sub folder is "
                               "allowed, e.g. portraits/ComfyUI",
                }),
                "stop_on_error": ("BOOLEAN", {
                    "default": True, "advanced": True,
                    "tooltip": "On: a failed upload stops the workflow with an error. Off: the workflow "
                               "continues and the success output is False (for automation).",
                }),
            },
            "optional": {
                "images": ("IMAGE", {"tooltip": "Images to save as PNG and upload."}),
                "video": ("VIDEO", {"tooltip": "Video to save as MP4 and upload."}),
                "file_paths": ("STRING", {
                    # A socket, not a text box: most people never need it, and a multiline box is big.
                    "forceInput": True, "advanced": True,
                    "tooltip": "Optional: connect a text node listing existing files to upload, one per line, "
                               "relative to ComfyUI's output folder, e.g. video/ComfyUI_00001_.mp4",
                }),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "unique_id": "UNIQUE_ID"},
        }

    def save_and_upload(self, provider, remote_folder, encrypt=False, preview=False, keep_local_copy=True,
                        filename_prefix="ComfyUI", stop_on_error=True, images=None, video=None, file_paths="",
                        prompt=None, extra_pnginfo=None, unique_id=None):
        provider_name = PROVIDER_LABELS.get(provider, provider)
        if provider_name not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")

        now = datetime.now()
        remote_folder = expand_date_tokens(remote_folder, now)
        filename_prefix = expand_date_tokens(filename_prefix, now)
        folder_paths = _folder_paths()
        out_dir = folder_paths.get_output_directory() if keep_local_copy else folder_paths.get_temp_directory()
        save_type = "output" if keep_local_copy else "temp"
        ui_images = []
        to_upload: list[str] = []

        if images is not None:
            for path, entry in self._save_images(images, filename_prefix, out_dir, save_type, prompt, extra_pnginfo):
                to_upload.append(path)
                ui_images.append(entry)
        if video is not None:
            to_upload.append(self._save_video(video, filename_prefix, out_dir, prompt, extra_pnginfo))
        for line in (file_paths or "").splitlines():
            if line.strip():
                to_upload.append(_resolve_local_file(line.strip()))

        if not to_upload:
            raise ValueError("Nothing to upload: connect images or video, or fill in file_paths.")

        results: list[str] = []
        failure = None
        reporter = _ProgressReporter(to_upload, unique_id)
        current = None
        try:
            client = PROVIDERS[provider_name]()
            vault = CryptomatorVault.load(client) if encrypt else None
            for index, path in enumerate(to_upload):
                current = path
                mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
                on_progress = reporter.for_file(index)
                if vault is not None:
                    result = vault.upload(path, remote_folder, progress=on_progress)
                else:
                    result = client.upload(path, remote_folder, mime_type=mime, progress=on_progress)
                reporter.file_done(index)
                logger.info("Uploaded %s -> %s", path, result.describe())
                results.append(result.describe())
        except Exception as e:  # noqa: BLE001 - every upload failure is explained to the user
            failure = explain(e, provider_name, provider,
                              file_name=os.path.basename(current) if current else "",
                              local_copy=current if (current and keep_local_copy) else "")
            logger.warning("Upload to %s failed [%s]: %s", provider, failure.code, failure.detail)
            if stop_on_error:
                raise RuntimeError(f"{failure.text(ui_locale())}\n\n{failure.detail}") from e

        text = "\n".join(results)
        ui = {"text": [text], "upload_ok": [failure is None], "upload_total": [len(to_upload)]}
        if failure:
            ui["upload_error"] = [{"code": failure.code, "zh": failure.zh, "en": failure.en, "detail": failure.detail}]
        if preview and ui_images:
            ui["images"] = ui_images
        return {"ui": ui, "result": (text, failure is None)}

    @staticmethod
    def _save_images(images, filename_prefix, out_dir, save_type, prompt, extra_pnginfo):
        folder, filename, counter, subfolder, _ = _folder_paths().get_save_image_path(
            filename_prefix, out_dir, images[0].shape[1], images[0].shape[0])
        for batch_number, image in enumerate(images):
            img = Image.fromarray(np.clip(255.0 * image.cpu().numpy(), 0, 255).astype(np.uint8))
            metadata = None
            if not _metadata_disabled():
                metadata = PngInfo()
                if prompt is not None:
                    metadata.add_text("prompt", json.dumps(prompt))
                for key, value in (extra_pnginfo or {}).items():
                    metadata.add_text(key, json.dumps(value))
            file = f"{filename.replace('%batch_num%', str(batch_number))}_{counter:05}_.png"
            path = os.path.join(folder, file)
            img.save(path, pnginfo=metadata, compress_level=4)
            counter += 1
            yield path, {"filename": file, "subfolder": subfolder, "type": save_type}

    @staticmethod
    def _save_video(video, filename_prefix, out_dir, prompt, extra_pnginfo):
        from comfy_api.latest import Types

        width, height = video.get_dimensions()
        folder, filename, counter, _, _ = _folder_paths().get_save_image_path(
            filename_prefix, out_dir, width, height)
        metadata = None
        if not _metadata_disabled():
            metadata = dict(extra_pnginfo or {})
            if prompt is not None:
                metadata["prompt"] = prompt
        path = os.path.join(folder, f"{filename}_{counter:05}_.mp4")
        video.save_to(path, format=Types.VideoContainer.MP4, codec=Types.VideoCodec.H264,
                      metadata=metadata or None)
        return path
