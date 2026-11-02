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
except ImportError:  # tests or plain Python: the terminal auth.py still works
    PromptServer = None

if PromptServer is not None:
    import logging

    try:
        from .nodes.routes import register

        register(PromptServer.instance.routes)
        logging.getLogger(__name__).info("SnackNodes: drive setup routes ready (/snacknodes/drive/...)")
    except Exception:  # noqa: BLE001 - never stop the node from loading because of the setup panel
        logging.getLogger(__name__).exception("SnackNodes: could not add the drive setup routes; "
                                              "the node still works, connect drives with auth.py")

# Frontend extension (shows the upload result on the node) and locales/ live next to this file.
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
