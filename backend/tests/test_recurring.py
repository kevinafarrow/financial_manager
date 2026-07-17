"""Recurring detection + balance-threat alerting."""

from datetime import date, timedelta

import pytest

from app import recurring
from tests.conftest import CSRF, FakeAlerts
from tests.test_api_accounts import make_account


@pytest.fixture
def acct(db):
    return db.execute(
        "INSERT INTO accounts (name, type, low_balance_threshold_cents) "
        "VALUES ('Joint Checking', 'checking', 50000)")


def seed_monthly(db, acct, payee="VALON MORTGAGE", amount=-280000, months=4,
                 day=1, start_month=2):
    for i in range(months):
        db.execute(
            "INSERT INTO transactions (account_id, content_hash, posted_at, "
            "amount_cents, payee_raw, payee_norm, memo) VALUES (?, 'h', ?, ?, ?, ?, '')",
            (acct, f"2026-{start_month + i:02d}-{day:02d}", amount, payee, payee))


def test_detects_monthly_pattern(db, acct):
    seed_monthly(db, acct)
    stats = recurring.detect(db)
    assert stats["proposed"] == 1
    r = db.query_one("SELECT * FROM recurring")
    assert r["period"] == "monthly"
    assert r["amount_cents"] == 280000
    assert r["status"] == "proposed"
    assert r["next_due"] == "2026-06-01"


def test_detect_is_idempotent_and_updates_last_seen(db, acct):
    seed_monthly(db, acct)
    recurring.detect(db)
    assert recurring.detect(db) == {"proposed": 0, "updated": 0}
    # a new month arrives → same row updated, not duplicated
    seed_monthly(db, acct, months=1, start_month=6)
    stats = recurring.detect(db)
    assert stats == {"proposed": 0, "updated": 1}
    rows = db.query("SELECT * FROM recurring")
    assert len(rows) == 1 and rows[0]["next_due"] == "2026-07-01"


def test_irregular_amounts_not_detected(db, acct):
    for i, amt in enumerate([-5000, -18000, -2500, -9900]):
        db.execute(
            "INSERT INTO transactions (account_id, content_hash, posted_at, "
            "amount_cents, payee_raw, payee_norm, memo) VALUES (?, 'h', ?, ?, 'AMZN', 'AMZN', '')",
            (acct, f"2026-0{i + 2}-01", amt))
    assert recurring.detect(db)["proposed"] == 0


def test_irregular_intervals_not_detected(db, acct):
    for d in ["2026-01-01", "2026-01-04", "2026-03-20", "2026-04-02"]:
        db.execute(
            "INSERT INTO transactions (account_id, content_hash, posted_at, "
            "amount_cents, payee_raw, payee_norm, memo) VALUES (?, 'h', ?, -5000, 'X', 'X', '')",
            (acct, d))
    assert recurring.detect(db)["proposed"] == 0


def test_weekly_pattern(db, acct):
    for i in range(4):
        d = (date(2026, 6, 1) + timedelta(weeks=i)).isoformat()
        db.execute(
            "INSERT INTO transactions (account_id, content_hash, posted_at, "
            "amount_cents, payee_raw, payee_norm, memo) "
            "VALUES (?, 'h', ?, -2000, 'CLEANER', 'CLEANER', '')", (acct, d))
    recurring.detect(db)
    assert db.query_one("SELECT period FROM recurring")["period"] == "weekly"


# -- balance projection ------------------------------------------------------

def test_latest_balance_adjusts_for_newer_transactions(db, acct):
    db.execute("INSERT INTO balance_snapshots (account_id, as_of, balance_cents) "
               "VALUES (?, '2026-06-01', 500000)", (acct,))
    db.execute("INSERT INTO transactions (account_id, content_hash, posted_at, "
               "amount_cents, payee_raw, payee_norm, memo) "
               "VALUES (?, 'h', '2026-06-05', -120000, 'X', 'X', '')", (acct,))
    bal = recurring.latest_balance(db, acct)
    assert bal["balance_cents"] == 380000


