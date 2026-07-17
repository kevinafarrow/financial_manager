from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit, recurring
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/recurring", tags=["recurring"])

VALID_STATUS = {"proposed", "confirmed", "rejected", "paused"}
VALID_PERIODS = {"weekly", "biweekly", "monthly", "yearly"}


class RecurringPatch(BaseModel):
    display_name: str | None = None
    amount_cents: int | None = None
    tolerance_cents: int | None = None
    period: str | None = None
    next_due: str | None = None
    status: str | None = None


class RecurringBody(BaseModel):
    display_name: str
    account_id: int
    amount_cents: int
    period: str
    next_due: str


@router.get("")
def list_recurring(state=Depends(require_unlocked), user=Depends(require_user)):
    return state.db.query(
        "SELECT r.*, a.name AS account_name FROM recurring r "
        "JOIN accounts a ON a.id = r.account_id "
        "ORDER BY CASE r.status WHEN 'proposed' THEN 0 WHEN 'confirmed' THEN 1 "
        "ELSE 2 END, r.next_due")


@router.post("/detect")
def run_detection(state=Depends(require_unlocked), user=Depends(require_user)):
    return recurring.detect(state.db)


@router.post("")
def create_manual(body: RecurringBody, state=Depends(require_unlocked),
                  user=Depends(require_user)):
    if body.period not in VALID_PERIODS:
        raise HTTPException(400, f"period must be one of {sorted(VALID_PERIODS)}")
    if not state.db.query_one("SELECT id FROM accounts WHERE id = ?", (body.account_id,)):
        raise HTTPException(400, "unknown account")
    rec_id = state.db.execute(
        "INSERT INTO recurring (payee_norm, display_name, account_id, amount_cents, "
        "tolerance_cents, period, next_due, status) VALUES (?, ?, ?, ?, 0, ?, ?, 'confirmed')",
        (body.display_name.upper(), body.display_name, body.account_id,
         body.amount_cents, body.period, body.next_due))
    audit.record(state.db, user["id"], "create", "recurring", rec_id)
    state.data_changed()
    return state.db.query_one("SELECT * FROM recurring WHERE id = ?", (rec_id,))


@router.patch("/{rec_id}")
def update_recurring(rec_id: int, body: RecurringPatch,
                     state=Depends(require_unlocked), user=Depends(require_user)):
    if not state.db.query_one("SELECT id FROM recurring WHERE id = ?", (rec_id,)):
        raise HTTPException(404, "not found")
    updates = body.model_dump(exclude_none=True)
    if "status" in updates and updates["status"] not in VALID_STATUS:
        raise HTTPException(400, "invalid status")
    if "period" in updates and updates["period"] not in VALID_PERIODS:
        raise HTTPException(400, "invalid period")
    if updates:
        sets = ", ".join(f"{k} = ?" for k in updates)
        state.db.execute(f"UPDATE recurring SET {sets} WHERE id = ?",
                         (*updates.values(), rec_id))
        audit.record(state.db, user["id"], "update", "recurring", rec_id, updates)
        state.data_changed()
    return state.db.query_one("SELECT * FROM recurring WHERE id = ?", (rec_id,))


@router.post("/check-balances")
def check_balances(state=Depends(require_unlocked), user=Depends(require_user)):
    """Manual trigger of the balance-threat check (also runs on a schedule)."""
    return recurring.check_balance_threats(state.db, state.alerts)
