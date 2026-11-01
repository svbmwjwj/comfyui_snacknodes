"""auth.py: vault password choice and built-in OAuth client fallback."""

import argparse

import pytest

import auth


def _args(**kw):
    return argparse.Namespace(**{"generate_password": False, "own_password": False, **kw})


def _feed(monkeypatch, answers, secrets=()):
    it, sec = iter(answers), iter(secrets)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))
    monkeypatch.setattr(auth.getpass, "getpass", lambda prompt="": next(sec))


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("SNACK_VAULT_PASSWORD", raising=False)


def test_generated_password_is_strong_and_unambiguous():
    pw = auth.generate_password()
    groups = pw.split("-")
    assert len(groups) == 6 and all(len(g) == 5 for g in groups)
    assert not set(pw) & set("01loIO")
    assert auth.generate_password() != pw


def test_generate_requires_confirming_last_group(monkeypatch, capsys):
    monkeypatch.setattr(auth, "generate_password", lambda: "aaaaa-bbbbb-ccccc")
    _feed(monkeypatch, ["2", "wrong", "ccccc"])
    assert auth._new_vault_password(_args()) == "aaaaa-bbbbb-ccccc"
    out = capsys.readouterr().out
    assert "ONLY way to recover" in out and "aaaaa-bbbbb-ccccc" in out


def test_generate_not_confirmed_aborts(monkeypatch):
    monkeypatch.setattr(auth, "generate_password", lambda: "aaaaa-bbbbb")
    _feed(monkeypatch, ["x", "y", "z"])
    with pytest.raises(SystemExit, match="Not confirmed"):
        auth._new_vault_password(_args(generate_password=True))


def test_own_password(monkeypatch, capsys):
    _feed(monkeypatch, ["", "1"], ["my-long-pass", "my-long-pass"])
    assert auth._new_vault_password(_args()) == "my-long-pass"
    assert "ONLY way to recover" in capsys.readouterr().out
    _feed(monkeypatch, [], ["short", "short"])
    with pytest.raises(SystemExit, match="8 characters"):
        auth._new_vault_password(_args(own_password=True))
    _feed(monkeypatch, [], ["my-long-pass", "different!"])
    with pytest.raises(SystemExit, match="do not match"):
        auth._new_vault_password(_args(own_password=True))


def test_env_password_skips_prompts(monkeypatch):
    monkeypatch.setenv("SNACK_VAULT_PASSWORD", "from-env-123")
    assert auth._new_vault_password(_args()) == "from-env-123"


def test_google_client_resolution_order(monkeypatch):
    from cloud_drive import google_drive as gd
    from cloud_drive.base import CloudDriveError
    monkeypatch.delenv("SNACK_GDRIVE_CLIENT_ID", raising=False)
    monkeypatch.delenv("SNACK_GDRIVE_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(gd, "BUILTIN_CLIENT_ID", "")
    monkeypatch.setattr(gd, "BUILTIN_CLIENT_SECRET", "")
    assert gd.resolve_client() == (None, None, "none")
    monkeypatch.setattr(gd, "BUILTIN_CLIENT_ID", "b-id")
    monkeypatch.setattr(gd, "BUILTIN_CLIENT_SECRET", "b-sec")
    assert gd.resolve_client() == ("b-id", "b-sec", "built-in")
    monkeypatch.setenv("SNACK_GDRIVE_CLIENT_ID", "e-id")
    monkeypatch.setenv("SNACK_GDRIVE_CLIENT_SECRET", "e-sec")
    assert gd.resolve_client() == ("e-id", "e-sec", "environment")
    assert gd.resolve_client("a-id", "a-sec") == ("a-id", "a-sec", "command line")
    with pytest.raises(CloudDriveError, match="both"):
        gd.resolve_client("a-id", None)
