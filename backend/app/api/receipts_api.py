from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/receipts", tags=["receipts"])


class MatchBody(BaseModel):
    tx_id: int


@router.get("")
def list_receipts(state=Depends(require_unlocked), user=Depends(require_user)):
    rows = state.db.query(
        "SELECT r.id, r.imap_uid, r.from_addr, r.subject, r.received_at, r.status, "
        "r.reject_reason, r.parsed_json, r.matched_tx_id, r.created_at "
        "FROM receipts r ORDER BY r.created_at DESC LIMIT 200")
    for r in rows:
        r["parsed"] = json.loads(r.pop("parsed_json")) if r["parsed_json"] else None
    return rows


@router.get("/{receipt_id}/body")
def receipt_body(receipt_id: int, state=Depends(require_unlocked),
                 user=Depends(require_user)):
    from ..receipts import intake

    r = state.db.query_one("SELECT raw_email FROM receipts WHERE id = ?", (receipt_id,))
    if r is None:
        raise HTTPException(404, "receipt not found")
    parts = intake.extract_parts(r["raw_email"])
    return {"subject": parts["subject"], "from_addr": parts["from_addr"],
            "body": parts["body"][:50000]}


@router.post("/poll")
def poll(state=Depends(require_unlocked), user=Depends(require_user)):
    result = state.receipts.poll()
    state.data_changed()
    return result


@router.post("/{receipt_id}/process")
def process(receipt_id: int, state=Depends(require_unlocked),
            user=Depends(require_user)):
    """Re-run parse+match (e.g. after fixing the API key or for a quarantined
    mail the user has inspected and trusts)."""
    try:
        state.receipts.process(receipt_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    audit.record(state.db, user["id"], "process", "receipt", receipt_id)
    state.data_changed()
    return state.db.query_one(
        "SELECT id, status, reject_reason, matched_tx_id FROM receipts WHERE id = ?",
        (receipt_id,))


@router.post("/{receipt_id}/match")
def match(receipt_id: int, body: MatchBody, state=Depends(require_unlocked),
          user=Depends(require_user)):
    try:
        state.receipts.apply_to_transaction(receipt_id, body.tx_id, user["id"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.record(state.db, user["id"], "match", "receipt", receipt_id,
                 {"tx_id": body.tx_id})
    state.data_changed()
    return {"ok": True}


@router.get("/{receipt_id}/candidates")
def candidates(receipt_id: int, state=Depends(require_unlocked),
               user=Depends(require_user)):
    r = state.db.query_one("SELECT parsed_json FROM receipts WHERE id = ?", (receipt_id,))
    if r is None or not r["parsed_json"]:
        raise HTTPException(404, "receipt not parsed")
    return state.receipts.find_matches(json.loads(r["parsed_json"]))


@router.post("/{receipt_id}/reject")
def reject(receipt_id: int, state=Depends(require_unlocked),
           user=Depends(require_user)):
    if not state.db.query_one("SELECT id FROM receipts WHERE id = ?", (receipt_id,)):
        raise HTTPException(404, "receipt not found")
    state.db.execute("UPDATE receipts SET status = 'rejected' WHERE id = ?",
                     (receipt_id,))
    audit.record(state.db, user["id"], "reject", "receipt", receipt_id)
    state.data_changed()
    return {"ok": True}
