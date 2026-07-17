"""Queue + rules API tests, including the import→queue→assign→reimport loop."""

from tests.conftest import CSRF
from tests.test_api_accounts import make_account
from tests.test_api_imports import upload


def get_category_id(authed, name):
    r = authed.get("/api/categories")
    return next(c["id"] for c in r.json() if c["name"] == name)


def test_import_lands_in_queue_then_user_assignment_teaches_pipeline(authed, appstate):
    a = make_account(authed)
    upload(authed, a["id"], "wellsfargo.ofx")

    r = authed.get("/api/queue")
    queue = r.json()
    assert len(queue) == 3  # no history/rules yet, no API key → all queued

    groceries = get_category_id(authed, "Groceries")
    wholefds = next(t for t in queue if "WHOLEFDS" in t["payee_raw"])
    r = authed.post(f"/api/queue/{wholefds['id']}", headers=CSRF,
                    json={"category_id": groceries})
    assert r.status_code == 200
    assert r.json()["cat_source"] == "user"

    # same merchant in a fresh import is now auto-categorized via history
    csv = b'"07/10/2026","-42.00","*","","WHOLEFDS #105 SEATTLE WA"\n'
    upload(authed, a["id"], "july.csv", content=csv)
    row = appstate.db.query_one(
        "SELECT * FROM transactions WHERE posted_at = '2026-07-10'")
    assert row["cat_source"] == "history"
    assert row["category_id"] == groceries


def test_rule_applies_on_import(authed, appstate):
    gas = get_category_id(authed, "Gas")
    r = authed.post("/api/rules", headers=CSRF,
                    json={"pattern": r"SHELL\s+OIL", "category_id": gas})
    assert r.status_code == 200

    a = make_account(authed)
    upload(authed, a["id"], "wellsfargo.ofx")
    row = appstate.db.query_one(
        "SELECT * FROM transactions WHERE payee_raw LIKE 'SHELL%'")
    assert row["cat_source"] == "rule" and row["category_id"] == gas


def test_invalid_regex_rejected(authed):
    gas = get_category_id(authed, "Gas")
    r = authed.post("/api/rules", headers=CSRF,
                    json={"pattern": "(broken", "category_id": gas})
    assert r.status_code == 400
    assert "invalid regex" in r.json()["detail"]


def test_rule_crud(authed):
    gas = get_category_id(authed, "Gas")
    r = authed.post("/api/rules", headers=CSRF,
                    json={"pattern": "CHEVRON", "category_id": gas, "priority": 5})
    rule_id = r.json()["id"]

    r = authed.patch(f"/api/rules/{rule_id}", headers=CSRF, json={"enabled": False})
    assert r.json()["enabled"] == 0

    r = authed.get("/api/rules")
    assert r.json()[0]["category_name"] == "Gas"

    r = authed.delete(f"/api/rules/{rule_id}", headers=CSRF)
    assert r.status_code == 200
    assert authed.get("/api/rules").json() == []


def test_assign_unknown_category_rejected(authed, appstate):
    a = make_account(authed)
    upload(authed, a["id"], "wellsfargo.ofx")
    tx = authed.get("/api/queue").json()[0]
    r = authed.post(f"/api/queue/{tx['id']}", headers=CSRF, json={"category_id": 9999})
    assert r.status_code == 400


def test_assign_unknown_tx_404(authed):
    groceries = get_category_id(authed, "Groceries")
    r = authed.post("/api/queue/99999", headers=CSRF, json={"category_id": groceries})
    assert r.status_code == 404
