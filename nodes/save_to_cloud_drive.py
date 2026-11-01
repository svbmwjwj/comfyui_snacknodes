"""Save to Cloud Drive: save images / video / files and upload them to a personal cloud drive."""

from __future__ import annotations

import json
import logging
import mimetypes
import os

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from ..cloud_drive import PROVIDERS, CloudDriveError
from ..cloud_drive.vault import CryptomatorVault

logger = logging.getLogger(__name__)

PROVIDER_LABELS = {cls.display_name: name for name, cls in PROVIDERS.items()}
ENCRYPTION_OPTIONS = ["none", "Cryptomator vault"]


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
    """Save outputs locally, then upload them to Google Drive or Aliyun Drive,
    optionally end-to-end encrypted into a Cryptomator vault."""

    CATEGORY = "SnackNodes"
    FUNCTION = "save_and_upload"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("remote_paths",)
    OUTPUT_TOOLTIPS = ("One line per uploaded file: a share link when the drive provides one, "
                       "otherwise provider:path.",)
    DESCRIPTION = ("Uploads images, a video, or existing output files to your own cloud drive, optionally "
                   "end-to-end encrypted (Cryptomator vault). Authorize once with auth.py; credentials and "
                   "keys are never stored in the workflow.")
    SEARCH_ALIASES = ["upload", "google drive", "aliyun", "alipan", "cloud", "export", "backup",
                      "encrypt", "cryptomator"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "provider": (list(PROVIDER_LABELS), {"tooltip": "Which cloud drive to upload to."}),
                "encryption": (ENCRYPTION_OPTIONS, {
                    "default": "none",
                    "tooltip": "Cryptomator vault: file contents and names are encrypted before upload; "
                               "open them with the Cryptomator app. Set up the vault once with auth.py.",
                }),
                "remote_folder": ("STRING", {
                    "default": "ComfyUI",
                    "tooltip": "Folder on the drive (or inside the vault when encrypting), e.g. "
                               "ComfyUI/portraits. Created if missing.",
                }),
                "filename_prefix": ("STRING", {
                    "default": "ComfyUI",
                    "tooltip": "Prefix for saved images/videos. Supports the same tokens as Save Image.",
                }),
                "keep_local_copy": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Keep images/videos in the output folder. Off: use the temp folder.",
                }),
            },
            "optional": {
                "images": ("IMAGE", {"tooltip": "Images to save as PNG and upload."}),
                "video": ("VIDEO", {"tooltip": "Video to save as MP4 and upload."}),
                "file_paths": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "Existing files to upload, one per line, relative to the output folder.",
                }),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    def save_and_upload(self, provider, encryption, remote_folder, filename_prefix, keep_local_copy,
                        images=None, video=None, file_paths="", prompt=None, extra_pnginfo=None):
        provider_name = PROVIDER_LABELS.get(provider, provider)
        if provider_name not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")

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
        return {"ui": {"images": ui_images, "text": [text]}, "result": (text,)}

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
