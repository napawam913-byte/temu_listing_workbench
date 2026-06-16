from __future__ import annotations

from typing import Any

from app.modules.visual_generation.queue import (
    acquire_worker_lock,
    default_drain_max_jobs,
    default_max_retries,
    default_retry_delay_seconds,
    enqueue_visual_dead,
    enqueue_visual_retry,
    pop_visual_job,
    promote_due_retry_jobs,
    redis_queue_enabled,
    release_worker_lock,
    set_visual_progress,
)
from app.modules.visual_generation.service import (
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
    mark_task_failed,
    mark_task_retry_waiting,
    run_visual_task_pipeline,
    update_task_status,
)


def run_visual_queue_drain(*, max_jobs: int | None = None) -> dict[str, int]:
    """Drain queued visual jobs.

    This is intentionally small and safe for the current FastAPI process. A
    later production worker can call the same function in a long-running loop.
    """
    acquired, token = acquire_worker_lock()
    if not acquired:
        return {"processed": 0, "skipped": 1, "failed": 0}

    processed = 0
    failed = 0
    promoted = 0
    try:
        limit = max_jobs if max_jobs is not None else default_drain_max_jobs()
        for _ in range(max(1, int(limit or 1))):
            promoted += promote_due_retry_jobs()
            job = pop_visual_job()
            if not job:
                break
            processed += 1
            try:
                run_visual_job(job)
            except Exception:
                failed += 1
        return {"processed": processed, "skipped": 0, "failed": failed, "promoted": promoted}
    finally:
        release_worker_lock(token)


def run_visual_job(job: dict[str, Any]) -> None:
    task_id = str(job.get("taskId") or "").strip()
    user_id = str(job.get("userId") or "").strip()
    if not task_id or not user_id:
        raise ValueError("visual job requires taskId and userId")

    set_visual_progress(task_id, {"state": "running", "jobId": job.get("jobId")})
    update_task_status(task_id, user_id, TASK_STATUS_RUNNING)
    try:
        run_visual_task_pipeline(
            task_id=task_id,
            user_id=user_id,
            source_image_ref=clean_optional(job.get("sourceImageRef")),
            reference_image_refs=job.get("referenceImageRefs") if isinstance(job.get("referenceImageRefs"), list) else [],
            allow_short_labels=job.get("allowShortLabels"),
            analysis_model=clean_optional(job.get("analysisModel")),
            prompt_model=clean_optional(job.get("promptModel")),
            split_after=job.get("splitAfter"),
            upload_to_oss=job.get("uploadToOss"),
            image_model=clean_optional(job.get("imageModel")),
            image_size=clean_optional(job.get("imageSize")),
            use_reference_image=job.get("useReferenceImage"),
            apply_to_link_record=bool(job.get("applyToLinkRecord", True)),
        )
        set_visual_progress(task_id, {"state": "completed", "jobId": job.get("jobId")})
    except Exception as exc:
        if should_retry_visual_job(job):
            retry_delay = default_retry_delay_seconds()
            mark_task_retry_waiting(task_id, user_id, str(exc))
            if enqueue_visual_retry(job, error_message=str(exc), delay_seconds=retry_delay):
                return

        mark_task_failed(task_id, user_id, str(exc))
        enqueue_visual_dead(job, error_message=str(exc))
        set_visual_progress(
            task_id,
            {"state": TASK_STATUS_FAILED, "jobId": job.get("jobId"), "error": str(exc)[:2000]},
        )
        raise


def clean_optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def should_retry_visual_job(job: dict[str, Any]) -> bool:
    if not redis_queue_enabled():
        return False
    try:
        retry_count = int(job.get("retryCount") or 0)
    except (TypeError, ValueError):
        retry_count = 0
    return retry_count < default_max_retries()
