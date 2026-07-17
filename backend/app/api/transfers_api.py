from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit, transfers
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


class LinkBody(BaseModel):
    from_tx: int
    to_tx: int


@router.get("")
def list_transfers(state=Depends(require_unlocked), user=Depends(require_user)):
    return transfers.list_transfers(state.db)


@router.get("/candidates")
def candidates(state=Depends(require_unlocked), user=Depends(require_user)):
    return state.db.query(
        "SELECT tc.id, tc.score, "
        "  a.id AS tx_a, a.posted_at AS a_posted_at, a.amount_cents AS a_amount, "
        "  a.payee_raw AS a_payee, aa.name AS a_account, "
        "  b.id AS tx_b, b.posted_at AS b_posted_at, b.amount_cents AS b_amount, "
        "  b.payee_raw AS b_payee, ab.name AS b_account "
        "FROM transfer_candidates tc "
        "JOIN transactions a ON a.id = tc.tx_a JOIN transactions b ON b.id = tc.tx_b "
        "JOIN accounts aa ON aa.id = a.account_id JOIN accounts ab ON ab.id = b.account_id "
        "WHERE tc.status = 'pending' ORDER BY a.posted_at DESC")


@router.post("/candidates/{candidate_id}/accept")
def accept_candidate(candidate_id: int, state=Depends(require_unlocked),
                     user=Depends(require_user)):
    c = state.db.query_one(
        "SELECT * FROM transfer_candidates WHERE id = ? AND status = 'pending'",
        (candidate_id,))
    if c is None:
        raise HTTPException(404, "candidate not found")
    try:
        transfer_id = transfers.link(state.db, c["tx_a"], c["tx_b"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.record(state.db, user["id"], "accept", "transfer", transfer_id)
    state.data_changed()
    return {"transfer_id": transfer_id}


@router.post("/candidates/{candidate_id}/reject")
def reject_candidate(candidate_id: int, state=Depends(require_unlocked),
                     user=Depends(require_user)):
    n = state.db.query_one(
        "SELECT count(*) c FROM transfer_candidates WHERE id = ? AND status = 'pending'",
        (candidate_id,))["c"]
    if not n:
        raise HTTPException(404, "candidate not found")
    state.db.execute("UPDATE transfer_candidates SET status = 'rejected' WHERE id = ?",
                     (candidate_id,))
    audit.record(state.db, user["id"], "reject", "transfer_candidate", candidate_id)
    state.data_changed()
    return {"ok": True}


@router.post("/link")
def manual_link(body: LinkBody, state=Depends(require_unlocked),
                user=Depends(require_user)):
    try:
        transfer_id = transfers.link(state.db, body.from_tx, body.to_tx)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.record(state.db, user["id"], "link", "transfer", transfer_id)
    state.data_changed()
    return {"transfer_id": transfer_id}


@router.delete("/{transfer_id}")
def unlink(transfer_id: int, state=Depends(require_unlocked),
           user=Depends(require_user)):
    try:
        transfers.unlink(state.db, transfer_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    audit.record(state.db, user["id"], "unlink", "transfer", transfer_id)
    state.data_changed()
    return {"ok": True}
