from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.database import (
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
):
    return {"items": list_link_list_records(include_deleted=include_deleted, limit=limit)}


@router.post("")
def save_link_record(payload: LinkListRecordRequest):
    try:
        return upsert_link_list_record(payload.record)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/batch")
def save_link_records(payload: LinkListRecordsRequest):
    try:
        return {"items": upsert_link_list_records(payload.records)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{record_id}")
def update_link_record(record_id: str, payload: LinkListRecordRequest):
    record = {**payload.record, "id": record_id}
    try:
        return upsert_link_list_record(record)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{record_id}")
def delete_link_record(record_id: str):
    deleted = soft_delete_link_list_record(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="链接记录不存在")
    return {"ok": True}
