"""Import orchestration: parse → dedupe → insert → categorize hook → record."""

from __future__ import annotations

import hashlib
from collections import Counter

from ..categorize.normalize import normalize_payee
from .csv_importer import parse_csv
from .ofx import parse_ofx
from .types import ParsedFile, RawTxn


class ImportError_(ValueError):
    pass


def content_hash(t: RawTxn) -> str:
    key = f"{t.posted_at}|{t.amount_cents}|{t.payee_raw}|{t.memo}"
    return hashlib.sha256(key.encode()).hexdigest()


def parse_file(filename: str, data: bytes, mapping: dict | None = None) -> ParsedFile:
    lower = filename.lower()
    if lower.endswith((".ofx", ".qfx", ".qbo")):
        return parse_ofx(data)
    if lower.endswith(".csv"):
        return parse_csv(data, mapping)
    # sniff: OFX files start with 'OFXHEADER' or '<?xml'/'<OFX>'
    head = data[:200].lstrip().upper()
    if head.startswith(b"OFXHEADER") or b"<OFX>" in head or head.startswith(b"<?XML"):
        return parse_ofx(data)
    return parse_csv(data, mapping)


def import_file(state, account_id: int, filename: str, data: bytes,
                mapping: dict | None = None, user_id: int | None = None) -> dict:
    db = state.db
    account = db.query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if account is None:
        raise ImportError_("account not found")

    parsed = parse_file(filename, data, mapping)
    if not parsed.transactions and parsed.balance_cents is None:
        raise ImportError_("no transactions found in file")

    import_id = db.execute(
        "INSERT INTO imports (filename, account_id, format, user_id) VALUES (?, ?, ?, ?)",
        (filename, account_id, parsed.format, user_id),
    )

    # Dedupe. fitid is authoritative when present; otherwise content-hash with
    # multiplicity (two identical coffees the same day are two transactions, but
    # re-uploading an overlapping statement must not duplicate them).
    new_txns: list[RawTxn] = []
    dup_count = 0
    hash_budget: Counter[str] = Counter()
    for t in parsed.transactions:
        if t.fitid:
            exists = db.query_one(
                "SELECT id FROM transactions WHERE account_id = ? AND fitid = ?",
                (account_id, t.fitid))
            if exists:
                dup_count += 1
                continue
            new_txns.append(t)
        else:
            h = content_hash(t)
            if h not in hash_budget:
                in_db = db.query_one(
                    "SELECT count(*) c FROM transactions WHERE account_id = ? "
                    "AND content_hash = ?", (account_id, h))["c"]
                hash_budget[h] = in_db
            if hash_budget[h] > 0:
                hash_budget[h] -= 1
                dup_count += 1
                continue
            new_txns.append(t)

    inserted_ids: list[int] = []
    for t in new_txns:
        tx_id = db.execute(
            "INSERT INTO transactions (account_id, fitid, content_hash, posted_at, "
            "amount_cents, payee_raw, payee_norm, memo, import_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, t.fitid, content_hash(t), t.posted_at, t.amount_cents,
             t.payee_raw, normalize_payee(t.payee_raw), t.memo, import_id),
        )
        inserted_ids.append(tx_id)

    if parsed.balance_cents is not None:
        db.execute(
            "INSERT INTO balance_snapshots (account_id, as_of, balance_cents, source) "
            "VALUES (?, ?, ?, 'import')",
            (account_id, parsed.balance_as_of or "", parsed.balance_cents),
        )

    db.execute("UPDATE imports SET tx_count = ?, dup_count = ? WHERE id = ?",
               (len(inserted_ids), dup_count, import_id))

    # Post-import hooks (categorization pipeline, transfer matching) — pluggable
    # so early phases work before later ones exist.
    for hook in getattr(state, "post_import_hooks", []):
        hook(inserted_ids)

    state.data_changed()
    return {
        "import_id": import_id,
        "imported": len(inserted_ids),
        "duplicates": dup_count,
        "transaction_ids": inserted_ids,
        "balance_recorded": parsed.balance_cents is not None,
    }
