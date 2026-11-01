"""Upload files to personal cloud drives."""

from .aliyundrive import AliyunDrive
from .base import AuthRequired, CloudDriveError, UploadResult
from .config import CredentialStore, config_dir
from .google_drive import GoogleDrive

PROVIDERS = {GoogleDrive.name: GoogleDrive, AliyunDrive.name: AliyunDrive}

__all__ = ["PROVIDERS", "AliyunDrive", "GoogleDrive", "AuthRequired", "CloudDriveError",
           "UploadResult", "CredentialStore", "config_dir"]
