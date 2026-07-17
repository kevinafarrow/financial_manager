from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

ACCOUNT_TYPES = {"checking", "savings", "credit", "investment", "mortgage", "benefits"}


class AccountBody(BaseModel):
    name: str = Field(min_length=1)
    institution: str = ""
    type: str
    kind: str = "ledger"
    currency: str = "USD"
    low_balance_threshold_cents: int | None = None
    staleness_days: int = 10


class AccountPatch(BaseModel):
    name: str | None = None
    institution: str | None = None
    type: str | None = None
    kind: str | None = None
    low_balance_threshold_cents: int | None = None
    staleness_days: int | None = None
    archived: bool | None = None


class SnapshotBody(BaseModel):
    as_of: str  # YYYY-MM-DD
    balance_cents: int


def _account_or_404(state, account_id: int) -> dict:
    row = state.db.query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if row is None:
        raise HTTPException(404, "account not found")
    return row


@router.get("")
def list_accounts(state=Depends(require_unlocked), user=Depends(require_user)):
    accounts = state.db.query("SELECT * FROM accounts ORDER BY archived, name")
    for a in accounts:
        a["latest_balance"] = state.db.query_one(
            "SELECT as_of, balance_cents FROM balance_snapshots "
            "WHERE account_id = ? ORDER BY as_of DESC, id DESC LIMIT 1", (a["id"],))
        a["last_activity"] = state.db.query_one(
            "SELECT max(posted_at) m FROM transactions WHERE account_id = ?", (a["id"],))["m"]
        a["tx_count"] = state.db.query_one(
            "SELECT count(*) c FROM transactions WHERE account_id = ?", (a["id"],))["c"]
    return accounts


@router.post("")
def create_account(body: AccountBody, state=Depends(require_unlocked),
                   user=Depends(require_user)):
    if body.type not in ACCOUNT_TYPES:
        raise HTTPException(400, f"type must be one of {sorted(ACCOUNT_TYPES)}")
    if body.kind not in ("ledger", "balance_only"):
        raise HTTPException(400, "kind must be 'ledger' or 'balance_only'")
    try:
        account_id = state.db.execute(
            "INSERT INTO accounts (name, institution, type, kind, currency, "
            "low_balance_threshold_cents, staleness_days) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (body.name, body.institution, body.type, body.kind, body.currency,
             body.low_balance_threshold_cents, body.staleness_days),
        )
    except Exception:
        raise HTTPException(409, "account name already exists")
    audit.record(state.db, user["id"], "create", "account", account_id, {"name": body.name})
    state.data_changed()
    return _account_or_404(state, account_id)


@router.patch("/{account_id}")
def update_account(account_id: int, body: AccountPatch, state=Depends(require_unlocked),
                   user=Depends(require_user)):
    _account_or_404(state, account_id)
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if "type" in updates and updates["type"] not in ACCOUNT_TYPES:
        raise HTTPException(400, "invalid type")
    if "kind" in updates and updates["kind"] not in ("ledger", "balance_only"):
        raise HTTPException(400, "invalid kind")
    if updates:
        if "archived" in updates:
            updates["archived"] = 1 if updates["archived"] else 0
        sets = ", ".join(f"{k} = ?" for k in updates)
        state.db.execute(f"UPDATE accounts SET {sets} WHERE id = ?",
                         (*updates.values(), account_id))
        audit.record(state.db, user["id"], "update", "account", account_id, updates)
        state.data_changed()
    return _account_or_404(state, account_id)


@router.post("/{account_id}/snapshots")
def add_snapshot(account_id: int, body: SnapshotBody, state=Depends(require_unlocked),
                 user=Depends(require_user)):
    _account_or_404(state, account_id)
    snap_id = state.db.execute(
        "INSERT INTO balance_snapshots (account_id, as_of, balance_cents, source) "
        "VALUES (?, ?, ?, 'manual')",
        (account_id, body.as_of, body.balance_cents),
    )
    audit.record(state.db, user["id"], "create", "balance_snapshot", snap_id,
                 {"account_id": account_id, "balance_cents": body.balance_cents})
    state.data_changed()
    return {"id": snap_id}


@router.get("/{account_id}/snapshots")
def list_snapshots(account_id: int, state=Depends(require_unlocked),
                   user=Depends(require_user)):
    _account_or_404(state, account_id)
    return state.db.query(
        "SELECT * FROM balance_snapshots WHERE account_id = ? ORDER BY as_of DESC",
        (account_id,))
