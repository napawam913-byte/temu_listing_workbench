from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

try:
    import psycopg
except ImportError as exc:  # pragma: no cover - depends on local env
    psycopg = None  # type: ignore[assignment]
    _PSYCOPG_IMPORT_ERROR = exc
else:
    _PSYCOPG_IMPORT_ERROR = None


SCRIPT_PATH = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_PATH.parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_SQLITE_PATH = BACKEND_DIR / "data" / "app.db"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sqlite_table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def sqlite_virtual_table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return {
        str(row["name"])
        for row in rows
        if str(row["sql"] or "").lstrip().upper().startswith("CREATE VIRTUAL TABLE")
    }


def migratable_table_names(conn: sqlite3.Connection) -> list[str]:
    all_tables = sqlite_table_names(conn)
    virtual_tables = sqlite_virtual_table_names(conn)
    skipped_prefixes = tuple(f"{name}_" for name in virtual_tables)
    return [
        table
        for table in all_tables
        if table not in virtual_tables and not table.startswith(skipped_prefixes)
    ]


def sqlite_table_info(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()


def postgres_type(sqlite_type: str | None) -> str:
    raw = (sqlite_type or "").strip().upper()
    if "INT" in raw:
        return "BIGINT"
    if any(token in raw for token in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE PRECISION"
    if "BLOB" in raw:
        return "BYTEA"
    if any(token in raw for token in ("NUM", "DEC", "BOOL")):
        return "NUMERIC"
    return "TEXT"


def postgres_default(default_value: Any) -> str:
    if default_value is None:
        return ""
    raw = str(default_value).strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper in {"NULL", "CURRENT_DATE", "CURRENT_TIME", "CURRENT_TIMESTAMP"}:
        return f" DEFAULT {upper}"
    if raw.startswith("(") and raw.endswith(")"):
        return f" DEFAULT {raw}"
    return f" DEFAULT {raw}"


def primary_key_columns(columns: Iterable[sqlite3.Row]) -> list[str]:
    pk_rows = [row for row in columns if int(row["pk"] or 0) > 0]
    return [str(row["name"]) for row in sorted(pk_rows, key=lambda row: int(row["pk"]))]


def create_table_sql(conn: sqlite3.Connection, table: str) -> str:
    columns = sqlite_table_info(conn, table)
    pk_columns = primary_key_columns(columns)
    single_pk = pk_columns[0] if len(pk_columns) == 1 else None
    definitions: list[str] = []
    for row in columns:
        name = str(row["name"])
        col_type = postgres_type(row["type"])
        not_null = " NOT NULL" if row["notnull"] and name not in pk_columns else ""
        default = postgres_default(row["dflt_value"])
        pk = " PRIMARY KEY" if single_pk == name else ""
        definitions.append(f"{quote_ident(name)} {col_type}{not_null}{default}{pk}")
    if len(pk_columns) > 1:
        pk_sql = ", ".join(quote_ident(name) for name in pk_columns)
        definitions.append(f"PRIMARY KEY ({pk_sql})")
    body = ",\n  ".join(definitions)
    return f"CREATE TABLE IF NOT EXISTS {quote_ident(table)} (\n  {body}\n)"


def sqlite_index_rows(conn: sqlite3.Connection, tables: set[str]) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT name, tbl_name, sql
        FROM sqlite_master
        WHERE type = 'index'
          AND sql IS NOT NULL
        ORDER BY name
        """
    ).fetchall()


def convert_index_sql(raw_sql: str) -> str:
    sql = raw_sql.strip().rstrip(";")
    sql = re.sub(
        r"^CREATE\s+UNIQUE\s+INDEX\s+",
        "CREATE UNIQUE INDEX IF NOT EXISTS ",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"^CREATE\s+INDEX\s+",
        "CREATE INDEX IF NOT EXISTS ",
        sql,
        flags=re.IGNORECASE,
    )
    return sql


def select_all_sql(table: str, columns: list[str]) -> str:
    column_sql = ", ".join(quote_ident(column) for column in columns)
    return f"SELECT {column_sql} FROM {quote_ident(table)}"


def upsert_sql(table: str, columns: list[str], pk_columns: list[str]) -> str:
    table_sql = quote_ident(table)
    column_sql = ", ".join(quote_ident(column) for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert = f"INSERT INTO {table_sql} ({column_sql}) VALUES ({placeholders})"
    if not pk_columns:
        return insert
    conflict = ", ".join(quote_ident(column) for column in pk_columns)
    update_columns = [column for column in columns if column not in pk_columns]
    if not update_columns:
        return f"{insert} ON CONFLICT ({conflict}) DO NOTHING"
    assignments = ", ".join(
        f"{quote_ident(column)} = EXCLUDED.{quote_ident(column)}" for column in update_columns
    )
    return f"{insert} ON CONFLICT ({conflict}) DO UPDATE SET {assignments}"


def chunked(rows: Iterable[tuple[Any, ...]], size: int) -> Iterable[list[tuple[Any, ...]]]:
    chunk: list[tuple[Any, ...]] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def table_count_sql(table: str) -> str:
    return f"SELECT COUNT(*) FROM {quote_ident(table)}"


def read_sqlite_rows(
    conn: sqlite3.Connection, table: str, columns: list[str]
) -> Iterable[tuple[Any, ...]]:
    for row in conn.execute(select_all_sql(table, columns)):
        yield tuple(row[column] for column in columns)


def drop_existing_tables(pg_conn: Any, tables: list[str]) -> None:
    with pg_conn.cursor() as cur:
        for table in reversed(tables):
            cur.execute(f"DROP TABLE IF EXISTS {quote_ident(table)} CASCADE")
    pg_conn.commit()


def migrate(
    *,
    sqlite_path: Path,
    postgres_url: str,
    reset: bool,
    batch_size: int,
    create_indexes: bool,
    only_tables: set[str] | None,
) -> None:
    if psycopg is None:
        raise RuntimeError(
            "Missing PostgreSQL driver. Run: python -m pip install \"psycopg[binary]>=3.2.3,<3.3.0\""
        ) from _PSYCOPG_IMPORT_ERROR
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    sqlite_conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    sqlite_conn.row_factory = sqlite3.Row
    try:
        tables = migratable_table_names(sqlite_conn)
        if only_tables is not None:
            tables = [table for table in tables if table in only_tables]
        if not tables:
            print("No migratable tables found.")
            return

        skipped_virtual = sorted(sqlite_virtual_table_names(sqlite_conn))
        if skipped_virtual:
            print("Skipping SQLite virtual tables:", ", ".join(skipped_virtual))

        with psycopg.connect(postgres_url) as pg_conn:
            if reset:
                print(f"Dropping {len(tables)} PostgreSQL tables before migration...")
                drop_existing_tables(pg_conn, tables)

            print(f"Creating {len(tables)} PostgreSQL tables...")
            with pg_conn.cursor() as cur:
                for table in tables:
                    cur.execute(create_table_sql(sqlite_conn, table))
            pg_conn.commit()

            print("Copying rows...")
            summary: list[tuple[str, int, int]] = []
            for table in tables:
                columns = [str(row["name"]) for row in sqlite_table_info(sqlite_conn, table)]
                pk_columns = primary_key_columns(sqlite_table_info(sqlite_conn, table))
                source_count = int(sqlite_conn.execute(table_count_sql(table)).fetchone()[0])
                if not columns:
                    summary.append((table, source_count, 0))
                    continue
                sql = upsert_sql(table, columns, pk_columns)
                copied = 0
                with pg_conn.cursor() as cur:
                    for batch in chunked(read_sqlite_rows(sqlite_conn, table, columns), batch_size):
                        cur.executemany(sql, batch)
                        copied += len(batch)
                pg_conn.commit()
                summary.append((table, source_count, copied))
                print(f"  {table}: {copied}/{source_count}")

            if create_indexes:
                print("Creating indexes...")
                table_set = set(tables)
                with pg_conn.cursor() as cur:
                    for row in sqlite_index_rows(sqlite_conn, table_set):
                        if str(row["tbl_name"]) not in table_set:
                            continue
                        cur.execute(convert_index_sql(str(row["sql"])))
                pg_conn.commit()

            print("Verifying row counts...")
            failures: list[str] = []
            with pg_conn.cursor() as cur:
                for table, source_count, _copied in summary:
                    cur.execute(table_count_sql(table))
                    target_count = int(cur.fetchone()[0])
                    print(f"  {table}: sqlite={source_count}, postgres={target_count}")
                    if reset and source_count != target_count:
                        failures.append(f"{table}: sqlite={source_count}, postgres={target_count}")
            if failures:
                raise RuntimeError("Row count mismatch after migration:\n" + "\n".join(failures))
            print("Migration completed.")
    finally:
        sqlite_conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate local SQLite app.db to PostgreSQL.")
    parser.add_argument(
        "--sqlite-path",
        default=str(DEFAULT_SQLITE_PATH),
        help="Source SQLite database path. Default: backend/data/app.db",
    )
    parser.add_argument(
        "--postgres-url",
        default="",
        help="PostgreSQL URL. If omitted, DATABASE_URL or POSTGRES_DATABASE_URL is read from .env/env.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop existing PostgreSQL tables before copying data.",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--no-indexes", action="store_true", help="Skip index creation.")
    parser.add_argument(
        "--only-table",
        action="append",
        dest="only_tables",
        help="Migrate only the named table. Can be passed multiple times.",
    )
    return parser.parse_args()


def main() -> int:
    load_env_file(DEFAULT_ENV_PATH)
    args = parse_args()
    postgres_url = (
        args.postgres_url
        or os.getenv("POSTGRES_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )
    if not postgres_url:
        print(
            "Missing PostgreSQL connection URL. Set DATABASE_URL in .env or pass --postgres-url.",
            file=sys.stderr,
        )
        return 2
    migrate(
        sqlite_path=Path(args.sqlite_path).expanduser().resolve(),
        postgres_url=postgres_url,
        reset=args.reset,
        batch_size=max(1, args.batch_size),
        create_indexes=not args.no_indexes,
        only_tables=set(args.only_tables) if args.only_tables else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
