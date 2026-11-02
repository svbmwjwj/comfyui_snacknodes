#!/usr/bin/env python3
"""One-time setup for Save to Cloud Drive. Run on the machine that runs ComfyUI.

  python auth.py google_drive  [--client-id ID --client-secret SECRET]
  python auth.py webdav        --url https://dav.example.com/ --username USER
  python auth.py r2            --url https://<account>.r2.cloudflarestorage.com/<bucket>  [--limit-gb 10]
  python auth.py s3            --endpoint https://s3.us-east-1.amazonaws.com --region us-east-1 --bucket BUCKET
  python auth.py aliyundrive   --client-id ID --client-secret SECRET
  python auth.py vault-create  google_drive  --path ComfyUI-Vault  [--generate-password]
  python auth.py vault-unlock  aliyundrive   --path ComfyUI-Vault
  python auth.py status
  python auth.py logout        google_drive
  python auth.py uploads       [--wait] [--timeout SECONDS]

`uploads --wait` waits until every background upload is done, e.g. before shutting down a rented
GPU machine:  python custom_nodes/snacknodes/auth.py uploads --wait && shutdown
Exit codes: 0 all uploaded, 1 some failed, 2 uploads left but ComfyUI is not running, 3 timed out.

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
    from cloud_drive.google_drive import GoogleDrive, resolve_client
    client_id, client_secret, source = resolve_client(args.client_id, args.client_secret)
    if not client_id:
        print("No built-in Google OAuth client in this build; use your own (see README).")
        client_id = _ask("Google OAuth client ID: ", None)
        client_secret = _ask("Google OAuth client secret: ", None, secret=True)
    elif source != "built-in":
        print(f"Using your own OAuth client (from {source}).")
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


def auth_webdav(args, store):
    from cloud_drive.webdav import WebDAV, is_insecure_url
    url = _ask("WebDAV URL (e.g. https://dav.jianguoyun.com/dav/): ", args.url or os.environ.get("SNACK_WEBDAV_URL"))
    if is_insecure_url(url):
        print("WARNING: plain http:// sends your password unencrypted. Use https:// if the server supports it.")
    username = _ask("Username: ", args.username or os.environ.get("SNACK_WEBDAV_USERNAME"))
    password = os.environ.get("SNACK_WEBDAV_PASSWORD") or getpass.getpass("Password (app password if offered): ")
    WebDAV(store).configure(url, username, password)
    print(f"WebDAV connected: {url}")


def auth_s3(args, store):
    """r2 and s3: keys are checked by listing the bucket before they are stored."""
    from cloud_drive import PROVIDERS
    cls = PROVIDERS[args.cmd]
    env = cls.env_prefix
    values = {"public_url": args.public_url, "limit_gb": args.limit_gb}
    if args.cmd == "r2":
        from cloud_drive.s3 import parse_r2_url
        if args.account_id:
            values["account_id"] = args.account_id
        else:
            # The bucket's "S3 API" URL carries both the account and the bucket name.
            values.update(parse_r2_url(_ask("S3 API URL (bucket → Settings → S3 API): ", args.url)))
    else:
        values["endpoint"] = _ask("Endpoint URL (e.g. https://s3.us-east-1.amazonaws.com): ",
                                  args.endpoint or os.environ.get(env + "ENDPOINT"))
        values["region"] = args.region or os.environ.get(env + "REGION") or "us-east-1"
    values["bucket"] = _ask("Bucket name: ", args.bucket or values.get("bucket") or os.environ.get(env + "BUCKET"))
    values["access_key_id"] = _ask("Access Key ID: ", args.access_key_id or os.environ.get(env + "ACCESS_KEY_ID"))
    values["secret_access_key"] = (os.environ.get(env + "SECRET_ACCESS_KEY")
                                   or getpass.getpass("Secret Access Key: ").strip())
    provider = cls(store)
    provider.configure(values)
    print(f"{cls.display_name} connected: bucket '{values['bucket']}'.")
    limit = provider.limit_bytes()
    if limit > 0:
        used = provider.used_bytes()
        print(f"Bucket usage: {used / 1e9:.2f} GB of the {limit / 1e9:g} GB limit. Uploads that would go over "
              f"are refused (change with --limit-gb, 0 = no limit).")
    elif args.cmd == "r2":
        print("No storage limit: storage above R2's 10 GB free tier will be billed by Cloudflare.")


PASSWORD_WARNING = """
  !! The vault password is the ONLY way to recover your files. There is no reset
  !! and no recovery key. Save it in a password manager now.
  !! 保险库密码是恢复文件的唯一方式，没有找回或重置的途径，请立即妥善保存（如密码管理器）。
