"""Budgets: drafted from a 3-month weighted average, approved by the user,
measured month-to-date. All spend figures are positive cents."""

from __future__ import annotations

import json

WEIGHTS = [3, 2, 1]  # most recent full month first
ROUND_TO_CENTS = 500  # proposals rounded to $5


def month_add(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    total = y * 12 + (m - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def month_range(month: str) -> tuple[str, str]:
    return f"{month}-01", f"{month}-31"


def spending_by_category(db, month: str) -> dict[int, int]:
    """Positive cents spent per expense category, split-aware, transfer-free."""
    lo, hi = month_range(month)
    out: dict[int, int] = {}
    rows = db.query(
        "SELECT t.category_id AS cid, sum(-t.amount_cents) AS spent "
        "FROM transactions t JOIN categories c ON c.id = t.category_id "
        "WHERE c.kind = 'expense' AND t.transfer_id IS NULL "
        "AND t.posted_at BETWEEN ? AND ? "
        "AND NOT EXISTS (SELECT 1 FROM transaction_splits s WHERE s.transaction_id = t.id) "
        "GROUP BY t.category_id", (lo, hi))
    for r in rows:
        out[r["cid"]] = out.get(r["cid"], 0) + r["spent"]
    rows = db.query(
        "SELECT s.category_id AS cid, sum(-s.amount_cents) AS spent "
        "FROM transaction_splits s "
        "JOIN transactions t ON t.id = s.transaction_id "
        "JOIN categories c ON c.id = s.category_id "
        "WHERE c.kind = 'expense' AND t.transfer_id IS NULL "
        "AND t.posted_at BETWEEN ? AND ? GROUP BY s.category_id", (lo, hi))
    for r in rows:
        out[r["cid"]] = out.get(r["cid"], 0) + r["spent"]
    return {k: v for k, v in out.items() if v > 0}


def income_for_month(db, month: str) -> int:
    lo, hi = month_range(month)
    row = db.query_one(
        "SELECT coalesce(sum(t.amount_cents), 0) s FROM transactions t "
        "JOIN categories c ON c.id = t.category_id "
        "WHERE c.kind = 'income' AND t.transfer_id IS NULL "
        "AND t.posted_at BETWEEN ? AND ?", (lo, hi))
    return row["s"]


def draft_budget(db, month: str) -> int:
    """Creates/regenerates the draft for `month`. Returns budget_id."""
    existing = db.query_one("SELECT * FROM budgets WHERE month = ?", (month,))
    if existing and existing["status"] == "approved":
        raise ValueError(f"budget for {month} is already approved")

    history_months = [month_add(month, -i) for i in range(1, len(WEIGHTS) + 1)]
    per_month = {m: spending_by_category(db, m) for m in history_months}
    categories = db.query(
        "SELECT id, name FROM categories WHERE kind = 'expense' AND archived = 0")

    lines, reasoning = [], {}
    for cat in categories:
        weighted, weight_total, observed = 0, 0, {}
        for w, m in zip(WEIGHTS, history_months):
            spent = per_month[m].get(cat["id"], 0)
            observed[m] = spent
            weighted += w * spent
            weight_total += w
        if not any(observed.values()):
            continue
        avg = weighted // weight_total
        proposal = max(ROUND_TO_CENTS,
                       round(avg / ROUND_TO_CENTS) * ROUND_TO_CENTS)
        lines.append((cat["id"], proposal))
        reasoning[str(cat["id"])] = {
            "name": cat["name"], "weighted_avg_cents": avg,
            "months": observed, "proposal_cents": proposal}

    goals = db.query("SELECT * FROM savings_goals WHERE enabled = 1")
    reasoning["_savings_goals"] = [
        {"name": g["name"], "monthly_cents": g["monthly_cents"]} for g in goals]
    reasoning["_total_proposed_cents"] = sum(a for _, a in lines)
    reasoning["_savings_total_cents"] = sum(g["monthly_cents"] for g in goals)

    if existing:
        budget_id = existing["id"]
        db.execute("DELETE FROM budget_lines WHERE budget_id = ?", (budget_id,))
        db.execute("UPDATE budgets SET reasoning_json = ?, created_at = datetime('now') "
                   "WHERE id = ?", (json.dumps(reasoning), budget_id))
    else:
        budget_id = db.execute(
            "INSERT INTO budgets (month, status, reasoning_json) VALUES (?, 'draft', ?)",
            (month, json.dumps(reasoning)))
    db.executemany(
        "INSERT INTO budget_lines (budget_id, category_id, amount_cents) VALUES (?, ?, ?)",
        [(budget_id, cid, amount) for cid, amount in lines])
    return budget_id


def approve(db, budget_id: int, user_id: int) -> None:
    b = db.query_one("SELECT * FROM budgets WHERE id = ?", (budget_id,))
    if b is None:
        raise ValueError("budget not found")
    if b["status"] == "approved":
        raise ValueError("already approved")
    db.execute("UPDATE budgets SET status = 'approved', approved_at = datetime('now'), "
               "approved_by = ? WHERE id = ?", (user_id, budget_id))


def progress(db, month: str) -> dict | None:
    """Budget lines vs month-to-date spending. None if no budget exists."""
    b = db.query_one("SELECT * FROM budgets WHERE month = ?", (month,))
    if b is None:
        return None
    spent = spending_by_category(db, month)
    lines = db.query(
        "SELECT bl.*, c.name AS category_name FROM budget_lines bl "
        "JOIN categories c ON c.id = bl.category_id "
        "WHERE bl.budget_id = ? ORDER BY c.name", (b["id"],))
    out_lines = []
    for line in lines:
        s = spent.get(line["category_id"], 0)
        out_lines.append({
            "category_id": line["category_id"],
            "category_name": line["category_name"],
            "budget_cents": line["amount_cents"],
            "spent_cents": s,
            "remaining_cents": line["amount_cents"] - s,
            "pct": round(s / line["amount_cents"], 4) if line["amount_cents"] else None,
        })
    unbudgeted = {cid: s for cid, s in spent.items()
                  if cid not in {ln["category_id"] for ln in lines}}
    unbudgeted_rows = []
    if unbudgeted:
        names = {c["id"]: c["name"] for c in db.query("SELECT id, name FROM categories")}
        unbudgeted_rows = [{"category_id": cid, "category_name": names.get(cid, "?"),
                            "spent_cents": s} for cid, s in sorted(unbudgeted.items())]
    return {
        "budget_id": b["id"], "month": month, "status": b["status"],
        "reasoning": json.loads(b["reasoning_json"]),
        "lines": out_lines,
        "unbudgeted": unbudgeted_rows,
        "total_budget_cents": sum(ln["budget_cents"] for ln in out_lines),
        "total_spent_cents": sum(spent.values()),
        "income_cents": income_for_month(db, month),
    }
