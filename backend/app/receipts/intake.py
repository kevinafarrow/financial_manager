"""Receipt-mail intake policy: bearer token + sender allowlist, or quarantine.

Receipt content is treated strictly as data. Anything failing the checks is
stored as 'quarantined' with a reason and surfaced in the UI — never processed.
"""

from __future__ import annotations

import email
import email.utils
import re
from html import unescape


def extract_parts(raw: bytes) -> dict:
    msg = email.message_from_bytes(raw)
    from_addr = (email.utils.parseaddr(msg.get("From", ""))[1] or "").lower()
    subject = msg.get("Subject", "") or ""
    received = msg.get("Date", "")
    try:
        dt = email.utils.parsedate_to_datetime(received)
        received_iso = dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        received_iso = None

    text_parts, html_parts = [], []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace") if payload else ""
        except Exception:
            continue
        (text_parts if ctype == "text/plain" else html_parts).append(body)
    body = "\n".join(text_parts) if text_parts else _strip_html("\n".join(html_parts))
    return {"from_addr": from_addr, "subject": subject, "body": body,
            "received_at": received_iso}


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", unescape(html)).strip()


def check_policy(parts: dict, token: str | None, allowlist: list[str]) -> str | None:
    """Returns a rejection reason, or None when the mail passes."""
    if not token:
        return "no receipt token configured"
    haystack = f"{parts['subject']}\n{parts['body']}"
    if token not in haystack:
        return "bearer token missing from subject/body"
    senders = {s.strip().lower() for s in allowlist if s.strip()}
    if not senders:
        return "sender allowlist is empty"
    if parts["from_addr"] not in senders:
        return f"sender {parts['from_addr'] or '(none)'} not in allowlist"
    return None
