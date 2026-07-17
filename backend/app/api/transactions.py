from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit
from ..search import BadPattern, search_transactions
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class CategorizeBody(BaseModel):
    category_id: int


class SplitItem(BaseModel):
    category_id: int
    amount_cents: int
    note: str = ""


class SplitsBody(BaseModel):
    splits: list[SplitItem]


@router.get("")
def list_transactions(q: str | None = None, regex: bool = False,
                      account_id: int | None = None, category_id: int | None = None,
                      date_from: str | None = None, date_to: str | None = None,
                      amount_min_cents: int | None = None,
                      amount_max_cents: int | None = None,
                      uncategorized: bool = False, include_transfers: bool = True,
                      limit: int = 100, offset: int = 0,
                      state=Depends(require_unlocked), user=Depends(require_user)):
    try:
        return search_transactions(
            state.db, q=q, use_regex=regex, account_id=account_id,
            category_id=category_id, date_from=date_from, date_to=date_to,
            amount_min_cents=amount_min_cents, amount_max_cents=amount_max_cents,
            uncategorized=uncategorized, include_transfers=include_transfers,
            limit=limit, offset=offset)
    except BadPattern as e:
        raise HTTPException(400, str(e))


def _tx_or_404(state, tx_id: int) -> dict:
    tx = state.db.query_one("SELECT * FROM transactions WHERE id = ?", (tx_id,))
    if tx is None:
        raise HTTPException(404, "transaction not found")
    return tx


@router.post("/{tx_id}/category")
def set_category(tx_id: int, body: CategorizeBody, state=Depends(require_unlocked),
                 user=Depends(require_user)):
    tx = _tx_or_404(state, tx_id)
    if tx["transfer_id"]:
        raise HTTPException(400, "transfer legs cannot be categorized")
    if not state.db.query_one("SELECT id FROM categories WHERE id = ? AND archived = 0",
                              (body.category_id,)):
        raise HTTPException(400, "unknown category")
    state.categorizer.user_categorize(tx_id, body.category_id, user["id"])
    audit.record(state.db, user["id"], "categorize", "transaction", tx_id,
                 {"category_id": body.category_id})
    state.data_changed()
    return _tx_or_404(state, tx_id)


@router.put("/{tx_id}/splits")
def set_splits(tx_id: int, body: SplitsBody, state=Depends(require_unlocked),
               user=Depends(require_user)):
    tx = _tx_or_404(state, tx_id)
    if tx["transfer_id"]:
        raise HTTPException(400, "transfer legs cannot be split")
    if len(body.splits) < 2:
        raise HTTPException(400, "a split needs at least two lines")
    if sum(s.amount_cents for s in body.splits) != tx["amount_cents"]:
        raise HTTPException(400, "split amounts must sum to the transaction amount")
    for s in body.splits:
        if not state.db.query_one(
                "SELECT id FROM categories WHERE id = ? AND archived = 0",
                (s.category_id,)):
            raise HTTPException(400, f"unknown category {s.category_id}")
    with state.db.transaction() as conn:
        conn.execute("DELETE FROM transaction_splits WHERE transaction_id = ?", (tx_id,))
        for s in body.splits:
            conn.execute(
                "INSERT INTO transaction_splits (transaction_id, category_id, "
                "amount_cents, note) VALUES (?, ?, ?, ?)",
                (tx_id, s.category_id, s.amount_cents, s.note))
        conn.execute(
            "UPDATE transactions SET category_id = NULL, cat_source = 'user', "
            "cat_confidence = 1.0, updated_at = datetime('now'), updated_by = ? "
            "WHERE id = ?", (user["id"], tx_id))
    audit.record(state.db, user["id"], "split", "transaction", tx_id,
                 {"parts": len(body.splits)})
    state.data_changed()
    return search_one(state, tx_id)


@router.delete("/{tx_id}/splits")
def clear_splits(tx_id: int, state=Depends(require_unlocked),
                 user=Depends(require_user)):
    _tx_or_404(state, tx_id)
    state.db.execute("DELETE FROM transaction_splits WHERE transaction_id = ?", (tx_id,))
    state.db.execute("UPDATE transactions SET cat_source = 'none', category_id = NULL, "
                     "updated_at = datetime('now') WHERE id = ?", (tx_id,))
    audit.record(state.db, user["id"], "unsplit", "transaction", tx_id)
    state.data_changed()
    return {"ok": True}


def search_one(state, tx_id: int) -> dict:
    tx = _tx_or_404(state, tx_id)
    result = search_transactions(state.db, account_id=tx["account_id"],
                                 date_from=tx["posted_at"], date_to=tx["posted_at"])
    return next(t for t in result["transactions"] if t["id"] == tx_id)
