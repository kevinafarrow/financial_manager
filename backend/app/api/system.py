"""Setup / unlock / lock / status — the only endpoints that work while locked."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..vault import VaultError, WrongPassphrase
from .deps import get_state, require_user

router = APIRouter(prefix="/api/system", tags=["system"])


class SetupBody(BaseModel):
    passphrase: str = Field(min_length=10)
    username: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    password: str = Field(min_length=8)


class UnlockBody(BaseModel):
    passphrase: str


@router.get("/status")
def status(state=Depends(get_state)):
    return state.status()


@router.post("/setup")
def setup(body: SetupBody, state=Depends(get_state)):
    if state.vault.initialized:
        raise HTTPException(409, "already initialized")
    try:
        state.setup(body.passphrase, body.username, body.display_name, body.password)
    except (VaultError, ValueError) as e:
        raise HTTPException(400, str(e))
    return state.status()


@router.post("/unlock")
def unlock(body: UnlockBody, state=Depends(get_state)):
    if not state.vault.initialized:
        raise HTTPException(409, "not initialized; run setup")
    try:
        state.unlock(body.passphrase)
    except WrongPassphrase:
        raise HTTPException(403, "wrong passphrase")
    except VaultError as e:
        raise HTTPException(400, str(e))
    return state.status()


@router.post("/lock")
def lock(state=Depends(get_state), user=Depends(require_user)):
    state.lock()
    return state.status()
