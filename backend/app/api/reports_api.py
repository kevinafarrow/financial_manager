from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import reports
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/pulse")
def pulse(state=Depends(require_unlocked), user=Depends(require_user)):
    p = reports.weekly_pulse(state.db)
    if p is None:
        raise HTTPException(404, "no budget for the current month")
    p["message"] = reports.pulse_message(p)
    return p


@router.get("/monthly/{month}")
def monthly(month: str, state=Depends(require_unlocked), user=Depends(require_user)):
    return reports.monthly_report(state.db, month)


@router.post("/send-pulse")
def send_pulse(state=Depends(require_unlocked), user=Depends(require_user)):
    sent = reports.send_weekly_pulse(state.db, state.alerts, state.config.base_url)
    return {"sent": sent}


@router.get("/alerts")
def alert_history(state=Depends(require_unlocked), user=Depends(require_user)):
    return state.db.query(
        "SELECT * FROM alert_log ORDER BY created_at DESC, id DESC LIMIT 100")
