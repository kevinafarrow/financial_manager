"""Lightweight who-changed-what log."""

from __future__ import annotations

import json


def record(db, user_id: int | None, action: str, entity: str,
           entity_id: int | None = None, detail: dict | None = None) -> None:
    db.execute(
        "INSERT INTO audit_log (user_id, action, entity, entity_id, detail_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, action, entity, entity_id, json.dumps(detail or {})),
    )
