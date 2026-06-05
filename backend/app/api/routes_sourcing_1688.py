from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.core.database import (
    assign_sourcing_material_1688,
    create_product_from_sourcing_material_1688,
    create_sourcing_material_1688,
    create_sourcing_candidate_1688,
    delete_sourcing_candidate_1688,
    delete_sourcing_material_1688,
    get_active_sourcing_product,
    list_sourcing_materials_1688,
    list_sourcing_candidates_1688,
    set_active_sourcing_product,
)
from app.modules.sourcing_1688.search_url import build_1688_search_url
from app.modules.sourcing_1688.image_search_api import (
    ImageSearchApiError,
    ImageSearchConfigError,
    search_1688_by_image_url,
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


class AssignMaterialRequest(BaseModel):
    temu_product_id: str = Field(..., min_length=1)


class ImageSearchRequest(BaseModel):
    image_url: str = Field(..., min_length=1)
    keyword: str | None = None
    limit: int = Field(default=20, ge=1, le=20)


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


@router.post("/materials")
def capture_1688_material(payload: Capture1688Request):
    try:
        return create_sourcing_material_1688(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/materials")
def get_1688_materials(limit: int = Query(100, ge=1, le=300)):
    return {"items": list_sourcing_materials_1688(limit)}


@router.post("/materials/{material_id}/assign")
def assign_1688_material(material_id: str, payload: AssignMaterialRequest):
    try:
        return assign_sourcing_material_1688(material_id, payload.temu_product_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/materials/{material_id}/add-to-products")
def add_1688_material_to_products(material_id: str):
    try:
        return create_product_from_sourcing_material_1688(material_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/search")
def open_1688_search(keyword: str = Query(..., min_length=1)):
    try:
        return RedirectResponse(build_1688_search_url(keyword), status_code=302)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/image-search")
def image_search_1688(payload: ImageSearchRequest):
    try:
        return search_1688_by_image_url(
            image_url=payload.image_url,
            keyword=payload.keyword or "",
            limit=payload.limit,
        )
    except ImageSearchConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ImageSearchApiError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/candidates/{candidate_id}")
def delete_1688_candidate(candidate_id: str):
    if not delete_sourcing_candidate_1688(candidate_id):
        raise HTTPException(status_code=404, detail="1688 采集货源不存在")
    return {"ok": True}


@router.delete("/materials/{material_id}")
def delete_1688_material(material_id: str):
    if not delete_sourcing_material_1688(material_id):
        raise HTTPException(status_code=404, detail="1688 采集素材不存在")
    return {"ok": True}
