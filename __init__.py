"""ComfyUI SnackNodes package."""

from .nodes.save_to_cloud_drive import SaveToCloudDrive

NODE_CLASS_MAPPINGS = {
    "SnackSaveToCloudDrive": SaveToCloudDrive,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SnackSaveToCloudDrive": "Save to Cloud Drive",
}

try:  # only inside a running ComfyUI server
    from server import PromptServer

    from .nodes.routes import register

    register(PromptServer.instance.routes)
except ImportError:  # tests, or no ComfyUI server: the terminal auth.py still works
    pass
except Exception:  # noqa: BLE001 - never stop the node from loading because of the setup panel
    import logging
    logging.getLogger(__name__).exception("SnackNodes: could not add the drive setup routes")

# Frontend extension (shows the upload result on the node) and locales/ live next to this file.
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
