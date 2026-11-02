"""Upload files to personal cloud drives."""

from .aliyundrive import AliyunDrive
from .base import AuthRequired, CloudDriveError, UploadResult
from .config import CredentialStore, config_dir
from .google_drive import GoogleDrive
from .s3 import R2, S3
from .webdav import WebDAV

# Order = order in the node's provider dropdown.
PROVIDERS = {GoogleDrive.name: GoogleDrive, WebDAV.name: WebDAV, R2.name: R2, S3.name: S3,
             AliyunDrive.name: AliyunDrive}

__all__ = ["PROVIDERS", "AliyunDrive", "GoogleDrive", "AuthRequired", "CloudDriveError",
           "UploadResult", "CredentialStore", "R2", "S3", "WebDAV", "config_dir"]
