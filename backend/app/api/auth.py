from __future__ import annotations

from typing import Any

from fastapi import Cookie, Depends, Header, HTTPException

from app.core.config import WORKBENCH_SESSION_COOKIE_NAME
from app.core.database import get_user_by_session_token

try:
    from psycopg import OperationalError as PostgresOperationalError
except Exception:  # pragma: no cover - psycopg is optional in local sqlite modes
    PostgresOperationalError = None  # type: ignore[assignment]


def clean_bearer_token(value: str | None) -> str:
    token = str(value or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def require_current_user(
    authorization: str | None = Header(None),
    session_cookie: str | None = Cookie(None, alias=WORKBENCH_SESSION_COOKIE_NAME),
) -> dict[str, Any]:
    token = str(session_cookie or "").strip() or clean_bearer_token(authorization)
    try:
        user = get_user_by_session_token(token)
    except Exception as exc:
        if PostgresOperationalError is not None and isinstance(exc, PostgresOperationalError):
            raise HTTPException(status_code=503, detail="数据库连接暂时不可用，请稍后重试") from exc
        raise
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def require_admin_user(current_user: dict[str, Any] = Depends(require_current_user)) -> dict[str, Any]:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user
