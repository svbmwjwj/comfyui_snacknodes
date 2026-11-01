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

from ..cloud_drive import PROVIDERS, CloudDriveError
from ..cloud_drive.vault import CryptomatorVault

logger = logging.getLogger(__name__)

PROVIDER_LABELS = {cls.display_name: name for name, cls in PROVIDERS.items()}
ENCRYPTION_OPTIONS = ["none", "Cryptomator vault"]


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


class SaveToCloudDrive:
    """Save outputs locally, then upload them to Google Drive, a WebDAV server or Aliyun Drive,
    optionally end-to-end encrypted into a Cryptomator vault."""

    CATEGORY = "SnackNodes"
    FUNCTION = "save_and_upload"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("remote_paths",)
    OUTPUT_TOOLTIPS = ("One line per uploaded file: a share link when the drive provides one, "
                       "otherwise provider:path.",)
    # English texts live here; other languages in locales/<lang>/nodeDefs.json.
    DESCRIPTION = """Upload images, a video or existing files to your own cloud drive, optionally end-to-end encrypted.

One-time setup (in a terminal on the ComfyUI machine):
  python custom_nodes/comfyui_snacknodes/auth.py google_drive
  python custom_nodes/comfyui_snacknodes/auth.py webdav --url URL --username USER
  python custom_nodes/comfyui_snacknodes/auth.py vault-create webdav   (only for encryption)
Credentials are stored on that machine, never in the workflow.

Usage
- Connect images and/or video; pick the drive.
- remote_folder: folder on the drive, created if missing. Date tokens:
  ComfyUI/%date:yyyy-MM-dd%  ->  ComfyUI/2026-11-01
  ComfyUI/%year%/%month%     ->  ComfyUI/2026/11
- encryption = Cryptomator vault: file contents and names are encrypted before upload;
  open them with the Cryptomator app.
- preview: show the images on the node after the run.
- Advanced: filename_prefix and keep_local_copy control the local copy.
- file_paths (input): connect a text node listing files that already exist in the output
  folder, one per line, e.g. video/ComfyUI_00001_.mp4
Existing files are never overwritten (name_1, name_2 ...)."""
    SEARCH_ALIASES = ["upload", "google drive", "aliyun", "alipan", "cloud", "export", "backup",
                      "encrypt", "cryptomator", "webdav", "nutstore", "jianguoyun", "nextcloud",
                      "上传", "网盘", "云盘", "备份", "加密", "坚果云"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "provider": (list(PROVIDER_LABELS), {
                    "tooltip": "Which cloud drive to upload to. Authorize it once with auth.py.",
                }),
                "remote_folder": ("STRING", {
                    "default": "ComfyUI/%date:yyyy-MM-dd%",
                    "tooltip": "Folder on the drive (inside the vault when encrypting); created if missing. "
                               "Date tokens: %date:yyyy-MM-dd%, %year%, %month%, %day%, %hour%, %minute%, "
                               "%second% (server local time). Example: ComfyUI/%date:yyyy-MM%",
                }),
                "encryption": (ENCRYPTION_OPTIONS, {
                    "default": "none",
                    "tooltip": "Cryptomator vault: file contents and names are encrypted before upload; open "
                               "them with the Cryptomator app. Create the vault once with auth.py vault-create.",
                }),
                "preview": ("BOOLEAN", {
                    "default": True, "label_on": "开 on", "label_off": "关 off",
                    "tooltip": "Show the saved images on the node after the run.",
                }),
                "filename_prefix": ("STRING", {
                    "default": "ComfyUI", "advanced": True,
                    "tooltip": "Name prefix for saved images/videos, same as Save Image. A sub folder is "
                               "allowed, e.g. portraits/ComfyUI",
                }),
                "keep_local_copy": ("BOOLEAN", {
                    "default": True, "advanced": True, "label_on": "开 on", "label_off": "关 off",
                    "tooltip": "On: also keep the files in ComfyUI's output folder. Off: use the temp folder "
                               "(cleared when ComfyUI restarts).",
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
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    def save_and_upload(self, provider, remote_folder, encryption, preview=True, filename_prefix="ComfyUI",
                        keep_local_copy=True, images=None, video=None, file_paths="", prompt=None,
                        extra_pnginfo=None):
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

        client = PROVIDERS[provider_name]()
        vault = CryptomatorVault.load(client) if encryption == "Cryptomator vault" else None
        results = []
        for path in to_upload:
            mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
            try:
                if vault is not None:
                    result = vault.upload(path, remote_folder)
                else:
                    result = client.upload(path, remote_folder, mime_type=mime)
            except CloudDriveError as e:
                raise RuntimeError(f"Upload to {provider} failed for {os.path.basename(path)}: {e}"
                                   + (f" (local copy kept at {path})" if keep_local_copy else "")) from e
            logger.info("Uploaded %s -> %s", path, result.describe())
            results.append(result.describe())

        text = "\n".join(results)
        ui = {"text": [text]}
        if preview and ui_images:
            ui["images"] = ui_images
        return {"ui": ui, "result": (text,)}

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