"""
# Unambiguous alphabet (no 0/O, 1/l/I): 6 groups x 5 chars ~ 148 bits.
_GEN_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def generate_password(groups: int = 6, size: int = 5) -> str:
    import secrets
    return "-".join("".join(secrets.choice(_GEN_ALPHABET) for _ in range(size)) for _ in range(groups))


def _confirm_saved(password: str) -> None:
    # Make the user prove they recorded it before anything is uploaded.
    tail = password.rsplit("-", 1)[-1]
    for _ in range(3):
        if input("Type the LAST group of the password to confirm you saved it: ").strip() == tail:
            return
        print("  That does not match.")
    sys.exit("Not confirmed. Nothing was created.")


def _new_vault_password(args) -> str:
    env = os.environ.get("SNACK_VAULT_PASSWORD")
    if env:
        return env
    print(PASSWORD_WARNING)
    choice = "2" if args.generate_password else "1" if args.own_password else ""
    while choice not in ("1", "2"):
        choice = input("  [1] Enter my own password\n  [2] Generate a strong password for me\nChoose 1 or 2: ").strip()
    if choice == "2":
        pw = generate_password()
        print(f"\n  Your vault password:   {pw}\n")
        _confirm_saved(pw)
        return pw
    pw = getpass.getpass("Vault password: ")
    if len(pw) < 8:
        sys.exit("Use at least 8 characters.")
    if getpass.getpass("Repeat password: ") != pw:
        sys.exit("Passwords do not match.")
    return pw


def vault(args, store, create: bool):
    provider = PROVIDERS[args.provider](store)
    if create:
        password = _new_vault_password(args)
    else:
        password = os.environ.get("SNACK_VAULT_PASSWORD") or getpass.getpass("Vault password: ")
    print("Deriving key (scrypt, a few seconds)...")
    if create:
        v = CryptomatorVault.create(provider, args.path, password)
        print(f"Created Cryptomator vault '{args.path}' on {provider.display_name}.")
    else:
        v = CryptomatorVault.unlock(provider, args.path, password)
        print(f"Unlocked vault '{args.path}' on {provider.display_name}.")
    v.save(store)
    print("Nodes with encryption = 'Cryptomator vault' will now upload into this vault.")


def status(store):
    for name, cls in PROVIDERS.items():
        authed = cls(store).is_authorized()
        v = store.get(f"vault:{name}")
        vault_txt = f", vault: {v['path']}" if v.get("enc_key") else ""
        print(f"{cls.display_name:14} {'authorized' if authed else 'not authorized'}{vault_txt}")
    print(f"\nCredential file: {store.path}")


def uploads(args) -> int:
    from cloud_drive import uploads as up
    if args.wait:
        return up.wait_for_uploads(timeout=args.timeout)
    data = up.read_queue()
    lines = up.describe(data)
    s = up.summarize(data)
    print("\n".join(lines) if lines else "No uploads waiting.")
    if s["active"] and not s["worker_alive"]:
        print("ComfyUI is not running; these continue when it starts.")
    print(f"\nQueue file: {up.queue_path()}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("google_drive", "aliyundrive"):
        p = sub.add_parser(name, help=f"Authorize {PROVIDERS[name].display_name}")
        own = " (optional: a built-in client is used by default)" if name == "google_drive" else ""
        p.add_argument("--client-id", help="Your own OAuth client ID" + own)
        p.add_argument("--client-secret", help="Your own OAuth client secret" + own)
        if name == "aliyundrive":
            p.add_argument("--refresh-token", help="Skip the QR code and import an existing refresh token")
    p = sub.add_parser("webdav", help="Connect a WebDAV server (Nutstore/坚果云, Nextcloud, NAS, OpenList...)")
    p.add_argument("--url")
    p.add_argument("--username")
    for name in ("r2", "s3"):
        r2 = name == "r2"
        p = sub.add_parser(name, help="Connect Cloudflare R2 (10 GB free)" if r2 else
                           "Connect S3-compatible storage (AWS S3, Backblaze B2, MinIO, Wasabi...)")
        if r2:
            p.add_argument("--url", help="The bucket's S3 API URL, https://<account>.r2.cloudflarestorage.com/<bucket>")
            p.add_argument("--account-id", help="Cloudflare account ID (instead of --url)")
        else:
            p.add_argument("--endpoint", help="S3 endpoint URL, e.g. https://s3.us-east-1.amazonaws.com")
            p.add_argument("--region", help="Region (default us-east-1)")
        p.add_argument("--bucket")
        p.add_argument("--access-key-id")
        p.add_argument("--public-url", help="Optional public base URL (r2.dev or custom domain); "
                                            "the node then outputs links")
        p.add_argument("--limit-gb", type=float,
                       help="Refuse uploads that would take the bucket over this size "
                            + ("(default 10 = R2 free tier; 0 = no limit)" if r2 else "(default 0 = no limit)"))
    for cmd in ("vault-create", "vault-unlock"):
        p = sub.add_parser(cmd, help=f"{cmd.split('-')[1].title()} a Cryptomator vault")
        p.add_argument("provider", choices=list(PROVIDERS))
        p.add_argument("--path", default="ComfyUI-Vault", help="Vault folder on the drive")
        if cmd == "vault-create":
            g = p.add_mutually_exclusive_group()
            g.add_argument("--generate-password", action="store_true", help="Generate a strong password")
            g.add_argument("--own-password", action="store_true", help="Type your own password")
    sub.add_parser("status", help="Show what is configured")
    p = sub.add_parser("uploads", help="Show background uploads; --wait blocks until they are done")
    p.add_argument("--wait", action="store_true", help="Wait until every upload is done (exit code 0)")
    p.add_argument("--timeout", type=float, default=0, help="Give up waiting after this many seconds (exit 3)")
    p = sub.add_parser("logout", help="Remove stored credentials and vault keys")
    p.add_argument("provider", choices=list(PROVIDERS))
    args = ap.parse_args()

    store = CredentialStore()
    try:
        if args.cmd == "google_drive":
            auth_google(args, store)
        elif args.cmd == "aliyundrive":
            auth_aliyun(args, store)
        elif args.cmd == "webdav":
            auth_webdav(args, store)
        elif args.cmd in ("r2", "s3"):
            auth_s3(args, store)
        elif args.cmd in ("vault-create", "vault-unlock"):
            vault(args, store, create=args.cmd == "vault-create")
        elif args.cmd == "status":
            status(store)
        elif args.cmd == "uploads":
            sys.exit(uploads(args))
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
