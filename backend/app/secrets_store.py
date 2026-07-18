"""Encrypted secrets stored in the DB, AES-256-GCM under the vault key."""

from __future__ import annotations

KNOWN_SECRETS = ["anthropic_api_key", "imap_password", "pushover_user", "pushover_token"]


class SecretsStore:
    def __init__(self, db, vault):
        self.db = db
        self.vault = vault

    def set(self, name: str, value: str) -> None:
        nonce, ct = self.vault.encrypt(value)
        self.db.execute(
            "INSERT INTO secrets (name, nonce, ciphertext, updated_at) "
            "VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(name) DO UPDATE SET nonce=excluded.nonce, "
            "ciphertext=excluded.ciphertext, updated_at=excluded.updated_at",
            (name, nonce, ct),
        )

    def get(self, name: str) -> str | None:
        row = self.db.query_one("SELECT nonce, ciphertext FROM secrets WHERE name = ?", (name,))
        if row is None:
            return None
        return self.vault.decrypt(row["nonce"], row["ciphertext"])

    def delete(self, name: str) -> None:
        self.db.execute("DELETE FROM secrets WHERE name = ?", (name,))

    def status(self) -> dict[str, bool]:
        present = {r["name"] for r in self.db.query("SELECT name FROM secrets")}
        return {name: name in present for name in KNOWN_SECRETS}
