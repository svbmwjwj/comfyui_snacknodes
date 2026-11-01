"""WebDAV provider against a small in-memory WebDAV fake."""

import pytest
import requests
from fake_http import FakeResponse, FakeSession

from cloud_drive.base import AuthRequired, CloudDriveError
from cloud_drive.config import CredentialStore
from cloud_drive.vault import CryptomatorVault
from cloud_drive.webdav import WebDAV, is_insecure_url

BASE = "https://dav.example.com/dav/"
AUTH = (b"me", b"app-pw")


class FakeDav(FakeSession):
    """Path-keyed store; checks auth on every call."""

    def __init__(self, fail_puts=0):
        super().__init__()
        self.files = {}
        self.dirs = {""}
        self.fail_puts = fail_puts
        self.route("PROPFIND", BASE, self._propfind)
        self.route("MKCOL", BASE, self._mkcol)
        self.route("PUT", BASE, self._put)
        self.route("GET", BASE, self._get)

    @staticmethod
    def _path(url):
        from urllib.parse import unquote
        return unquote(url[len(BASE):]).strip("/")

    def _authed(self, kw):
        return kw.get("auth") == AUTH

    def _propfind(self, url, **kw):
        if not self._authed(kw):
            return FakeResponse(401, content=b"<html>no</html>")
        assert kw["headers"]["Depth"] == "0"
        p = self._path(url)
        return FakeResponse(207, content=b"<multistatus/>") if p in self.dirs or p in self.files \
            else FakeResponse(404, content=b"")

    def _mkcol(self, url, **kw):
        p = self._path(url)
        if p in self.dirs:
            return FakeResponse(405, content=b"")
        assert p.rsplit("/", 1)[0] in self.dirs or "/" not in p, "parent must exist"
        self.dirs.add(p)
        return FakeResponse(201, content=b"")

    def _put(self, url, **kw):
        body = kw["data"].read()
        if self.fail_puts:
            self.fail_puts -= 1
            return FakeResponse(503, content=b"busy")
        self.files[self._path(url)] = body
        return FakeResponse(201, content=b"")

    def _get(self, url, **kw):
        return FakeResponse(200, content=self.files[self._path(url)])


@pytest.fixture
def env(tmp_path, monkeypatch):
    for v in ("SNACK_WEBDAV_URL", "SNACK_WEBDAV_USERNAME", "SNACK_WEBDAV_PASSWORD"):
        monkeypatch.delenv(v, raising=False)
    store = CredentialStore(tmp_path / "c.json")
    dav = FakeDav()
    return store, dav, WebDAV(store, dav, sleep=lambda s: None)


def test_configure_checks_credentials(env):
    store, dav, w = env
    with pytest.raises(CloudDriveError, match="wrong username or password"):
        w.configure(BASE, "me", "bad")
    assert not w.is_authorized()
    with pytest.raises(CloudDriveError, match="https://"):
        w.configure("dav.example.com", "me", "app-pw")
    w.configure(BASE, "me", "app-pw")
    assert w.is_authorized() and store.get("webdav")["username"] == "me"


def test_unconfigured_raises_auth_required(env):
    _, _, w = env
    with pytest.raises(AuthRequired):
        w.find_child("", "x")


def test_env_vars(env, monkeypatch):
    _, dav, w = env
    monkeypatch.setenv("SNACK_WEBDAV_URL", BASE)
    monkeypatch.setenv("SNACK_WEBDAV_USERNAME", "me")
    monkeypatch.setenv("SNACK_WEBDAV_PASSWORD", "app-pw")
    assert w.is_authorized()
    assert w.ensure_folder("a/b") == "a/b"


def test_upload_quotes_paths_and_never_overwrites(env, tmp_path):
    _, dav, w = env
    w.configure(BASE, "me", "app-pw")
    src = tmp_path / "x.png"
    src.write_bytes(b"one")
    r1 = w.upload(str(src), "ComfyUI/测试 目录/#1", "pic.png")
    src.write_bytes(b"two")
    r2 = w.upload(str(src), "ComfyUI/测试 目录/#1", "pic.png")
    assert r1.remote_path == "ComfyUI/测试 目录/#1/pic.png"
    assert r2.remote_path == "ComfyUI/测试 目录/#1/pic_1.png"
    assert dav.files == {"ComfyUI/测试 目录/#1/pic.png": b"one", "ComfyUI/测试 目录/#1/pic_1.png": b"two"}
    urls = [u for m, u, _ in dav.calls if m == "PUT"]
    assert all(" " not in u and "#" not in u for u in urls)
    assert r1.describe() == "webdav:ComfyUI/测试 目录/#1/pic.png"
    with pytest.raises(CloudDriveError, match="already exists"):
        w.upload_file("ComfyUI/测试 目录/#1", "pic.png", str(src), allow_rename=False)


def test_put_retries_resend_whole_file(env, tmp_path):
    store, _, _ = env
    dav = FakeDav(fail_puts=2)
    w = WebDAV(store, dav, sleep=lambda s: None)
    w.configure(BASE, "me", "app-pw")
    src = tmp_path / "v.mp4"
    src.write_bytes(b"video-bytes")
    w.upload(str(src), "", "v.mp4")
    assert dav.files["v.mp4"] == b"video-bytes"


def test_put_network_error_then_success(env, tmp_path):
    store, dav, w = env
    w.configure(BASE, "me", "app-pw")
    real, calls = dav._put, []

    def flaky(url, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ConnectionError("reset")
        return real(url, **kw)
    dav.routes = [r if r[0] != "PUT" else ("PUT", BASE, flaky) for r in dav.routes]
    src = tmp_path / "f.bin"
    src.write_bytes(b"data")
    w.upload(str(src), "d", "f.bin")
    assert dav.files["d/f.bin"] == b"data" and len(calls) == 2


def test_vault_on_webdav_roundtrip(env, tmp_path):
    from cloud_drive import cryptomator as cm
    store, dav, w = env
    w.configure(BASE, "me", "app-pw")
    v = CryptomatorVault.create(w, "Vault", "pw-12345678")
    src = tmp_path / "a.png"
    src.write_bytes(b"secret image")
    v.upload(str(src), "ComfyUI/x")
    v.upload(str(src), "ComfyUI/x")
    again = CryptomatorVault.unlock(w, "Vault", "pw-12345678")
    assert again.keys.enc_key == v.keys.enc_key
    blobs = [b for p, b in dav.files.items() if p.endswith(".c9r") and not p.endswith(("dir.c9r", "dirid.c9r"))]
    assert len(blobs) == 2 and all(cm.decrypt_bytes(v.keys, b) == b"secret image" for b in blobs)
    assert not any("ComfyUI" in p or "a.png" in p for p in dav.files)


def test_insecure_url():
    assert is_insecure_url("http://dav.example.com/")
    assert not is_insecure_url("http://127.0.0.1:8080/dav")
    assert not is_insecure_url("https://dav.example.com/")


def test_non_latin1_password_is_sent_as_utf8(tmp_path):
    """requests would encode str credentials as latin-1 and crash on Chinese passwords."""
    import base64
    from requests.auth import _basic_auth_str
    store = CredentialStore(tmp_path / "c.json")
    seen = []

    class S(FakeSession):
        pass
    s = S()
    s.route("PROPFIND", BASE, lambda url, **kw: (seen.append(kw["auth"]), FakeResponse(207, content=b""))[1])
    WebDAV(store, s, sleep=lambda x: None).configure(BASE, "用户", "密码 pw!")
    header = _basic_auth_str(*seen[0])
    assert base64.b64decode(header.split()[1]).decode("utf-8") == "用户:密码 pw!"
