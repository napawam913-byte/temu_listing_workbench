from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.modules.ai_gateway import store


RECENT_WINDOW_SECONDS = 60
CHANNEL_OPEN_SECONDS = 60
MIN_HEALTH_SCORE = 0.05
MAX_HEALTH_SCORE = 1.0


@dataclass
class RuntimeState:
    in_flight: int = 0
    health_score: float = MAX_HEALTH_SCORE
    consecutive_failures: int = 0
    recent_events: deque[tuple[float, bool]] = field(default_factory=deque)
    recent_starts: deque[float] = field(default_factory=deque)
    open_until: float = 0.0
    last_error: str = ""


_lock = threading.RLock()
_credential_states: dict[str, RuntimeState] = {}
_channel_states: dict[str, RuntimeState] = {}


def resolve_candidates(
    stage: str,
    *,
    task_type: str = "api",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    raw_candidates = store.resolve_candidates(stage, include_all=True)
    attempt_limit = store.resolve_route_attempt_limit(stage)
    now = time.time()
    scored: list[tuple[float, dict[str, Any]]] = []
    with _lock:
        prune_runtime_state(now)
        for candidate in raw_candidates:
            credential_id = candidate_key(candidate)
            channel_id = channel_key(candidate)
            credential_state = _credential_states.setdefault(credential_id, RuntimeState())
            channel_state = _channel_states.setdefault(channel_id, RuntimeState())
            if credential_state.open_until > now or channel_state.open_until > now:
                continue
            max_concurrency = max(0, int(candidate.get("maxConcurrency") or 0))
            if max_concurrency and credential_state.in_flight >= max_concurrency:
                continue
            rpm_limit = max(0, int(candidate.get("rpmLimit") or 0))
            if rpm_limit and len(credential_state.recent_starts) >= rpm_limit:
                continue
            score = candidate_score(candidate, credential_state, channel_state)
            scored.append((score, {**candidate, "taskType": task_type, "schedulerScore": score}))

    scored.sort(key=lambda item: item[0], reverse=True)
    candidates = [candidate for _score, candidate in scored]
    candidate_limit = limit or attempt_limit
    return candidates[:candidate_limit] if candidate_limit else candidates


def resolve_attempt_limit(stage: str) -> int:
    return store.resolve_route_attempt_limit(stage)


def acquire_candidate(
    stage: str,
    *,
    task_type: str = "api",
    excluded_credential_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    raw_candidates = store.resolve_candidates(stage, include_all=True)
    now = time.time()
    excluded = excluded_credential_ids or set()
    best_score = float("-inf")
    best_candidate: dict[str, Any] | None = None
    with _lock:
        prune_runtime_state(now)
        for candidate in raw_candidates:
            credential_id = candidate_key(candidate)
            if credential_id in excluded:
                continue
            channel_id = channel_key(candidate)
            credential_state = _credential_states.setdefault(credential_id, RuntimeState())
            channel_state = _channel_states.setdefault(channel_id, RuntimeState())
            if credential_state.open_until > now or channel_state.open_until > now:
                continue
            max_concurrency = max(0, int(candidate.get("maxConcurrency") or 0))
            if max_concurrency and credential_state.in_flight >= max_concurrency:
                continue
            rpm_limit = max(0, int(candidate.get("rpmLimit") or 0))
            if rpm_limit and len(credential_state.recent_starts) >= rpm_limit:
                continue
            score = candidate_score(candidate, credential_state, channel_state)
            if score > best_score:
                best_score = score
                best_candidate = {**candidate, "taskType": task_type, "schedulerScore": score}

        if best_candidate:
            mark_attempt_started(best_candidate, now)
    return best_candidate


def begin_attempt(candidate: dict[str, Any]) -> dict[str, str]:
    credential_id = candidate_key(candidate)
    channel_id = channel_key(candidate)
    with _lock:
        now = time.time()
        mark_attempt_started(candidate, now)
    return {"credentialId": credential_id, "channelId": channel_id}


def mark_attempt_started(candidate: dict[str, Any], now: float) -> None:
    credential_id = candidate_key(candidate)
    channel_id = channel_key(candidate)
    credential_state = _credential_states.setdefault(credential_id, RuntimeState())
    channel_state = _channel_states.setdefault(channel_id, RuntimeState())
    credential_state.in_flight += 1
    channel_state.in_flight += 1
    credential_state.recent_starts.append(now)
    channel_state.recent_starts.append(now)
    prune_starts(credential_state, now)
    prune_starts(channel_state, now)


def finish_attempt(
    candidate: dict[str, Any],
    *,
    success: bool,
    error_message: str = "",
    latency_ms: int | None = None,
) -> None:
    credential_id = candidate_key(candidate)
    channel_id = channel_key(candidate)
    should_close_persisted = False
    should_open_persisted = False
    should_open_channel = False
    with _lock:
        now = time.time()
        credential_state = _credential_states.setdefault(credential_id, RuntimeState())
        channel_state = _channel_states.setdefault(channel_id, RuntimeState())
        credential_state.in_flight = max(0, credential_state.in_flight - 1)
        channel_state.in_flight = max(0, channel_state.in_flight - 1)
        credential_state.recent_events.append((now, success))
        channel_state.recent_events.append((now, success))
        prune_events(credential_state, now)
        prune_events(channel_state, now)

        if success:
            should_close_persisted = credential_state.consecutive_failures > 0 or credential_state.health_score < MAX_HEALTH_SCORE
            credential_state.consecutive_failures = 0
            credential_state.health_score = min(MAX_HEALTH_SCORE, credential_state.health_score + 0.08)
            channel_state.consecutive_failures = 0
            channel_state.health_score = min(MAX_HEALTH_SCORE, channel_state.health_score + 0.03)
        else:
            severity = classify_error(error_message)
            credential_state.consecutive_failures += 1
            channel_state.consecutive_failures += 1
            credential_state.last_error = error_message
            channel_state.last_error = error_message
            credential_state.health_score = max(MIN_HEALTH_SCORE, credential_state.health_score * health_multiplier(severity))
            channel_state.health_score = max(MIN_HEALTH_SCORE, channel_state.health_score * channel_health_multiplier(severity))
            if should_open_credential(credential_state, severity):
                credential_state.open_until = now + credential_open_seconds(severity)
                should_open_persisted = True
            if should_open_channel_runtime(channel_state):
                channel_state.open_until = now + CHANNEL_OPEN_SECONDS
                should_open_channel = True

    if success and should_close_persisted:
        store.record_attempt_result(candidate, success=True, latency_ms=latency_ms)
    elif not success:
        store.record_attempt_result(candidate, success=False, error_message=error_message, latency_ms=latency_ms)
    if should_open_channel:
        try:
            store.set_circuit_state(
                scope_type="channel",
                scope_id=channel_id,
                state="open",
                stage=str(candidate.get("stage") or ""),
                model="",
                updated_by="scheduler",
                error_message=error_message,
            )
        except Exception:
            pass


def candidate_score(candidate: dict[str, Any], credential_state: RuntimeState, channel_state: RuntimeState) -> float:
    weight = max(1, int(candidate.get("weight") or 1))
    priority = max(1, int(candidate.get("priority") or 100))
    max_concurrency = max(0, int(candidate.get("maxConcurrency") or 0))
    load_ratio = credential_state.in_flight / max_concurrency if max_concurrency else min(1.0, credential_state.in_flight / 100)
    priority_factor = 1 + min(1.0, 100 / priority) * 0.05
    weight_factor = 1 + min(10, weight) * 0.03
    load_penalty = 1 + load_ratio * 50 + credential_state.in_flight * 2 + channel_state.in_flight * 0.05
    return (
        credential_state.health_score
        * channel_state.health_score
        * priority_factor
        * weight_factor
        / load_penalty
    )


def classify_error(error_message: str) -> str:
    text = str(error_message or "").lower()
    if "invalid_api_key" in text or "api key is invalid" in text or "http 401" in text or "permission denied" in text:
        return "auth"
    if "429" in text or "rate limit" in text or "quota" in text or "too frequent" in text:
        return "rate_limit"
    if "timeout" in text or "timed out" in text or "502" in text or "503" in text or "504" in text:
        return "transient"
    if "remote end closed" in text or "connection reset" in text or "connection aborted" in text:
        return "transient"
    if "http 400" in text or "bad request" in text or "invalid_request" in text or "content policy" in text:
        return "bad_request"
    return "error"


def health_multiplier(severity: str) -> float:
    if severity == "auth":
        return 0.05
    if severity == "rate_limit":
        return 0.45
    if severity == "transient":
        return 0.65
    if severity == "bad_request":
        return 0.9
    return 0.75


def channel_health_multiplier(severity: str) -> float:
    if severity == "auth":
        return 0.95
    if severity == "rate_limit":
        return 0.75
    if severity == "transient":
        return 0.65
    if severity == "bad_request":
        return 1.0
    return 0.85


def should_open_credential(state: RuntimeState, severity: str) -> bool:
    if severity == "auth":
        return True
    if severity in {"rate_limit", "transient"}:
        return True
    if severity == "bad_request":
        return False
    if state.consecutive_failures >= 3:
        return True
    failures, total = recent_failure_counts(state)
    return total >= 5 and failures / total >= 0.6


def should_open_channel_runtime(state: RuntimeState) -> bool:
    failures, total = recent_failure_counts(state)
    if total < 5:
        return False
    return failures / total >= 0.6 and state.consecutive_failures >= 3


def credential_open_seconds(severity: str) -> int:
    if severity == "auth":
        return 86400
    if severity == "rate_limit":
        return 90
    if severity == "transient":
        return 30
    return 120


def recent_failure_counts(state: RuntimeState) -> tuple[int, int]:
    total = len(state.recent_events)
    failures = sum(1 for _timestamp, success in state.recent_events if not success)
    return failures, total


def prune_runtime_state(now: float) -> None:
    for state in list(_credential_states.values()) + list(_channel_states.values()):
        prune_events(state, now)
        prune_starts(state, now)
        if state.open_until and state.open_until <= now:
            state.open_until = 0.0


def prune_events(state: RuntimeState, now: float) -> None:
    while state.recent_events and now - state.recent_events[0][0] > RECENT_WINDOW_SECONDS:
        state.recent_events.popleft()


def prune_starts(state: RuntimeState, now: float) -> None:
    while state.recent_starts and now - state.recent_starts[0] > 60:
        state.recent_starts.popleft()


def candidate_key(candidate: dict[str, Any]) -> str:
    return str(candidate.get("credentialId") or "")


def channel_key(candidate: dict[str, Any]) -> str:
    return str(candidate.get("channelId") or "")


def runtime_snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "credentials": {
                key: state_to_api(value)
                for key, value in sorted(_credential_states.items())
            },
            "channels": {
                key: state_to_api(value)
                for key, value in sorted(_channel_states.items())
            },
        }


def state_to_api(state: RuntimeState) -> dict[str, Any]:
    failures, total = recent_failure_counts(state)
    return {
        "inFlight": state.in_flight,
        "healthScore": round(state.health_score, 4),
        "consecutiveFailures": state.consecutive_failures,
        "recentFailureCount": failures,
        "recentTotalCount": total,
        "recentStartCount": len(state.recent_starts),
        "openUntil": state.open_until,
        "lastError": state.last_error,
    }
