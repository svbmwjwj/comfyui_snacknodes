#!/usr/bin/env python3
"""One-time setup for Save to Cloud Drive. Run on the machine that runs ComfyUI.

  python auth.py google_drive  --client-id ID --client-secret SECRET
  python auth.py aliyundrive   --client-id ID --client-secret SECRET
  python auth.py vault-create  google_drive  --path ComfyUI-Vault
  python auth.py vault-unlock  aliyundrive   --path ComfyUI-Vault
  python auth.py status
  python auth.py logout        google_drive

Credentials go to ~/.config/comfyui_snacknodes/cloud_drive.json (mode 600), or to
$SNACKNODES_CONFIG_DIR. They are never written into workflows.
Vault passwords are read interactively (or from $SNACK_VAULT_PASSWORD) and are
not stored; only the unlocked vault keys are kept in the credential file.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cloud_drive import PROVIDERS, CredentialStore  # noqa: E402
from cloud_drive.base import CloudDriveError  # noqa: E402
from cloud_drive.cryptomator import VaultError  # noqa: E402
from cloud_drive.vault import CryptomatorVault  # noqa: E402


def _ask(prompt: str, value: str | None, secret: bool = False) -> str:
    if value:
        return value
    return (getpass.getpass if secret else input)(prompt).strip()


def auth_google(args, store):
    from cloud_drive.google_drive import GoogleDrive
    client_id = _ask("Google OAuth client ID: ", args.client_id or os.environ.get("SNACK_GDRIVE_CLIENT_ID"))
    client_secret = _ask("Google OAuth client secret: ",
                         args.client_secret or os.environ.get("SNACK_GDRIVE_CLIENT_SECRET"), secret=True)
    drive = GoogleDrive(store)
    flow = drive.start_device_flow(client_id)
    print(f"\n  1. On any device, open:  {flow['verification_url']}")
    print(f"  2. Enter this code:       {flow['user_code']}\n")
    print("Waiting for approval...")
    drive.finish_device_flow(client_id, client_secret, flow)
    print("Google Drive authorized.")


def auth_aliyun(args, store):
    from cloud_drive.aliyundrive import AliyunDrive
    client_id = _ask("Aliyun Drive Open Platform client_id: ",
                     args.client_id or os.environ.get("SNACK_ALIYUNDRIVE_CLIENT_ID"))
    client_secret = _ask("Aliyun Drive Open Platform client_secret: ",
                         args.client_secret or os.environ.get("SNACK_ALIYUNDRIVE_CLIENT_SECRET"), secret=True)
    drive = AliyunDrive(store)
    if args.refresh_token:
        drive.import_refresh_token(client_id, client_secret, args.refresh_token)
        print("Aliyun Drive authorized (refresh token imported).")
        return
    qr = drive.start_qr_flow(client_id, client_secret)
    print("\n  Open this QR code image and scan it with the Aliyun Drive (阿里云盘) app:")
    print(f"  {qr['qrCodeUrl']}\n")
    labels = {"WaitLogin": "waiting for scan...", "ScanSuccess": "scanned, confirm in the app...",
              "LoginSuccess": "confirmed."}
    drive.finish_qr_flow(client_id, client_secret, qr["sid"],
                         on_status=lambda s: print(" ", labels.get(s, s)))
    print("Aliyun Drive authorized.")


def _vault_password(confirm: bool) -> str:
    env = os.environ.get("SNACK_VAULT_PASSWORD")
    if env:
        return env
    pw = getpass.getpass("Vault password: ")
    if confirm:
        if len(pw) < 8:
            sys.exit("Use at least 8 characters. There is no way to recover a forgotten vault password.")
        if getpass.getpass("Repeat password: ") != pw:
            sys.exit("Passwords do not match.")
    return pw


def vault(args, store, create: bool):
    provider = PROVIDERS[args.provider](store)
    password = _vault_password(confirm=create)
    print("Deriving key (scrypt, a few seconds)...")
    if create:
        v = CryptomatorVault.create(provider, args.path, password)
        print(f"Created Cryptomator vault '{args.path}' on {provider.display_name}.")
        print("IMPORTANT: store the password safely; without it the files cannot be decrypted.")
    else:
        v = CryptomatorVault.unlock(provider, args.path, password)
        print(f"Unlocked vault '{args.path}' on {provider.display_name}.")
    v.save(store)
    print("Nodes with encryption = 'Cryptomator vault' will now upload into this vault.")


def status(store):
    for name, cls in PROVIDERS.items():
        authed = bool(cls(store)._creds().get("refresh_token"))
        v = store.get(f"vault:{name}")
        vault_txt = f", vault: {v['path']}" if v.get("enc_key") else ""
        print(f"{cls.display_name:14} {'authorized' if authed else 'not authorized'}{vault_txt}")
    print(f"\nCredential file: {store.path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in PROVIDERS:
        p = sub.add_parser(name, help=f"Authorize {PROVIDERS[name].display_name}")
        p.add_argument("--client-id")
        p.add_argument("--client-secret")
        if name == "aliyundrive":
            p.add_argument("--refresh-token", help="Skip the QR code and import an existing refresh token")
    for cmd in ("vault-create", "vault-unlock"):
        p = sub.add_parser(cmd, help=f"{cmd.split('-')[1].title()} a Cryptomator vault")
        p.add_argument("provider", choices=list(PROVIDERS))
        p.add_argument("--path", default="ComfyUI-Vault", help="Vault folder on the drive")
    sub.add_parser("status", help="Show what is configured")
    p = sub.add_parser("logout", help="Remove stored credentials and vault keys")
    p.add_argument("provider", choices=list(PROVIDERS))
    args = ap.parse_args()

    store = CredentialStore()
    try:
        if args.cmd == "google_drive":
            auth_google(args, store)
        elif args.cmd == "aliyundrive":
            auth_aliyun(args, store)
        elif args.cmd in ("vault-create", "vault-unlock"):
            vault(args, store, create=args.cmd == "vault-create")
        elif args.cmd == "status":
            status(store)
        elif args.cmd == "logout":
            store.clear(args.provider)
            store.clear(f"vault:{args.provider}")
            print("Removed.")
    except (CloudDriveError, VaultError) as e:
        sys.exit(f"Error: {e}")
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
