"""Where this plugin is installed, for the terminal commands shown in hints.

The folder is SnackNodes when installed from the Comfy Registry (the node ID), but older installs
and manual clones may use another name (e.g. comfyui_snacknodes), so read it instead of hard-coding.
"""

from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent.name
AUTH_SCRIPT = f"python custom_nodes/{PLUGIN_DIR}/auth.py"
