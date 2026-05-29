from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.database import (
    create_sourcing_candidate_1688,
    delete_sourcing_candidate_1688,
    get_active_sourcing_product,
    list_sourcing_candidates_1688,
    set_active_sourcing_product,
)

router = APIRouter(prefix="/api/sourcing/1688", tags=["sourcing-1688"])


class ActiveSessionRequest(BaseModel):
    temu_product_id: str = Field(..., min_length=1)


class Capture1688Request(BaseModel):
    temu_product_id: str | None = None
    offer_id: str | None = None
    product_url: str
    title: str
    main_image_url: str | None = None
    price: float | None = None
    price_range: str | None = None
    moq: int | None = None
    shop_name: str | None = None
    shop_url: str | None = None
    sku_list: list[dict[str, Any]] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)
    captured_at: str | None = None


@router.post("/active-session")
def set_active_session(payload: ActiveSessionRequest):
    try:
        return set_active_sourcing_product(payload.temu_product_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/active-session")
def get_active_session():
    return get_active_sourcing_product() or {}


@router.post("/capture")
def capture_1688_candidate(payload: Capture1688Request):
    try:
        return create_sourcing_candidate_1688(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/candidates")
def get_1688_candidates(temu_product_id: str = Query(..., min_length=1)):
    return {"items": list_sourcing_candidates_1688(temu_product_id)}


@router.delete("/candidates/{candidate_id}")
def delete_1688_candidate(candidate_id: str):
    if not delete_sourcing_candidate_1688(candidate_id):
        raise HTTPException(status_code=404, detail="1688 采集货源不存在")
    return {"ok": True}
