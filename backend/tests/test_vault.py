import json

import pytest

from app.vault import Vault, VaultError, VaultLocked, WrongPassphrase


def test_initialize_and_unlock_roundtrip(tmp_path):
    v = Vault(tmp_path / "vault.json")
    assert not v.initialized
    v.initialize("a strong passphrase")
    assert v.initialized and v.unlocked
    key1 = v.key

    v2 = Vault(tmp_path / "vault.json")
    v2.unlock("a strong passphrase")
    assert v2.key == key1


def test_wrong_passphrase_rejected(tmp_path):
    v = Vault(tmp_path / "vault.json")
    v.initialize("a strong passphrase")
    v2 = Vault(tmp_path / "vault.json")
    with pytest.raises(WrongPassphrase):
        v2.unlock("a wrong passphrase!")
    assert not v2.unlocked


def test_lock_wipes_key(vault):
    vault.lock()
    assert not vault.unlocked
    with pytest.raises(VaultLocked):
        _ = vault.key


def test_meta_file_contains_no_secrets(vault):
    meta = json.loads(vault.meta_path.read_text())
    assert set(meta) == {"version", "salt", "kdf", "key_verifier"}
    # verifier is an argon2 hash of the derived key, not the key or passphrase
    assert "correct horse" not in json.dumps(meta)
    assert vault.key.hex() not in json.dumps(meta)


def test_short_passphrase_rejected(tmp_path):
    v = Vault(tmp_path / "vault.json")
    with pytest.raises(VaultError):
        v.initialize("short")


def test_double_initialize_rejected(vault):
    with pytest.raises(VaultError):
        vault.initialize("another passphrase!")


def test_secret_encrypt_decrypt_roundtrip(vault):
    nonce, ct = vault.encrypt("sk-ant-secret-key")
    assert b"sk-ant" not in ct
    assert vault.decrypt(nonce, ct) == "sk-ant-secret-key"


def test_decrypt_with_other_key_fails(tmp_path, vault):
    nonce, ct = vault.encrypt("topsecret")
    other = Vault(tmp_path / "other.json")
    other.initialize("a different passphrase")
    with pytest.raises(Exception):
        other.decrypt(nonce, ct)
