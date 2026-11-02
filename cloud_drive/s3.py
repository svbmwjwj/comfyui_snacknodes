"""S3-compatible object storage: Cloudflare R2, AWS S3, Backblaze B2, MinIO, Wasabi, ...

Requests are signed with AWS Signature Version 4 directly (no boto3), using path-style
URLs: {endpoint}/{bucket}/{key}. Ids are object keys; "folders" are key prefixes, and
create_folder writes an empty "prefix/" marker object (as the AWS console and rclone do)
so that empty folders, which a Cryptomator vault needs, exist for other tools too.

Cloudflare R2 (the R2 class) needs only the account id: the endpoint is
https://<account_id>.r2.cloudflarestorage.com and the region is "auto". R2's free tier
is 10 GB of storage per month with no egress fees, so R2 defaults to a 10 GB limit:
before each upload the bucket's size is summed (ListObjectsV2) and the upload is refused
if it would go over. Set limit_gb to 0 to turn this off.

Files are never overwritten: a key that already exists gets _1, _2, ... (as in WebDAV).
"""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import quote, urlsplit

import requests

from .base import (DEFAULT_TIMEOUT, RETRY_STATUS, AuthRequired, CloudDriveError, Progress, Provider,
                   raise_after_retries)
from .config import CredentialStore

GB = 1000 ** 3  # Cloudflare bills in decimal GB
PART_SIZE = 16 * 1024 * 1024
MULTIPART_THRESHOLD = 64 * 1024 * 1024
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
# S3 error codes that mean the keys themselves are wrong (HTTP 403, not a permission problem)
BAD_KEY_CODES = ("SignatureDoesNotMatch", "InvalidAccessKeyId", "InvalidToken")


class StorageLimitReached(CloudDriveError):
    """The upload would take the bucket over the configured limit (e.g. R2's 10 GB free tier)."""


def _uri(text: str, safe: str = "") -> str:
    return quote(text, safe="-_.~" + safe)


def _join(parent_id: str, name: str) -> str:
    return f"{parent_id}/{name}" if parent_id else name


def _xml_code(body: str) -> str:
    try:
        return ET.fromstring(body).findtext("Code") or ""
    except ET.ParseError:
        return ""


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


class _CountingReader:
    def __init__(self, data: bytes, progress: Optional[Progress], offset: int, total: int):
        self.f, self.progress, self.offset, self.total, self.size = io.BytesIO(data), progress, offset, total, len(data)
        self.sent = 0

    def read(self, n: int = -1) -> bytes:
        chunk = self.f.read(n)
        self.sent += len(chunk)
        if self.progress and chunk:
            self.progress(self.offset + self.sent, self.total)
        return chunk

    def __len__(self) -> int:
        return self.size


def sign_v4(method: str, url: str, headers: dict[str, str], payload_hash: str, access_key: str,
            secret_key: str, region: str, now: Optional[datetime] = None) -> dict[str, str]:
    """Headers to add (x-amz-date, x-amz-content-sha256, Authorization) for an S3 request.
    url must already be percent-encoded the way it will be sent."""
    now = now or datetime.now(timezone.utc)
    amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    parts = urlsplit(url)
    host = parts.netloc
    query = sorted(tuple(p.split("=", 1)) if "=" in p else (p, "") for p in parts.query.split("&") if p)
    canonical_query = "&".join(f"{k}={v}" for k, v in query)
    all_headers = {k.lower(): v.strip() for k, v in headers.items()}
    all_headers.update({"host": host, "x-amz-date": amz_date, "x-amz-content-sha256": payload_hash})
    signed = sorted(all_headers)
    canonical = "\n".join([method, parts.path or "/", canonical_query,
                           "".join(f"{h}:{all_headers[h]}\n" for h in signed), ";".join(signed), payload_hash])
    scope = f"{day}/{region}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = ("AWS4" + secret_key).encode()
    for part in (day, region, "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {"x-amz-date": amz_date, "x-amz-content-sha256": payload_hash,
            "Authorization": f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
                             f"SignedHeaders={';'.join(signed)}, Signature={signature}"}


