"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from ..state import AppState

SESSION_COOKIE = "fm_session"


def get_state(request: Request) -> AppState:
    return request.app.state.appstate


def require_unlocked(state: AppState = Depends(get_state)) -> AppState:
    if not state.unlocked:
        raise HTTPException(status_code=423, detail="vault is locked")
    return state


def require_user(request: Request, state: AppState = Depends(require_unlocked)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    user = state.auth.get_user_for_token(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user
