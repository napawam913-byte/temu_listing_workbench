from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.api.auth import clean_bearer_token
from app.core.config import WORKBENCH_INGEST_TOKEN, WORKBENCH_SESSION_COOKIE_NAME
from app.core.database import get_user_by_session_token
from app.modules.ingestion.schemas import IngestRequest
from app.modules.ingestion.service import IngestError, ingest_records

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.post("")
def ingest_json(
    payload: IngestRequest,
    authorization: str | None = Header(None),
    x_workbench_ingest_token: str | None = Header(None, alias="X-Workbench-Ingest-Token"),
    session_cookie: str | None = Cookie(None, alias=WORKBENCH_SESSION_COOKIE_NAME),
):
    actor = resolve_ingest_actor(
        authorization=authorization,
        x_workbench_ingest_token=x_workbench_ingest_token,
        session_cookie=session_cookie,
    )
    try:
        return ingest_records(payload, user_id=actor.get("id"))
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"数据接收失败：{exc}") from exc


def resolve_ingest_actor(
    *,
    authorization: str | None,
    x_workbench_ingest_token: str | None,
    session_cookie: str | None,
) -> dict[str, Any]:
    expected_token = WORKBENCH_INGEST_TOKEN.strip()
    provided_ingest_token = clean_token(x_workbench_ingest_token) or clean_token(authorization)
    if expected_token and provided_ingest_token and secrets.compare_digest(provided_ingest_token, expected_token):
        return {"id": None, "username": "ingest-token", "role": "system"}

    session_token = str(session_cookie or "").strip() or clean_bearer_token(authorization)
    user = get_user_by_session_token(session_token)
    if user:
        return user

    if expected_token:
        raise HTTPException(status_code=401, detail="Invalid ingest token or session")
    raise HTTPException(status_code=401, detail="请先登录，或配置 WORKBENCH_INGEST_TOKEN 后使用机器人写入")


def clean_token(value: str | None) -> str:
    token = str(value or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token
