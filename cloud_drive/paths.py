"""Where this plugin is installed, for the terminal commands shown in hints.

The folder is SnackNodes when installed from the Comfy Registry (the node ID), but older installs
and manual clones may use another name (e.g. comfyui_snacknodes), so read it instead of hard-coding.
"""

import os
from pathlib import Path

# Not resolve(): with a symlink in custom_nodes/ (common for development) ComfyUI uses the link's name.
PLUGIN_DIR = Path(os.path.abspath(__file__)).parent.parent.name
AUTH_SCRIPT = f"python custom_nodes/{PLUGIN_DIR}/auth.py"
