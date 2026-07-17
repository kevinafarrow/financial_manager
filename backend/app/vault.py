"""Master-passphrase vault.

The passphrase is stretched with argon2id into a 32-byte key that (a) keys the
SQLCipher database and (b) AES-256-GCM-encrypts individual secrets stored in it.
Only non-secret KDF metadata is written to disk (vault.json); the derived key
lives in memory for the lifetime of the unlocked process.
"""

from __future__ import annotations

import base64
import json
import os
import secrets as pysecrets
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KDF_PARAMS = {"time_cost": 3, "memory_cost": 65536, "parallelism": 2, "hash_len": 32}


class VaultError(Exception):
    pass


class VaultLocked(VaultError):
    pass


class WrongPassphrase(VaultError):
    pass


class Vault:
    def __init__(self, meta_path: Path):
        self.meta_path = meta_path
        self._key: bytes | None = None
        self._hasher = PasswordHasher()

    # -- state ---------------------------------------------------------------

    @property
    def initialized(self) -> bool:
        return self.meta_path.exists()

    @property
    def unlocked(self) -> bool:
        return self._key is not None

    @property
    def key(self) -> bytes:
        if self._key is None:
            raise VaultLocked("vault is locked")
        return self._key

    @property
    def key_hex(self) -> str:
        return self.key.hex()

    # -- lifecycle -----------------------------------------------------------

    def initialize(self, passphrase: str) -> None:
        if self.initialized:
            raise VaultError("vault already initialized")
        if len(passphrase) < 10:
            raise VaultError("passphrase must be at least 10 characters")
        salt = os.urandom(16)
        key = self._derive(passphrase, salt)
        meta = {
            "version": 1,
            "salt": base64.b64encode(salt).decode(),
            "kdf": dict(KDF_PARAMS),
            "key_verifier": self._hasher.hash(key),
        }
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, indent=2))
        tmp.replace(self.meta_path)
        self._key = key

    def unlock(self, passphrase: str) -> None:
        if not self.initialized:
            raise VaultError("vault not initialized")
        meta = json.loads(self.meta_path.read_text())
        salt = base64.b64decode(meta["salt"])
        key = self._derive(passphrase, salt, meta["kdf"])
        try:
            self._hasher.verify(meta["key_verifier"], key)
        except VerifyMismatchError:
            raise WrongPassphrase("wrong passphrase") from None
        self._key = key

    def lock(self) -> None:
        self._key = None

    # -- crypto --------------------------------------------------------------

    def _derive(self, passphrase: str, salt: bytes, params: dict | None = None) -> bytes:
        p = params or KDF_PARAMS
        return hash_secret_raw(
            secret=passphrase.encode(),
            salt=salt,
            time_cost=p["time_cost"],
            memory_cost=p["memory_cost"],
            parallelism=p["parallelism"],
            hash_len=p["hash_len"],
            type=Type.ID,
        )

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes]:
        """Returns (nonce, ciphertext) for storage in the secrets table."""
        nonce = pysecrets.token_bytes(12)
        ct = AESGCM(self.key).encrypt(nonce, plaintext.encode(), None)
        return nonce, ct

    def decrypt(self, nonce: bytes, ciphertext: bytes) -> str:
        return AESGCM(self.key).decrypt(nonce, ciphertext, None).decode()
