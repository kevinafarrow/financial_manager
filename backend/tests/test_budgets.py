"""Budget drafting, approval, and progress math."""

import pytest

from app import budgets
from tests.conftest import CSRF
from tests.test_api_accounts import make_account


def spend(db, acct, month, amount_cents, cat_id, day=10):
    return db.execute(
        "INSERT INTO transactions (account_id, content_hash, posted_at, amount_cents, "
        "payee_raw, payee_norm, memo, category_id, cat_source) "
        "VALUES (?, 'h', ?, ?, 'X', 'X', '', ?, 'user')",
        (acct, f"{month}-{day:02d}", -amount_cents, cat_id))


@pytest.fixture
def world(db):
    acct = db.execute("INSERT INTO accounts (name, type) VALUES ('Chk', 'checking')")
    groceries = db.execute("INSERT INTO categories (name, kind) VALUES ('Groceries', 'expense')")
    gas = db.execute("INSERT INTO categories (name, kind) VALUES ('Gas', 'expense')")
    income = db.execute("INSERT INTO categories (name, kind) VALUES ('Income', 'income')")
    return {"acct": acct, "groceries": groceries, "gas": gas, "income": income}


def test_month_math():
    assert budgets.month_add("2026-07", -1) == "2026-06"
    assert budgets.month_add("2026-01", -1) == "2025-12"
    assert budgets.month_add("2025-12", 1) == "2026-01"


def test_spending_by_category_respects_splits_and_transfers(db, world):
    w = world
    spend(db, w["acct"], "2026-06", 10000, w["groceries"])
    # a split transaction: $80 groceries + $20 gas
    tx = db.execute(
        "INSERT INTO transactions (account_id, content_hash, posted_at, amount_cents, "
        "payee_raw, payee_norm, memo) VALUES (?, 'h', '2026-06-15', -10000, 'T', 'T', '')",
        (w["acct"],))
    db.execute("INSERT INTO transaction_splits (transaction_id, category_id, amount_cents) "
               "VALUES (?, ?, -8000)", (tx, w["groceries"]))
    db.execute("INSERT INTO transaction_splits (transaction_id, category_id, amount_cents) "
               "VALUES (?, ?, -2000)", (tx, w["gas"]))
    s = budgets.spending_by_category(db, "2026-06")
    assert s[w["groceries"]] == 18000
    assert s[w["gas"]] == 2000


def test_draft_weighted_average_and_rounding(db, world):
    w = world
    # groceries: may 40000, jun 50000, jul(current-1=jun)... draft for 2026-08
    spend(db, w["acct"], "2026-05", 40000, w["groceries"])
    spend(db, w["acct"], "2026-06", 50000, w["groceries"])
    spend(db, w["acct"], "2026-07", 60000, w["groceries"])
    budgets.draft_budget(db, "2026-08")
    p = budgets.progress(db, "2026-08")
    line = p["lines"][0]
    # weighted avg = (3*60000 + 2*50000 + 1*40000)/6 = 53333 → rounds to 53500
    assert line["budget_cents"] == 53500
    r = p["reasoning"][str(w["groceries"])]
    assert r["weighted_avg_cents"] == 53333
    assert r["months"]["2026-07"] == 60000


def test_draft_skips_categories_with_no_history(db, world):
    spend(db, world["acct"], "2026-07", 5000, world["gas"])
    budgets.draft_budget(db, "2026-08")
    p = budgets.progress(db, "2026-08")
    assert [ln["category_name"] for ln in p["lines"]] == ["Gas"]


def test_draft_includes_savings_goals_in_reasoning(db, world):
    db.execute("INSERT INTO savings_goals (name, monthly_cents) VALUES ('Save', 150000)")
    spend(db, world["acct"], "2026-07", 5000, world["gas"])
    budgets.draft_budget(db, "2026-08")
    p = budgets.progress(db, "2026-08")
    assert p["reasoning"]["_savings_goals"][0]["monthly_cents"] == 150000


