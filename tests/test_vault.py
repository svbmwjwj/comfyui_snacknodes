import os

import pytest

from cloud_drive import cryptomator as cm
from cloud_drive.base import CloudDriveError
from cloud_drive.config import CredentialStore
from cloud_drive.vault import CryptomatorVault
from local_provider import LocalProvider


def _decrypt_tree(root, keys, dir_id="", prefix=""):
    """Independent reader: walk the vault layout and return {clear_path: bytes}."""
    a, b = cm.dir_path(keys, dir_id)
    folder = os.path.join(root, "d", a, b)
    out = {}
    for node in os.listdir(folder):
        full = os.path.join(folder, node)
        if node == "dirid.c9r":
            assert cm.decrypt_bytes(keys, open(full, "rb").read()).decode() == dir_id
            continue
        if node.endswith(".c9s"):
            enc = open(os.path.join(full, "name.c9s")).read()
            assert cm.shortened_name(enc) == node
        else:
            enc = node
        name = cm.decrypt_name(keys, enc, dir_id)
        if os.path.isdir(full) and os.path.exists(os.path.join(full, "dir.c9r")):
            child = open(os.path.join(full, "dir.c9r")).read()
            out.update(_decrypt_tree(root, keys, child, f"{prefix}{name}/"))
        else:
            path = os.path.join(full, "contents.c9r") if node.endswith(".c9s") else full
            out[prefix + name] = cm.decrypt_bytes(keys, open(path, "rb").read())
    return out


@pytest.fixture
def src(tmp_path):
    def make(name, data):
        p = tmp_path / "src" / name
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(data)
        return str(p)
    return make


def test_create_upload_and_read_back(tmp_path, src):
    drive = tmp_path / "drive"
    drive.mkdir()
    provider = LocalProvider(drive)
    vault = CryptomatorVault.create(provider, "Vault", "correct horse")
    long_name = "L" * 200 + ".png"
    vault.upload(src("a", b"one"), "ComfyUI", "a.png")
    vault.upload(src("b", b"two"), "ComfyUI/深层/x", "图.png")
    vault.upload(src("c", b"three"), "ComfyUI", long_name)
    r = vault.upload(src("d", b"dup"), "ComfyUI", "a.png")
    assert r.remote_path == "Vault/ComfyUI/a_1.png" and r.encrypted

    tree = _decrypt_tree(str(drive / "Vault"), vault.keys)
    assert tree == {"ComfyUI/a.png": b"one", "ComfyUI/a_1.png": b"dup",
                    "ComfyUI/深层/x/图.png": b"two", f"ComfyUI/{long_name}": b"three"}
    # nothing readable leaks into the drive's file names
    for _, dirs, files in os.walk(drive):
        for n in dirs + files:
            assert "ComfyUI" not in n and ".png" not in n


def test_unlock_reuses_existing_folders(tmp_path, src):
    drive = tmp_path / "drive"
    drive.mkdir()
    provider = LocalProvider(drive)
    CryptomatorVault.create(provider, "Vault", "pw123456").upload(src("a", b"1"), "Out", "a.png")
    again = CryptomatorVault.unlock(LocalProvider(drive), "Vault", "pw123456")
    again.upload(src("b", b"2"), "Out", "b.png")
    assert _decrypt_tree(str(drive / "Vault"), again.keys) == {"Out/a.png": b"1", "Out/b.png": b"2"}


def test_unlock_wrong_password_and_missing_vault(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    provider = LocalProvider(drive)
    with pytest.raises(CloudDriveError, match="No Cryptomator vault"):
        CryptomatorVault.unlock(provider, "Vault", "x")
    CryptomatorVault.create(provider, "Vault", "right-password")
    with pytest.raises(cm.VaultError):
        CryptomatorVault.unlock(provider, "Vault", "wrong-password")
    with pytest.raises(CloudDriveError, match="already exists"):
        CryptomatorVault.create(provider, "Vault", "right-password")


def test_keys_persist_in_store(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    store = CredentialStore(tmp_path / "cfg" / "c.json")
    provider = LocalProvider(drive)
    CryptomatorVault.create(provider, "Vault", "pw123456").save(store)
    assert oct(os.stat(store.path).st_mode & 0o777) == "0o600"
    loaded = CryptomatorVault.load(provider, store)
    assert loaded.vault_path == "Vault"
    with pytest.raises(CloudDriveError, match="No vault configured"):
        CryptomatorVault.load(provider, CredentialStore(tmp_path / "empty.json"))
