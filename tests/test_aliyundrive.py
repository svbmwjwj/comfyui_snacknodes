import pytest

from cloud_drive import aliyundrive as ad
from cloud_drive.base import CloudDriveError
from cloud_drive.config import CredentialStore
from fake_http import FakeResponse, FakeSession

API = ad.API


@pytest.fixture
def store(tmp_path):
    s = CredentialStore(tmp_path / "c.json")
    s.update("aliyundrive", {"client_id": "cid", "client_secret": "sec", "refresh_token": "rt0"})
    return s


def base_session():
    s = FakeSession()
    s.route("POST", f"{API}/oauth/access_token",
            lambda **kw: FakeResponse(200, {"access_token": "at", "refresh_token": "rt1", "expires_in": 7200}))
    s.route("POST", f"{API}/adrive/v1.0/user/getDriveInfo",
            lambda **kw: FakeResponse(200, {"default_drive_id": "backup", "resource_drive_id": "res"}))
    return s


def make(store, session):
    return ad.AliyunDrive(store, session, clock=lambda: 1000.0, sleep=lambda s: None)


def test_refresh_token_rotation_is_persisted(store):
    drive = make(store, base_session())
    assert drive.access_token() == "at"
    assert store.get("aliyundrive")["refresh_token"] == "rt1"


def test_upload_multipart_with_expired_url(store, tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "PART_SIZE", 1000)
    data = b"x" * 2500  # 3 parts
    f = tmp_path / "v.mp4"
    f.write_bytes(data)
    session = base_session()
    creates = []

    def list_children(json, **kw):
        names = {"root": [{"name": "ComfyUI", "file_id": "f-comfy", "type": "folder"}]}
        return FakeResponse(200, {"items": names.get(json["parent_file_id"], []), "next_marker": ""})

    def create(json, **kw):
        creates.append(json)
        if json["type"] == "folder":
            return FakeResponse(200, {"file_id": "f-day"})
        return FakeResponse(200, {"file_id": "file1", "upload_id": "up1", "part_info_list": [
            {"part_number": i, "upload_url": f"https://oss/part{i}"} for i in (1, 2, 3)]})

    session.route("POST", f"{API}/adrive/v1.0/openFile/list", list_children)
    session.route("POST", f"{API}/adrive/v1.0/openFile/create", create)
    session.route("POST", f"{API}/adrive/v1.0/openFile/getUploadUrl", lambda json, **kw: FakeResponse(
        200, {"part_info_list": [{"part_number": 2, "upload_url": "https://oss/part2-fresh"}]}))
    session.route("POST", f"{API}/adrive/v1.0/openFile/complete", lambda json, **kw: FakeResponse(
        200, {"name": "v.mp4", "file_id": json["file_id"]}))
    parts = {}

    def put(url, data, **kw):
        if url == "https://oss/part2":
            return FakeResponse(403, {})
        parts[url] = data
        return FakeResponse(200, {})

    session.route("PUT", "https://oss/", put)
    result = make(store, session).upload(str(f), "ComfyUI/2026-11-01")

    assert parts == {"https://oss/part1": b"x" * 1000, "https://oss/part2-fresh": b"x" * 1000,
                     "https://oss/part3": b"x" * 500}
    assert creates[0] == {"drive_id": "res", "parent_file_id": "f-comfy", "name": "2026-11-01",
                          "type": "folder", "check_name_mode": "refuse"}
    assert creates[1]["parent_file_id"] == "f-day" and creates[1]["size"] == 2500
    assert creates[1]["check_name_mode"] == "auto_rename"
    assert result.remote_path == "ComfyUI/2026-11-01/v.mp4"


def test_refuse_mode_reports_existing_file(store, tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"1")
    session = base_session()
    session.route("POST", f"{API}/adrive/v1.0/openFile/create",
                  lambda **kw: FakeResponse(200, {"file_id": "old", "exist": True}))
    with pytest.raises(CloudDriveError, match="already exists"):
        make(store, session).upload_file("root", "a", str(f), allow_rename=False)


def test_backup_drive_can_be_selected(store):
    store.update("aliyundrive", {"drive": "backup"})
    assert make(store, base_session()).drive_id() == "backup"


def test_qr_flow(tmp_path):
    store = CredentialStore(tmp_path / "c.json")
    session = base_session()
    states = iter([{"status": "WaitLogin"}, {"status": "ScanSuccess"},
                   {"status": "LoginSuccess", "authCode": "code1"}])
    session.route("GET", f"{API}/oauth/qrcode/sid1/status", lambda **kw: FakeResponse(200, next(states)))
    seen = []
    make(store, session).finish_qr_flow("cid", "sec", "sid1", on_status=seen.append)
    assert seen == ["WaitLogin", "ScanSuccess", "LoginSuccess"]
    assert store.get("aliyundrive")["refresh_token"] == "rt1"


def test_part_urls_are_refreshed_after_50_minutes(store, tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "PART_SIZE", 10)
    f = tmp_path / "a"
    f.write_bytes(b"y" * 25)
    now = [1000.0]
    session = base_session()
    session.route("POST", f"{API}/adrive/v1.0/openFile/create", lambda json, **kw: FakeResponse(200, {
        "file_id": "f", "upload_id": "u",
        "part_info_list": [{"part_number": i, "upload_url": f"https://oss/old{i}"} for i in (1, 2, 3)]}))
    refreshed = []

    def get_url(json, **kw):
        n = json["part_info_list"][0]["part_number"]
        refreshed.append(n)
        return FakeResponse(200, {"part_info_list": [{"part_number": n, "upload_url": f"https://oss/new{n}"}]})

    session.route("POST", f"{API}/adrive/v1.0/openFile/getUploadUrl", get_url)
    session.route("POST", f"{API}/adrive/v1.0/openFile/complete", lambda **kw: FakeResponse(200, {"name": "a"}))
    put_urls = []

    def put(url, **kw):
        put_urls.append(url)
        now[0] += 31 * 60  # each part takes 31 minutes
        return FakeResponse(200, {})

    session.route("PUT", "https://oss/", put)
    drive = ad.AliyunDrive(store, session, clock=lambda: now[0], sleep=lambda s: None)
    drive.upload_file("root", "a", str(f))
    assert put_urls == ["https://oss/old1", "https://oss/old2", "https://oss/new3"]
    assert refreshed == [3]


def test_import_refresh_token(tmp_path):
    store = CredentialStore(tmp_path / "c.json")
    make(store, base_session()).import_refresh_token("cid", "sec", "given")
    saved = store.get("aliyundrive")
    assert saved["refresh_token"] == "rt1" and saved["client_id"] == "cid"
