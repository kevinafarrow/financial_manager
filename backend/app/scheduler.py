"""Background jobs. Runs only while the vault is unlocked; every job is
wrapped so one failure never kills the scheduler."""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import budgets, recurring, reports

log = logging.getLogger(__name__)


def _safe(name, fn):
    def run():
        try:
            fn()
        except Exception:
            log.exception("scheduled job %s failed", name)

    run.__name__ = name
    return run


def start(state) -> BackgroundScheduler:
    s = BackgroundScheduler(daemon=True)
    base_url = state.config.base_url

    def month_now() -> str:
        return datetime.now().strftime("%Y-%m")

    jobs = [
        ("bayes_retrain", CronTrigger(hour=3, minute=0),
         lambda: state.categorizer.retrain()),
        ("recurring_detect", CronTrigger(hour=3, minute=15),
         lambda: recurring.detect(state.db)),
        ("balance_threats", CronTrigger(hour=8, minute=0),
         lambda: recurring.check_balance_threats(state.db, state.alerts)),
        ("staleness", CronTrigger(hour=9, minute=0),
         lambda: reports.check_staleness(state.db, state.alerts)),
        ("category_thresholds", CronTrigger(hour=18, minute=30),
         lambda: reports.check_category_thresholds(state.db, state.alerts, base_url)),
        ("weekly_pulse", CronTrigger(day_of_week="sun", hour=18, minute=0),
         lambda: reports.send_weekly_pulse(state.db, state.alerts, base_url)),
        ("budget_draft", CronTrigger(day=28, hour=18, minute=0),
         lambda: _draft_next_month(state)),
        ("monthly_report", CronTrigger(day=1, hour=8, minute=0),
         lambda: reports.send_monthly_report(
             state.db, state.alerts, base_url,
             budgets.month_add(month_now(), -1))),
        ("session_cleanup", IntervalTrigger(hours=1),
         lambda: state.auth.cleanup_sessions()),
    ]
    if state.receipts is not None:
        jobs.append(("imap_poll", IntervalTrigger(minutes=5),
                     lambda: state.receipts.poll()))
    if state.backups is not None:
        jobs.append(("backup_prune", CronTrigger(hour=4, minute=0),
                     lambda: state.backups.prune()))

    for name, trigger, fn in jobs:
        s.add_job(_safe(name, fn), trigger, id=name, coalesce=True,
                  misfire_grace_time=3600)
    s.start()
    log.info("scheduler started with %d jobs", len(jobs))
    return s


def _draft_next_month(state) -> None:
    month = budgets.month_add(datetime.now().strftime("%Y-%m"), 1)
    try:
        budgets.draft_budget(state.db, month)
    except ValueError:
        return  # already approved — nothing to do
    state.alerts.send(
        "budget_draft", f"Budget draft ready — {month}",
        "Next month's budget draft is ready for review and approval.",
        url=f"{state.config.base_url}/budget")
