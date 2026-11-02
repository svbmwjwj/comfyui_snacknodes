"""The node's connect panel backend (cloud_drive/connect.py)."""

import json

import pytest
from test_s3 import ACCOUNT, BUCKET, ENDPOINT, KEY_ID, SECRET, FakeS3
from test_webdav import BASE, FakeDav

from cloud_drive.config import CredentialStore
from cloud_drive.connect import FORMS, Connector
from cloud_drive.s3 import R2, S3
from cloud_drive.webdav import WebDAV


@pytest.fixture
def env(tmp_path, monkeypatch):
    for prefix in ("SNACK_R2_", "SNACK_S3_"):
        for f in S3.FIELDS + ("account_id",):
            monkeypatch.delenv(prefix + f.upper(), raising=False)
    for v in ("SNACK_WEBDAV_URL", "SNACK_WEBDAV_USERNAME", "SNACK_WEBDAV_PASSWORD"):
        monkeypatch.delenv(v, raising=False)
    store = CredentialStore(tmp_path / "c.json")
    s3, dav = FakeS3(), FakeDav()

    class R2Fake(R2):
        def __init__(self, store):
            super().__init__(store, s3, sleep=lambda s: None)

    class DavFake(WebDAV):
        def __init__(self, store):
            super().__init__(store, dav, sleep=lambda s: None)

    return store, s3, Connector(store, {"r2": R2Fake, "webdav": DavFake})


def test_r2_from_s3_api_url(env):
    store, s3, c = env
    assert c.status("r2")["connected"] is False and c.status("r2")["form"] is FORMS["r2"]
    s3.objects["old.png"] = b"x" * 1000
    out = c.connect("r2", {"s3_url": f"https://{ACCOUNT}.r2.cloudflarestorage.com/{BUCKET}",
                           "access_key_id": KEY_ID, "secret_access_key": SECRET, "limit_gb": ""})
    assert out["connected"] and out["summary"]["zh"] == f"存储桶 {BUCKET}，上限 10 GB"
    assert out["note"]["en"] == "0.00 GB used"
    saved = store.get("r2")
    assert saved["endpoint"] == ENDPOINT and saved["bucket"] == BUCKET and saved["limit_gb"] == 10.0


def test_status_never_contains_secrets(env):
    _, _, c = env
    c.connect("r2", {"s3_url": f"{ACCOUNT}.r2.cloudflarestorage.com/{BUCKET}", "access_key_id": KEY_ID,
                     "secret_access_key": SECRET, "limit_gb": "0"})
    text = json.dumps(c.status("r2"), ensure_ascii=False)
    assert SECRET not in text and KEY_ID not in text and "不限容量" in text


def test_r2_errors_are_explained(env):
    _, _, c = env
    with pytest.raises(Exception) as e:
        c.connect("r2", {"s3_url": f"https://{ACCOUNT}.r2.cloudflarestorage.com", "access_key_id": KEY_ID,
                         "secret_access_key": SECRET})
    assert "bucket" in str(e.value)
    with pytest.raises(Exception) as e:
        c.connect("r2", {"s3_url": f"https://{ACCOUNT}.r2.cloudflarestorage.com/{BUCKET}",
                         "access_key_id": "wrong", "secret_access_key": SECRET})
    err = c.error("r2", e.value)
    assert err["zh"].startswith("Cloudflare R2 的 Access Key ID 或 Secret Access Key 错误")
    assert not c.status("r2")["connected"]
    with pytest.raises(Exception) as e:
        c.connect("r2", {"s3_url": "https://example.com/x", "access_key_id": "a", "secret_access_key": "b"})
    assert c.error("r2", e.value)["zh"] == "连接失败。" and "not an R2 address" in c.error("r2", e.value)["detail"]


