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


def _upload(mod, provider, encryption, remote_folder, filename_prefix, **kw):
    return mod.SaveToCloudDrive().save_and_upload(provider=provider, encrypt=encryption == "Cryptomator vault",
                                                  remote_folder=remote_folder, filename_prefix=filename_prefix,
                                                  keep_local_copy=True, **kw)


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
    res = _upload(mod, "Google Drive", "none", "ComfyUI/x", "pic", images=images)
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
    res = _upload(mod, "Google Drive", "Cryptomator vault", "ComfyUI", "pic",
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
        _upload(mod, "Google Drive", "none", "a", "p", file_paths=str(secret))
    with pytest.raises(ValueError, match="Refusing"):
        _upload(mod, "Google Drive", "none", "a", "p", file_paths="../secret.txt")
    (out / "ok.txt").write_text("fine")
    res = _upload(mod, "Google Drive", "none", "a", "p", file_paths="ok.txt")
    assert res["result"][0] == "local:a/ok.txt"


def test_nothing_to_upload(node_module):
    mod = node_module[0]
    with pytest.raises(ValueError, match="Nothing to upload"):
        _upload(mod, "Google Drive", "none", "a", "p")


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
    res = _upload(mod, "Google Drive", "none", "ComfyUI/%date:yyyy-MM%", "pic",
                                                 images=images)
    month = datetime.now().strftime("%Y-%m")
    assert res["result"][0] == f"local:ComfyUI/{month}/pic_00001_.png"
    assert (drive / "ComfyUI" / month / "pic_00001_.png").exists()


def test_preview_switch(node_module):
    mod = node_module[0]
    images = FakeTensor(np.random.rand(1, 8, 8, 3).astype(np.float32))
    on = mod.SaveToCloudDrive().save_and_upload(provider="Google Drive", remote_folder="p", encrypt=False,
                                                preview=True, filename_prefix="on", images=images)
    off = mod.SaveToCloudDrive().save_and_upload(provider="Google Drive", remote_folder="p", encrypt=False,
                                                 preview=False, filename_prefix="off", images=images)
    assert len(on["ui"]["images"]) == 1 and "images" not in off["ui"]
    assert on["result"][1] is True and on["ui"]["upload_ok"] == [True]
    assert off["ui"]["text"] == ["local:p/off_00001_.png"]


def test_layout_and_defaults(node_module):
    mod = node_module[0]
    spec = mod.SaveToCloudDrive.INPUT_TYPES()
    assert list(spec["required"]) == ["provider", "remote_folder", "encrypt", "preview", "keep_local_copy",
                                      "filename_prefix", "stop_on_error"]
    assert spec["required"]["remote_folder"][1]["default"] == "ComfyUI/%date:yyyy-MM-dd%"
    advanced = [k for part in ("required", "optional") for k, v in spec[part].items() if v[1].get("advanced")]
    assert advanced == ["filename_prefix", "stop_on_error", "file_paths"]
    assert mod.SaveToCloudDrive.RETURN_TYPES == ("STRING", "BOOLEAN")
    assert spec["required"]["encrypt"][1]["default"] is False and spec["required"]["stop_on_error"][1]["default"]


def test_locales_cover_every_input(node_module):
    import json
    mod = node_module[0]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = mod.SaveToCloudDrive.INPUT_TYPES()
    names = set(spec["required"]) | set(spec["optional"])
    for lang in ("en", "zh"):
        with open(os.path.join(root, "locales", lang, "nodeDefs.json"), encoding="utf-8") as f:
            node = json.load(f)["SnackSaveToCloudDrive"]
        assert set(node["inputs"]) == names, lang
        assert all(v["name"] and v["tooltip"] for v in node["inputs"].values()), lang
        assert node["display_name"] and node["description"], lang
        assert len(node["outputs"]) == len(mod.SaveToCloudDrive.RETURN_TYPES), lang


def test_stop_on_error(node_module, monkeypatch):
    mod = node_module[0]

    class Broken:  # uses the node's own CloudDriveError (package import, not tests/ path)
        def upload(self, *a, **kw):
            raise mod.CloudDriveError("HTTP 503 server busy")
    monkeypatch.setitem(mod.PROVIDERS, "google_drive", Broken)
    images = FakeTensor(np.random.rand(1, 8, 8, 3).astype(np.float32))
    with pytest.raises(RuntimeError, match="503"):
        _upload(mod, "Google Drive", "none", "a", "p", images=images)
    res = _upload(mod, "Google Drive", "none", "a", "q", images=images, stop_on_error=False)
    assert res["result"] == ("", False)
    assert res["ui"]["upload_ok"] == [False] and "503" in res["ui"]["upload_error"][0]


def test_progress_reports_bytes_over_all_files(node_module, monkeypatch, tmp_path):
    mod, out, _, _ = node_module
    (out / "a.bin").write_bytes(b"x" * 300)
    (out / "b.bin").write_bytes(b"y" * 100)
    calls, texts = [], []

    class Bar:
        def __init__(self, total, node_id=None):
            self.total = total

        def update_absolute(self, value, total=None):
            calls.append((value, total))

    class Server:
        def send_progress_text(self, text, node_id):
            texts.append((text, node_id))

    comfy = types.ModuleType("comfy")
    comfy.utils = types.SimpleNamespace(ProgressBar=Bar)
    monkeypatch.setitem(sys.modules, "comfy", comfy)
    monkeypatch.setitem(sys.modules, "comfy.utils", comfy.utils)
    monkeypatch.setitem(sys.modules, "server", types.SimpleNamespace(PromptServer=types.SimpleNamespace(
        instance=Server())))
    res = mod.SaveToCloudDrive().save_and_upload(provider="Google Drive", remote_folder="r",
                                                 file_paths="a.bin\nb.bin", unique_id="7")
    assert res["result"][1] is True
    assert calls[-1] == (400, 400) and all(t == 400 for _, t in calls)
    assert [v for v, _ in calls] == sorted(v for v, _ in calls)  # never goes backwards
    assert texts[-1] == ("2/2 · b.bin · 0.0 MB/0.0 MB", "7") and texts[0][0].startswith("1/2 · a.bin")
