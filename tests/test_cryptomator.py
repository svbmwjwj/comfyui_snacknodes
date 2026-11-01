import os

import pytest

from cloud_drive import cryptomator as cm


def test_aes_siv_rfc5297_vector():
    key = bytes.fromhex("fffefdfcfbfaf9f8f7f6f5f4f3f2f1f0f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff")
    ad = bytes.fromhex("101112131415161718191a1b1c1d1e1f2021222324252627")
    pt = bytes.fromhex("112233445566778899aabbccddee")
    ct = cm.siv_encrypt(key[16:], key[:16], pt, ad)
    assert ct.hex() == "85632d07c6e8f37f950acd320a2ecc9340c02b9690c4dc04daef7f6afe5c"
    assert cm.siv_decrypt(key[16:], key[:16], ct, ad) == pt


def test_aes_siv_empty_plaintext_roundtrip():
    k1, k2 = os.urandom(32), os.urandom(32)
    assert cm.siv_decrypt(k1, k2, cm.siv_encrypt(k1, k2, b"")) == b""


@pytest.mark.parametrize("size", [0, 1, cm.CHUNK_PLAIN - 1, cm.CHUNK_PLAIN, cm.CHUNK_PLAIN * 3 + 7])
def test_file_content_roundtrip_and_size(size):
    keys = cm.VaultKeys.generate()
    data = os.urandom(size)
    ct = cm.encrypt_bytes(keys, data)
    chunks = -(-size // cm.CHUNK_PLAIN)
    assert len(ct) == cm.HEADER_SIZE + size + chunks * (cm.NONCE + cm.TAG)
    assert cm.decrypt_bytes(keys, ct) == data


def test_tampered_chunk_is_rejected():
    keys = cm.VaultKeys.generate()
    ct = bytearray(cm.encrypt_bytes(keys, b"x" * 100))
    ct[-1] ^= 1
    with pytest.raises(cm.VaultError):
        cm.decrypt_bytes(keys, bytes(ct))


def test_masterkey_roundtrip_and_wrong_password():
    keys = cm.VaultKeys.generate()
    data = cm.create_masterkey_file(keys, "pässwörd 测试")
    assert cm.unlock_masterkey_file(data, "pässwörd 测试") == keys
    with pytest.raises(cm.VaultError, match="Wrong vault password"):
        cm.unlock_masterkey_file(data, "nope")


def test_vault_config_signature():
    keys = cm.VaultKeys.generate()
    cfg = cm.create_vault_config(keys)
    assert cm.verify_vault_config(cfg, keys)["format"] == 8
    with pytest.raises(cm.VaultError):
        cm.verify_vault_config(cfg, cm.VaultKeys.generate())


def test_names_are_deterministic_and_bound_to_parent():
    keys = cm.VaultKeys.generate()
    a = cm.encrypt_name(keys, "image.png", "dir-a")
    assert a == cm.encrypt_name(keys, "image.png", "dir-a")
    assert a != cm.encrypt_name(keys, "image.png", "dir-b")
    assert cm.decrypt_name(keys, a, "dir-a") == "image.png"
    with pytest.raises(cm.VaultError):
        cm.decrypt_name(keys, a, "dir-b")


def test_dir_path_shape():
    a, b = cm.dir_path(cm.VaultKeys.generate(), "")
    assert len(a) == 2 and len(b) == 30
