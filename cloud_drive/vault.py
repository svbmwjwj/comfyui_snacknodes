"""Write files into a Cryptomator vault stored on any Provider.

Everything that leaves the machine is encrypted: file contents, file names and
folder names. The cloud drive only sees the vault's opaque d/XX/YYYY layout.
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional

from . import cryptomator as cm
from .base import CloudDriveError, Progress, Provider, UploadResult, split_folder
from .config import CredentialStore
from .paths import AUTH_SCRIPT

class VaultNotConfigured(CloudDriveError):
    """Encryption is on but no vault was created/unlocked for this drive."""


AUTH_HINT = ("Set it up below encrypt on the node, or run: "
             f"{AUTH_SCRIPT} vault-create (or vault-unlock)")


def _store_key(provider_name: str) -> str:
    return f"vault:{provider_name}"


class CryptomatorVault:
    def __init__(self, provider: Provider, vault_path: str, keys: cm.VaultKeys):
        self.provider = provider
        self.vault_path = "/".join(split_folder(vault_path))
        self.keys = keys
        self._root_id: Optional[str] = None
        self._dir_ids: dict[str, str] = {"": ""}  # clear path -> dir id

    # ---------------------------------------------------------- lifecycle
    @classmethod
    def create(cls, provider: Provider, vault_path: str, password: str) -> CryptomatorVault:
        if provider.find_path(vault_path + "/" + cm.VAULT_CONFIG_FILE):
            raise CloudDriveError(f"A vault already exists at {vault_path}; use vault-unlock")
        keys = cm.VaultKeys.generate()
        vault = cls(provider, vault_path, keys)
        root = vault._vault_root()
        vault._upload_bytes(root, cm.MASTERKEY_FILE, cm.create_masterkey_file(keys, password))
        vault._upload_bytes(root, cm.VAULT_CONFIG_FILE, cm.create_vault_config(keys))
        vault._create_content_dir("")
        return vault

    @classmethod
    def unlock(cls, provider: Provider, vault_path: str, password: str) -> CryptomatorVault:
        mk_id = provider.find_path(vault_path + "/" + cm.MASTERKEY_FILE)
        cfg_id = provider.find_path(vault_path + "/" + cm.VAULT_CONFIG_FILE)
        if not (mk_id and cfg_id):
            hint = (" Google Drive can only see vaults created by this tool; create one with vault-create."
                    if provider.name == "google_drive" else " Check the path (it is case-sensitive).")
            raise CloudDriveError(f"No Cryptomator vault found at {vault_path}.{hint}")
        keys = cm.unlock_masterkey_file(provider.download(mk_id), password)
        cm.verify_vault_config(provider.download(cfg_id), keys)
        return cls(provider, vault_path, keys)

    def save(self, store: CredentialStore) -> None:
        store.update(_store_key(self.provider.name), {"path": self.vault_path, **self.keys.to_dict()})

    @classmethod
    def load(cls, provider: Provider, store: Optional[CredentialStore] = None) -> CryptomatorVault:
        data = (store or CredentialStore()).get(_store_key(provider.name))
        if not data.get("enc_key"):
            raise VaultNotConfigured(f"No vault configured for {provider.display_name}. {AUTH_HINT}")
        return cls(provider, data["path"], cm.VaultKeys.from_dict(data))

    # ---------------------------------------------------------- internals
    def _vault_root(self) -> str:
        if self._root_id is None:
            self._root_id = self.provider.ensure_folder(self.vault_path)
        return self._root_id

    def _upload_bytes(self, parent_id: str, name: str, data: bytes) -> str:
        fd, tmp = tempfile.mkstemp(prefix="snack_vault_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            return self.provider.upload_file(parent_id, name, tmp, allow_rename=False)[0]
        finally:
            os.unlink(tmp)

    def _content_dir(self, dir_id: str) -> str:
        a, b = cm.dir_path(self.keys, dir_id)
        p = self.provider
        return p.ensure_child_folder(p.ensure_child_folder(p.ensure_child_folder(
            self._vault_root(), cm.DATA_DIR), a), b)

    def _create_content_dir(self, dir_id: str) -> str:
        folder = self._content_dir(dir_id)
        # dirid.c9r: encrypted backup of the dir id, used by Cryptomator's recovery tools
        self._upload_bytes(folder, "dirid.c9r", cm.encrypt_bytes(self.keys, dir_id.encode()))
        return folder

    def _node(self, parent_folder: str, name: str, parent_dir_id: str) -> tuple[str, Optional[str], bool]:
        """Returns (node_name, existing_node_id, shortened)."""
        full = cm.encrypt_name(self.keys, name, parent_dir_id)
        node = cm.shortened_name(full) if cm.needs_shortening(full) else full
        return node, self.provider.find_child(parent_folder, node), node != full

    def ensure_dir(self, clear_path: str) -> str:
        """Returns the dir id of a clear-text folder inside the vault, creating it if needed."""
        parts = split_folder(clear_path)
        dir_id = ""
        for i, part in enumerate(parts):
            key = "/".join(parts[: i + 1])
            if key in self._dir_ids:
                dir_id = self._dir_ids[key]
                continue
            parent_folder = self._content_dir(dir_id)
            node, node_id, short = self._node(parent_folder, part, dir_id)
            if node_id:
                marker = self.provider.find_child(node_id, "dir.c9r")
                if not marker:
                    raise CloudDriveError(f"Vault folder '{key}' is a file or is damaged")
                dir_id = self.provider.download(marker).decode("utf-8")
            else:
                new_id = cm.new_dir_id()
                node_id = self.provider.create_folder(parent_folder, node)
                if short:
                    self._upload_bytes(node_id, "name.c9s",
                                       cm.encrypt_name(self.keys, part, dir_id).encode())
                self._upload_bytes(node_id, "dir.c9r", new_id.encode("utf-8"))
                self._create_content_dir(new_id)
                dir_id = new_id
            self._dir_ids[key] = dir_id
        return dir_id

    def upload(self, local_path: str, clear_folder: str, clear_name: Optional[str] = None,
               progress: Optional[Progress] = None) -> UploadResult:
        dir_id = self.ensure_dir(clear_folder)
        folder = self._content_dir(dir_id)
        base = clear_name or os.path.basename(local_path)
        stem, ext = os.path.splitext(base)
        name, n = base, 1
        while True:  # never overwrite: pick a free clear-text name
            node, existing, short = self._node(folder, name, dir_id)
            if not existing:
                break
            name, n = f"{stem}_{n}{ext}", n + 1

        fd, tmp = tempfile.mkstemp(prefix="snack_vault_")
        try:
            with os.fdopen(fd, "wb") as dst, open(local_path, "rb") as src:
                cm.encrypt_stream(self.keys, src, dst)
            if short:
                node_id = self.provider.create_folder(folder, node)
                self._upload_bytes(node_id, "name.c9s", cm.encrypt_name(self.keys, name, dir_id).encode())
                file_id = self.provider.upload_file(node_id, "contents.c9r", tmp, allow_rename=False,
                                                    progress=progress)[0]
            else:
                file_id = self.provider.upload_file(folder, node, tmp, allow_rename=False, progress=progress)[0]
        finally:
            os.unlink(tmp)
        clear = "/".join(split_folder(self.vault_path) + split_folder(clear_folder) + [name])
        return UploadResult(self.provider.name, clear, file_id, encrypted=True)
