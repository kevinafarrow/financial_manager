import sqlite3

import pytest

from app.db import Database, WrongKey
from tests.conftest import TEST_KEY_HEX


def test_migrate_creates_schema(db):
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {
        "users", "sessions", "secrets", "accounts", "balance_snapshots", "categories",
        "imports", "transactions", "transaction_splits", "category_history", "rules",
        "transfers", "transfer_candidates", "recurring", "budgets", "budget_lines",
        "savings_goals", "receipts", "chat_threads", "chat_messages", "alert_log",
        "audit_log", "settings",
    }
    assert expected <= tables


def test_migrate_is_idempotent(db):
    db.migrate()
    db.migrate()
    assert db.query_one("PRAGMA user_version")["user_version"] == 1


def test_file_is_actually_encrypted(tmp_path):
    d = Database(tmp_path / "enc.db", TEST_KEY_HEX)
    d.migrate()
    d.execute("INSERT INTO settings (key, value_json) VALUES ('probe', '\"sentinel-value\"')")
    d.close()

    raw = (tmp_path / "enc.db").read_bytes()
    assert b"sentinel-value" not in raw
    assert not raw.startswith(b"SQLite format 3")  # plaintext sqlite header absent

    with pytest.raises(sqlite3.DatabaseError):
        conn = sqlite3.connect(tmp_path / "enc.db")
        conn.execute("SELECT * FROM settings").fetchall()


def test_wrong_key_rejected(tmp_path):
    d = Database(tmp_path / "k.db", TEST_KEY_HEX)
    d.migrate()
    d.close()
    with pytest.raises(WrongKey):
        Database(tmp_path / "k.db", "bb" * 32)


def test_write_and_query_roundtrip(db):
    rowid = db.execute(
        "INSERT INTO categories (name, kind) VALUES (?, ?)", ("Groceries", "expense")
    )
    row = db.query_one("SELECT * FROM categories WHERE id = ?", (rowid,))
    assert row["name"] == "Groceries"


def test_transaction_rolls_back_on_error(db):
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute("INSERT INTO categories (name) VALUES ('Doomed')")
            raise RuntimeError("boom")
    assert db.query_one("SELECT count(*) c FROM categories WHERE name='Doomed'")["c"] == 0


def test_foreign_keys_enforced(db):
    with pytest.raises(Exception):
        db.execute(
            "INSERT INTO balance_snapshots (account_id, as_of, balance_cents) VALUES (999, '2026-01-01', 100)"
        )
