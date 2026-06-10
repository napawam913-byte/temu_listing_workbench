from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.auth import require_current_user
from app.modules.visual_generation.clients import VisualGenerationError
from app.modules.visual_generation.service import (
    VisualTaskError,
    create_visual_task,
    generate_visual_task,
    get_visual_task,
    list_visual_tasks,
    plan_visual_task,
    split_mother_image_stateless,
    split_visual_task,
)
from app.modules.visual_generation.splitter import GridSplitError

router = APIRouter(prefix="/api/visual", tags=["visual-generation"])


class VisualTaskCreateRequest(BaseModel):
    record: dict[str, Any] = Field(default_factory=dict)
    linkRecordId: str | None = None
    productId: str | None = None
    mode: str | None = None
    layout: str | None = None
    requestedCount: int | None = Field(default=None, ge=1, le=9)
    sourceImageRef: str | None = None


class VisualTaskPlanRequest(BaseModel):
    sourceImageRef: str | None = None
    allowShortLabels: bool | None = None
    analysisModel: str | None = None
    promptModel: str | None = None


class VisualTaskGenerateRequest(BaseModel):
    splitAfter: bool | None = None
    uploadToOss: bool | None = None
    imageModel: str | None = None
    imageSize: str | None = None
    useReferenceImage: bool | None = None


class VisualTaskSplitRequest(BaseModel):
    motherImageRef: str | None = None
    uploadToOss: bool | None = None
    targetSize: int | None = Field(default=None, ge=256, le=2048)
    safeMarginRatio: float | None = Field(default=None, ge=0, lt=0.25)
    outputFormat: str | None = None
    quality: int | None = Field(default=None, ge=1, le=100)
    sharpen: float | None = Field(default=None, ge=0, le=3)


class VisualSplitRequest(VisualTaskSplitRequest):
    motherImageRef: str
    layout: str | None = None


@router.get("/tasks")
def get_visual_tasks(
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    current_user: dict[str, Any] = Depends(require_current_user),
):
    return {"items": list_visual_tasks(user_id=current_user["id"], status=status, limit=limit)}


@router.post("/tasks")
def create_task(payload: VisualTaskCreateRequest, current_user: dict[str, Any] = Depends(require_current_user)):
    try:
        task = create_visual_task(
            user_id=current_user["id"],
            record=payload.record,
            link_record_id=payload.linkRecordId,
            product_id=payload.productId,
            mode=payload.mode,
            layout=payload.layout,
            requested_count=payload.requestedCount,
            source_image_ref=payload.sourceImageRef,
        )
    except (VisualTaskError, GridSplitError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": task}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, current_user: dict[str, Any] = Depends(require_current_user)):
    try:
        return {"item": get_visual_task(task_id=task_id, user_id=current_user["id"])}
    except VisualTaskError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/plan")
def plan_task(
    task_id: str,
    payload: VisualTaskPlanRequest,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    try:
        return {
            "item": plan_visual_task(
                task_id=task_id,
                user_id=current_user["id"],
                source_image_ref=payload.sourceImageRef,
                allow_short_labels=payload.allowShortLabels,
                analysis_model=payload.analysisModel,
                prompt_model=payload.promptModel,
            )
        }
    except VisualTaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VisualGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/generate")
def generate_task(
    task_id: str,
    payload: VisualTaskGenerateRequest,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    try:
        return {
            "item": generate_visual_task(
                task_id=task_id,
                user_id=current_user["id"],
                split_after=payload.splitAfter,
                upload_to_oss=payload.uploadToOss,
                image_model=payload.imageModel,
                image_size=payload.imageSize,
                use_reference_image=payload.useReferenceImage,
            )
        }
    except VisualTaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VisualGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/split")
def split_task(
    task_id: str,
    payload: VisualTaskSplitRequest,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    try:
        return {
            "item": split_visual_task(
                task_id=task_id,
                user_id=current_user["id"],
                mother_image_ref=payload.motherImageRef,
                upload_to_oss=payload.uploadToOss,
                target_size=payload.targetSize,
                safe_margin_ratio=payload.safeMarginRatio,
                output_format=payload.outputFormat,
                quality=payload.quality,
                sharpen=payload.sharpen,
            )
        }
    except (VisualTaskError, GridSplitError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/split")
def split_image(payload: VisualSplitRequest, current_user: dict[str, Any] = Depends(require_current_user)):
    try:
        return {
            "item": split_mother_image_stateless(
                user_id=current_user["id"],
                mother_image_ref=payload.motherImageRef,
                layout=payload.layout,
                upload_to_oss=payload.uploadToOss,
                target_size=payload.targetSize,
                safe_margin_ratio=payload.safeMarginRatio,
                output_format=payload.outputFormat,
                quality=payload.quality,
                sharpen=payload.sharpen,
            )
        }
    except (VisualTaskError, GridSplitError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
