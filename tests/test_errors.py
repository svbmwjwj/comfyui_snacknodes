"""Friendly error messages for upload failures."""

import os

import pytest
import requests

from cloud_drive.base import AuthRequired, CloudDriveError
from cloud_drive.errors import classify, explain
from cloud_drive.vault import VaultNotConfigured


@pytest.mark.parametrize("exc, provider, code", [
    (AuthRequired("Google Drive is not authorized."), "google_drive", "not_authorized"),
    (AuthRequired("rejected", status=401), "webdav", "wrong_password"),
    (CloudDriveError("x", status=401), "google_drive", "not_authorized"),
    (CloudDriveError("PUT failed: HTTP 403", status=403, body="Forbidden"), "webdav", "forbidden"),
    (CloudDriveError("x", status=403, body='{"error":{"errors":[{"reason":"storageQuotaExceeded"}]}}'),
     "google_drive", "quota"),
    (CloudDriveError("x", status=403, body='{"error":{"errors":[{"reason":"userRateLimitExceeded"}]}}'),
     "google_drive", "rate_limited"),
    (CloudDriveError("x", status=400, body='{"code":"QuotaExhausted.Drive"}'), "aliyundrive", "quota"),
    (CloudDriveError("x", status=507, body=""), "webdav", "quota"),
    (CloudDriveError("x", status=413, body=""), "webdav", "too_large"),
    (CloudDriveError("x", status=409, body="Conflict"), "webdav", "conflict"),
    (CloudDriveError("x", status=404, body=""), "webdav", "not_found"),
    (CloudDriveError("x", status=429, body=""), "webdav", "rate_limited"),
    (CloudDriveError("x", status=503, body=""), "webdav", "rate_limited"),
    (CloudDriveError("x", status=500, body=""), "webdav", "server_error"),
    (CloudDriveError("failed after 4 attempts: ConnectionError", network=True), "webdav", "network"),
    (requests.ConnectionError("proxy"), "google_drive", "network"),
    (VaultNotConfigured("No vault configured"), "webdav", "vault_not_configured"),
    (FileNotFoundError("nope"), "webdav", "local_file"),
    (ValueError("odd"), "webdav", "unknown"),
])
def test_classify(exc, provider, code):
    assert classify(exc, provider) == code


def test_cause_chain_is_followed():
    try:
        try:
            raise requests.Timeout("read timed out")
        except requests.Timeout as inner:
            raise RuntimeError("wrapper") from inner
    except RuntimeError as outer:
        assert classify(outer) == "network"


def test_explain_texts():
    e = explain(AuthRequired("not authorized"), "webdav", "WebDAV", file_name="a.png", local_copy="/out/a.png")
    assert e.code == "not_authorized"
    assert e.zh.splitlines()[0] == "WebDAV 尚未授权，或授权已失效。"
    assert "auth.py webdav" in e.zh and "auth.py webdav" in e.en
    assert "文件：a.png（本地副本已保存在 /out/a.png）" in e.zh
    assert e.detail == "not authorized"
    assert e.text("zh-CN") == e.zh and e.text("en") == e.en and e.text(None) == f"{e.zh}\n{e.en}"
    v = explain(VaultNotConfigured("x"), "google_drive", "Google Drive")
    assert "vault-create google_drive" in v.zh


def test_retries_keep_status_or_mark_network():
    from fake_http import FakeResponse, FakeSession

    from cloud_drive.base import request
    s = FakeSession()
    s.route("GET", "https://busy/", lambda **kw: FakeResponse(503, content=b"busy"))
    with pytest.raises(CloudDriveError) as info:
        request(s, "GET", "https://busy/", sleep=lambda x: None)
    assert info.value.status == 503 and classify(info.value) == "rate_limited"

    s2 = FakeSession()

    def down(**kw):
        raise requests.ConnectionError("refused")
    s2.route("GET", "https://down/", down)
    with pytest.raises(CloudDriveError) as info:
        request(s2, "GET", "https://down/", sleep=lambda x: None)
    assert info.value.network and classify(info.value) == "network"


def test_terminal_hint_uses_the_folder_name_in_custom_nodes(tmp_path):
    """With a symlink in custom_nodes/ the hint must show the link's name, not the target's."""
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    nodes = tmp_path / "custom_nodes"
    nodes.mkdir()
    (nodes / "SnackNodes").symlink_to(root)
    code = "import importlib; print(importlib.import_module('SnackNodes.cloud_drive.paths').AUTH_SCRIPT)"
    out = subprocess.run([sys.executable, "-c", code], cwd=nodes, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(nodes)})
    assert out.stdout.strip() == "python custom_nodes/SnackNodes/auth.py", out.stderr