def test_balance_threat_fires(db, acct):
    db.execute("INSERT INTO balance_snapshots (account_id, as_of, balance_cents) "
               "VALUES (?, '2026-06-28', 300000)", (acct,))
    db.execute("INSERT INTO recurring (payee_norm, display_name, account_id, "
               "amount_cents, period, next_due, status) "
               "VALUES ('VALON', 'Valon Mortgage', ?, 280000, 'monthly', "
               "'2026-07-01', 'confirmed')", (acct,))
    alerts = FakeAlerts()
    fired = recurring.check_balance_threats(db, alerts, today="2026-06-29")
    assert len(fired) == 1 and fired[0]["projected_cents"] == 20000
    assert alerts.sent[0]["type"] == "balance_threat"
    assert "Valon Mortgage" in alerts.sent[0]["message"]
    assert "$200.00" in alerts.sent[0]["message"]


def test_balance_threat_respects_horizon_and_status(db, acct):
    db.execute("INSERT INTO balance_snapshots (account_id, as_of, balance_cents) "
               "VALUES (?, '2026-06-28', 300000)", (acct,))
    # due beyond the 7-day lookahead
    db.execute("INSERT INTO recurring (payee_norm, account_id, amount_cents, period, "
               "next_due, status) VALUES ('A', ?, 280000, 'monthly', '2026-08-01', "
               "'confirmed')", (acct,))
    # big but only proposed, not confirmed
    db.execute("INSERT INTO recurring (payee_norm, account_id, amount_cents, period, "
               "next_due, status) VALUES ('B', ?, 280000, 'monthly', '2026-07-01', "
               "'proposed')", (acct,))
    alerts = FakeAlerts()
    assert recurring.check_balance_threats(db, alerts, today="2026-06-29") == []
    assert alerts.sent == []


def test_no_threat_when_balance_sufficient(db, acct):
    db.execute("INSERT INTO balance_snapshots (account_id, as_of, balance_cents) "
               "VALUES (?, '2026-06-28', 900000)", (acct,))
    db.execute("INSERT INTO recurring (payee_norm, account_id, amount_cents, period, "
               "next_due, status) VALUES ('A', ?, 280000, 'monthly', '2026-07-01', "
               "'confirmed')", (acct,))
    alerts = FakeAlerts()
    assert recurring.check_balance_threats(db, alerts, today="2026-06-29") == []


def test_stale_data_noted_in_alert(db, acct):
    db.execute("INSERT INTO balance_snapshots (account_id, as_of, balance_cents) "
               "VALUES (?, '2026-05-01', 300000)", (acct,))
    db.execute("INSERT INTO recurring (payee_norm, account_id, amount_cents, period, "
               "next_due, status) VALUES ('A', ?, 280000, 'monthly', '2026-07-01', "
               "'confirmed')", (acct,))
    alerts = FakeAlerts()
    recurring.check_balance_threats(db, alerts, today="2026-06-29")
    assert "days old" in alerts.sent[0]["message"]


# -- API ---------------------------------------------------------------------

def test_recurring_api_flow(authed, appstate):
    a = make_account(authed)
    for i in range(4):
        appstate.db.execute(
            "INSERT INTO transactions (account_id, content_hash, posted_at, "
            "amount_cents, payee_raw, payee_norm, memo) "
            "VALUES (?, 'h', ?, -1549, 'NETFLIX.COM', 'NETFLIX COM', '')",
            (a["id"], f"2026-0{i + 2}-15"))
    r = authed.post("/api/recurring/detect", headers=CSRF)
    assert r.json()["proposed"] == 1

    rec = authed.get("/api/recurring").json()[0]
    assert rec["status"] == "proposed" and rec["account_name"] == "Joint Checking"

    r = authed.patch(f"/api/recurring/{rec['id']}", headers=CSRF,
                     json={"status": "confirmed", "display_name": "Netflix"})
    assert r.json()["status"] == "confirmed"

    r = authed.post("/api/recurring", headers=CSRF, json={
        "display_name": "Car Insurance", "account_id": a["id"],
        "amount_cents": 95000, "period": "monthly", "next_due": "2026-08-01"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"

    r = authed.patch(f"/api/recurring/{rec['id']}", headers=CSRF,
                     json={"status": "bogus"})
    assert r.status_code == 400
