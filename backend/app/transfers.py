"""Transfer detection: link the two sides of a between-accounts movement.

A linked pair is displayed as one event ("$X transferred from A to B") and is
excluded from spending, budgets, and reports. Confident matches auto-link;
ambiguous candidates go to a review queue.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

WINDOW_DAYS = 4
AUTO_LINK_SCORE = 0.8

TRANSFERISH = re.compile(
    r"TRANSFER|XFER|PAYMENT THANK YOU|ONLINE PMT|ONLINE PAYMENT|AUTOPAY|"
    r"AUTOMATIC PAYMENT|EPAY|E-PAYMENT|DIRECTPAY|CARDPAY", re.IGNORECASE)


def _score(tx_out: dict, tx_in: dict, competing: int) -> float:
    score = 0.4
    text_out = f"{tx_out['payee_raw']} {tx_out['memo']}"
    text_in = f"{tx_in['payee_raw']} {tx_in['memo']}"
    hits = int(bool(TRANSFERISH.search(text_out))) + int(bool(TRANSFERISH.search(text_in)))
    score += 0.3 * hits
    days = abs((date.fromisoformat(tx_out["posted_at"])
                - date.fromisoformat(tx_in["posted_at"])).days)
    score -= 0.05 * days
    amount = abs(tx_out["amount_cents"])
    if amount < 5000 or amount % 10000 == 0 and amount <= 20000:
        score -= 0.15  # small or small-round amounts collide by coincidence
    if competing > 1:
        score -= 0.3
    return max(0.0, min(1.0, score))


def find_and_link(db, tx_ids: list[int]) -> dict:
    """Examines newly imported transactions for transfer counterparts."""
    stats = {"linked": 0, "candidates": 0}
    for tx_id in tx_ids:
        tx = db.query_one(
            "SELECT * FROM transactions WHERE id = ? AND transfer_id IS NULL", (tx_id,))
        if tx is None:
            continue
        d = date.fromisoformat(tx["posted_at"])
        lo, hi = (d - timedelta(days=WINDOW_DAYS)).isoformat(), \
                 (d + timedelta(days=WINDOW_DAYS)).isoformat()
        counterparts = db.query(
            "SELECT * FROM transactions WHERE account_id != ? AND amount_cents = ? "
            "AND transfer_id IS NULL AND posted_at BETWEEN ? AND ? "
            "AND id NOT IN (SELECT tx_a FROM transfer_candidates WHERE status='pending') "
            "AND id NOT IN (SELECT tx_b FROM transfer_candidates WHERE status='pending')",
            (tx["account_id"], -tx["amount_cents"], lo, hi))
        if not counterparts:
            continue
        best, best_score = None, -1.0
        for c in counterparts:
            pair = (tx, c) if tx["amount_cents"] < 0 else (c, tx)
            s = _score(pair[0], pair[1], competing=len(counterparts))
            if s > best_score:
                best, best_score = c, s
        pair = (tx, best) if tx["amount_cents"] < 0 else (best, tx)
        if best_score >= AUTO_LINK_SCORE:
            link(db, pair[0]["id"], pair[1]["id"], status="auto")
            stats["linked"] += 1
        else:
            _add_candidate(db, pair[0]["id"], pair[1]["id"], best_score)
            stats["candidates"] += 1
    return stats


def _add_candidate(db, tx_a: int, tx_b: int, score: float) -> None:
    db.execute(
        "INSERT INTO transfer_candidates (tx_a, tx_b, score) VALUES (?, ?, ?) "
        "ON CONFLICT (tx_a, tx_b) DO NOTHING", (tx_a, tx_b, score))


def link(db, from_tx: int, to_tx: int, status: str = "confirmed") -> int:
    """from_tx = the negative side (money leaving), to_tx = the positive side."""
    a = db.query_one("SELECT * FROM transactions WHERE id = ?", (from_tx,))
    b = db.query_one("SELECT * FROM transactions WHERE id = ?", (to_tx,))
    if a is None or b is None:
        raise ValueError("transaction not found")
    if a["transfer_id"] or b["transfer_id"]:
        raise ValueError("transaction already part of a transfer")
    if a["amount_cents"] >= 0 or b["amount_cents"] <= 0:
        raise ValueError("transfer sides must be one debit and one credit")
    if a["amount_cents"] != -b["amount_cents"]:
        raise ValueError("transfer amounts must match")
    transfer_id = db.execute(
        "INSERT INTO transfers (from_tx, to_tx, status) VALUES (?, ?, ?)",
        (from_tx, to_tx, status))
    db.executemany(
        "UPDATE transactions SET transfer_id = ?, category_id = NULL, "
        "cat_source = 'none', updated_at = datetime('now') WHERE id = ?",
        [(transfer_id, from_tx), (transfer_id, to_tx)])
    # a linked pair is no longer a pending candidate anywhere
    db.execute(
        "UPDATE transfer_candidates SET status = 'accepted' "
        "WHERE status = 'pending' AND tx_a = ? AND tx_b = ?", (from_tx, to_tx))
    db.execute(
        "UPDATE transfer_candidates SET status = 'rejected' WHERE status = 'pending' "
        "AND (tx_a IN (?, ?) OR tx_b IN (?, ?))",
        (from_tx, to_tx, from_tx, to_tx))
    return transfer_id


def unlink(db, transfer_id: int) -> None:
    t = db.query_one("SELECT * FROM transfers WHERE id = ?", (transfer_id,))
    if t is None:
        raise ValueError("transfer not found")
    db.execute("UPDATE transactions SET transfer_id = NULL, "
               "updated_at = datetime('now') WHERE transfer_id = ?", (transfer_id,))
    db.execute("DELETE FROM transfers WHERE id = ?", (transfer_id,))


def list_transfers(db, limit: int = 100) -> list[dict]:
    return db.query(
        "SELECT tr.id, tr.status, tr.created_at, "
        "  o.id AS from_tx, o.posted_at, -o.amount_cents AS amount_cents, "
        "  o.payee_raw AS from_payee, ao.name AS from_account, "
        "  i.id AS to_tx, ai.name AS to_account "
        "FROM transfers tr "
        "JOIN transactions o ON o.id = tr.from_tx "
        "JOIN transactions i ON i.id = tr.to_tx "
        "JOIN accounts ao ON ao.id = o.account_id "
        "JOIN accounts ai ON ai.id = i.account_id "
        "ORDER BY o.posted_at DESC LIMIT ?", (limit,))
