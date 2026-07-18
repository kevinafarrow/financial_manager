"""Typed access to the settings key/value table."""

from __future__ import annotations

import json


def get(db, key: str, default=None):
    row = db.query_one("SELECT value_json FROM settings WHERE key = ?", (key,))
    return json.loads(row["value_json"]) if row else default


def set_(db, key: str, value) -> None:
    db.execute(
        "INSERT INTO settings (key, value_json) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
        (key, json.dumps(value)))
