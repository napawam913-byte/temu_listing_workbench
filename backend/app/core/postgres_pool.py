from __future__ import annotations

import os
from contextlib import contextmanager
from threading import Lock
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional runtime dependency
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

try:
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover - allows boot before requirements are installed
    ConnectionPool = None  # type: ignore[assignment]


_pools: dict[str, Any] = {}
_pools_lock = Lock()
_runtime_config_lock = Lock()
_runtime_min_size: int | None = None
_runtime_max_size: int | None = None
_runtime_connect_timeout_seconds: int | None = None


def bounded_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    return bounded_int(os.getenv(name, str(default)), default, minimum=minimum, maximum=maximum)


def apply_postgres_pool_runtime_config(
    *,
    min_size: Any | None = None,
    max_size: Any | None = None,
    connect_timeout_seconds: Any | None = None,
) -> dict[str, int]:
    min_value = bounded_int(min_size, db_pool_min_size(), minimum=0, maximum=50)
    max_value = bounded_int(max_size, db_pool_max_size(), minimum=1, maximum=200)
    if max_value < min_value:
        max_value = min_value or 1
    timeout_value = bounded_int(
        connect_timeout_seconds,
        db_connect_timeout_seconds(),
        minimum=1,
        maximum=60,
    )

    global _runtime_min_size, _runtime_max_size, _runtime_connect_timeout_seconds
    with _runtime_config_lock:
        _runtime_min_size = min_value
        _runtime_max_size = max_value
        _runtime_connect_timeout_seconds = timeout_value

    close_all_postgres_pools()
    return postgres_pool_runtime_config()


def postgres_pool_runtime_config() -> dict[str, int]:
    return {
        "minSize": db_pool_min_size(),
        "maxSize": db_pool_max_size(),
        "connectTimeoutSeconds": db_connect_timeout_seconds(),
    }


def db_pool_min_size() -> int:
    if _runtime_min_size is not None:
        return _runtime_min_size
    return int_env("DB_POOL_MIN_SIZE", 1, minimum=0, maximum=50)


def db_pool_max_size() -> int:
    if _runtime_max_size is not None:
        return _runtime_max_size
    return int_env("DB_POOL_MAX_SIZE", 5, minimum=1, maximum=200)


def db_connect_timeout_seconds() -> int:
    if _runtime_connect_timeout_seconds is not None:
        return _runtime_connect_timeout_seconds
    return int_env("POSTGRES_CONNECT_TIMEOUT_SECONDS", 3, minimum=1, maximum=60)


def connection_kwargs() -> dict[str, Any]:
    return {"row_factory": dict_row, "connect_timeout": db_connect_timeout_seconds()}


def require_psycopg() -> None:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed; run python -m pip install -r requirements.txt")


def get_pool(url: str) -> Any:
    require_psycopg()
    clean_url = str(url or "").strip()
    if not clean_url:
        raise RuntimeError("PostgreSQL database URL is required")
    if ConnectionPool is None:
        return None

    with _pools_lock:
        pool = _pools.get(clean_url)
        if pool is None:
            pool = ConnectionPool(
                conninfo=clean_url,
                kwargs=connection_kwargs(),
                min_size=db_pool_min_size(),
                max_size=db_pool_max_size(),
                open=True,
                name="temu-workbench-postgres",
            )
            _pools[clean_url] = pool
        return pool


@contextmanager
def get_postgres_connection(url: str) -> Iterator[Any]:
    require_psycopg()
    clean_url = str(url or "").strip()
    if not clean_url:
        raise RuntimeError("PostgreSQL database URL is required")

    pool = get_pool(clean_url)
    if pool is None:
        with psycopg.connect(clean_url, **connection_kwargs()) as conn:
            yield conn
        return

    with pool.connection() as conn:
        yield conn


def close_all_postgres_pools() -> None:
    with _pools_lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        try:
            pool.close()
        except Exception:
            continue
