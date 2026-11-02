"""S3 / Cloudflare R2 provider against a small in-memory S3 fake."""

from datetime import datetime, timezone
from urllib.parse import parse_qsl, unquote, urlsplit

import pytest
from fake_http import FakeResponse, FakeSession

from cloud_drive import s3 as s3mod
from cloud_drive.base import AuthRequired, CloudDriveError
from cloud_drive.config import CredentialStore
from cloud_drive.errors import classify
from cloud_drive.s3 import EMPTY_SHA256, R2, S3, StorageLimitReached, sign_v4
from cloud_drive.vault import CryptomatorVault

ACCOUNT = "abc123"
ENDPOINT = f"https://{ACCOUNT}.r2.cloudflarestorage.com"
BUCKET = "comfy"
KEY_ID, SECRET = "AKID", "s3cr3t"


class FakeS3(FakeSession):
    def __init__(self, fail_puts=0, bucket=BUCKET):
        super().__init__()
        self.objects = {}
        self.uploads = {}
        self.fail_puts = fail_puts
        self.bucket = bucket
        for m in ("HEAD", "GET", "PUT", "POST", "DELETE"):
            self.route(m, ENDPOINT, getattr(self, "_" + m.lower()))

    def _parse(self, url, headers):
        auth = headers.get("Authorization", "")
        assert auth.startswith("AWS4-HMAC-SHA256 Credential=")
        if f"Credential={KEY_ID}/" not in auth:
            return None, None, None, FakeResponse(403, content=b"<Error><Code>InvalidAccessKeyId</Code></Error>")
        parts = urlsplit(url)
        bucket, _, key = parts.path.lstrip("/").partition("/")
        if bucket != self.bucket:
            return None, None, None, FakeResponse(404, content=b"<Error><Code>NoSuchBucket</Code></Error>")
        return unquote(key), dict(parse_qsl(parts.query, keep_blank_values=True)), parts, None

    @staticmethod
    def _body(kw):
        data = kw.get("data")
        if data is None:
            return b""
        return data if isinstance(data, bytes) else data.read()

    def _head(self, url, **kw):
        key, _, _, err = self._parse(url, kw["headers"])
        return err or FakeResponse(200 if key in self.objects else 404, content=b"")

    def _get(self, url, **kw):
        key, q, _, err = self._parse(url, kw["headers"])
        if err:
            return err
        if q.get("list-type") == "2":
            keys = sorted(k for k in self.objects if k.startswith(q["prefix"]))
            start = int(q.get("continuation-token") or 0)
            n = int(q["max-keys"])
            page, more = keys[start:start + n], start + n < len(keys)
            xml = ('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                   + "".join(f"<Contents><Key>{k}</Key><Size>{len(self.objects[k])}</Size></Contents>" for k in page)
                   + f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>"
                   + (f"<NextContinuationToken>{start + n}</NextContinuationToken>" if more else "")
                   + "</ListBucketResult>")
            return FakeResponse(200, content=xml.encode())
        return FakeResponse(200, content=self.objects[key]) if key in self.objects else FakeResponse(404, content=b"")

    def _put(self, url, **kw):
        key, q, _, err = self._parse(url, kw["headers"])
        if err:
            return err
        body = self._body(kw)
        if self.fail_puts:
            self.fail_puts -= 1
            return FakeResponse(503, content=b"<Error><Code>SlowDown</Code></Error>")
        if "uploadId" in q:
            self.uploads[q["uploadId"]][int(q["partNumber"])] = body
            return FakeResponse(200, content=b"", headers={"ETag": f'"etag{q["partNumber"]}"'})
        self.objects[key] = body
        return FakeResponse(200, content=b"")

    def _post(self, url, **kw):
        key, q, _, err = self._parse(url, kw["headers"])
        if err:
            return err
        if "uploads" in q:
            self.uploads["U1"] = {}
            return FakeResponse(200, content=b"<InitiateMultipartUploadResult xmlns='x'>"
                                             b"<UploadId>U1</UploadId></InitiateMultipartUploadResult>")
        parts = self.uploads.pop(q["uploadId"])
        assert b"<PartNumber>1</PartNumber><ETag>\"etag1\"</ETag>" in self._body(kw)
        self.objects[key] = b"".join(parts[i] for i in sorted(parts))
        return FakeResponse(200, content=b"<CompleteMultipartUploadResult/>")

    def _delete(self, url, **kw):
        _, q, _, err = self._parse(url, kw["headers"])
        self.uploads.pop(q.get("uploadId"), None)
        return err or FakeResponse(204, content=b"")