def test_redraft_replaces_but_approved_locks(db, world):
    spend(db, world["acct"], "2026-07", 5000, world["gas"])
    bid = budgets.draft_budget(db, "2026-08")
    assert budgets.draft_budget(db, "2026-08") == bid  # redraft, same row
    budgets.approve(db, bid, user_id=None)
    with pytest.raises(ValueError):
        budgets.draft_budget(db, "2026-08")
    with pytest.raises(ValueError):
        budgets.approve(db, bid, user_id=None)


def test_progress_math(db, world):
    w = world
    spend(db, w["acct"], "2026-07", 40000, w["groceries"])
    bid = budgets.draft_budget(db, "2026-08")
    spend(db, w["acct"], "2026-08", 30000, w["groceries"])
    spend(db, w["acct"], "2026-08", 7000, w["gas"])  # unbudgeted
    db.execute("INSERT INTO transactions (account_id, content_hash, posted_at, "
               "amount_cents, payee_raw, payee_norm, memo, category_id) "
               "VALUES (?, 'h', '2026-08-05', 250000, 'PAYROLL', 'PAYROLL', '', ?)",
               (w["acct"], w["income"]))
    p = budgets.progress(db, "2026-08")
    line = p["lines"][0]
    assert line["spent_cents"] == 30000
    assert line["remaining_cents"] == line["budget_cents"] - 30000
    assert p["unbudgeted"][0]["category_name"] == "Gas"
    assert p["unbudgeted"][0]["spent_cents"] == 7000
    assert p["income_cents"] == 250000
    assert p["total_spent_cents"] == 37000


def test_progress_none_without_budget(db):
    assert budgets.progress(db, "2026-01") is None


# -- API ---------------------------------------------------------------------

def test_budget_api_flow(authed, appstate):
    a = make_account(authed)
    groceries = next(c["id"] for c in authed.get("/api/categories").json()
                     if c["name"] == "Groceries")
    appstate.db.execute(
        "INSERT INTO transactions (account_id, content_hash, posted_at, amount_cents, "
        "payee_raw, payee_norm, memo, category_id, cat_source) "
        "VALUES (?, 'h', '2026-06-10', -45000, 'W', 'W', '', ?, 'user')",
        (a["id"], groceries))

    assert authed.get("/api/budgets/2026-07").status_code == 404
    assert authed.post("/api/budgets/July/draft", headers=CSRF).status_code == 400

    r = authed.post("/api/budgets/2026-07/draft", headers=CSRF)
    assert r.status_code == 200
    p = r.json()
    assert p["status"] == "draft" and len(p["lines"]) == 1
    bid = p["budget_id"]

    # tweak the line then approve
    r = authed.put(f"/api/budgets/{bid}/lines", headers=CSRF, json={
        "lines": [{"category_id": groceries, "amount_cents": 40000}]})
    assert r.json()["lines"][0]["budget_cents"] == 40000

    r = authed.post(f"/api/budgets/{bid}/approve", headers=CSRF)
    assert r.json()["status"] == "approved"

    # locked after approval
    assert authed.put(f"/api/budgets/{bid}/lines", headers=CSRF, json={
        "lines": [{"category_id": groceries, "amount_cents": 1}]}).status_code == 409
    assert authed.post("/api/budgets/2026-07/draft", headers=CSRF).status_code == 409


def test_savings_goals_api(authed):
    r = authed.post("/api/savings-goals", headers=CSRF,
                    json={"name": "Emergency fund", "monthly_cents": 150000})
    gid = r.json()["id"]
    r = authed.patch(f"/api/savings-goals/{gid}", headers=CSRF,
                     json={"monthly_cents": 100000, "enabled": False})
    assert r.json()["monthly_cents"] == 100000 and r.json()["enabled"] == 0
    assert len(authed.get("/api/savings-goals").json()) == 1
    r = authed.post("/api/savings-goals", headers=CSRF,
                    json={"name": "Bad", "monthly_cents": -5})
    assert r.status_code == 400
