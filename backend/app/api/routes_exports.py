from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.auth import require_current_user
from app.modules.exports.dianxiaomi_temu import EXPORT_MODE_CURATED, DianxiaomiExportError, export_dianxiaomi_temu_template
from app.modules.exports.product_attributes import (
    get_product_attribute_queue_summary,
    prepare_product_attribute_jobs,
    process_pending_product_attribute_jobs,
)

router = APIRouter(prefix="/api/exports", tags=["exports"])


class DianxiaomiTemuExportRequest(BaseModel):
    records: list[dict[str, Any]] = Field(default_factory=list)
    export_mode: str = Field(default=EXPORT_MODE_CURATED)


class ProductAttributePrepareRequest(BaseModel):
    records: list[dict[str, Any]] = Field(default_factory=list)
    process_now: bool = False


@router.post("/dianxiaomi/temu-semi-managed")
def export_dianxiaomi_temu(
    payload: DianxiaomiTemuExportRequest,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    user_id = str(current_user["id"])
    try:
        # Export is the last mile. Browser export already prepares and polls the
        # async attribute queue; this only prevents direct API calls from missing
        # queue records while keeping the Excel download responsive.
        prepare_product_attribute_jobs(payload.records, user_id=user_id, process_now=False)
        export_path = export_dianxiaomi_temu_template(
            payload.records,
            export_mode=payload.export_mode,
            user_id=user_id,
        )
    except DianxiaomiExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FileResponse(
        export_path,
        filename=export_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/dianxiaomi/product-attributes/prepare")
def prepare_dianxiaomi_product_attributes(
    payload: ProductAttributePrepareRequest,
    background_tasks: BackgroundTasks,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    user_id = str(current_user["id"])
    summary = prepare_product_attribute_jobs(payload.records, user_id=user_id, process_now=payload.process_now)
    if not payload.process_now and summary.get("queued", 0) > 0:
        background_tasks.add_task(process_pending_product_attribute_jobs, user_id=user_id, limit=50)
    return summary


@router.get("/dianxiaomi/product-attributes/status")
def dianxiaomi_product_attribute_status(
    current_user: dict[str, Any] = Depends(require_current_user),
):
    return get_product_attribute_queue_summary(user_id=str(current_user["id"]))
