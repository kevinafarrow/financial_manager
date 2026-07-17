"""The manual categorization queue: transactions nothing could categorize."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/queue", tags=["queue"])


class AssignBody(BaseModel):
    category_id: int


@router.get("")
def list_queue(limit: int = 100, state=Depends(require_unlocked),
               user=Depends(require_user)):
    return state.db.query(
        "SELECT t.*, a.name AS account_name FROM transactions t "
        "JOIN accounts a ON a.id = t.account_id "
        "WHERE t.category_id IS NULL AND t.transfer_id IS NULL "
        "ORDER BY t.posted_at DESC LIMIT ?", (min(limit, 500),))


@router.post("/{tx_id}")
def assign(tx_id: int, body: AssignBody, state=Depends(require_unlocked),
           user=Depends(require_user)):
    cat = state.db.query_one(
        "SELECT id FROM categories WHERE id = ? AND archived = 0", (body.category_id,))
    if cat is None:
        raise HTTPException(400, "unknown category")
    try:
        state.categorizer.user_categorize(tx_id, body.category_id, user["id"])
    except ValueError as e:
        raise HTTPException(404, str(e))
    audit.record(state.db, user["id"], "categorize", "transaction", tx_id,
                 {"category_id": body.category_id})
    state.data_changed()
    return state.db.query_one("SELECT * FROM transactions WHERE id = ?", (tx_id,))
