"""SQLCipher database layer: connection management and migrations.

A single connection is shared across FastAPI's threadpool, serialized by an RLock.
All amounts are stored as integer cents. Dates are ISO-8601 TEXT (UTC).
"""

from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import regex as regex_lib
import sqlcipher3


@lru_cache(maxsize=256)
def _compile(pattern: str):
    return regex_lib.compile(pattern, regex_lib.IGNORECASE)


def _regexp(pattern: str, value) -> bool:
    """Backs SQL `column REGEXP ?` — powered by the `regex` library."""
    if value is None:
        return False
    return _compile(pattern).search(str(value)) is not None

MIGRATIONS: list[str] = [
    # v1 — full initial schema
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at TEXT NOT NULL,
        ip TEXT
    );
    CREATE TABLE secrets (
        name TEXT PRIMARY KEY,
        nonce BLOB NOT NULL,
        ciphertext BLOB NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE accounts (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        institution TEXT NOT NULL DEFAULT '',
        type TEXT NOT NULL CHECK (type IN ('checking','savings','credit','investment','mortgage','benefits')),
        kind TEXT NOT NULL DEFAULT 'ledger' CHECK (kind IN ('ledger','balance_only')),
        currency TEXT NOT NULL DEFAULT 'USD',
        low_balance_threshold_cents INTEGER,
        staleness_days INTEGER NOT NULL DEFAULT 10,
        archived INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE balance_snapshots (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        as_of TEXT NOT NULL,
        balance_cents INTEGER NOT NULL,
        source TEXT NOT NULL DEFAULT 'manual',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE categories (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL DEFAULT 'expense' CHECK (kind IN ('expense','income','system')),
        sort_order INTEGER NOT NULL DEFAULT 0,
        archived INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE imports (
        id INTEGER PRIMARY KEY,
        filename TEXT NOT NULL,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        format TEXT NOT NULL,
        tx_count INTEGER NOT NULL DEFAULT 0,
        dup_count INTEGER NOT NULL DEFAULT 0,
        user_id INTEGER REFERENCES users(id),
        imported_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE transactions (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        fitid TEXT,
        content_hash TEXT NOT NULL,
        posted_at TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        payee_raw TEXT NOT NULL,
        payee_norm TEXT NOT NULL,
        memo TEXT NOT NULL DEFAULT '',
        category_id INTEGER REFERENCES categories(id),
        cat_source TEXT NOT NULL DEFAULT 'none'
            CHECK (cat_source IN ('history','rule','bayes','claude','user','receipt','none')),
        cat_confidence REAL,
        transfer_id INTEGER,
        import_id INTEGER REFERENCES imports(id),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_by INTEGER REFERENCES users(id)
    );
    CREATE INDEX idx_tx_account_posted ON transactions(account_id, posted_at);
    CREATE INDEX idx_tx_payee_norm ON transactions(payee_norm);
    CREATE INDEX idx_tx_category ON transactions(category_id);
    CREATE UNIQUE INDEX idx_tx_fitid ON transactions(account_id, fitid) WHERE fitid IS NOT NULL;
    CREATE INDEX idx_tx_content_hash ON transactions(account_id, content_hash);
    CREATE TABLE transaction_splits (
        id INTEGER PRIMARY KEY,
        transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
        category_id INTEGER NOT NULL REFERENCES categories(id),
        amount_cents INTEGER NOT NULL,
        note TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE category_history (
        id INTEGER PRIMARY KEY,
        payee_norm TEXT NOT NULL,
        category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
        source TEXT NOT NULL CHECK (source IN ('user','receipt','claude')),
        user_id INTEGER REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_cathist_payee ON category_history(payee_norm, created_at);
    CREATE TABLE rules (
        id INTEGER PRIMARY KEY,
        field TEXT NOT NULL DEFAULT 'payee' CHECK (field IN ('payee','memo')),
        pattern TEXT NOT NULL,
        category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
        priority INTEGER NOT NULL DEFAULT 100,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE transfers (
        id INTEGER PRIMARY KEY,
        from_tx INTEGER NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
        to_tx INTEGER NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
        status TEXT NOT NULL DEFAULT 'auto' CHECK (status IN ('auto','confirmed')),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE transfer_candidates (
        id INTEGER PRIMARY KEY,
        tx_a INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
        tx_b INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
        score REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','rejected')),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (tx_a, tx_b)
    );
    CREATE TABLE recurring (
        id INTEGER PRIMARY KEY,
        payee_norm TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        amount_cents INTEGER NOT NULL,
        tolerance_cents INTEGER NOT NULL DEFAULT 0,
        period TEXT NOT NULL CHECK (period IN ('weekly','biweekly','monthly','yearly')),
        day_of_month INTEGER,
        next_due TEXT,
        status TEXT NOT NULL DEFAULT 'proposed'
            CHECK (status IN ('proposed','confirmed','rejected','paused')),
        last_seen TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (account_id, payee_norm, period)
    );
    CREATE TABLE budgets (
        id INTEGER PRIMARY KEY,
        month TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved')),
        reasoning_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        approved_at TEXT,
        approved_by INTEGER REFERENCES users(id)
    );
    CREATE TABLE budget_lines (
        id INTEGER PRIMARY KEY,
        budget_id INTEGER NOT NULL REFERENCES budgets(id) ON DELETE CASCADE,
        category_id INTEGER NOT NULL REFERENCES categories(id),
        amount_cents INTEGER NOT NULL,
        UNIQUE (budget_id, category_id)
    );
    CREATE TABLE savings_goals (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        monthly_cents INTEGER NOT NULL,
        account_id INTEGER REFERENCES accounts(id),
        enabled INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE receipts (
        id INTEGER PRIMARY KEY,
        imap_uid TEXT,
        from_addr TEXT NOT NULL,
        subject TEXT NOT NULL DEFAULT '',
        received_at TEXT,
        status TEXT NOT NULL DEFAULT 'quarantined'
            CHECK (status IN ('quarantined','parsed','matched','rejected')),
        reject_reason TEXT,
        raw_email BLOB,
        parsed_json TEXT,
        matched_tx_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE chat_threads (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL DEFAULT 'New chat',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE chat_messages (
        id INTEGER PRIMARY KEY,
        thread_id INTEGER NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user','assistant')),
        content_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE alert_log (
        id INTEGER PRIMARY KEY,
        type TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        ok INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY,
        user_id INTEGER REFERENCES users(id),
        action TEXT NOT NULL,
        entity TEXT NOT NULL,
        entity_id INTEGER,
        detail_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL
    );
    """,
]


class Database:
    def __init__(self, path: Path | str, key_hex: str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlcipher3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlcipher3.Row
        # Hex keys must use the x'..' form so SQLCipher uses raw bytes, not a passphrase.
        self._conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        self._conn.execute("PRAGMA cipher_memory_security = ON")
        try:
            self._conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlcipher3.DatabaseError as e:
            self._conn.close()
            raise WrongKey("database key is incorrect") from e
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.create_function("REGEXP", 2, _regexp, deterministic=True)

    # -- migrations ----------------------------------------------------------

    def migrate(self) -> None:
        with self._lock:
            (current,) = self._conn.execute("PRAGMA user_version").fetchone()
            for version, script in enumerate(MIGRATIONS, start=1):
                if version > current:
                    with self._conn:
                        self._conn.executescript(script)
                        self._conn.execute(f"PRAGMA user_version = {version}")

    # -- query helpers -------------------------------------------------------

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
            return [dict(r) for r in rows]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Runs a write inside a transaction; returns lastrowid."""
        with self._lock, self._conn:
            cur = self._conn.execute(sql, tuple(params))
            return cur.lastrowid

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(sql, [tuple(p) for p in seq])

    def vacuum_into(self, dest_path: str) -> None:
        """Writes a compacted, still-encrypted copy of the DB to dest_path.
        VACUUM cannot run inside a transaction, so this bypasses the usual
        write wrapper."""
        with self._lock:
            self._conn.execute("VACUUM INTO ?", (dest_path,))

    def transaction(self):
        """Context manager: `with db.transaction() as conn:` for multi-statement writes."""
        return _Txn(self)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class _Txn:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        self.db._lock.acquire()
        self.db._conn.execute("BEGIN")
        return self.db._conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.db._conn.execute("COMMIT")
            else:
                self.db._conn.execute("ROLLBACK")
        finally:
            self.db._lock.release()
        return False


class WrongKey(Exception):
    pass
