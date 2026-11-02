"""Upload files to personal cloud drives."""

from .aliyundrive import AliyunDrive
from .base import AuthRequired, CloudDriveError, UploadResult
from .config import CredentialStore, config_dir
from .google_drive import GoogleDrive
from .s3 import R2, S3
from .webdav import WebDAV

# Every provider auth.py knows about.
PROVIDERS = {GoogleDrive.name: GoogleDrive, WebDAV.name: WebDAV, R2.name: R2, S3.name: S3,
             AliyunDrive.name: AliyunDrive}
# Shown in the node's dropdown, in this order: only drives tested with real accounts.
# S3 (generic) and Aliyun Drive stay usable from auth.py and tests until they are tested for real.
NODE_PROVIDERS = (GoogleDrive.name, WebDAV.name, R2.name)

__all__ = ["NODE_PROVIDERS", "PROVIDERS", "AliyunDrive", "GoogleDrive", "AuthRequired", "CloudDriveError",
           "UploadResult", "CredentialStore", "R2", "S3", "WebDAV", "config_dir"]
