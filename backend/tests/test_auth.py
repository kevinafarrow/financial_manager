"""Unit tests for AuthService (fake clock/sleep, no network)."""

import pytest

from app.auth import FAILED_THRESHOLD, AuthService
from tests.conftest import FakeAlerts


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)


@pytest.fixture
def svc(db):
    clock = FakeClock()
    alerts = FakeAlerts()
    s = AuthService(db, alert_service=alerts, sleep=clock.sleep, clock=clock.now)
    s.create_user("kevin", "Kevin", "password123", is_admin=True)
    return s, clock, alerts


def test_login_success_and_session(svc):
    s, _, _ = svc
    token = s.login("kevin", "password123")
    assert token
    user = s.get_user_for_token(token)
    assert user["username"] == "kevin" and user["is_admin"] == 1


def test_login_wrong_password(svc):
    s, _, _ = svc
    assert s.login("kevin", "wrongpass") is None


def test_login_unknown_user(svc):
    s, _, _ = svc
    assert s.login("nobody", "password123") is None


def test_username_case_insensitive(svc):
    s, _, _ = svc
    assert s.login("KeViN", "password123") is not None


def test_logout_invalidates_token(svc):
    s, _, _ = svc
    token = s.login("kevin", "password123")
    s.logout(token)
    assert s.get_user_for_token(token) is None


def test_expired_session_rejected(svc, monkeypatch):
    s, _, _ = svc
    token = s.login("kevin", "password123")
    s.db.execute("UPDATE sessions SET expires_at = '2000-01-01 00:00:00'")
    assert s.get_user_for_token(token) is None
    s.cleanup_sessions()
    assert s.db.query_one("SELECT count(*) c FROM sessions")["c"] == 0


def test_failed_login_alert_fires_once_at_threshold(svc):
    s, clock, alerts = svc
    for _ in range(FAILED_THRESHOLD):
        s.login("kevin", "wrongpass", ip="10.0.0.9")
    assert len(alerts.sent) == 1
    assert alerts.sent[0]["type"] == "failed_logins"
    assert "10.0.0.9" in alerts.sent[0]["message"]
    # further failures within the window don't re-alert
    s.login("kevin", "wrongpass")
    assert len(alerts.sent) == 1


def test_throttle_after_threshold(svc):
    s, clock, _ = svc
    for _ in range(FAILED_THRESHOLD):
        s.login("kevin", "wrongpass")
    assert clock.slept == []
    s.login("kevin", "wrongpass")
    assert len(clock.slept) == 1


def test_failures_expire_outside_window(svc):
    s, clock, alerts = svc
    for _ in range(FAILED_THRESHOLD - 1):
        s.login("kevin", "wrongpass")
    clock.t += 16 * 60
    s.login("kevin", "wrongpass")
    assert alerts.sent == []  # old failures aged out, threshold never hit


def test_successful_login_resets_failures(svc):
    s, _, alerts = svc
    for _ in range(FAILED_THRESHOLD - 1):
        s.login("kevin", "wrongpass")
    s.login("kevin", "password123")
    s.login("kevin", "wrongpass")
    assert alerts.sent == []


def test_short_password_rejected(svc):
    s, _, _ = svc
    with pytest.raises(ValueError):
        s.create_user("mary", "Mary", "short")