class S3(Provider):
    name = "s3"
    display_name = "S3"
    root_id = ""
    env_prefix = "SNACK_S3_"
    default_region = "us-east-1"
    default_limit_gb = 0.0
    auth_hint = ("Run: python custom_nodes/comfyui_snacknodes/auth.py s3 --endpoint URL --bucket BUCKET "
                 "--access-key-id KEY")
    FIELDS = ("endpoint", "region", "bucket", "access_key_id", "secret_access_key", "public_url", "limit_gb")

    def __init__(
        self,
        store: Optional[CredentialStore] = None,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        super().__init__()
        self.store = store or CredentialStore()
        self.session = session or requests.Session()
        self.sleep = sleep
        self._used: Optional[int] = None  # bytes in the bucket, summed once then kept up to date

    # ---------------------------------------------------------------- auth
    def _creds(self) -> dict[str, Any]:
        creds = self.store.get(self.name)
        for key in self.FIELDS + ("account_id",):
            env = os.environ.get(self.env_prefix + key.upper())
            if env:
                creds[key] = env
        if not creds.get("endpoint") and creds.get("account_id"):
            creds["endpoint"] = f"https://{creds['account_id']}.r2.cloudflarestorage.com"
        creds.setdefault("region", self.default_region)
        return creds

    def is_authorized(self) -> bool:
        c = self._creds()
        return bool(c.get("endpoint") and c.get("bucket") and c.get("access_key_id")
                    and c.get("secret_access_key"))

    def _conf(self) -> dict[str, Any]:
        if not self.is_authorized():
            raise AuthRequired(f"{self.display_name} is not configured. {self.auth_hint}")
        return self._creds()

    def limit_bytes(self) -> int:
        raw = self._creds().get("limit_gb", self.default_limit_gb)
        try:
            return int(float(raw) * GB)
        except (TypeError, ValueError):
            return int(self.default_limit_gb * GB)

    # ------------------------------------------------------------ requests
    def _url(self, conf: dict[str, Any], key: str = "", query: Optional[dict[str, str]] = None) -> str:
        url = f"{conf['endpoint'].rstrip('/')}/{_uri(conf['bucket'])}"
        if key:
            url += "/" + _uri(key, safe="/")
        if query:
            url += "?" + "&".join(f"{_uri(k)}={_uri(v)}" for k, v in sorted(query.items()))
        return url

    def _send(self, method: str, key: str = "", *, query: Optional[dict[str, str]] = None, body: bytes = b"",
              ok: tuple[int, ...] = (200,), headers: Optional[dict[str, str]] = None,
              progress: Optional[Progress] = None, offset: int = 0, total: int = 0,
              conf: Optional[dict[str, Any]] = None, retries: int = 3) -> requests.Response:
        conf = conf or self._conf()
        url = self._url(conf, key, query)
        payload_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
        last: Optional[Exception] = None
        for attempt in range(retries + 1):
            # Signed per attempt (the signature carries the time); the body is resent whole.
            h = dict(headers or {})
            h.update(sign_v4(method, url, h, payload_hash, conf["access_key_id"], conf["secret_access_key"],
                             conf.get("region") or self.default_region))
            data: Any = _CountingReader(body, progress, offset, total or len(body)) if progress else body
            if body:
                h["Content-Length"] = str(len(body))
            try:
                resp = self.session.request(method, url, data=data if body else None, headers=h,
                                            timeout=DEFAULT_TIMEOUT)
            except requests.RequestException as e:
                last = e
            else:
                if resp.status_code in ok:
                    return resp
                text = resp.text[:2000] if method != "HEAD" else ""
                code = _xml_code(text)
                if method == "HEAD" and resp.status_code == 403 and not query:
                    # HEAD replies have no body: list the bucket to learn whether the key itself is bad
                    # (raises AuthRequired) or it is a plain permission problem (falls through).
                    try:
                        self._list("", max_keys=1, conf=conf)
                    except AuthRequired:
                        raise
                    except CloudDriveError:
                        pass
                if code in BAD_KEY_CODES:
                    raise AuthRequired(f"{self.display_name} rejected the access key ({code}). {self.auth_hint}",
                                       status=resp.status_code, body=text)
                if resp.status_code not in RETRY_STATUS or attempt == retries:
                    raise CloudDriveError(f"{method} {url} failed: HTTP {resp.status_code} {text[:500]}",
                                          status=resp.status_code, body=text)
                last = CloudDriveError(f"HTTP {resp.status_code}", status=resp.status_code, body=text)
            if attempt < retries:
                self.sleep(2.0 * (2 ** attempt))
        raise_after_retries(f"{method} {url}", retries + 1, last)
        raise AssertionError("unreachable")

    def _list(self, prefix: str, max_keys: int = 1000, token: str = "",
              conf: Optional[dict[str, Any]] = None) -> ET.Element:
        q = {"list-type": "2", "prefix": prefix, "max-keys": str(max_keys)}
        if token:
            q["continuation-token"] = token
        return _strip_ns(ET.fromstring(self._send("GET", query=q, conf=conf).content))

    def configure(self, values: dict[str, Any]) -> None:
        """Check the bucket can be listed with these keys, then store them."""
        conf = {k: v for k, v in values.items() if v not in (None, "")}
        merged = {**self._creds(), **conf}
        if not merged.get("endpoint") and merged.get("account_id"):
            merged["endpoint"] = f"https://{merged['account_id']}.r2.cloudflarestorage.com"
        for field in ("endpoint", "bucket", "access_key_id", "secret_access_key"):
            if not merged.get(field):
                raise CloudDriveError(f"Missing {field}. {self.auth_hint}")
        if not str(merged["endpoint"]).startswith(("http://", "https://")):
            raise CloudDriveError("The endpoint must start with https:// (or http://)")
        try:
            self._list("", max_keys=1, conf=merged)
        except AuthRequired as e:
            raise CloudDriveError(f"Wrong Access Key ID or Secret Access Key ({e.body and _xml_code(e.body)}).",
                                  status=e.status, body=e.body) from e
        except CloudDriveError as e:
            code = _xml_code(e.body)
            if code == "NoSuchBucket" or e.status == 404:
                raise CloudDriveError(f"Bucket '{merged['bucket']}' does not exist. Create it first.",
                                      status=404, body=e.body) from e
            if e.status == 403:
                raise CloudDriveError("The key has no permission to list this bucket. Give the token "
                                      "Object Read & Write access to this bucket.", status=403, body=e.body) from e
            raise CloudDriveError(f"Could not open the bucket: {e}", status=e.status, body=e.body,
                                  network=e.network) from e
        self.store.update(self.name, conf)

    # ---------------------------------------------------------- primitives
    def find_child(self, parent_id: str, name: str) -> Optional[str]:
        key = _join(parent_id, name)
        if self._send("HEAD", key, ok=(200, 404)).status_code == 200:
            return key
        root = self._list(key + "/", max_keys=1)
        return key if root.find("Contents") is not None or root.find("CommonPrefixes") is not None else None

    def create_folder(self, parent_id: str, name: str) -> str:
        key = _join(parent_id, name)
        self._send("PUT", key + "/", ok=(200, 201))
        return key

    def download(self, file_id: str) -> bytes:
        return self._send("GET", file_id).content

    def used_bytes(self) -> int:
        """Total size of all objects in the bucket."""
        total, token = 0, ""
        while True:
            root = self._list("", token=token)
            total += sum(int(c.findtext("Size") or 0) for c in root.findall("Contents"))
            token = root.findtext("NextContinuationToken") or ""
            if root.findtext("IsTruncated") != "true" or not token:
                return total

    def _check_limit(self, size: int) -> None:
        limit = self.limit_bytes()
        if limit <= 0:
            return
        if self._used is None:
            self._used = self.used_bytes()
        if self._used + size > limit:
            raise StorageLimitReached(
                f"Uploading {size / GB:.2f} GB would take bucket '{self._creds()['bucket']}' to "
                f"{(self._used + size) / GB:.2f} GB, over the {limit / GB:g} GB limit "
                f"(limit_gb; set it to 0 to turn the check off).")

    def upload_file(self, parent_id: str, name: str, local_path: str,
                    mime_type: str = "application/octet-stream",
                    allow_rename: bool = True,
                    progress: Optional[Progress] = None) -> tuple[str, str, Optional[str]]:
        final = name
        if self._send("HEAD", _join(parent_id, name), ok=(200, 404)).status_code == 200:
            if not allow_rename:
                raise CloudDriveError(f"{_join(parent_id, name)} already exists")
            stem, ext = os.path.splitext(name)
            n = 1
            while self._send("HEAD", _join(parent_id, final := f"{stem}_{n}{ext}"), ok=(200, 404)).status_code == 200:
                n += 1
        key = _join(parent_id, final)
        size = os.path.getsize(local_path)
        self._check_limit(size)
        headers = {"Content-Type": mime_type}
        if size <= MULTIPART_THRESHOLD:
            with open(local_path, "rb") as f:
                body = f.read()
            self._send("PUT", key, body=body, headers=headers, progress=progress, total=size)
        else:
            self._multipart(key, local_path, size, headers, progress)
        if self._used is not None:
            self._used += size
        public = self._creds().get("public_url")
        url = f"{public.rstrip('/')}/{_uri(key, safe='/')}" if public else None
        return key, final, url

    def _multipart(self, key: str, local_path: str, size: int, headers: dict[str, str],
                   progress: Optional[Progress]) -> None:
        resp = self._send("POST", key, query={"uploads": ""}, headers=headers)
        upload_id = _strip_ns(ET.fromstring(resp.content)).findtext("UploadId")
        if not upload_id:
            raise CloudDriveError(f"No UploadId in the reply: {resp.text[:300]}", body=resp.text[:2000])
        etags: list[str] = []
        try:
            with open(local_path, "rb") as f:
                offset = 0
                while offset < size:
                    chunk = f.read(PART_SIZE)
                    part = self._send("PUT", key, body=chunk, progress=progress, offset=offset, total=size,
                                      query={"partNumber": str(len(etags) + 1), "uploadId": upload_id})
                    etags.append(part.headers.get("ETag", ""))
                    offset += len(chunk)
            xml = "<CompleteMultipartUpload>" + "".join(
                f"<Part><PartNumber>{i}</PartNumber><ETag>{etag}</ETag></Part>"
                for i, etag in enumerate(etags, 1)) + "</CompleteMultipartUpload>"
            done = self._send("POST", key, query={"uploadId": upload_id}, body=xml.encode(),
                              headers={"Content-Type": "application/xml"})
            # S3 may answer 200 and still report an error in the body
            if b"<Error>" in done.content:
                raise CloudDriveError(f"Completing the upload failed: {done.text[:300]}", body=done.text[:2000])
        except BaseException:
            try:
                self._send("DELETE", key, query={"uploadId": upload_id}, ok=(200, 204, 404), retries=1)
            except Exception:  # noqa: BLE001 - best effort; the original error matters
                pass
            raise


class R2(S3):
    """Cloudflare R2: S3 API at https://<account_id>.r2.cloudflarestorage.com, region "auto",
    10 GB of free storage per month and no egress fees."""

    name = "r2"
    display_name = "Cloudflare R2"
    env_prefix = "SNACK_R2_"
    default_region = "auto"
    default_limit_gb = 10.0
    auth_hint = ("Run: python custom_nodes/comfyui_snacknodes/auth.py r2 --account-id ID --bucket BUCKET "
                 "--access-key-id KEY")