@pytest.fixture
def env(tmp_path, monkeypatch):
    for prefix in ("SNACK_R2_", "SNACK_S3_"):
        for f in S3.FIELDS + ("account_id",):
            monkeypatch.delenv(prefix + f.upper(), raising=False)
    store = CredentialStore(tmp_path / "c.json")
    fake = FakeS3()
    return store, fake, R2(store, fake, sleep=lambda s: None)


def _configure(r2, **extra):
    r2.configure({"account_id": ACCOUNT, "bucket": BUCKET, "access_key_id": KEY_ID,
                  "secret_access_key": SECRET, **extra})


def test_sigv4_matches_aws_examples():
    when = datetime(2013, 5, 24, tzinfo=timezone.utc)
    key = ("AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1")
    h = sign_v4("GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"},
                EMPTY_SHA256, *key, now=when)
    assert h["Authorization"].endswith("f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
    h = sign_v4("GET", "https://examplebucket.s3.amazonaws.com/?max-keys=2&prefix=J", {},
                EMPTY_SHA256, *key, now=when)
    assert h["Authorization"].endswith("34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7")


def test_configure_checks_keys_and_bucket(env):
    store, fake, r2 = env
    with pytest.raises(CloudDriveError, match="Wrong Access Key"):
        r2.configure({"account_id": ACCOUNT, "bucket": BUCKET, "access_key_id": "nope", "secret_access_key": "x"})
    with pytest.raises(CloudDriveError, match="does not exist"):
        r2.configure({"account_id": ACCOUNT, "bucket": "other", "access_key_id": KEY_ID, "secret_access_key": "x"})
    with pytest.raises(CloudDriveError, match="Missing bucket"):
        r2.configure({"account_id": ACCOUNT, "access_key_id": KEY_ID, "secret_access_key": "x"})
    assert not r2.is_authorized()
    _configure(r2)
    assert r2.is_authorized() and store.get("r2")["account_id"] == ACCOUNT
    assert r2._creds()["endpoint"] == ENDPOINT and r2._creds()["region"] == "auto"


def test_unconfigured_raises_auth_required(env):
    with pytest.raises(AuthRequired):
        env[2].find_child("", "x")


def test_env_vars(env, monkeypatch):
    _, fake, r2 = env
    for k, v in (("ACCOUNT_ID", ACCOUNT), ("BUCKET", BUCKET), ("ACCESS_KEY_ID", KEY_ID),
                 ("SECRET_ACCESS_KEY", SECRET)):
        monkeypatch.setenv("SNACK_R2_" + k, v)
    assert r2.is_authorized()
    assert r2.ensure_folder("a/b") == "a/b"
    assert set(fake.objects) == {"a/", "a/b/"}


def test_upload_quotes_keys_and_never_overwrites(env, tmp_path):
    _, fake, r2 = env
    _configure(r2)
    src = tmp_path / "x.png"
    src.write_bytes(b"one")
    r1 = r2.upload(str(src), "ComfyUI/测试 目录/#1", "pic.png", mime_type="image/png")
    src.write_bytes(b"two")
    r_2 = r2.upload(str(src), "ComfyUI/测试 目录/#1", "pic.png")
    assert r1.remote_path == "ComfyUI/测试 目录/#1/pic.png"
    assert r_2.remote_path == "ComfyUI/测试 目录/#1/pic_1.png"
    assert fake.objects["ComfyUI/测试 目录/#1/pic.png"] == b"one"
    assert fake.objects["ComfyUI/测试 目录/#1/pic_1.png"] == b"two"
    assert all(" " not in u and "#" not in u for _, u, _ in fake.calls)
    assert r1.describe() == "r2:ComfyUI/测试 目录/#1/pic.png"
    with pytest.raises(CloudDriveError, match="already exists"):
        r2.upload_file("ComfyUI/测试 目录/#1", "pic.png", str(src), allow_rename=False)


def test_public_url(env, tmp_path):
    _, _, r2 = env
    _configure(r2, public_url="https://pub-x.r2.dev/")
    src = tmp_path / "a b.png"
    src.write_bytes(b"x")
    assert r2.upload(str(src), "d").describe() == "https://pub-x.r2.dev/d/a%20b.png"


def test_retries_resend_whole_body(env, tmp_path):
    store, _, _ = env
    fake = FakeS3(fail_puts=2)
    r2 = R2(store, fake, sleep=lambda s: None)
    _configure(r2)
    src = tmp_path / "v.mp4"
    src.write_bytes(b"video-bytes")
    seen = []
    r2.upload(str(src), "", "v.mp4", progress=lambda a, b: seen.append((a, b)))
    assert fake.objects["v.mp4"] == b"video-bytes" and seen[-1] == (11, 11)


def test_multipart(env, tmp_path, monkeypatch):
    _, fake, r2 = env
    monkeypatch.setattr(s3mod, "PART_SIZE", 4)
    monkeypatch.setattr(s3mod, "MULTIPART_THRESHOLD", 5)
    _configure(r2, limit_gb=0)
    src = tmp_path / "big.mp4"
    src.write_bytes(b"0123456789")
    seen = []
    r2.upload(str(src), "v", progress=lambda a, b: seen.append(a))
    assert fake.objects["v/big.mp4"] == b"0123456789" and not fake.uploads
    assert seen[-1] == 10


def test_multipart_failure_aborts(env, tmp_path, monkeypatch):
    _, fake, r2 = env
    monkeypatch.setattr(s3mod, "PART_SIZE", 4)
    monkeypatch.setattr(s3mod, "MULTIPART_THRESHOLD", 5)
    _configure(r2, limit_gb=0)
    fake.routes = [r if r[0] != "PUT" else ("PUT", ENDPOINT, lambda url, **kw: FakeResponse(400, content=b"bad"))
                   for r in fake.routes]
    src = tmp_path / "big.mp4"
    src.write_bytes(b"0123456789")
    with pytest.raises(CloudDriveError):
        r2.upload_file("", "big.mp4", str(src))
    assert not fake.uploads and any(m == "DELETE" for m, _, _ in fake.calls)


def test_free_tier_limit(env, tmp_path):
    store, fake, r2 = env
    _configure(r2, limit_gb=0.000000010)  # 10 bytes
    assert r2.limit_bytes() == 10
    fake.objects["old.bin"] = b"123456"
    src = tmp_path / "f.bin"
    src.write_bytes(b"abc")
    r2.upload(str(src), "")  # 6 + 3 <= 10
    with pytest.raises(StorageLimitReached) as e:
        r2.upload(str(src), "")  # 9 + 3 > 10
    assert classify(e.value, "r2") == "storage_limit"
    assert "f_1.bin" not in fake.objects


def test_r2_defaults_to_free_tier_limit_and_s3_to_none(tmp_path):
    store = CredentialStore(tmp_path / "c.json")
    assert R2(store).limit_bytes() == 10 * 1000 ** 3
    assert S3(store).limit_bytes() == 0


def test_listing_paginates(env):
    _, fake, r2 = env
    _configure(r2)
    for i in range(2500):
        fake.objects[f"k{i}"] = b"xx"
    assert r2.used_bytes() == 5000


def test_bad_key_is_explained(env):
    store, fake, r2 = env
    _configure(r2)
    store.update("r2", {"access_key_id": "revoked"})
    with pytest.raises(AuthRequired) as e:
        r2.find_child("", "x")
    assert classify(e.value, "r2") == "wrong_keys"


def test_generic_s3_endpoint(tmp_path, monkeypatch):
    for f in S3.FIELDS:
        monkeypatch.delenv("SNACK_S3_" + f.upper(), raising=False)
    store = CredentialStore(tmp_path / "c.json")
    fake = FakeS3()
    s = S3(store, fake, sleep=lambda x: None)
    s.configure({"endpoint": ENDPOINT, "region": "eu-west-1", "bucket": BUCKET, "access_key_id": KEY_ID,
                 "secret_access_key": SECRET})
    assert "/eu-west-1/s3/aws4_request" in fake.calls[-1][2]["headers"]["Authorization"]


def test_vault_on_r2_roundtrip(env, tmp_path):
    from cloud_drive import cryptomator as cm
    _, fake, r2 = env
    _configure(r2)
    v = CryptomatorVault.create(r2, "Vault", "pw-12345678")
    src = tmp_path / "a.png"
    src.write_bytes(b"secret image")
    v.upload(str(src), "ComfyUI/x")
    v.upload(str(src), "ComfyUI/x")
    again = CryptomatorVault.unlock(R2(r2.store, fake, sleep=lambda s: None), "Vault", "pw-12345678")
    assert again.keys.enc_key == v.keys.enc_key
    blobs = [b for k, b in fake.objects.items() if k.endswith(".c9r") and not k.endswith(("dir.c9r", "dirid.c9r"))]
    assert len(blobs) == 2 and all(cm.decrypt_bytes(v.keys, b) == b"secret image" for b in blobs)
    assert not any("ComfyUI" in k or "a.png" in k for k in fake.objects)
