from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.core import config as app_config
from app.modules.visual_generation.clients import get_runtime_setting

try:  # pragma: no cover - optional runtime dependency
    import redis
except Exception:  # pragma: no cover - Redis is optional in local dev
    redis = None


class VisualQueueUnavailable(RuntimeError):
    pass


def queue_bool_setting(key: str, default: bool) -> bool:
    value = get_runtime_setting(key, "1" if default else "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


def queue_int_setting(key: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(float(get_runtime_setting(key, str(default))))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def redis_url() -> str:
    return get_runtime_setting("REDIS_URL", app_config.REDIS_URL).strip()


def queue_name() -> str:
    return get_runtime_setting("VISUAL_QUEUE_NAME", app_config.VISUAL_QUEUE_NAME).strip() or "visual:tasks:queue"


def retry_queue_name() -> str:
    configured = get_runtime_setting("VISUAL_QUEUE_RETRY_NAME", app_config.VISUAL_QUEUE_RETRY_NAME).strip()
    return configured or f"{queue_name()}:retry"


def dead_queue_name() -> str:
    configured = get_runtime_setting("VISUAL_QUEUE_DEAD_NAME", app_config.VISUAL_QUEUE_DEAD_NAME).strip()
    return configured or f"{queue_name()}:dead"


def redis_queue_enabled() -> bool:
    return bool(redis_url()) and queue_bool_setting("VISUAL_QUEUE_REDIS_ENABLED", False)


def redis_client():
    if redis is None:
        raise VisualQueueUnavailable("redis package is not installed")
    url = redis_url()
    if not url:
        raise VisualQueueUnavailable("REDIS_URL is not configured")
    return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=5)


def enqueue_visual_job(job: dict[str, Any]) -> bool:
    if not redis_queue_enabled():
        return False
    payload = dict(job)
    payload.setdefault("jobId", f"visual_job_{uuid.uuid4().hex}")
    payload.setdefault("queuedAt", int(time.time()))
    try:
        client = redis_client()
        client.rpush(queue_name(), json.dumps(payload, ensure_ascii=False))
        set_visual_progress(
            str(payload.get("taskId") or ""),
            {
                "state": "queued",
                "queue": queue_name(),
                "jobId": payload.get("jobId"),
                "queuedAt": payload.get("queuedAt"),
            },
        )
        return True
    except Exception:
        return False


def visual_queue_length() -> int | None:
    if not redis_queue_enabled():
        return None
    try:
        return int(redis_client().llen(queue_name()) or 0)
    except Exception:
        return None


def visual_retry_queue_length() -> int | None:
    if not redis_queue_enabled():
        return None
    try:
        return int(redis_client().zcard(retry_queue_name()) or 0)
    except Exception:
        return None


def visual_dead_queue_length() -> int | None:
    if not redis_queue_enabled():
        return None
    try:
        return int(redis_client().llen(dead_queue_name()) or 0)
    except Exception:
        return None


def pop_visual_job(*, timeout_seconds: int | None = None) -> dict[str, Any] | None:
    client = redis_client()
    timeout = timeout_seconds
    if timeout is None:
        timeout = queue_int_setting("VISUAL_QUEUE_POP_TIMEOUT_SECONDS", 1, minimum=0, maximum=30)
    item = client.blpop(queue_name(), timeout=timeout)
    if not item:
        return None
    _, raw_payload = item
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise VisualQueueUnavailable(f"invalid visual queue payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise VisualQueueUnavailable("invalid visual queue payload")
    return payload


def enqueue_visual_retry(job: dict[str, Any], *, error_message: str, delay_seconds: int | None = None) -> bool:
    if not redis_queue_enabled():
        return False
    payload = dict(job)
    payload["retryCount"] = int(payload.get("retryCount") or 0) + 1
    payload["lastError"] = error_message[:2000]
    payload["retryQueuedAt"] = int(time.time())
    delay = delay_seconds
    if delay is None:
        delay = queue_int_setting("VISUAL_QUEUE_RETRY_DELAY_SECONDS", 30, minimum=1, maximum=3600)
    payload["nextRetryAt"] = int(time.time()) + max(1, int(delay or 1))
    try:
        redis_client().zadd(retry_queue_name(), {json.dumps(payload, ensure_ascii=False): payload["nextRetryAt"]})
        set_visual_progress(
            str(payload.get("taskId") or ""),
            {
                "state": "retry_waiting",
                "queue": retry_queue_name(),
                "jobId": payload.get("jobId"),
                "retryCount": payload.get("retryCount"),
                "nextRetryAt": payload.get("nextRetryAt"),
                "error": payload.get("lastError"),
            },
        )
        return True
    except Exception:
        return False


def enqueue_visual_dead(job: dict[str, Any], *, error_message: str) -> bool:
    if not redis_queue_enabled():
        return False
    payload = dict(job)
    payload["deadAt"] = int(time.time())
    payload["lastError"] = error_message[:2000]
    try:
        redis_client().rpush(dead_queue_name(), json.dumps(payload, ensure_ascii=False))
        set_visual_progress(
            str(payload.get("taskId") or ""),
            {
                "state": "failed",
                "queue": dead_queue_name(),
                "jobId": payload.get("jobId"),
                "retryCount": payload.get("retryCount") or 0,
                "error": payload.get("lastError"),
            },
        )
        return True
    except Exception:
        return False


def promote_due_retry_jobs(*, limit: int = 50) -> int:
    if not redis_queue_enabled():
        return 0
    client = redis_client()
    retry_key = retry_queue_name()
    due_payloads = client.zrangebyscore(retry_key, "-inf", int(time.time()), start=0, num=max(1, limit))
    promoted = 0
    for raw_payload in due_payloads:
        pipe = client.pipeline()
        pipe.zrem(retry_key, raw_payload)
        pipe.rpush(queue_name(), raw_payload)
        results = pipe.execute()
        if results and int(results[0] or 0) > 0:
            promoted += 1
            try:
                payload = json.loads(raw_payload)
                set_visual_progress(
                    str(payload.get("taskId") or ""),
                    {
                        "state": "queued",
                        "queue": queue_name(),
                        "jobId": payload.get("jobId"),
                        "retryCount": payload.get("retryCount") or 0,
                    },
                )
            except Exception:
                continue
    return promoted


def visual_progress_key(task_id: str) -> str:
    return f"visual:task:{task_id}:progress"


def set_visual_progress(task_id: str, progress: dict[str, Any], *, ttl_seconds: int = 3600) -> None:
    if not task_id or not redis_queue_enabled():
        return
    try:
        client = redis_client()
        client.setex(visual_progress_key(task_id), ttl_seconds, json.dumps(progress, ensure_ascii=False))
    except Exception:
        return


def get_visual_progress(task_id: str) -> dict[str, Any]:
    if not task_id or not redis_queue_enabled():
        return {}
    try:
        raw = redis_client().get(visual_progress_key(task_id))
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def acquire_worker_lock() -> tuple[bool, str]:
    if not redis_queue_enabled():
        return False, ""
    token = f"worker_{uuid.uuid4().hex}"
    ttl = queue_int_setting("VISUAL_QUEUE_WORKER_LOCK_SECONDS", 3600, minimum=30, maximum=86400)
    try:
        ok = redis_client().set("visual:queue:worker-lock", token, nx=True, ex=ttl)
    except Exception:
        return False, ""
    return bool(ok), token


def release_worker_lock(token: str) -> None:
    if not token or not redis_queue_enabled():
        return
    script = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    end
    return 0
    """
    try:
        redis_client().eval(script, 1, "visual:queue:worker-lock", token)
    except Exception:
        return


def default_drain_max_jobs() -> int:
    return queue_int_setting("VISUAL_QUEUE_DRAIN_MAX_JOBS", 3, minimum=1, maximum=50)


def default_max_retries() -> int:
    return queue_int_setting("VISUAL_QUEUE_MAX_RETRIES", 2, minimum=0, maximum=10)


def default_retry_delay_seconds() -> int:
    return queue_int_setting("VISUAL_QUEUE_RETRY_DELAY_SECONDS", 30, minimum=1, maximum=3600)
