from __future__ import annotations

import threading
import time
from typing import Any

from app.modules.visual_generation.queue import (
    acquire_worker_lock,
    default_drain_max_jobs,
    default_max_retries,
    default_retry_delay_seconds,
    enqueue_visual_deferred,
    enqueue_visual_dead,
    enqueue_visual_retry,
    pop_visual_job,
    promote_due_deferred_jobs,
    promote_due_retry_jobs,
    redis_queue_enabled,
    release_worker_lock,
    set_visual_progress,
)
from app.modules.visual_generation.service import (
    TASK_STATUS_FAILED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    VisualTaskError,
    assert_visual_concurrency_available,
    count_running_visual_tasks_global,
    mark_task_failed,
    mark_task_retry_waiting,
    run_visual_task_pipeline,
    update_task_status,
)

CONCURRENCY_WAIT_POLL_SECONDS = 3
_VISUAL_RUN_SLOT_LOCK = threading.Lock()


def run_visual_queue_drain(*, max_jobs: int | None = None, dispatch_async: bool = True) -> dict[str, int]:
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
            job = pop_visual_job()
            if not job:
                promoted += promote_due_deferred_jobs()
                job = pop_visual_job()
            if not job and not count_running_visual_tasks_global():
                promoted += promote_due_retry_jobs()
                job = pop_visual_job()
            if not job:
                break
            processed += 1
            if dispatch_async:
                start_visual_job_thread(job)
            else:
                try:
                    run_visual_job(job)
                except Exception:
                    failed += 1
        return {"processed": processed, "skipped": 0, "failed": failed, "promoted": promoted}
    finally:
        release_worker_lock(token)


def start_visual_job_thread(job: dict[str, Any]) -> threading.Thread:
    thread = threading.Thread(target=run_visual_job_and_refill, args=(dict(job),), name=f"visual-job-{job.get('taskId')}")
    thread.start()
    return thread


def run_visual_job_and_refill(job: dict[str, Any]) -> None:
    try:
        run_visual_job(job)
    except Exception:
        pass
    finally:
        run_visual_queue_drain(max_jobs=default_drain_max_jobs(), dispatch_async=True)


def run_visual_job(job: dict[str, Any]) -> None:
    task_id = str(job.get("taskId") or "").strip()
    user_id = str(job.get("userId") or "").strip()
    if not task_id or not user_id:
        raise ValueError("visual job requires taskId and userId")

    slot_ready, wait_reason = reserve_visual_run_slot(task_id, user_id, job_id=job.get("jobId"))
    if not slot_ready:
        if enqueue_visual_deferred(job, reason=wait_reason, delay_seconds=CONCURRENCY_WAIT_POLL_SECONDS):
            return
        waited_for_slot = wait_for_visual_run_slot(task_id, user_id, job_id=job.get("jobId"))
    else:
        waited_for_slot = False
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
            reuse_existing_outputs=bool(job.get("reuseExistingOutputs") or visual_job_retry_count(job) > 0),
        )
        set_visual_progress(
            task_id,
            {"state": "completed", "jobId": job.get("jobId"), "waitedForConcurrency": waited_for_slot},
        )
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


def wait_for_visual_run_slot(task_id: str, user_id: str, *, job_id: Any = None) -> bool:
    waited = False
    wait_reason = ""
    while True:
        with _VISUAL_RUN_SLOT_LOCK:
            try:
                assert_visual_concurrency_available(user_id, exclude_task_id=task_id)
            except VisualTaskError as exc:
                wait_reason = str(exc)
            else:
                update_task_status(task_id, user_id, TASK_STATUS_RUNNING, clear_error=True)
                set_visual_progress(
                    task_id,
                    {"state": TASK_STATUS_RUNNING, "jobId": job_id, "waitedForConcurrency": waited},
                )
                return waited

        waited = True
        update_task_status(task_id, user_id, TASK_STATUS_QUEUED, clear_error=True)
        set_visual_progress(
            task_id,
            {
                "state": TASK_STATUS_QUEUED,
                "jobId": job_id,
                "waitReason": wait_reason,
                "waitedForConcurrency": True,
            },
        )
        time.sleep(CONCURRENCY_WAIT_POLL_SECONDS)


def reserve_visual_run_slot(task_id: str, user_id: str, *, job_id: Any = None) -> tuple[bool, str]:
    with _VISUAL_RUN_SLOT_LOCK:
        try:
            assert_visual_concurrency_available(user_id, exclude_task_id=task_id)
        except VisualTaskError as exc:
            reason = str(exc)
            update_task_status(task_id, user_id, TASK_STATUS_QUEUED, clear_error=True)
            set_visual_progress(
                task_id,
                {
                    "state": TASK_STATUS_QUEUED,
                    "jobId": job_id,
                    "waitReason": reason,
                    "deferredForConcurrency": True,
                },
            )
            return False, reason

        update_task_status(task_id, user_id, TASK_STATUS_RUNNING, clear_error=True)
        set_visual_progress(
            task_id,
            {"state": TASK_STATUS_RUNNING, "jobId": job_id, "waitedForConcurrency": False},
        )
        return True, ""


def clean_optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def should_retry_visual_job(job: dict[str, Any]) -> bool:
    if not redis_queue_enabled():
        return False
    retry_count = visual_job_retry_count(job)
    return retry_count < default_max_retries()


def visual_job_retry_count(job: dict[str, Any]) -> int:
    try:
        return int(job.get("retryCount") or 0)
    except (TypeError, ValueError):
        return 0
