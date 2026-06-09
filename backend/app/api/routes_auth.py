from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from app.api.auth import clean_bearer_token, require_current_user
from app.core.config import (
    WORKBENCH_SESSION_COOKIE_MAX_AGE_SECONDS,
    WORKBENCH_SESSION_COOKIE_NAME,
    WORKBENCH_SESSION_COOKIE_SAMESITE,
    WORKBENCH_SESSION_COOKIE_SECURE,
)
from app.core.database import authenticate_user, create_user, create_user_session, revoke_user_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2)
    password: str = Field(..., min_length=6)
    display_name: str | None = None


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=WORKBENCH_SESSION_COOKIE_NAME,
        value=token,
        max_age=WORKBENCH_SESSION_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=WORKBENCH_SESSION_COOKIE_SECURE,
        samesite=WORKBENCH_SESSION_COOKIE_SAMESITE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=WORKBENCH_SESSION_COOKIE_NAME,
        path="/",
        secure=WORKBENCH_SESSION_COOKIE_SECURE,
        samesite=WORKBENCH_SESSION_COOKIE_SAMESITE,
    )


@router.post("/login")
def login(payload: LoginRequest, response: Response):
    user = authenticate_user(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    session = create_user_session(user["id"])
    set_session_cookie(response, session["token"])
    return {"user": session["user"]}


@router.post("/register")
def register(payload: RegisterRequest, response: Response):
    try:
        user = create_user(payload.username, payload.password, payload.display_name)
        session = create_user_session(user["id"])
        set_session_cookie(response, session["token"])
        return {"user": session["user"]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/me")
def me(current_user: dict[str, Any] = Depends(require_current_user)):
    return {"user": current_user}


@router.post("/logout")
def logout(
    response: Response,
    authorization: str | None = Header(None),
    session_cookie: str | None = Cookie(None, alias=WORKBENCH_SESSION_COOKIE_NAME),
):
    token = str(session_cookie or "").strip() or clean_bearer_token(authorization)
    revoke_user_session(token)
    clear_session_cookie(response)
    return {"ok": True}
