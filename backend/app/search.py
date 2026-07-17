"""Transaction search: text or regex over payee/memo plus structured filters."""

from __future__ import annotations

import regex


class BadPattern(ValueError):
    pass


def search_transactions(db, q: str | None = None, use_regex: bool = False,
                        account_id: int | None = None,
                        category_id: int | None = None,
                        date_from: str | None = None, date_to: str | None = None,
                        amount_min_cents: int | None = None,
                        amount_max_cents: int | None = None,
                        uncategorized: bool = False,
                        include_transfers: bool = True,
                        limit: int = 100, offset: int = 0) -> dict:
    where, params = ["1=1"], []
    if q:
        if use_regex:
            try:
                regex.compile(q)
            except regex.error as e:
                raise BadPattern(f"invalid regex: {e}")
            where.append("(t.payee_raw REGEXP ? OR t.memo REGEXP ?)")
            params += [q, q]
        else:
            like = f"%{q}%"
            where.append("(t.payee_raw LIKE ? OR t.memo LIKE ? OR t.payee_norm LIKE ?)")
            params += [like, like, like]
    if account_id is not None:
        where.append("t.account_id = ?")
        params.append(account_id)
    if category_id is not None:
        where.append("(t.category_id = ? OR t.id IN "
                     "(SELECT transaction_id FROM transaction_splits WHERE category_id = ?))")
        params += [category_id, category_id]
    if date_from:
        where.append("t.posted_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("t.posted_at <= ?")
        params.append(date_to)
    if amount_min_cents is not None:
        where.append("abs(t.amount_cents) >= ?")
        params.append(amount_min_cents)
    if amount_max_cents is not None:
        where.append("abs(t.amount_cents) <= ?")
        params.append(amount_max_cents)
    if uncategorized:
        where.append("t.category_id IS NULL AND t.transfer_id IS NULL")
    if not include_transfers:
        where.append("t.transfer_id IS NULL")

    clause = " AND ".join(where)
    total = db.query_one(
        f"SELECT count(*) c FROM transactions t WHERE {clause}", params)["c"]
    rows = db.query(
        f"SELECT t.*, a.name AS account_name, c.name AS category_name, "
        f"  tr.status AS transfer_status, "
        f"  peer_a.name AS transfer_peer_account, "
        f"  (t.amount_cents > 0 AND t.transfer_id IS NOT NULL) AS is_transfer_in "
        f"FROM transactions t "
        f"JOIN accounts a ON a.id = t.account_id "
        f"LEFT JOIN categories c ON c.id = t.category_id "
        f"LEFT JOIN transfers tr ON tr.id = t.transfer_id "
        f"LEFT JOIN transactions peer ON peer.transfer_id = t.transfer_id "
        f"  AND peer.id != t.id "
        f"LEFT JOIN accounts peer_a ON peer_a.id = peer.account_id "
        f"WHERE {clause} "
        f"ORDER BY t.posted_at DESC, t.id DESC LIMIT ? OFFSET ?",
        (*params, min(limit, 500), offset))
    tx_ids = [r["id"] for r in rows]
    splits: dict[int, list] = {}
    if tx_ids:
        marks = ",".join("?" * len(tx_ids))
        for s in db.query(
                f"SELECT s.*, c.name AS category_name FROM transaction_splits s "
                f"JOIN categories c ON c.id = s.category_id "
                f"WHERE s.transaction_id IN ({marks})", tx_ids):
            splits.setdefault(s["transaction_id"], []).append(s)
    for r in rows:
        r["splits"] = splits.get(r["id"], [])
    return {"total": total, "transactions": rows}
