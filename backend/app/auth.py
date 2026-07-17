"""Users, sessions, and failed-login throttling/alerting."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

SESSION_TTL_DAYS = 30
FAILED_WINDOW_SECONDS = 15 * 60
FAILED_THRESHOLD = 5

_hasher = PasswordHasher()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, db, alert_service=None, sleep=time.sleep, clock=time.monotonic):
        self.db = db
        self.alerts = alert_service
        self._sleep = sleep
        self._clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    # -- users ---------------------------------------------------------------

    def create_user(self, username: str, display_name: str, password: str,
                    is_admin: bool = False) -> int:
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        return self.db.execute(
            "INSERT INTO users (username, display_name, password_hash, is_admin) "
            "VALUES (?, ?, ?, ?)",
            (username.strip().lower(), display_name.strip(), hash_password(password),
             1 if is_admin else 0),
        )

    def change_password(self, user_id: int, new_password: str) -> None:
        if len(new_password) < 8:
            raise ValueError("password must be at least 8 characters")
        self.db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )

    def user_count(self) -> int:
        return self.db.query_one("SELECT count(*) c FROM users")["c"]

    # -- login/session -------------------------------------------------------

    def login(self, username: str, password: str, ip: str | None = None) -> str | None:
        """Returns a session token, or None on bad credentials."""
        username = username.strip().lower()
        self._throttle(username)
        user = self.db.query_one("SELECT * FROM users WHERE username = ?", (username,))
        ok = False
        if user is not None:
            try:
                _hasher.verify(user["password_hash"], password)
                ok = True
            except VerifyMismatchError:
                ok = False
        if not ok:
            self._record_failure(username, ip)
            return None
        self._failures.pop(username, None)
        token = secrets.token_urlsafe(32)
        expires = _iso(_utcnow() + timedelta(days=SESSION_TTL_DAYS))
        self.db.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at, ip) VALUES (?, ?, ?, ?)",
            (_token_hash(token), user["id"], expires, ip),
        )
        return token

    def get_user_for_token(self, token: str) -> dict | None:
        row = self.db.query_one(
            "SELECT u.id, u.username, u.display_name, u.is_admin "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ?",
            (_token_hash(token), _iso(_utcnow())),
        )
        return row

    def logout(self, token: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    def cleanup_sessions(self) -> None:
        self.db.execute("DELETE FROM sessions WHERE expires_at <= ?", (_iso(_utcnow()),))

    # -- failed-login handling ----------------------------------------------

    def _recent_failures(self, username: str) -> int:
        q = self._failures[username]
        cutoff = self._clock() - FAILED_WINDOW_SECONDS
        while q and q[0] < cutoff:
            q.popleft()
        return len(q)

    def _throttle(self, username: str) -> None:
        n = self._recent_failures(username)
        if n >= FAILED_THRESHOLD:
            self._sleep(min(2 * (n - FAILED_THRESHOLD + 1), 30))

    def _record_failure(self, username: str, ip: str | None) -> None:
        self._failures[username].append(self._clock())
        n = self._recent_failures(username)
        if n == FAILED_THRESHOLD and self.alerts:
            self.alerts.send(
                "failed_logins",
                "Repeated failed logins",
                f"{n} failed login attempts for '{username}' in the last 15 minutes"
                + (f" (last from {ip})" if ip else ""),
                priority=1,
            )
