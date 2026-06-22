from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from app.modules.visual_generation.clients import get_runtime_setting


class SharedConcurrencyError(RuntimeError):
    pass


@dataclass
class RuntimeSlot:
    user_id: str
    task_type: str
    task_id: str
    started_at: float


_lock = threading.RLock()
_runtime_slots: dict[str, RuntimeSlot] = {}


def user_concurrency_limit() -> int:
    try:
        value = int(float(get_runtime_setting("VISUAL_USER_CONCURRENCY_LIMIT", "5")))
    except ValueError:
        value = 5
    return max(0, min(value, 100))


def running_runtime_slot_count(user_id: str) -> int:
    clean_user_id = str(user_id or "").strip()
    if not clean_user_id:
        return 0
    with _lock:
        return sum(1 for slot in _runtime_slots.values() if slot.user_id == clean_user_id)


def assert_user_concurrency_available(
    user_id: str,
    *,
    persistent_running_count: int = 0,
    exclude_slot_id: str | None = None,
) -> None:
    limit = user_concurrency_limit()
    if limit <= 0:
        return
    runtime_count = running_runtime_slot_count_excluding(user_id, exclude_slot_id=exclude_slot_id)
    total_count = max(0, int(persistent_running_count or 0)) + runtime_count
    if total_count >= limit:
        raise SharedConcurrencyError(f"当前成员已有 {total_count} 个模型任务正在运行，成员并发上限为 {limit}")


def running_runtime_slot_count_excluding(user_id: str, *, exclude_slot_id: str | None = None) -> int:
    clean_user_id = str(user_id or "").strip()
    clean_exclude = str(exclude_slot_id or "").strip()
    if not clean_user_id:
        return 0
    with _lock:
        return sum(
            1
            for slot_id, slot in _runtime_slots.items()
            if slot.user_id == clean_user_id and (not clean_exclude or slot_id != clean_exclude)
        )


def acquire_runtime_slot(user_id: str, *, task_type: str, task_id: str) -> str:
    clean_user_id = str(user_id or "").strip()
    clean_task_type = str(task_type or "task").strip() or "task"
    clean_task_id = str(task_id or "").strip() or f"{clean_task_type}_{int(time.time() * 1000)}"
    slot_id = f"{clean_task_type}:{clean_user_id}:{clean_task_id}:{threading.get_ident()}"
    with _lock:
        _runtime_slots[slot_id] = RuntimeSlot(
            user_id=clean_user_id,
            task_type=clean_task_type,
            task_id=clean_task_id,
            started_at=time.time(),
        )
    return slot_id


def release_runtime_slot(slot_id: str) -> None:
    clean_slot_id = str(slot_id or "").strip()
    if not clean_slot_id:
        return
    with _lock:
        _runtime_slots.pop(clean_slot_id, None)


def wait_for_user_concurrency_slot(
    user_id: str,
    *,
    task_type: str,
    task_id: str,
    persistent_running_count: Callable[[], int] | None = None,
    poll_seconds: float = 0.5,
) -> str:
    slot_id = ""
    while True:
        running_count = persistent_running_count() if persistent_running_count is not None else 0
        with _lock:
            try:
                assert_user_concurrency_available(
                    user_id,
                    persistent_running_count=running_count,
                    exclude_slot_id=slot_id or None,
                )
            except SharedConcurrencyError:
                pass
            else:
                if slot_id:
                    return slot_id
                return acquire_runtime_slot(user_id, task_type=task_type, task_id=task_id)
        time.sleep(max(0.1, float(poll_seconds or 0.5)))


@contextmanager
def user_concurrency_slot(
    user_id: str,
    *,
    task_type: str,
    task_id: str,
    persistent_running_count: Callable[[], int] | None = None,
    poll_seconds: float = 0.5,
) -> Iterator[None]:
    slot_id = wait_for_user_concurrency_slot(
        user_id,
        task_type=task_type,
        task_id=task_id,
        persistent_running_count=persistent_running_count,
        poll_seconds=poll_seconds,
    )
    try:
        yield
    finally:
        release_runtime_slot(slot_id)
