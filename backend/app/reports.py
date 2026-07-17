"""Progress reports and their Pushover delivery."""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime

from . import budgets

THRESHOLD = 0.9  # category alert when spend crosses 90% of its cap


def _today() -> date:
    return datetime.now().date()


def weekly_pulse(db, today: date | None = None) -> dict | None:
    """One-paragraph mid-month status. None if there is no budget this month."""
    today = today or _today()
    month = today.strftime("%Y-%m")
    p = budgets.progress(db, month)
    if p is None or not p["lines"]:
        return None
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    pct_month = today.day / days_in_month
    total_budget = p["total_budget_cents"]
    budgeted_spent = sum(ln["spent_cents"] for ln in p["lines"])
    pct_budget = budgeted_spent / total_budget if total_budget else 0
    hot = sorted(
        (ln for ln in p["lines"]
         if ln["pct"] is not None and ln["pct"] > pct_month + 0.10),
        key=lambda ln: ln["pct"], reverse=True)[:3]
    return {
        "month": month,
        "pct_month": round(pct_month, 4),
        "pct_budget": round(pct_budget, 4),
        "total_budget_cents": total_budget,
        "spent_cents": budgeted_spent,
        "hot_categories": [{"name": ln["category_name"], "pct": ln["pct"],
                            "spent_cents": ln["spent_cents"],
                            "budget_cents": ln["budget_cents"]} for ln in hot],
    }


def pulse_message(pulse: dict) -> str:
    msg = (f"{pulse['pct_month']:.0%} through the month, "
           f"{pulse['pct_budget']:.0%} of budget spent "
           f"(${pulse['spent_cents'] / 100:,.0f} of "
           f"${pulse['total_budget_cents'] / 100:,.0f}).")
    if pulse["hot_categories"]:
        hot = "; ".join(f"{h['name']} at {h['pct']:.0%}"
                        for h in pulse["hot_categories"])
        msg += f" Trending hot: {hot}."
    else:
        msg += " All categories on pace."
    return msg


def send_weekly_pulse(db, alerts, base_url: str, today: date | None = None) -> bool:
    pulse = weekly_pulse(db, today)
    if pulse is None:
        return False
    return alerts.send("weekly_pulse", f"Budget pulse — {pulse['month']}",
                       pulse_message(pulse),
                       url=f"{base_url}/reports/{pulse['month']}")


def monthly_report(db, month: str) -> dict:
    """Full month report: budget outcome, deltas vs prior month, savings result."""
    p = budgets.progress(db, month)
    prev_spend = budgets.spending_by_category(db, budgets.month_add(month, -1))
    this_spend = budgets.spending_by_category(db, month)
    names = {c["id"]: c["name"] for c in db.query("SELECT id, name FROM categories")}
    categories = []
    for cid in sorted(set(prev_spend) | set(this_spend), key=lambda c: -this_spend.get(c, 0)):
        categories.append({
            "category_id": cid, "category_name": names.get(cid, "?"),
            "spent_cents": this_spend.get(cid, 0),
            "prev_spent_cents": prev_spend.get(cid, 0),
            "delta_cents": this_spend.get(cid, 0) - prev_spend.get(cid, 0),
        })
    income = budgets.income_for_month(db, month)
    total_spent = sum(this_spend.values())
    goals = db.query("SELECT * FROM savings_goals WHERE enabled = 1")
    return {
        "month": month,
        "budget": p,
        "categories": categories,
        "income_cents": income,
        "total_spent_cents": total_spent,
        "net_cents": income - total_spent,
        "savings_goal_cents": sum(g["monthly_cents"] for g in goals),
    }


def send_monthly_report(db, alerts, base_url: str, month: str) -> bool:
    r = monthly_report(db, month)
    over = [c for c in (r["budget"] or {}).get("lines", [])
            if c["remaining_cents"] < 0]
    msg = (f"Spent ${r['total_spent_cents'] / 100:,.0f} against "
           f"${r['income_cents'] / 100:,.0f} income "
           f"(net ${r['net_cents'] / 100:,.0f}).")
    if r["savings_goal_cents"]:
        met = "met" if r["net_cents"] >= r["savings_goal_cents"] else "missed"
        msg += (f" Savings goal ${r['savings_goal_cents'] / 100:,.0f}: {met}.")
    if over:
        msg += " Over budget: " + ", ".join(c["category_name"] for c in over) + "."
    return alerts.send("monthly_report", f"Monthly report — {month}", msg,
                       url=f"{base_url}/reports/{month}")


def check_category_thresholds(db, alerts, base_url: str,
                              today: date | None = None) -> list[str]:
    """Ping when a category crosses 90% of its cap — once per category per month."""
    today = today or _today()
    month = today.strftime("%Y-%m")
    p = budgets.progress(db, month)
    if p is None:
        return []
    already = {json.loads(r["payload_json"]).get("dedupe")
               for r in db.query(
                   "SELECT payload_json FROM alert_log WHERE type = 'budget_threshold'")}
    fired = []
    for ln in p["lines"]:
        if ln["pct"] is None or ln["pct"] < THRESHOLD:
            continue
        dedupe = f"{month}:{ln['category_id']}"
        if dedupe in already:
            continue
        state_word = "over" if ln["pct"] >= 1 else f"at {ln['pct']:.0%} of"
        ok = alerts.send(
            "budget_threshold",
            f"{ln['category_name']} {'over budget' if ln['pct'] >= 1 else 'near cap'}",
            f"{ln['category_name']} is {state_word} its "
            f"${ln['budget_cents'] / 100:,.0f} budget "
            f"(${ln['spent_cents'] / 100:,.2f} spent).",
            url=f"{base_url}/reports/{month}")
        # stamp the dedupe key onto the alert we just logged
        row = db.query_one("SELECT id, payload_json FROM alert_log "
                           "ORDER BY id DESC LIMIT 1")
        payload = json.loads(row["payload_json"])
        payload["dedupe"] = dedupe
        db.execute("UPDATE alert_log SET payload_json = ? WHERE id = ?",
                   (json.dumps(payload), row["id"]))
        if ok:
            fired.append(ln["category_name"])
    return fired


def check_staleness(db, alerts, today: date | None = None) -> list[str]:
    """Daily nag listing accounts whose data is older than their staleness_days."""
    today = today or _today()
    rows = db.query(
        "SELECT a.id, a.name, a.staleness_days, "
        "  max(coalesce((SELECT max(t.posted_at) FROM transactions t "
        "                WHERE t.account_id = a.id), ''), "
        "      coalesce((SELECT max(b.as_of) FROM balance_snapshots b "
        "                WHERE b.account_id = a.id), '')) AS freshest "
        "FROM accounts a WHERE a.archived = 0")
    stale = []
    for r in rows:
        if not r["freshest"]:
            continue  # brand-new account, nothing to nag about yet
        age = (today - date.fromisoformat(r["freshest"][:10])).days
        if age > r["staleness_days"]:
            stale.append(f"{r['name']} ({age}d)")
    if stale:
        alerts.send("staleness", "Bank data getting stale",
                    "Time for an import: " + ", ".join(stale))
    return stale
