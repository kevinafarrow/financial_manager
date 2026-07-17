"""Pushover alerting. Every alert is recorded in alert_log; delivery failures
never raise into calling code (alerting must not break imports or jobs)."""

from __future__ import annotations

import json
import logging

import httpx

log = logging.getLogger(__name__)

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


class AlertService:
    def __init__(self, db, get_secret, http_client: httpx.Client | None = None):
        """`get_secret(name) -> str | None` reads from the encrypted secrets store."""
        self.db = db
        self.get_secret = get_secret
        self.http = http_client or httpx.Client(timeout=10)

    def send(self, type_: str, title: str, message: str, url: str | None = None,
             priority: int = 0) -> bool:
        payload = {"title": title, "message": message, "url": url, "priority": priority}
        ok = self._push(title, message, url, priority)
        self.db.execute(
            "INSERT INTO alert_log (type, payload_json, ok) VALUES (?, ?, ?)",
            (type_, json.dumps(payload), 1 if ok else 0),
        )
        return ok

    def _push(self, title: str, message: str, url: str | None, priority: int) -> bool:
        user = self.get_secret("pushover_user")
        token = self.get_secret("pushover_token")
        if not user or not token:
            log.info("pushover not configured; alert logged only: %s", title)
            return False
        data = {"token": token, "user": user, "title": title, "message": message,
                "priority": priority}
        if url:
            data["url"] = url
        try:
            resp = self.http.post(PUSHOVER_URL, data=data)
            return resp.status_code == 200
        except httpx.HTTPError as e:
            log.warning("pushover delivery failed: %s", e)
            return False


def send_boot_notice(config, http_client: httpx.Client | None = None) -> None:
    """Best-effort 'app restarted and is locked' notice using the optional
    plaintext env credentials (the real ones live in the still-locked DB)."""
    if not (config.boot_pushover_user and config.boot_pushover_token):
        return
    client = http_client or httpx.Client(timeout=10)
    try:
        client.post(PUSHOVER_URL, data={
            "token": config.boot_pushover_token,
            "user": config.boot_pushover_user,
            "title": "Financial Manager locked",
            "message": "The app restarted and is waiting for the vault passphrase.",
        })
    except httpx.HTTPError as e:
        log.warning("boot notice failed: %s", e)
