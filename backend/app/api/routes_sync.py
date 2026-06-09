from __future__ import annotations

import secrets
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile

from app.core.config import UPLOADS_DIR, WORKBENCH_SYNC_TOKEN, ensure_runtime_dirs
from app.modules.yunqi.collector import YunqiCollectorError, collect_yunqi_excel_file

router = APIRouter(prefix="/api/sync", tags=["sync"])


def ensure_sync_authorized(
    x_workbench_sync_token: str | None,
    authorization: str | None,
) -> None:
    expected_token = WORKBENCH_SYNC_TOKEN.strip()
    if not expected_token:
        return

    provided_token = clean_auth_token(x_workbench_sync_token) or clean_auth_token(authorization)
    if not provided_token or not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=401, detail="Invalid sync token")


def clean_auth_token(value: str | None) -> str:
    token = str(value or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


@router.post("/yunqi/file")
async def sync_yunqi_file(
    file: UploadFile = File(...),
    limit: int | None = Query(None, ge=1),
    rebuild_keywords: bool = Query(True),
    x_workbench_sync_token: str | None = Header(None, alias="X-Workbench-Sync-Token"),
    authorization: str | None = Header(None),
):
    ensure_sync_authorized(x_workbench_sync_token, authorization)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    try:
        saved_path = save_sync_upload(file)
        result = collect_yunqi_excel_file(
            saved_path,
            limit=limit,
            rebuild_keywords=rebuild_keywords,
        )
    except YunqiCollectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Yunqi sync failed: {exc}") from exc

    return {"ok": True, **result}


def save_sync_upload(file: UploadFile) -> Path:
    ensure_runtime_dirs()
    safe_filename = Path(file.filename or "yunqi_sync.xlsx").name
    saved_path = UPLOADS_DIR / f"sync_{uuid.uuid4().hex}_{safe_filename}"
    with saved_path.open("wb") as target:
        shutil.copyfileobj(file.file, target)
    return saved_path
