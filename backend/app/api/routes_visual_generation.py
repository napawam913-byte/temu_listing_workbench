from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.auth import require_current_user
from app.modules.visual_generation.clients import VisualGenerationError
from app.modules.visual_generation.service import (
    TASK_STATUS_QUEUED,
    VisualTaskError,
    assert_visual_concurrency_available,
    create_visual_task,
    delete_visual_task,
    generate_visual_task,
    get_visual_task,
    get_visual_task_status_summary,
    list_visual_tasks,
    plan_visual_task,
    run_visual_task_pipeline,
    split_mother_image_stateless,
    split_visual_task,
    update_task_status,
)
from app.modules.visual_generation.queue import (
    dead_queue_name,
    enqueue_visual_job,
    queue_name,
    redis_queue_enabled,
    retry_queue_name,
    visual_dead_queue_length,
    visual_queue_length,
    visual_retry_queue_length,
)
from app.modules.visual_generation.worker import run_visual_queue_drain
from app.modules.visual_generation.splitter import GridSplitError

router = APIRouter(prefix="/api/visual", tags=["visual-generation"])


class VisualReferenceImageRef(BaseModel):
    url: str
    label: str | None = None
    role: str | None = None



def visual_ref_to_dict(item: VisualReferenceImageRef) -> dict[str, Any]:
    return item.model_dump() if hasattr(item, "model_dump") else item.dict()


class VisualTaskCreateRequest(BaseModel):
    record: dict[str, Any] = Field(default_factory=dict)
    linkRecordId: str | None = None
    productId: str | None = None
    mode: str | None = None
    layout: str | None = None
    requestedCount: int | None = Field(default=None, ge=1, le=9)
    sourceImageRef: str | None = None
    referenceImageRefs: list[VisualReferenceImageRef] | None = None


class VisualTaskPlanRequest(BaseModel):
    sourceImageRef: str | None = None
    referenceImageRefs: list[VisualReferenceImageRef] | None = None
    allowShortLabels: bool | None = None
    analysisModel: str | None = None
    promptModel: str | None = None


class VisualTaskGenerateRequest(BaseModel):
    splitAfter: bool | None = None
    uploadToOss: bool | None = None
    imageModel: str | None = None
    imageSize: str | None = None
    useReferenceImage: bool | None = None


class VisualTaskRunRequest(VisualTaskPlanRequest, VisualTaskGenerateRequest):
    applyToLinkRecord: bool | None = True


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


@router.get("/queue/summary")
def get_visual_queue_summary(current_user: dict[str, Any] = Depends(require_current_user)):
    return {
        **get_visual_task_status_summary(user_id=str(current_user["id"])),
        "redisEnabled": redis_queue_enabled(),
        "redisQueueName": queue_name(),
        "redisQueueLength": visual_queue_length(),
        "redisRetryQueueName": retry_queue_name(),
        "redisRetryQueueLength": visual_retry_queue_length(),
        "redisDeadQueueName": dead_queue_name(),
        "redisDeadQueueLength": visual_dead_queue_length(),
    }


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
            reference_image_refs=[visual_ref_to_dict(item) for item in payload.referenceImageRefs or []],
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


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, current_user: dict[str, Any] = Depends(require_current_user)):
    try:
        delete_visual_task(task_id=task_id, user_id=current_user["id"])
    except VisualTaskError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}

@router.post("/tasks/{task_id}/plan")
def plan_task(
    task_id: str,
    payload: VisualTaskPlanRequest,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    try:
        assert_visual_concurrency_available(str(current_user["id"]), exclude_task_id=task_id)
        return {
            "item": plan_visual_task(
                task_id=task_id,
                user_id=current_user["id"],
                source_image_ref=payload.sourceImageRef,
                reference_image_refs=[visual_ref_to_dict(item) for item in payload.referenceImageRefs or []],
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
        assert_visual_concurrency_available(str(current_user["id"]), exclude_task_id=task_id)
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


@router.post("/tasks/{task_id}/run")
def run_task(
    task_id: str,
    payload: VisualTaskRunRequest,
    background_tasks: BackgroundTasks,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    user_id = str(current_user["id"])
    try:
        task = get_visual_task(task_id=task_id, user_id=user_id)
    except VisualTaskError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        assert_visual_concurrency_available(user_id, exclude_task_id=task_id)
    except VisualTaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    reference_image_refs = [visual_ref_to_dict(item) for item in payload.referenceImageRefs or []]
    run_payload = {
        "taskId": task_id,
        "userId": user_id,
        "sourceImageRef": payload.sourceImageRef,
        "referenceImageRefs": reference_image_refs,
        "allowShortLabels": payload.allowShortLabels,
        "analysisModel": payload.analysisModel,
        "promptModel": payload.promptModel,
        "splitAfter": True if payload.splitAfter is None else payload.splitAfter,
        "uploadToOss": True if payload.uploadToOss is None else payload.uploadToOss,
        "imageModel": payload.imageModel,
        "imageSize": payload.imageSize,
        "useReferenceImage": True if payload.useReferenceImage is None else payload.useReferenceImage,
        "applyToLinkRecord": True if payload.applyToLinkRecord is None else payload.applyToLinkRecord,
    }
    update_task_status(task_id, user_id, TASK_STATUS_QUEUED)
    queued_in_redis = enqueue_visual_job(run_payload)
    if queued_in_redis:
        background_tasks.add_task(run_visual_queue_drain)
        queue_backend = "redis"
    else:
        background_tasks.add_task(
            run_visual_task_pipeline,
            task_id=task_id,
            user_id=user_id,
            source_image_ref=payload.sourceImageRef,
            reference_image_refs=reference_image_refs,
            allow_short_labels=payload.allowShortLabels,
            analysis_model=payload.analysisModel,
            prompt_model=payload.promptModel,
            split_after=run_payload["splitAfter"],
            upload_to_oss=run_payload["uploadToOss"],
            image_model=payload.imageModel,
            image_size=payload.imageSize,
            use_reference_image=run_payload["useReferenceImage"],
            apply_to_link_record=run_payload["applyToLinkRecord"],
        )
        queue_backend = "background"
    return {"item": get_visual_task(task_id=task_id, user_id=user_id), "queued": True, "queueBackend": queue_backend}


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
