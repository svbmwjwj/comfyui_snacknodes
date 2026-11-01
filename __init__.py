"""ComfyUI SnackNodes package."""

from .nodes.save_to_cloud_drive import SaveToCloudDrive

NODE_CLASS_MAPPINGS = {
    "SnackSaveToCloudDrive": SaveToCloudDrive,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SnackSaveToCloudDrive": "Save to Cloud Drive",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
