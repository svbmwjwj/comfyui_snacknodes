"""ComfyUI SnackNodes package."""

from .nodes.save_to_cloud_drive import SaveToCloudDrive

NODE_CLASS_MAPPINGS = {
    "SnackSaveToCloudDrive": SaveToCloudDrive,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SnackSaveToCloudDrive": "Save to Cloud Drive",
}

# Frontend extension (shows the upload result on the node) and locales/ live next to this file.
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
