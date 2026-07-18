"""Runtime settings + encrypted secrets management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit, settings_store
from ..secrets_store import KNOWN_SECRETS
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SecretBody(BaseModel):
    name: str
    value: str = Field(min_length=1)


class ReceiptSettingsBody(BaseModel):
    receipt_token: str | None = None
    receipt_allowed_senders: list[str] | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    imap_username: str | None = None


@router.get("")
def get_settings(state=Depends(require_unlocked), user=Depends(require_user)):
    imap = settings_store.get(state.db, "imap", {})
    return {
        "secrets": state.secrets.status(),
        "receipt_token": settings_store.get(state.db, "receipt_token"),
        "receipt_allowed_senders": settings_store.get(
            state.db, "receipt_allowed_senders", []),
        "imap": {"host": imap.get("host"), "port": imap.get("port", 993),
                 "username": imap.get("username")},
        "models": {"chat": state.config.model_chat,
                   "categorize": state.config.model_categorize},
        "base_url": state.config.base_url,
    }


@router.put("/secrets")
def set_secret(body: SecretBody, state=Depends(require_unlocked),
               user=Depends(require_user)):
    if body.name not in KNOWN_SECRETS:
        raise HTTPException(400, f"unknown secret; expected one of {KNOWN_SECRETS}")
    state.secrets.set(body.name, body.value)
    audit.record(state.db, user["id"], "set_secret", "secret", None,
                 {"name": body.name})  # value never logged
    state.data_changed()
    return {"secrets": state.secrets.status()}


@router.delete("/secrets/{name}")
def delete_secret(name: str, state=Depends(require_unlocked),
                  user=Depends(require_user)):
    state.secrets.delete(name)
    audit.record(state.db, user["id"], "delete_secret", "secret", None, {"name": name})
    return {"secrets": state.secrets.status()}


@router.put("/receipts")
def set_receipt_settings(body: ReceiptSettingsBody, state=Depends(require_unlocked),
                         user=Depends(require_user)):
    if body.receipt_token is not None:
        settings_store.set_(state.db, "receipt_token", body.receipt_token)
    if body.receipt_allowed_senders is not None:
        settings_store.set_(state.db, "receipt_allowed_senders",
                            [s.strip().lower() for s in body.receipt_allowed_senders])
    imap = settings_store.get(state.db, "imap", {})
    for key, val in (("host", body.imap_host), ("port", body.imap_port),
                     ("username", body.imap_username)):
        if val is not None:
            imap[key] = val
    settings_store.set_(state.db, "imap", imap)
    audit.record(state.db, user["id"], "update", "receipt_settings", None)
    # re-wire the receipt service so imap changes take effect immediately
    state._wire_receipts()
    state.data_changed()
    return get_settings(state=state, user=user)
