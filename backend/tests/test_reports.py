"""Reports, threshold pings, staleness nag, scheduler wiring."""

from datetime import date

import pytest

from app import budgets, reports
from tests.conftest import FakeAlerts
from tests.test_budgets import spend, world  # noqa: F401 (fixture reuse)


@pytest.fixture
def budgeted(db, world):  # noqa: F811
    w = world
    spend(db, w["acct"], "2026-06", 40000, w["groceries"])
    spend(db, w["acct"], "2026-06", 10000, w["gas"])
    bid = budgets.draft_budget(db, "2026-07")
    budgets.approve(db, bid, None)
    return w


def test_weekly_pulse_math_and_hot_categories(db, budgeted):
    w = budgeted
    # July: groceries budget ≈ 40000, gas ≈ 10000. Overspend groceries early.
    spend(db, w["acct"], "2026-07", 35000, w["groceries"], day=8)
    pulse = reports.weekly_pulse(db, today=date(2026, 7, 10))
    assert pulse["pct_month"] == round(10 / 31, 4)
    assert pulse["hot_categories"][0]["name"] == "Groceries"
    msg = reports.pulse_message(pulse)
    assert "Trending hot: Groceries" in msg


def test_weekly_pulse_none_without_budget(db):
    assert reports.weekly_pulse(db, today=date(2026, 7, 10)) is None


def test_send_weekly_pulse(db, budgeted):
    alerts = FakeAlerts()
    assert reports.send_weekly_pulse(db, alerts, "http://fm", today=date(2026, 7, 10))
    assert alerts.sent[0]["type"] == "weekly_pulse"
    assert alerts.sent[0]["url"] == "http://fm/reports/2026-07"


def test_threshold_fires_once_per_category_month(db, budgeted, appstate=None):
    w = budgeted
    spend(db, w["acct"], "2026-07", 39000, w["groceries"], day=5)  # 97% of 40000
    alerts = FakeAlerts()

    class LoggingAlerts(FakeAlerts):
        def __init__(self, db):
            super().__init__()
            self.db = db

        def send(self, type_, title, message, url=None, priority=0):
            import json
            self.db.execute(
                "INSERT INTO alert_log (type, payload_json, ok) VALUES (?, ?, 1)",
                (type_, json.dumps({"title": title})))
            return super().send(type_, title, message, url, priority)

    alerts = LoggingAlerts(db)
    fired = reports.check_category_thresholds(db, alerts, "http://fm",
                                              today=date(2026, 7, 6))
    assert fired == ["Groceries"]
    # second run: deduped
    fired = reports.check_category_thresholds(db, alerts, "http://fm",
                                              today=date(2026, 7, 7))
    assert fired == []
    assert len([a for a in alerts.sent if a["type"] == "budget_threshold"]) == 1


def test_monthly_report_deltas_and_savings(db, budgeted):
    w = budgeted
    spend(db, w["acct"], "2026-07", 50000, w["groceries"])
    db.execute("INSERT INTO transactions (account_id, content_hash, posted_at, "
               "amount_cents, payee_raw, payee_norm, memo, category_id) "
               "VALUES (?, 'h', '2026-07-05', 300000, 'PAY', 'PAY', '', ?)",
               (w["acct"], w["income"]))
    db.execute("INSERT INTO savings_goals (name, monthly_cents) VALUES ('S', 200000)")
    r = reports.monthly_report(db, "2026-07")
    groceries_row = next(c for c in r["categories"] if c["category_name"] == "Groceries")
    assert groceries_row["delta_cents"] == 10000  # 50000 vs 40000 in June
    assert r["net_cents"] == 300000 - 50000
    assert r["savings_goal_cents"] == 200000

    alerts = FakeAlerts()
    reports.send_monthly_report(db, alerts, "http://fm", "2026-07")
    assert "met" in alerts.sent[0]["message"]
    assert "Over budget: Groceries" in alerts.sent[0]["message"]


def test_staleness_nag(db, world):  # noqa: F811
    w = world
    spend(db, w["acct"], "2026-05", 1000, w["gas"], day=1)
    alerts = FakeAlerts()
    stale = reports.check_staleness(db, alerts, today=date(2026, 7, 1))
    assert stale and "Chk" in stale[0]
    assert alerts.sent[0]["type"] == "staleness"

    # fresh data → no nag
    alerts2 = FakeAlerts()
    spend(db, w["acct"], "2026-06", 1000, w["gas"], day=28)
    assert reports.check_staleness(db, alerts2, today=date(2026, 7, 1)) == []
    assert alerts2.sent == []


def test_scheduler_starts_and_registers_jobs(tmp_path):
    from app.config import Config
    from app.state import AppState

    cfg = Config(data_dir=tmp_path / "data", backup_dir=tmp_path / "backups",
                 enable_scheduler=True)
    state = AppState(cfg)
    state.setup("test vault passphrase", "kevin", "Kevin", "kevin-pass-1")
    try:
        assert state.scheduler is not None
        job_ids = {j.id for j in state.scheduler.get_jobs()}
        assert {"bayes_retrain", "balance_threats", "staleness", "weekly_pulse",
                "budget_draft", "monthly_report", "category_thresholds",
                "recurring_detect", "session_cleanup"} <= job_ids
    finally:
        state.lock()
    assert state.scheduler is None


def test_reports_api(authed, appstate):
    assert authed.get("/api/reports/pulse").status_code == 404
    r = authed.get("/api/reports/monthly/2026-07")
    assert r.status_code == 200 and r.json()["budget"] is None
    assert authed.get("/api/reports/alerts").json() == []
