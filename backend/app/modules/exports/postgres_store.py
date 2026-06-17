from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional runtime dependency
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


class CompatRow(dict):
    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class CompatCursor:
    def __init__(self, cursor: Any):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)

    def fetchone(self) -> CompatRow | None:
        row = self._cursor.fetchone()
        return CompatRow(row) if row is not None else None

    def fetchall(self) -> list[CompatRow]:
        return [CompatRow(row) for row in self._cursor.fetchall()]


class CompatConnection:
    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: Any = None) -> CompatCursor:
        return CompatCursor(self._conn.execute(qmark_to_psycopg(sql), normalize_params(params)))

    def executemany(self, sql: str, params_seq: list[Any] | tuple[Any, ...]) -> CompatCursor:
        return CompatCursor(self._conn.executemany(qmark_to_psycopg(sql), [normalize_params(params) for params in params_seq]))

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            clean_statement = statement.strip()
            if clean_statement:
                self._conn.execute(clean_statement)


def qmark_to_psycopg(sql: str) -> str:
    return sql.replace("?", "%s")


def normalize_params(params: Any) -> Any:
    if params is None:
        return None
    if isinstance(params, list):
        return tuple(params)
    return params


def configured_url() -> str:
    return (
        os.getenv("EXPORTS_DATABASE_URL", "").strip()
        or os.getenv("POSTGRES_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )


@contextmanager
def get_export_connection() -> Iterator[CompatConnection]:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed; run python -m pip install -r requirements.txt")
    url = configured_url()
    if not url:
        raise RuntimeError("Exports PostgreSQL backend requires EXPORTS_DATABASE_URL, POSTGRES_DATABASE_URL, or DATABASE_URL")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield CompatConnection(conn)