def test_webdav_connect_and_disconnect(env):
    store, _, c = env
    with pytest.raises(Exception) as e:
        c.connect("webdav", {"url": BASE, "username": "me", "password": "bad"})
    assert c.error("webdav", e.value)["zh"].startswith("WebDAV 用户名或密码错误")
    out = c.connect("webdav", {"url": BASE, "username": "me", "password": "app-pw"})
    assert out["connected"] and out["summary"]["en"] == f"me @ {BASE}" and "app-pw" not in json.dumps(out)
    store.update("vault:webdav", {"enc_key": "k"})
    assert c.disconnect("webdav")["connected"] is False
    assert store.get("webdav") == {} and store.get("vault:webdav") == {}


def test_unknown_provider(env):
    with pytest.raises(KeyError):
        env[2].status("aliyundrive")


def test_google_device_flow_in_background(tmp_path, monkeypatch):
    import threading

    from cloud_drive import connect as mod
    store = CredentialStore(tmp_path / "c.json")
    release = threading.Event()

    class FakeGoogle:
        display_name = "Google Drive"

        def __init__(self, store):
            self.store = store

        def is_authorized(self):
            return bool(self.store.get("google_drive").get("refresh_token"))

        def _creds(self):
            return {}

        def start_device_flow(self, client_id):
            return {"verification_url": "https://www.google.com/device", "user_code": "ABCD-EFGH",
                    "device_code": "dc", "expires_in": 900}

        def finish_device_flow(self, cid, secret, flow):
            release.wait(5)
            self.store.update("google_drive", {"refresh_token": "rt"})

    c = Connector(store, {"google_drive": FakeGoogle})
    first = c.oauth_start("google_drive")
    assert first["oauth"] == {"state": "pending", "url": "https://www.google.com/device", "code": "ABCD-EFGH"}
    assert c.oauth_start("google_drive")["oauth"]["code"] == "ABCD-EFGH"  # same flow while pending
    release.set()
    for _ in range(100):
        if c.status("google_drive")["connected"]:
            break
        threading.Event().wait(0.02)
    status = c.status("google_drive")
    assert status["connected"] and status["oauth"]["state"] == "done"
    assert mod.FORMS["google_drive"]["kind"] == "oauth"


def _connected_dav(c):
    c.connect("webdav", {"url": BASE, "username": "me", "password": "app-pw"})


def test_vault_needs_a_connected_drive(env):
    _, _, c = env
    assert c.vault_status("webdav") == {"provider": "webdav", "connected": False, "vault": None,
                                        "default_path": "ComfyUI-Vault", "min_password": 8}
    with pytest.raises(Exception) as e:
        c.vault_create("webdav", {"path": "V", "password": "long enough"})
    assert c.vault_error("webdav", e.value)["zh"] == "请先在上面连接网盘。"


def test_vault_create_unlock_forget(env):
    store, _, c = env
    _connected_dav(c)
    with pytest.raises(Exception) as e:
        c.vault_create("webdav", {"path": "V", "password": "short"})
    assert "至少 8 个字符" in c.vault_error("webdav", e.value)["zh"]

    out = c.vault_create("webdav", {"path": "/My Vault/", "password": "correct horse"})
    assert out["vault"] == {"path": "My Vault"}
    saved = store.get("vault:webdav")
    assert saved["path"] == "My Vault" and saved["enc_key"]
    assert "correct horse" not in json.dumps(store.get("vault:webdav")) + json.dumps(out)

    with pytest.raises(Exception) as e:
        c.vault_create("webdav", {"path": "My Vault", "password": "correct horse"})
    assert "已经有一个保险库" in c.vault_error("webdav", e.value)["zh"]

    assert c.vault_forget("webdav")["vault"] is None and store.get("vault:webdav") == {}
    with pytest.raises(Exception) as e:
        c.vault_unlock("webdav", {"path": "My Vault", "password": "wrong password"})
    assert c.vault_error("webdav", e.value)["zh"] == "保险库密码错误。"
    with pytest.raises(Exception) as e:
        c.vault_unlock("webdav", {"path": "Nope", "password": "correct horse"})
    assert c.vault_error("webdav", e.value)["zh"].startswith("这个位置没有保险库")

    out = c.vault_unlock("webdav", {"path": "My Vault", "password": "correct horse"})
    assert out["vault"] == {"path": "My Vault"} and store.get("vault:webdav")["enc_key"] == saved["enc_key"]
