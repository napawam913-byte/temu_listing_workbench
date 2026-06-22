from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any, Iterator

try:
    import psycopg
except ImportError:  # pragma: no cover - optional runtime dependency
    psycopg = None  # type: ignore[assignment]

from app.core.postgres_pool import get_postgres_connection


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
        converted_sql, converted_params = convert_sql_params(sql, params)
        return CompatCursor(self._conn.execute(converted_sql, converted_params))

    def executemany(self, sql: str, params_seq: list[Any] | tuple[Any, ...]) -> CompatCursor:
        converted_items = [convert_sql_params(sql, params) for params in params_seq]
        converted_sql = converted_items[0][0] if converted_items else qmark_to_psycopg(sql)
        converted_params = [item[1] for item in converted_items]
        return CompatCursor(self._conn.executemany(converted_sql, converted_params))

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            clean_statement = statement.strip()
            if clean_statement:
                self._conn.execute(clean_statement)


def qmark_to_psycopg(sql: str) -> str:
    return sql.replace("?", "%s")


def convert_named_params(sql: str, params: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    values: list[Any] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        values.append(params[key])
        return "%s"

    converted_sql = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", replace, sql)
    return converted_sql, tuple(values)


def convert_sql_params(sql: str, params: Any) -> tuple[str, Any]:
    if isinstance(params, dict):
        return convert_named_params(sql, params)
    return qmark_to_psycopg(sql), normalize_params(params)


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
    with get_postgres_connection(url) as conn:
        yield CompatConnection(conn)
