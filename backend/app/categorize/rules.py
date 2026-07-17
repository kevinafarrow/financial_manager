"""Tier 2: user-defined regex rules."""

from __future__ import annotations

import regex


def validate_pattern(pattern: str) -> str | None:
    """Returns an error message, or None if the pattern compiles."""
    try:
        regex.compile(pattern, regex.IGNORECASE)
        return None
    except regex.error as e:
        return str(e)


def match(db, payee_raw: str, memo: str) -> tuple[int, int] | None:
    """Returns (category_id, rule_id) for the first matching enabled rule."""
    rows = db.query(
        "SELECT r.id, r.field, r.pattern, r.category_id FROM rules r "
        "JOIN categories c ON c.id = r.category_id AND c.archived = 0 "
        "WHERE r.enabled = 1 ORDER BY r.priority, r.id")
    for r in rows:
        subject = payee_raw if r["field"] == "payee" else memo
        try:
            if regex.search(r["pattern"], subject, regex.IGNORECASE):
                return r["category_id"], r["id"]
        except regex.error:
            continue  # a rule that stopped compiling must not break imports
    return None
