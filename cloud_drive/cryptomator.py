"""Cryptomator vault format 8 (cipher combo SIV_GCM), write-side implementation.

Files written here can be opened with the official Cryptomator apps
(desktop, iOS, Android). Spec: https://docs.cryptomator.org/en/latest/security/architecture/

- Master keys: two 256-bit keys (encryption + MAC), wrapped with a scrypt-derived KEK
  (RFC 3394 AES key wrap) in masterkey.cryptomator.
- vault.cryptomator: HS256 JWT signed with encKey||macKey.
- File content: 68-byte header (AES-GCM sealed content key), then 32 KiB chunks,
  each AES-GCM with AAD = chunk number (big-endian u64) || header nonce.
- Names: AES-SIV(name, AD=parent dir id), base64url, ".c9r" suffix.
- Directories: content lives at d/<2>/<30> = base32(sha1(AES-SIV(dir id))).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import unicodedata
import uuid
from dataclasses import dataclass
from typing import BinaryIO

from cryptography.hazmat.primitives import cmac
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.keywrap import aes_key_unwrap, aes_key_wrap

VAULT_FORMAT = 8
CIPHER_COMBO = "SIV_GCM"
SHORTENING_THRESHOLD = 220
MASTERKEY_FILE = "masterkey.cryptomator"
VAULT_CONFIG_FILE = "vault.cryptomator"
DATA_DIR = "d"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 32768, 8, 1

CHUNK_PLAIN = 32 * 1024
NONCE = 12
TAG = 16
HEADER_SIZE = NONCE + 8 + 32 + TAG  # 68
CHUNK_CIPHER = NONCE + CHUNK_PLAIN + TAG


class VaultError(ValueError):
    pass


def _b64url(data: bytes, pad: bool = True) -> str:
    s = base64.urlsafe_b64encode(data).decode("ascii")
    return s if pad else s.rstrip("=")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


# ----------------------------------------------------------------- AES-SIV
# Implemented directly (RFC 5297) because Cryptomator encrypts the empty string
# (the root directory id), which some library implementations refuse.

def _dbl(block: bytes) -> bytes:
    n = int.from_bytes(block, "big") << 1
    if n >> 128:
        n = (n & ((1 << 128) - 1)) ^ 0x87
    return n.to_bytes(16, "big")


def _cmac(key: bytes, data: bytes) -> bytes:
    c = cmac.CMAC(algorithms.AES(key))
    c.update(data)
    return c.finalize()


def _s2v(mac_key: bytes, plaintext: bytes, associated: list[bytes]) -> bytes:
    d = _cmac(mac_key, bytes(16))
    for ad in associated:
        d = bytes(a ^ b for a, b in zip(_dbl(d), _cmac(mac_key, ad), strict=True))
    if len(plaintext) >= 16:
        tail = bytes(a ^ b for a, b in zip(plaintext[-16:], d, strict=True))
        t = plaintext[:-16] + tail
    else:
        padded = plaintext + b"\x80" + bytes(15 - len(plaintext))
        t = bytes(a ^ b for a, b in zip(_dbl(d), padded, strict=True))
    return _cmac(mac_key, t)


def _siv_ctr(ctr_key: bytes, iv: bytes, data: bytes) -> bytes:
    q = bytearray(iv)
    q[8] &= 0x7F
    q[12] &= 0x7F
    enc = Cipher(algorithms.AES(ctr_key), modes.CTR(bytes(q))).encryptor()
    return enc.update(data) + enc.finalize()


def siv_encrypt(ctr_key: bytes, mac_key: bytes, plaintext: bytes, *associated: bytes) -> bytes:
    iv = _s2v(mac_key, plaintext, list(associated))
    return iv + _siv_ctr(ctr_key, iv, plaintext)


def siv_decrypt(ctr_key: bytes, mac_key: bytes, ciphertext: bytes, *associated: bytes) -> bytes:
    if len(ciphertext) < 16:
        raise VaultError("SIV ciphertext too short")
    iv, body = ciphertext[:16], ciphertext[16:]
    plaintext = _siv_ctr(ctr_key, iv, body)
    if not hmac.compare_digest(iv, _s2v(mac_key, plaintext, list(associated))):
        raise VaultError("SIV authentication failed")
    return plaintext


# -------------------------------------------------------------------- keys
@dataclass(frozen=True)
class VaultKeys:
    enc_key: bytes
    mac_key: bytes

    @classmethod
    def generate(cls) -> VaultKeys:
        return cls(os.urandom(32), os.urandom(32))

    def to_dict(self) -> dict[str, str]:
        return {"enc_key": _b64url(self.enc_key), "mac_key": _b64url(self.mac_key)}

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> VaultKeys:
        return cls(_b64url_decode(d["enc_key"]), _b64url_decode(d["mac_key"]))


def _kek(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(_nfc(password).encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          maxmem=256 * 1024 * 1024, dklen=32)


def create_masterkey_file(keys: VaultKeys, password: str) -> bytes:
    salt = os.urandom(8)
    kek = _kek(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    version = 999
    doc = {
        "version": version,
        "scryptSalt": base64.b64encode(salt).decode(),
        "scryptCostParam": SCRYPT_N,
        "scryptBlockSize": SCRYPT_R,
        "primaryMasterKey": base64.b64encode(aes_key_wrap(kek, keys.enc_key)).decode(),
        "hmacMasterKey": base64.b64encode(aes_key_wrap(kek, keys.mac_key)).decode(),
        "versionMac": base64.b64encode(
            hmac.new(keys.mac_key, struct.pack(">i", version), hashlib.sha256).digest()).decode(),
    }
    return json.dumps(doc, indent=2).encode()


def unlock_masterkey_file(data: bytes, password: str) -> VaultKeys:
    doc = json.loads(data)
    kek = _kek(password, base64.b64decode(doc["scryptSalt"]), int(doc["scryptCostParam"]),
               int(doc["scryptBlockSize"]), 1)
    try:
        enc = aes_key_unwrap(kek, base64.b64decode(doc["primaryMasterKey"]))
        mac = aes_key_unwrap(kek, base64.b64decode(doc["hmacMasterKey"]))
    except Exception as e:
        raise VaultError("Wrong vault password") from e
    expected = hmac.new(mac, struct.pack(">i", int(doc["version"])), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, base64.b64decode(doc["versionMac"])):
        raise VaultError("masterkey.cryptomator version MAC mismatch")
    return VaultKeys(enc, mac)


def create_vault_config(keys: VaultKeys) -> bytes:
    header = {"kid": f"masterkeyfile:{MASTERKEY_FILE}", "typ": "JWT", "alg": "HS256"}
    payload = {"jti": str(uuid.uuid4()), "format": VAULT_FORMAT,
               "cipherCombo": CIPHER_COMBO, "shorteningThreshold": SHORTENING_THRESHOLD}
    signing_input = ".".join(_b64url(json.dumps(x, separators=(",", ":")).encode(), pad=False)
                             for x in (header, payload))
    sig = hmac.new(keys.enc_key + keys.mac_key, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(sig, pad=False)}".encode()


def verify_vault_config(data: bytes, keys: VaultKeys) -> dict:
    try:
        h, p, s = data.decode("ascii").strip().split(".")
    except ValueError as e:
        raise VaultError("vault.cryptomator is not a JWT") from e
    header = json.loads(_b64url_decode(h))
    if header.get("alg") not in ("HS256", "HS384", "HS512"):
        raise VaultError(f"Unsupported vault config algorithm: {header.get('alg')}")
    digest = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}[header["alg"]]
    sig = hmac.new(keys.enc_key + keys.mac_key, f"{h}.{p}".encode(), digest).digest()
    if not hmac.compare_digest(sig, _b64url_decode(s)):
        raise VaultError("vault.cryptomator signature mismatch (wrong vault?)")
    payload = json.loads(_b64url_decode(p))
    if payload.get("format") != VAULT_FORMAT or payload.get("cipherCombo") != CIPHER_COMBO:
        raise VaultError(f"Unsupported vault: format={payload.get('format')} "
                         f"cipherCombo={payload.get('cipherCombo')} (need 8 / SIV_GCM)")
    return payload


# ------------------------------------------------------------- names, dirs
def new_dir_id() -> str:
    return str(uuid.uuid4())


def dir_path(keys: VaultKeys, dir_id: str) -> tuple[str, str]:
    """('d', 'XX', '30 chars') minus the 'd' -> ('XX', 'YYYY...')."""
    ct = siv_encrypt(keys.enc_key, keys.mac_key, dir_id.encode("utf-8"))
    h = base64.b32encode(hashlib.sha1(ct).digest()).decode("ascii")
    return h[:2], h[2:]


def encrypt_name(keys: VaultKeys, name: str, parent_dir_id: str) -> str:
    ct = siv_encrypt(keys.enc_key, keys.mac_key, _nfc(name).encode("utf-8"), parent_dir_id.encode("utf-8"))
    return _b64url(ct) + ".c9r"


def decrypt_name(keys: VaultKeys, node_name: str, parent_dir_id: str) -> str:
    if not node_name.endswith(".c9r"):
        raise VaultError(f"Not an encrypted name: {node_name}")
    ct = _b64url_decode(node_name[:-4])
    return siv_decrypt(keys.enc_key, keys.mac_key, ct, parent_dir_id.encode("utf-8")).decode("utf-8")


def shortened_name(full_node_name: str) -> str:
    return _b64url(hashlib.sha1(full_node_name.encode("utf-8")).digest()) + ".c9s"


def needs_shortening(full_node_name: str) -> bool:
    return len(full_node_name) > SHORTENING_THRESHOLD


# ------------------------------------------------------------ file content
def encrypt_stream(keys: VaultKeys, src: BinaryIO, dst: BinaryIO) -> None:
    header_nonce = os.urandom(NONCE)
    content_key = os.urandom(32)
    payload = b"\xff" * 8 + content_key
    dst.write(header_nonce + AESGCM(keys.enc_key).encrypt(header_nonce, payload, None))
    gcm = AESGCM(content_key)
    chunk_no = 0
    while True:
        chunk = src.read(CHUNK_PLAIN)
        if not chunk:
            break
        nonce = os.urandom(NONCE)
        aad = struct.pack(">Q", chunk_no) + header_nonce
        dst.write(nonce + gcm.encrypt(nonce, chunk, aad))
        chunk_no += 1


def decrypt_stream(keys: VaultKeys, src: BinaryIO, dst: BinaryIO) -> None:
    header = src.read(HEADER_SIZE)
    if len(header) != HEADER_SIZE:
        raise VaultError("Encrypted file header truncated")
    header_nonce = header[:NONCE]
    try:
        payload = AESGCM(keys.enc_key).decrypt(header_nonce, header[NONCE:], None)
    except Exception as e:
        raise VaultError("File header authentication failed") from e
    gcm = AESGCM(payload[8:])
    chunk_no = 0
    while True:
        chunk = src.read(CHUNK_CIPHER)
        if not chunk:
            break
        aad = struct.pack(">Q", chunk_no) + header_nonce
        try:
            dst.write(gcm.decrypt(chunk[:NONCE], chunk[NONCE:], aad))
        except Exception as e:
            raise VaultError(f"Chunk {chunk_no} authentication failed") from e
        chunk_no += 1


def encrypt_bytes(keys: VaultKeys, data: bytes) -> bytes:
    import io
    out = io.BytesIO()
    encrypt_stream(keys, io.BytesIO(data), out)
    return out.getvalue()


def decrypt_bytes(keys: VaultKeys, data: bytes) -> bytes:
    import io
    out = io.BytesIO()
    decrypt_stream(keys, io.BytesIO(data), out)
    return out.getvalue()
