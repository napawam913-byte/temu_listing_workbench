from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.auth import require_current_user
from app.modules.exports.dianxiaomi_export_tasks import (
    DianxiaomiExportTaskError,
    create_dianxiaomi_export_task,
    get_completed_export_task_path,
    get_dianxiaomi_export_task,
    list_dianxiaomi_export_tasks,
    run_dianxiaomi_export_task,
)
from app.modules.exports.dianxiaomi_temu import EXPORT_MODE_CURATED, DianxiaomiExportError, export_dianxiaomi_temu_template
from app.modules.exports.product_attributes import (
    get_product_attribute_queue_summary,
    prepare_product_attribute_jobs,
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


@router.post("/dianxiaomi/temu-semi-managed/tasks")
def create_dianxiaomi_temu_export_task(
    payload: DianxiaomiTemuExportRequest,
    background_tasks: BackgroundTasks,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    user_id = str(current_user["id"])
    try:
        task = create_dianxiaomi_export_task(
            payload.records,
            export_mode=payload.export_mode,
            user_id=user_id,
        )
    except (DianxiaomiExportTaskError, DianxiaomiExportError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_dianxiaomi_export_task, task_id=task["id"], user_id=user_id)
    return {"item": task, "queued": True}


@router.get("/dianxiaomi/temu-semi-managed/tasks")
def get_dianxiaomi_temu_export_tasks(
    limit: int = Query(50, ge=1, le=200),
    current_user: dict[str, Any] = Depends(require_current_user),
):
    return {"items": list_dianxiaomi_export_tasks(user_id=str(current_user["id"]), limit=limit)}


@router.get("/dianxiaomi/temu-semi-managed/tasks/{task_id}")
def get_dianxiaomi_temu_export_task(
    task_id: str,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    try:
        return {"item": get_dianxiaomi_export_task(task_id=task_id, user_id=str(current_user["id"]))}
    except DianxiaomiExportTaskError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/dianxiaomi/temu-semi-managed/tasks/{task_id}/download")
def download_dianxiaomi_temu_export_task(
    task_id: str,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    try:
        export_path = get_completed_export_task_path(task_id=task_id, user_id=str(current_user["id"]))
    except DianxiaomiExportTaskError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        export_path,
        filename=export_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/dianxiaomi/product-attributes/prepare")
def prepare_dianxiaomi_product_attributes(
    payload: ProductAttributePrepareRequest,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    user_id = str(current_user["id"])
    return prepare_product_attribute_jobs(payload.records, user_id=user_id, process_now=payload.process_now)


@router.get("/dianxiaomi/product-attributes/status")
def dianxiaomi_product_attribute_status(
    current_user: dict[str, Any] = Depends(require_current_user),
):
    return get_product_attribute_queue_summary(user_id=str(current_user["id"]))


@router.post("/dianxiaomi/product-attributes/status")
def dianxiaomi_product_attribute_status_for_records(
    payload: ProductAttributePrepareRequest,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    return get_product_attribute_queue_summary(user_id=str(current_user["id"]), records=payload.records)
