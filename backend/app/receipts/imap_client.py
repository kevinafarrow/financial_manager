"""Minimal IMAP fetcher for the dedicated receipts mailbox."""

from __future__ import annotations

import imaplib
import logging

log = logging.getLogger(__name__)


class ImapFetcher:
    """Fetches unseen messages. Injectable-by-interface: anything with
    `fetch_new() -> list[tuple[str, bytes]]` works in its place."""

    def __init__(self, host: str, port: int, username: str, get_password):
        self.host = host
        self.port = port
        self.username = username
        self.get_password = get_password

    def fetch_new(self) -> list[tuple[str, bytes]]:
        password = self.get_password()
        if not password:
            log.info("imap password not configured; skipping poll")
            return []
        out: list[tuple[str, bytes]] = []
        conn = imaplib.IMAP4_SSL(self.host, self.port)
        try:
            conn.login(self.username, password)
            conn.select("INBOX")
            status, data = conn.uid("SEARCH", None, "UNSEEN")
            if status != "OK":
                return []
            for uid in data[0].split():
                status, msg_data = conn.uid("FETCH", uid, "(RFC822)")
                if status == "OK" and msg_data and msg_data[0]:
                    out.append((uid.decode(), msg_data[0][1]))
                    conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        return out
