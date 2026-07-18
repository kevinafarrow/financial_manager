"""Receipt orchestration: poll → intake policy → parse → match → split."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from .. import settings_store
from . import intake

log = logging.getLogger(__name__)

MATCH_WINDOW_DAYS = 3
AMOUNT_SLACK_CENTS = 2


class ReceiptService:
    def __init__(self, db, parser, fetcher=None, categorizer=None):
        """`fetcher` needs fetch_new() -> [(uid, raw_bytes)]; `parser` needs
        parse(body, categories) -> dict|None. Both injectable for tests."""
        self.db = db
        self.parser = parser
        self.fetcher = fetcher
        self.categorizer = categorizer

    # -- polling -------------------------------------------------------------

    def poll(self) -> dict:
        if self.fetcher is None:
            return {"fetched": 0}
        stats = {"fetched": 0, "accepted": 0, "quarantined": 0}
        for uid, raw in self.fetcher.fetch_new():
            if self.db.query_one("SELECT id FROM receipts WHERE imap_uid = ?", (uid,)):
                continue
            stats["fetched"] += 1
            receipt_id = self.ingest(raw, imap_uid=uid)
            status = self.db.query_one(
                "SELECT status FROM receipts WHERE id = ?", (receipt_id,))["status"]
            stats["accepted" if status != "quarantined" else "quarantined"] += 1
        return stats

    # -- intake --------------------------------------------------------------

    def ingest(self, raw: bytes, imap_uid: str | None = None) -> int:
        parts = intake.extract_parts(raw)
        token = settings_store.get(self.db, "receipt_token")
        allowlist = settings_store.get(self.db, "receipt_allowed_senders", [])
        reason = intake.check_policy(parts, token, allowlist)
        receipt_id = self.db.execute(
            "INSERT INTO receipts (imap_uid, from_addr, subject, received_at, "
            "status, reject_reason, raw_email) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (imap_uid, parts["from_addr"], parts["subject"], parts["received_at"],
             "quarantined", reason, raw))
        if reason is None:
            self.process(receipt_id)
        return receipt_id

    # -- parse + match -------------------------------------------------------

    def process(self, receipt_id: int) -> None:
        """Parse a stored receipt and try to match/split. Idempotent."""
        r = self.db.query_one("SELECT * FROM receipts WHERE id = ?", (receipt_id,))
        if r is None:
            raise ValueError("receipt not found")
        parts = intake.extract_parts(r["raw_email"])
        categories = [c["name"] for c in self.db.query(
            "SELECT name FROM categories WHERE archived = 0 AND kind = 'expense'")]
        parsed = self.parser.parse(parts["body"], categories)
        if parsed is None:
            self.db.execute(
                "UPDATE receipts SET status = 'quarantined', "
                "reject_reason = 'could not parse receipt' WHERE id = ?", (receipt_id,))
            return
        self.db.execute(
            "UPDATE receipts SET status = 'parsed', reject_reason = NULL, "
            "parsed_json = ? WHERE id = ?", (json.dumps(parsed), receipt_id))
        matches = self.find_matches(parsed)
        if len(matches) == 1:
            try:
                self.apply_to_transaction(receipt_id, matches[0]["id"])
            except ValueError as e:
                log.info("auto-apply skipped for receipt %s: %s", receipt_id, e)

    def find_matches(self, parsed: dict) -> list[dict]:
        try:
            d = date.fromisoformat(parsed["date"][:10])
        except (ValueError, TypeError):
            return []
        lo = (d - timedelta(days=MATCH_WINDOW_DAYS)).isoformat()
        hi = (d + timedelta(days=MATCH_WINDOW_DAYS)).isoformat()
        return self.db.query(
            "SELECT * FROM transactions WHERE transfer_id IS NULL "
            "AND posted_at BETWEEN ? AND ? AND abs(amount_cents + ?) <= ?",
            (lo, hi, parsed["total_cents"], AMOUNT_SLACK_CENTS))

    def apply_to_transaction(self, receipt_id: int, tx_id: int,
                             user_id: int | None = None) -> None:
        r = self.db.query_one("SELECT * FROM receipts WHERE id = ?", (receipt_id,))
        tx = self.db.query_one("SELECT * FROM transactions WHERE id = ?", (tx_id,))
        if r is None or r["parsed_json"] is None:
            raise ValueError("receipt not parsed")
        if tx is None:
            raise ValueError("transaction not found")
        if tx["transfer_id"]:
            raise ValueError("cannot apply a receipt to a transfer leg")
        parsed = json.loads(r["parsed_json"])
        cat_ids = {c["name"]: c["id"] for c in self.db.query(
            "SELECT id, name FROM categories WHERE archived = 0")}
        # aggregate items by category
        per_cat: dict[str, int] = {}
        for item in parsed["items"]:
            if item["category"] not in cat_ids:
                raise ValueError(f"unknown category {item['category']!r}")
            per_cat[item["category"]] = per_cat.get(item["category"], 0) + item["amount_cents"]
        if sum(per_cat.values()) != abs(tx["amount_cents"]):
            raise ValueError("receipt total does not match transaction amount")

        with self.db.transaction() as conn:
            conn.execute("DELETE FROM transaction_splits WHERE transaction_id = ?",
                         (tx_id,))
            if len(per_cat) == 1:
                only_cat = cat_ids[next(iter(per_cat))]
                conn.execute(
                    "UPDATE transactions SET category_id = ?, cat_source = 'receipt', "
                    "cat_confidence = 1.0, updated_at = datetime('now') WHERE id = ?",
                    (only_cat, tx_id))
            else:
                for name, cents in per_cat.items():
                    conn.execute(
                        "INSERT INTO transaction_splits (transaction_id, category_id, "
                        "amount_cents, note) VALUES (?, ?, ?, ?)",
                        (tx_id, cat_ids[name], -cents, f"receipt: {parsed['merchant']}"))
                conn.execute(
                    "UPDATE transactions SET category_id = NULL, cat_source = 'receipt', "
                    "cat_confidence = 1.0, updated_at = datetime('now') WHERE id = ?",
                    (tx_id,))
            conn.execute("UPDATE receipts SET status = 'matched', matched_tx_id = ? "
                         "WHERE id = ?", (tx_id, receipt_id))
