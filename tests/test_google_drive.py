import json

import pytest

from cloud_drive import google_drive as gd
from cloud_drive.base import AuthRequired
from cloud_drive.config import CredentialStore
from fake_http import FakeResponse, FakeSession


@pytest.fixture
def store(tmp_path):
    s = CredentialStore(tmp_path / "c.json")
    s.update("google_drive", {"client_id": "cid", "client_secret": "sec", "refresh_token": "rt"})
    return s


def make_drive(store, session, now=1000.0):
    return gd.GoogleDrive(store, session, clock=lambda: now, sleep=lambda s: None)


def test_refresh_token_is_used_and_cached(store):
    session = FakeSession()
    session.route("POST", gd.TOKEN_URL, lambda **kw: FakeResponse(200, {"access_token": "at1", "expires_in": 3600}))
    drive = make_drive(store, session)
    assert drive.access_token() == "at1"
    assert drive.access_token() == "at1"
    assert len(session.calls) == 1
    assert store.get("google_drive")["refresh_token"] == "rt"


def test_missing_credentials_raise_auth_required(tmp_path):
    drive = make_drive(CredentialStore(tmp_path / "none.json"), FakeSession())
    with pytest.raises(AuthRequired, match="auth.py google_drive"):
        drive.access_token()


def test_upload_creates_folders_and_resumes_after_308(store, tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "CHUNK_SIZE", 256 * 1024)
    data = bytes(range(256)) * 4096  # 1 MiB -> 4 chunks
    f = tmp_path / "img.png"
    f.write_bytes(data)

    session = FakeSession()
    session.route("POST", gd.TOKEN_URL, lambda **kw: FakeResponse(200, {"access_token": "at", "expires_in": 3600}))
    created = []

    def list_files(params, **kw):
        # "ComfyUI" exists, "sub" does not
        return FakeResponse(200, {"files": [{"id": "fid-comfy"}] if "'ComfyUI'" in params["q"] else []})

    def create_folder(json, **kw):
        created.append(json)
        return FakeResponse(200, {"id": "fid-sub"})

    session.route("GET", gd.FILES_URL, list_files)
    session.route("POST", gd.FILES_URL, create_folder)
    session.route("POST", gd.UPLOAD_URL, lambda **kw: FakeResponse(200, {}, {"Location": "https://up/session"}))
    received = bytearray()
    flaky = {"done": False}

    def put(data, headers, **kw):
        rng = headers["Content-Range"]
        start = int(rng.split(" ")[1].split("-")[0])
        # simulate the server keeping only half of the 2nd chunk
        if start == 256 * 1024 and not flaky["done"]:
            flaky["done"] = True
            received.extend(data[:1000])
            return FakeResponse(308, {}, {"Range": f"bytes=0-{len(received) - 1}"})
        assert start == len(received)
        received.extend(data)
        if len(received) == len(data_all):
            return FakeResponse(200, {"id": "file1", "name": "img.png", "webViewLink": "https://drive/x"})
        return FakeResponse(308, {}, {"Range": f"bytes=0-{len(received) - 1}"})

    data_all = data
    session.route("PUT", "https://up/session", put)
    result = make_drive(store, session).upload(str(f), "ComfyUI/sub", mime_type="image/png")

    assert bytes(received) == data
    assert result.url == "https://drive/x"
    assert result.remote_path == "ComfyUI/sub/img.png"
    assert created == [{"name": "sub", "mimeType": gd.FOLDER_MIME, "parents": ["fid-comfy"]}]
    init = [c for c in session.calls if c[1].startswith(gd.UPLOAD_URL)][0][2]
    assert init["json"] == {"name": "img.png", "parents": ["fid-sub"]}
    assert init["headers"]["X-Upload-Content-Length"] == str(len(data))


def test_folder_names_are_escaped_in_queries(store):
    session = FakeSession()
    session.route("POST", gd.TOKEN_URL, lambda **kw: FakeResponse(200, {"access_token": "at", "expires_in": 3600}))
    seen = []
    session.route("GET", gd.FILES_URL,
                  lambda params, **kw: seen.append(params["q"]) or FakeResponse(200, {"files": [{"id": "x"}]}))
    make_drive(store, session).ensure_folder("it's")
    assert "name = 'it\\'s'" in seen[0]


def test_device_flow_saves_tokens(tmp_path):
    store = CredentialStore(tmp_path / "c.json")
    session = FakeSession()
    session.route("POST", gd.DEVICE_CODE_URL, lambda **kw: FakeResponse(200, {
        "device_code": "dc", "user_code": "ABCD", "verification_url": "https://g.co/device", "interval": 1}))
    answers = iter([FakeResponse(428, {"error": "authorization_pending"}),
                    FakeResponse(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600})])
    session.route("POST", gd.TOKEN_URL, lambda **kw: next(answers))
    drive = make_drive(store, session)
    drive.finish_device_flow("cid", "sec", drive.start_device_flow("cid"))
    saved = json.loads((tmp_path / "c.json").read_text())["google_drive"]
    assert saved["refresh_token"] == "rt" and saved["client_id"] == "cid"
