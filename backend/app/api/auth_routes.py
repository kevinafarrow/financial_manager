from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .deps import SESSION_COOKIE, require_unlocked, require_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    new_password: str


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response,
          state=Depends(require_unlocked)):
    ip = request.client.host if request.client else None
    token = state.auth.login(body.username, body.password, ip=ip)
    if token is None:
        raise HTTPException(401, "invalid credentials")
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="strict",
        max_age=30 * 24 * 3600, path="/",
    )
    return state.auth.get_user_for_token(token)


@router.post("/logout")
def logout(request: Request, response: Response, state=Depends(require_unlocked),
           user=Depends(require_user)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        state.auth.logout(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(require_user)):
    return user


@router.post("/password")
def change_password(body: PasswordBody, state=Depends(require_unlocked),
                    user=Depends(require_user)):
    try:
        state.auth.change_password(user["id"], body.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}
