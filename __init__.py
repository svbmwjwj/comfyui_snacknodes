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

    try:
        # Background uploads: continue what an earlier run left unfinished, and tell the page about progress.
        from .cloud_drive.uploads import get_queue

        def _notify(event):
            PromptServer.instance.send_sync("snacknodes.upload", event)

        _queue = get_queue()
        _queue.notify = _notify
        _queue.start()
        _left = _queue.summary()["files_left"]
        logging.getLogger(__name__).info("SnackNodes: background uploads ready%s",
                                         f" ({_left} file(s) left from before, continuing)" if _left else "")
    except Exception:  # noqa: BLE001 - uploads with wait_for_upload still work
        logging.getLogger(__name__).exception("SnackNodes: could not start background uploads")

# Frontend extension (shows the upload result on the node) and locales/ live next to this file.
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
