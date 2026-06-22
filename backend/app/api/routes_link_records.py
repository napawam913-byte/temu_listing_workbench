from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.auth import require_current_user
from app.modules.link_records.postgres_store import (
    list_link_list_records,
    soft_delete_link_list_record,
    upsert_link_list_record,
    upsert_link_list_records,
)

router = APIRouter(prefix="/api/link-records", tags=["link-records"])


class LinkListRecordRequest(BaseModel):
    record: dict[str, Any] = Field(default_factory=dict)


class LinkListRecordsRequest(BaseModel):
    records: list[dict[str, Any]] = Field(default_factory=list)


@router.get("")
def get_link_records(
    include_deleted: bool = False,
    limit: int = Query(500, ge=1, le=1000),
    current_user: dict[str, Any] = Depends(require_current_user),
):
    return {"items": list_link_list_records(user_id=current_user["id"], include_deleted=include_deleted, limit=limit)}


@router.post("")
def save_link_record(payload: LinkListRecordRequest, current_user: dict[str, Any] = Depends(require_current_user)):
    try:
        return upsert_link_list_record(payload.record, user_id=current_user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/batch")
def save_link_records(payload: LinkListRecordsRequest, current_user: dict[str, Any] = Depends(require_current_user)):
    try:
        return {"items": upsert_link_list_records(payload.records, user_id=current_user["id"])}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{record_id}")
def update_link_record(
    record_id: str,
    payload: LinkListRecordRequest,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    record = {**payload.record, "id": record_id}
    try:
        return upsert_link_list_record(record, user_id=current_user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{record_id}")
def delete_link_record(record_id: str, current_user: dict[str, Any] = Depends(require_current_user)):
    deleted = soft_delete_link_list_record(record_id, user_id=current_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="链接记录不存在")
    return {"ok": True}
