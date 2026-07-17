"""Recurring-payment detection and balance-threat alerting.

Detected patterns are *proposed*; the user confirms/edits/rejects them in the
UI. Only confirmed schedules drive low-balance alerts.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

MIN_OCCURRENCES = 3
AMOUNT_TOLERANCE = 0.10  # ±10% of median
PERIODS = [("weekly", 7, 1.5), ("biweekly", 14, 3), ("monthly", 30.5, 6),
           ("yearly", 365, 45)]
LOOKAHEAD_DAYS = 7


def _period_for(intervals: list[int]) -> str | None:
    """A period matches when the median fits AND the individual intervals are
    consistent (one outlier tolerated on longer histories, e.g. a skipped month)."""
    median_interval = statistics.median(intervals)
    for name, days, slack in PERIODS:
        if abs(median_interval - days) <= slack:
            violations = sum(1 for i in intervals if abs(i - days) > slack)
            allowed = 1 if len(intervals) >= 4 else 0
            if violations <= allowed:
                return name
            return None
    return None


def _next_due(last_seen: str, period: str) -> str:
    d = date.fromisoformat(last_seen)
    if period == "weekly":
        return (d + timedelta(days=7)).isoformat()
    if period == "biweekly":
        return (d + timedelta(days=14)).isoformat()
    if period == "yearly":
        return date(d.year + 1, d.month, d.day if d.day <= 28 else 28).isoformat()
    # monthly
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(d.day, 28)).isoformat()


def detect(db) -> dict:
    """Scans history for recurring patterns; inserts/updates `recurring` rows."""
    stats = {"proposed": 0, "updated": 0}
    groups = db.query(
        "SELECT account_id, payee_norm, count(*) n FROM transactions "
        "WHERE transfer_id IS NULL AND amount_cents < 0 "
        "GROUP BY account_id, payee_norm HAVING n >= ?", (MIN_OCCURRENCES,))
    for g in groups:
        rows = db.query(
            "SELECT posted_at, amount_cents FROM transactions "
            "WHERE account_id = ? AND payee_norm = ? AND transfer_id IS NULL "
            "AND amount_cents < 0 ORDER BY posted_at",
            (g["account_id"], g["payee_norm"]))
        dates = [date.fromisoformat(r["posted_at"]) for r in rows]
        amounts = [abs(r["amount_cents"]) for r in rows]
        intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        intervals = [i for i in intervals if i > 0]
        if len(intervals) < MIN_OCCURRENCES - 1:
            continue
        period = _period_for(intervals)
        if period is None:
            continue
        median_amount = int(statistics.median(amounts))
        if any(abs(a - median_amount) > median_amount * AMOUNT_TOLERANCE
               for a in amounts):
            continue
        tolerance = int(median_amount * AMOUNT_TOLERANCE)
        last_seen = rows[-1]["posted_at"]
        existing = db.query_one(
            "SELECT * FROM recurring WHERE account_id = ? AND payee_norm = ? "
            "AND period = ?", (g["account_id"], g["payee_norm"], period))
        if existing is None:
            db.execute(
                "INSERT INTO recurring (payee_norm, display_name, account_id, "
                "amount_cents, tolerance_cents, period, day_of_month, next_due, "
                "status, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?)",
                (g["payee_norm"], g["payee_norm"].title(), g["account_id"],
                 median_amount, tolerance, period,
                 dates[-1].day if period == "monthly" else None,
                 _next_due(last_seen, period), last_seen))
            stats["proposed"] += 1
        elif existing["status"] != "rejected" and existing["last_seen"] != last_seen:
            db.execute(
                "UPDATE recurring SET amount_cents = ?, tolerance_cents = ?, "
                "last_seen = ?, next_due = ? WHERE id = ?",
                (median_amount, tolerance, last_seen,
                 _next_due(last_seen, period), existing["id"]))
            stats["updated"] += 1
    return stats


# -- balance-threat alerting -------------------------------------------------

def latest_balance(db, account_id: int) -> dict | None:
    """Best known balance: newest snapshot adjusted by transactions after it."""
    snap = db.query_one(
        "SELECT as_of, balance_cents FROM balance_snapshots "
        "WHERE account_id = ? ORDER BY as_of DESC, id DESC LIMIT 1", (account_id,))
    if snap is None:
        return None
    delta = db.query_one(
        "SELECT coalesce(sum(amount_cents), 0) s FROM transactions "
        "WHERE account_id = ? AND posted_at > ?", (account_id, snap["as_of"]))["s"]
    return {"as_of": snap["as_of"], "balance_cents": snap["balance_cents"] + delta}


def check_balance_threats(db, alerts, today: str | None = None) -> list[dict]:
    """For each account with a threshold: project balance after upcoming
    confirmed payments; Pushover when it would dip below the threshold."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    horizon = (date.fromisoformat(today) + timedelta(days=LOOKAHEAD_DAYS)).isoformat()
    fired: list[dict] = []
    accounts = db.query(
        "SELECT * FROM accounts WHERE archived = 0 "
        "AND low_balance_threshold_cents IS NOT NULL")
    for acct in accounts:
        bal = latest_balance(db, acct["id"])
        if bal is None:
            continue
        upcoming = db.query(
            "SELECT * FROM recurring WHERE account_id = ? AND status = 'confirmed' "
            "AND next_due IS NOT NULL AND next_due BETWEEN ? AND ? "
            "ORDER BY next_due", (acct["id"], today, horizon))
        if not upcoming:
            continue
        projected = bal["balance_cents"] - sum(r["amount_cents"] for r in upcoming)
        if projected < acct["low_balance_threshold_cents"]:
            payments = ", ".join(
                f"{r['display_name'] or r['payee_norm']} "
                f"(${r['amount_cents'] / 100:,.2f} due {r['next_due']})"
                for r in upcoming)
            stale_note = ""
            age = (date.fromisoformat(today) - date.fromisoformat(bal["as_of"])).days
            if age > acct["staleness_days"]:
                stale_note = f" (balance data is {age} days old — import fresh data)"
            alerts.send(
                "balance_threat",
                f"Low balance warning: {acct['name']}",
                f"Upcoming payments ({payments}) would drop {acct['name']} to "
                f"${projected / 100:,.2f}, below your "
                f"${acct['low_balance_threshold_cents'] / 100:,.2f} threshold."
                + stale_note,
                priority=1,
            )
            fired.append({"account_id": acct["id"], "projected_cents": projected})
    return fired
