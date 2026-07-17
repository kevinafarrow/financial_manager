"""Tier 1: exact normalized-payee match against categorization history.

User decisions always outrank receipt-derived and Claude-derived entries;
within a source tier the most recent entry wins.
"""

from __future__ import annotations

SOURCE_RANK = {"user": 0, "receipt": 1, "claude": 2}


def record(db, payee_norm: str, category_id: int, source: str,
           user_id: int | None = None) -> None:
    if source not in SOURCE_RANK:
        raise ValueError(f"invalid history source: {source}")
    db.execute(
        "INSERT INTO category_history (payee_norm, category_id, source, user_id) "
        "VALUES (?, ?, ?, ?)",
        (payee_norm, category_id, source, user_id),
    )


def match(db, payee_norm: str) -> int | None:
    row = db.query_one(
        "SELECT ch.category_id FROM category_history ch "
        "JOIN categories c ON c.id = ch.category_id AND c.archived = 0 "
        "WHERE ch.payee_norm = ? "
        "ORDER BY CASE ch.source WHEN 'user' THEN 0 WHEN 'receipt' THEN 1 ELSE 2 END, "
        "ch.created_at DESC, ch.id DESC LIMIT 1",
        (payee_norm,),
    )
    return row["category_id"] if row else None
