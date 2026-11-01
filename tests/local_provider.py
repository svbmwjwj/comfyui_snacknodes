"""A Provider backed by a local directory, for tests (ids are relative paths)."""

import os
import shutil

from cloud_drive.base import CloudDriveError, Provider


class LocalProvider(Provider):
    name = "local"
    display_name = "Local"
    root_id = ""

    def __init__(self, root):
        super().__init__()
        self.root = str(root)

    def _abs(self, file_id):
        return os.path.join(self.root, file_id)

    def find_child(self, parent_id, name):
        rel = os.path.join(parent_id, name) if parent_id else name
        return rel if os.path.exists(self._abs(rel)) else None

    def create_folder(self, parent_id, name):
        rel = os.path.join(parent_id, name) if parent_id else name
        os.makedirs(self._abs(rel), exist_ok=True)
        return rel

    def upload_file(self, parent_id, name, local_path, mime_type="application/octet-stream", allow_rename=True,
                    progress=None):
        rel = os.path.join(parent_id, name) if parent_id else name
        if os.path.exists(self._abs(rel)):
            if not allow_rename:
                raise CloudDriveError("exists")
            raise AssertionError("tests never upload duplicates")
        shutil.copyfile(local_path, self._abs(rel))
        if progress:
            size = os.path.getsize(local_path)
            progress(size, size)
        return rel, name, None

    def download(self, file_id):
        with open(self._abs(file_id), "rb") as f:
            return f.read()
