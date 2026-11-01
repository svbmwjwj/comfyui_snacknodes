"""Node-level test with a stubbed ComfyUI environment (no torch needed)."""

import importlib
import os
import sys
import types

import numpy as np
import pytest

from cloud_drive import cryptomator as cm
from cloud_drive.config import CredentialStore
from cloud_drive.vault import CryptomatorVault
from local_provider import LocalProvider


class FakeTensor:
    def __init__(self, arr):
        self.arr = arr
        self.shape = arr.shape

    def __iter__(self):
        return (FakeTensor(a) for a in self.arr)

    def __getitem__(self, i):
        return FakeTensor(self.arr[i])

    def cpu(self):
        return self

    def numpy(self):
        return self.arr


@pytest.fixture
def node_module(tmp_path, monkeypatch):
    out, tmp, inp = (tmp_path / n for n in ("output", "temp", "input"))
    for d in (out, tmp, inp):
        d.mkdir()
    fp = types.ModuleType("folder_paths")
    fp.get_output_directory = lambda: str(out)
    fp.get_temp_directory = lambda: str(tmp)
    fp.get_input_directory = lambda: str(inp)

    def get_save_image_path(prefix, output_dir, w=0, h=0):
        return output_dir, prefix, 1, "", prefix
    fp.get_save_image_path = get_save_image_path
    monkeypatch.setitem(sys.modules, "folder_paths", fp)
    monkeypatch.setenv("SNACKNODES_CONFIG_DIR", str(tmp_path / "cfg"))

    # import the package the way ComfyUI does: as a top-level package from custom_nodes/
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.syspath_prepend(os.path.dirname(root))
    pkg = os.path.basename(root)
    for name in [m for m in sys.modules if m == pkg or m.startswith(pkg + ".")]:
        monkeypatch.delitem(sys.modules, name)
    mod = importlib.import_module(f"{pkg}.nodes.save_to_cloud_drive")
    drive = tmp_path / "drive"
    drive.mkdir()
    local = LocalProvider(drive)
    monkeypatch.setitem(mod.PROVIDERS, "google_drive", lambda: local)
    return mod, out, drive, local


def test_registration():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "__init__.py")).read()
    assert '"SnackSaveToCloudDrive"' in src


def test_plain_upload(node_module):
    mod, out, drive, _ = node_module
    images = FakeTensor(np.random.rand(2, 8, 8, 3).astype(np.float32))
    res = mod.SaveToCloudDrive().save_and_upload("Google Drive", "none", "ComfyUI/x", "pic", True, images=images)
    lines = res["result"][0].splitlines()
    assert lines == ["local:ComfyUI/x/pic_00001_.png", "local:ComfyUI/x/pic_00002_.png"]
    assert (drive / "ComfyUI" / "x" / "pic_00001_.png").read_bytes() == (out / "pic_00001_.png").read_bytes()
    assert len(res["ui"]["images"]) == 2


def test_encrypted_upload(node_module, tmp_path):
    mod, out, drive, local = node_module
    vault = CryptomatorVault.create(local, "Vault", "pw123456")
    store = CredentialStore()
    store.update("vault:local", {"path": "Vault", **vault.keys.to_dict()})
    images = FakeTensor(np.random.rand(1, 8, 8, 3).astype(np.float32))
    res = mod.SaveToCloudDrive().save_and_upload("Google Drive", "Cryptomator vault", "ComfyUI", "pic", True,
                                                 images=images)
    assert res["result"][0] == "local:Vault/ComfyUI/pic_00001_.png [encrypted]"
    assert not (drive / "ComfyUI").exists()
    # find the single encrypted png and decrypt it
    enc = [os.path.join(r, f) for r, _, fs in os.walk(drive / "Vault" / "d") for f in fs
           if f.endswith(".c9r") and f not in ("dir.c9r", "dirid.c9r")]
    assert len(enc) == 1
    assert cm.decrypt_bytes(vault.keys, open(enc[0], "rb").read()) == (out / "pic_00001_.png").read_bytes()


def test_file_paths_outside_comfy_dirs_are_refused(node_module, tmp_path):
    mod, out, _, _ = node_module
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    with pytest.raises(ValueError, match="Refusing"):
        mod.SaveToCloudDrive().save_and_upload("Google Drive", "none", "a", "p", True, file_paths=str(secret))
    with pytest.raises(ValueError, match="Refusing"):
        mod.SaveToCloudDrive().save_and_upload("Google Drive", "none", "a", "p", True, file_paths="../secret.txt")
    (out / "ok.txt").write_text("fine")
    res = mod.SaveToCloudDrive().save_and_upload("Google Drive", "none", "a", "p", True, file_paths="ok.txt")
    assert res["result"][0] == "local:a/ok.txt"


def test_nothing_to_upload(node_module):
    mod = node_module[0]
    with pytest.raises(ValueError, match="Nothing to upload"):
        mod.SaveToCloudDrive().save_and_upload("Google Drive", "none", "a", "p", True)


def test_expand_date_tokens(node_module):
    from datetime import datetime
    mod = node_module[0]
    now = datetime(2026, 3, 7, 9, 5, 4)
    assert mod.expand_date_tokens("ComfyUI/%date:yyyy-MM-dd%/x", now) == "ComfyUI/2026-03-07/x"
    assert mod.expand_date_tokens("%date:yyMMdd_hhmmss%", now) == "260307_090504"
    assert mod.expand_date_tokens("%year%/%month%/%day% %hour%%minute%%second%", now) == "2026/03/07 090504"
    assert mod.expand_date_tokens("plain/%width%", now) == "plain/%width%"


def test_remote_folder_date_tokens(node_module):
    from datetime import datetime
    mod, _, drive, _ = node_module
    images = FakeTensor(np.random.rand(1, 8, 8, 3).astype(np.float32))
    res = mod.SaveToCloudDrive().save_and_upload("Google Drive", "none", "ComfyUI/%date:yyyy-MM%", "pic", True,
                                                 images=images)
    month = datetime.now().strftime("%Y-%m")
    assert res["result"][0] == f"local:ComfyUI/{month}/pic_00001_.png"
    assert (drive / "ComfyUI" / month / "pic_00001_.png").exists()
