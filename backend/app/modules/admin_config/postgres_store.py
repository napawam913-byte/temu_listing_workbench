from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from threading import Lock
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional runtime dependency
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

from app.core import config as app_config
from app.core.secrets import decrypt_secret_value, encrypt_secret_value
from app.core.database import (
    clean_text,
    current_month_start_text,
    normalize_sensitive_term,
    parse_json_text,
    sensitive_term_row_to_api,
    user_usage_quota_to_api,
    utc_now_text,
)
from app.core.postgres_pool import get_postgres_connection
from app.modules.creative_generation.sensitive_terms_catalog import DEFAULT_SENSITIVE_TERMS

_api_usage_log_schema_ready = False
_app_settings_schema_ready = False
_sensitive_terms_schema_ready = False
_schema_lock = Lock()


def is_enabled() -> bool:
    return True


def configured_url() -> str:
    return (
        os.getenv("ADMIN_CONFIG_DATABASE_URL", "").strip()
        or os.getenv("POSTGRES_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )


@contextmanager
def get_pg_connection() -> Iterator[Any]:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed; run python -m pip install -r requirements.txt")
    url = configured_url()
    if not url:
        raise RuntimeError(
            "Admin config PostgreSQL backend requires ADMIN_CONFIG_DATABASE_URL, POSTGRES_DATABASE_URL, or DATABASE_URL"
        )
    with get_postgres_connection(url) as conn:
        yield conn


def pg_table_exists(conn: Any, table_name: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s) AS table_name", (f"public.{table_name}",)).fetchone()
    return bool(row and row["table_name"])


def ensure_admin_config_schema() -> None:
    now = utc_now_text()
    with get_pg_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'general',
                label TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                is_secret INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_api_settings (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                api_key TEXT NOT NULL DEFAULT '',
                base_url TEXT NOT NULL DEFAULT '',
                text_model TEXT NOT NULL DEFAULT '',
                image_model TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT
            )
            """
        )
        conn.execute(
            """
            UPDATE user_api_settings
            SET
                id = COALESCE(NULLIF(id, ''), md5(random()::text || clock_timestamp()::text)),
                api_key = COALESCE(api_key, ''),
                base_url = COALESCE(base_url, ''),
                text_model = COALESCE(text_model, ''),
                image_model = COALESCE(image_model, ''),
                enabled = COALESCE(enabled, 0),
                created_at = COALESCE(NULLIF(created_at, ''), %s),
                updated_at = COALESCE(NULLIF(updated_at, ''), %s)
            """,
            (now, now),
        )
        conn.execute(
            """
            DELETE FROM user_api_settings
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY user_id, channel_id
                            ORDER BY updated_at DESC, created_at DESC, id DESC
                        ) AS row_num
                    FROM user_api_settings
                ) ranked
                WHERE ranked.row_num > 1
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_user_api_settings_user_channel
                ON user_api_settings(user_id, channel_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_api_settings_user
                ON user_api_settings(user_id, enabled)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_usage_limits (
                user_id TEXT PRIMARY KEY,
                monthly_api_call_limit INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_usage_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                channel_id TEXT NOT NULL DEFAULT '',
                credential_id TEXT NOT NULL DEFAULT '',
                credential_name TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                api_type TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                call_count INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'success',
                source TEXT NOT NULL DEFAULT 'runtime-log',
                related_id TEXT,
                error_message TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_api_usage_logs_model
                ON api_usage_logs(provider, api_type, stage, model)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_api_usage_logs_created
                ON api_usage_logs(created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_api_usage_logs_user_channel
                ON api_usage_logs(user_id, channel_id, created_at)
            """
        )
        if pg_table_exists(conn, "api_usage_logs"):
            conn.execute("ALTER TABLE api_usage_logs ADD COLUMN IF NOT EXISTS credential_id TEXT NOT NULL DEFAULT ''")
            conn.execute("ALTER TABLE api_usage_logs ADD COLUMN IF NOT EXISTS credential_name TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_api_usage_logs_credential
                    ON api_usage_logs(credential_id, user_id, created_at)
                """
            )


def ensure_app_settings_schema() -> None:
    global _app_settings_schema_ready
    if _app_settings_schema_ready:
        return
    with _schema_lock:
        if _app_settings_schema_ready:
            return
        with get_pg_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'general',
                    label TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    is_secret INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT
                )
                """
            )
        _app_settings_schema_ready = True


def ensure_api_usage_log_schema() -> None:
    global _api_usage_log_schema_ready
    if _api_usage_log_schema_ready:
        return
    with _schema_lock:
        if _api_usage_log_schema_ready:
            return
        with get_pg_connection() as conn:
            ensure_api_usage_log_schema_on_connection(conn)
        _api_usage_log_schema_ready = True


def ensure_api_usage_log_schema_on_connection(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_usage_logs (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            channel_id TEXT NOT NULL DEFAULT '',
            credential_id TEXT NOT NULL DEFAULT '',
            credential_name TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            api_type TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            call_count INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'success',
            source TEXT NOT NULL DEFAULT 'runtime-log',
            related_id TEXT,
            error_message TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_api_usage_logs_model
            ON api_usage_logs(provider, api_type, stage, model)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_api_usage_logs_created
            ON api_usage_logs(created_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_api_usage_logs_user_channel
            ON api_usage_logs(user_id, channel_id, created_at)
        """
    )
    conn.execute("ALTER TABLE api_usage_logs ADD COLUMN IF NOT EXISTS credential_id TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE api_usage_logs ADD COLUMN IF NOT EXISTS credential_name TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_api_usage_logs_credential
            ON api_usage_logs(credential_id, user_id, created_at)
        """
    )


def app_setting_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    raw_value = str(row["value"] or "")
    value = decrypt_secret_value(raw_value) if bool(row["is_secret"]) else raw_value
    return {
        "key": row["key"],
        "value": value,
        "category": row["category"],
        "label": row["label"],
        "description": row["description"],
        "isSecret": bool(row["is_secret"]),
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
    }


def user_api_credential_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    api_key = decrypt_secret_value(str(row["api_key"] or ""))
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "channelId": row["channel_id"],
        "apiKey": api_key,
        "baseUrl": row["base_url"],
        "textModel": row["text_model"],
        "imageModel": row["image_model"],
        "enabled": bool(row["enabled"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
    }


def api_usage_log_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "channelId": row.get("channel_id") or "",
        "credentialId": row.get("credential_id") or "",
        "credentialName": row.get("credential_name") or "",
        "provider": row["provider"],
        "apiType": row["api_type"],
        "stage": row["stage"],
        "model": row["model"],
        "callCount": int(row["call_count"] or 0),
        "status": row["status"],
        "source": row["source"],
        "relatedId": row["related_id"],
        "errorMessage": row["error_message"],
        "metadata": parse_json_text(row["metadata_json"], {}),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def make_api_usage_summary_item(
    *,
    user_id: str = "",
    channel_id: str = "",
    credential_id: str = "",
    credential_name: str = "",
    provider: str,
    api_type: str,
    stage: str,
    model: str,
    call_count: int,
    success_count: int,
    failed_count: int,
    last_called_at: str | None,
    source: str,
    is_inferred: bool,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "id": "|".join(
            [
                user_id or "all-users",
                channel_id or "global",
                credential_id or "all-keys",
                provider or "unknown",
                api_type or "unknown",
                stage or "unknown",
                model or "unknown",
                source or "unknown",
            ]
        ),
        "userId": user_id,
        "channelId": channel_id,
        "credentialId": credential_id,
        "credentialName": credential_name,
        "provider": provider or "unknown",
        "apiType": api_type or "unknown",
        "stage": stage or "unknown",
        "model": model or "unknown",
        "callCount": int(call_count or 0),
        "successCount": int(success_count or 0),
        "failedCount": int(failed_count or 0),
        "lastCalledAt": last_called_at,
        "source": source or "runtime-log",
        "isInferred": is_inferred,
        "notes": notes,
    }


def merge_api_usage_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str, str, str, str, str, str], dict[str, Any]] = {}
    for item in items:
        key = (
            item.get("userId", ""),
            item.get("channelId", ""),
            item.get("credentialId", ""),
            item["provider"],
            item["apiType"],
            item["stage"],
            item["model"],
            item["source"],
        )
        current = merged.get(key)
        if not current:
            merged[key] = dict(item)
            continue
        current["callCount"] += item["callCount"]
        current["successCount"] += item["successCount"]
        current["failedCount"] += item["failedCount"]
        last_called_at = item.get("lastCalledAt")
        if last_called_at and (not current.get("lastCalledAt") or last_called_at > current["lastCalledAt"]):
            current["lastCalledAt"] = last_called_at
    return sorted(
        merged.values(),
        key=lambda item: (-int(item["callCount"] or 0), item["model"], item["stage"], item["source"]),
    )


def get_user_monthly_api_call_count(conn: Any, user_id: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(call_count), 0) AS call_count
        FROM api_usage_logs
        WHERE user_id = %s AND created_at >= %s
        """,
        (user_id, current_month_start_text()),
    ).fetchone()
    return int(row["call_count"] or 0) if row else 0


def get_user_usage_limit(user_id: str) -> dict[str, Any]:
    clean_user_id = clean_text(user_id)
    if not clean_user_id:
        raise ValueError("缺少成员 ID")
    ensure_admin_config_schema()
    with get_pg_connection() as conn:
        user_row = conn.execute("SELECT id FROM users WHERE id = %s", (clean_user_id,)).fetchone()
        if not user_row:
            raise ValueError("成员不存在")
        limit_row = conn.execute(
            "SELECT * FROM user_usage_limits WHERE user_id = %s",
            (clean_user_id,),
        ).fetchone()
        monthly_limit = int(limit_row["monthly_api_call_limit"] or 0) if limit_row else 0
        monthly_count = get_user_monthly_api_call_count(conn, clean_user_id)
    return user_usage_quota_to_api(
        user_id=clean_user_id,
        monthly_api_call_limit=monthly_limit,
        monthly_call_count=monthly_count,
        updated_at=limit_row["updated_at"] if limit_row else None,
    )


def upsert_user_usage_limit(
    *,
    user_id: str,
    monthly_api_call_limit: int,
    updated_by: str | None = None,
) -> dict[str, Any]:
    clean_user_id = clean_text(user_id)
    if not clean_user_id:
        raise ValueError("缺少成员 ID")
    ensure_admin_config_schema()
    limit = max(0, int(monthly_api_call_limit or 0))
    now = utc_now_text()
    with get_pg_connection() as conn:
        user_row = conn.execute("SELECT id FROM users WHERE id = %s", (clean_user_id,)).fetchone()
        if not user_row:
            raise ValueError("成员不存在")
        conn.execute(
            """
            INSERT INTO user_usage_limits (
                user_id, monthly_api_call_limit, created_at, updated_at, updated_by
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                monthly_api_call_limit = EXCLUDED.monthly_api_call_limit,
                updated_at = EXCLUDED.updated_at,
                updated_by = EXCLUDED.updated_by
            """,
            (clean_user_id, limit, now, now, clean_text(updated_by)),
        )
        monthly_count = get_user_monthly_api_call_count(conn, clean_user_id)
    return user_usage_quota_to_api(
        user_id=clean_user_id,
        monthly_api_call_limit=limit,
        monthly_call_count=monthly_count,
        updated_at=now,
    )


def assert_user_api_usage_allowed(user_id: str | None, requested_calls: int = 1) -> None:
    clean_user_id = clean_text(user_id)
    if not clean_user_id:
        return
    ensure_admin_config_schema()
    requested = max(1, int(requested_calls or 1))
    with get_pg_connection() as conn:
        row = conn.execute(
            "SELECT monthly_api_call_limit FROM user_usage_limits WHERE user_id = %s",
            (clean_user_id,),
        ).fetchone()
        limit = int(row["monthly_api_call_limit"] or 0) if row else 0
        if limit <= 0:
            return
        used = get_user_monthly_api_call_count(conn, clean_user_id)
    if used + requested > limit:
        raise ValueError(f"本月 API 用量已达上限：{used}/{limit}，请联系管理员调整额度")


def record_api_usage(
    *,
    provider: str,
    api_type: str,
    stage: str,
    model: str,
    user_id: str | None = None,
    channel_id: str | None = None,
    credential_id: str | None = None,
    credential_name: str | None = None,
    call_count: int = 1,
    status: str = "success",
    source: str = "runtime-log",
    related_id: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now_text()
    usage_id = uuid.uuid4().hex
    clean_status = str(status or "success").strip().lower()
    if clean_status not in {"success", "failed"}:
        clean_status = "success"
    ensure_api_usage_log_schema()
    with get_pg_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO api_usage_logs (
                id, user_id, channel_id, credential_id, credential_name, provider, api_type, stage, model, call_count, status, source,
                related_id, error_message, metadata_json, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                usage_id,
                clean_text(user_id),
                clean_text(channel_id),
                clean_text(credential_id),
                clean_text(credential_name),
                clean_text(provider),
                clean_text(api_type),
                clean_text(stage),
                clean_text(model) or "unknown",
                max(1, int(call_count or 1)),
                clean_status,
                clean_text(source) or "runtime-log",
                clean_text(related_id),
                clean_text(error_message)[:2000] or None,
                json.dumps(metadata or {}, ensure_ascii=False),
                now,
                now,
            ),
        ).fetchone()
    return api_usage_log_row_to_api(row)


def record_api_usage_safe(**kwargs: Any) -> None:
    try:
        record_api_usage(**kwargs)
    except Exception:
        return


def get_user_api_credentials_map(user_id: str) -> dict[str, dict[str, Any]]:
    clean_user_id = clean_text(user_id)
    if not clean_user_id:
        return {}
    with get_pg_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM user_api_settings
            WHERE user_id = %s
            ORDER BY channel_id ASC
            """,
            (clean_user_id,),
        ).fetchall()
    return {row["channel_id"]: user_api_credential_row_to_api(row) for row in rows}


def get_enabled_user_api_credential(user_id: str | None) -> dict[str, Any] | None:
    clean_user_id = clean_text(user_id)
    if not clean_user_id:
        return None
    with get_pg_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM user_api_settings
            WHERE user_id = %s AND enabled = 1 AND api_key != ''
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (clean_user_id,),
        ).fetchone()
    return user_api_credential_row_to_api(row) if row else None


def upsert_user_api_credential(
    *,
    user_id: str,
    channel_id: str,
    api_key: str | None = None,
    clear_api_key: bool = False,
    base_url: str | None = None,
    text_model: str | None = None,
    image_model: str | None = None,
    enabled: bool | None = None,
    updated_by: str | None = None,
) -> dict[str, Any]:
    clean_user_id = clean_text(user_id)
    clean_channel_id = clean_text(channel_id)
    if not clean_user_id:
        raise ValueError("缺少成员 ID")
    if not clean_channel_id:
        raise ValueError("缺少 API 渠道")

    now = utc_now_text()
    ensure_admin_config_schema()
    with get_pg_connection() as conn:
        user_row = conn.execute("SELECT id FROM users WHERE id = %s", (clean_user_id,)).fetchone()
        if not user_row:
            raise ValueError("成员不存在")

        existing = conn.execute(
            """
            SELECT *
            FROM user_api_settings
            WHERE user_id = %s AND channel_id = %s
            """,
            (clean_user_id, clean_channel_id),
        ).fetchone()

        next_api_key = decrypt_secret_value(str(existing["api_key"] or "")) if existing else ""
        if api_key is not None and clean_text(api_key):
            next_api_key = str(api_key or "").strip()
        elif clear_api_key:
            next_api_key = ""

        next_base_url = str(existing["base_url"] or "") if existing else ""
        next_text_model = str(existing["text_model"] or "") if existing else ""
        next_image_model = str(existing["image_model"] or "") if existing else ""
        if base_url is not None:
            next_base_url = str(base_url or "").strip().rstrip("/")
        if text_model is not None:
            next_text_model = str(text_model or "").strip()
        if image_model is not None:
            next_image_model = str(image_model or "").strip()

        next_enabled = int(bool(existing["enabled"])) if existing and enabled is None else (1 if enabled else 0)
        if next_enabled and not next_api_key:
            next_enabled = 0
        if next_enabled:
            conn.execute(
                """
                UPDATE user_api_settings
                SET enabled = 0, updated_at = %s, updated_by = %s
                WHERE user_id = %s AND channel_id != %s
                """,
                (now, clean_text(updated_by), clean_user_id, clean_channel_id),
            )

        row = conn.execute(
            """
            INSERT INTO user_api_settings (
                id, user_id, channel_id, api_key, base_url, text_model, image_model,
                enabled, created_at, updated_at, updated_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, channel_id) DO UPDATE SET
                api_key = EXCLUDED.api_key,
                base_url = EXCLUDED.base_url,
                text_model = EXCLUDED.text_model,
                image_model = EXCLUDED.image_model,
                enabled = EXCLUDED.enabled,
                updated_at = EXCLUDED.updated_at,
                updated_by = EXCLUDED.updated_by
            RETURNING *
            """,
            (
                existing["id"] if existing else uuid.uuid4().hex,
                clean_user_id,
                clean_channel_id,
                encrypt_secret_value(next_api_key, enabled=True),
                next_base_url,
                next_text_model,
                next_image_model,
                next_enabled,
                existing["created_at"] if existing else now,
                now,
                clean_text(updated_by),
            ),
        ).fetchone()
    return user_api_credential_row_to_api(row)


def get_app_settings_map() -> dict[str, dict[str, Any]]:
    ensure_app_settings_schema()
    with get_pg_connection() as conn:
        rows = conn.execute("SELECT * FROM app_settings").fetchall()
    return {row["key"]: app_setting_row_to_api(row) for row in rows}


def get_app_setting_value(key: str, default: str = "") -> str:
    clean_key = str(key or "").strip()
    if not clean_key:
        return default
    ensure_app_settings_schema()
    with get_pg_connection() as conn:
        row = conn.execute("SELECT value, is_secret FROM app_settings WHERE key = %s", (clean_key,)).fetchone()
    if not row:
        return default
    raw_value = str(row["value"] or "")
    return decrypt_secret_value(raw_value) if bool(row["is_secret"]) else raw_value


ADMIN_API_CHANNEL_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("chufan_ai", "https://api.aicoming.top/v1"),
)


def get_enabled_admin_api_channel_credential() -> dict[str, str] | None:
    for channel_id, default_base_url in ADMIN_API_CHANNEL_DEFAULTS:
        setting_prefix = f"AI_CHANNEL_{channel_id.upper()}"
        enabled = get_app_setting_value(f"{setting_prefix}_ENABLED", "0").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            continue
        api_key = get_app_setting_value(f"{setting_prefix}_API_KEY", "").strip()
        base_url = get_app_setting_value(f"{setting_prefix}_BASE_URL", default_base_url).strip().rstrip("/")
        text_model = get_app_setting_value(f"{setting_prefix}_TEXT_MODEL", "").strip()
        image_model = get_app_setting_value(f"{setting_prefix}_IMAGE_MODEL", "").strip()
        if api_key and base_url:
            return {
                "channelId": channel_id,
                "apiKey": api_key,
                "baseUrl": base_url,
                "textModel": text_model,
                "imageModel": image_model,
            }
    return None


def seed_default_sensitive_terms(conn: Any) -> None:
    now = utc_now_text()
    defaults = []
    for item in DEFAULT_SENSITIVE_TERMS:
        term = str(item["term"]).strip()
        normalized_term = normalize_sensitive_term(term)
        if not normalized_term:
            continue
        defaults.append(
            (
                normalized_term,
                uuid.uuid5(uuid.NAMESPACE_URL, f"sensitive-term:{normalized_term}").hex,
                term,
                item.get("language", "mixed"),
                item.get("category", "general"),
                item.get("severity", "block"),
                item.get("match_type", "contains"),
                item.get("replacement", ""),
                1 if item.get("enabled", True) else 0,
                item.get("source", "system"),
                item.get("notes"),
                now,
                now,
            ),
        )
    if not defaults:
        return
    existing_terms = {
        row["normalized_term"]
        for row in conn.execute(
            "SELECT normalized_term FROM sensitive_terms WHERE normalized_term = ANY(%s)",
            ([item[0] for item in defaults],),
        ).fetchall()
    }
    rows_to_insert = [
        (
            item[1],
            item[2],
            item[0],
            item[3],
            item[4],
            item[5],
            item[6],
            item[7],
            item[8],
            item[9],
            item[10],
            item[11],
            item[12],
        )
        for item in defaults
        if item[0] not in existing_terms
    ]
    if not rows_to_insert:
        return
    conn.executemany(
        """
        INSERT INTO sensitive_terms (
            id, term, normalized_term, language, category, severity, match_type,
            replacement, enabled, source, notes, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows_to_insert,
    )


def ensure_sensitive_terms_schema() -> None:
    global _sensitive_terms_schema_ready
    if _sensitive_terms_schema_ready:
        return
    with _schema_lock:
        if _sensitive_terms_schema_ready:
            return
        with get_pg_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sensitive_terms (
                    id TEXT PRIMARY KEY,
                    term TEXT NOT NULL,
                    normalized_term TEXT NOT NULL UNIQUE,
                    language TEXT NOT NULL DEFAULT 'mixed',
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'block',
                    match_type TEXT NOT NULL DEFAULT 'contains',
                    replacement TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT 'system',
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("ALTER TABLE sensitive_terms ADD COLUMN IF NOT EXISTS normalized_term TEXT NOT NULL DEFAULT ''")
            conn.execute("ALTER TABLE sensitive_terms ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'mixed'")
            conn.execute("ALTER TABLE sensitive_terms ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general'")
            conn.execute("ALTER TABLE sensitive_terms ADD COLUMN IF NOT EXISTS severity TEXT NOT NULL DEFAULT 'block'")
            conn.execute("ALTER TABLE sensitive_terms ADD COLUMN IF NOT EXISTS match_type TEXT NOT NULL DEFAULT 'contains'")
            conn.execute("ALTER TABLE sensitive_terms ADD COLUMN IF NOT EXISTS replacement TEXT NOT NULL DEFAULT ''")
            conn.execute("ALTER TABLE sensitive_terms ADD COLUMN IF NOT EXISTS enabled INTEGER NOT NULL DEFAULT 1")
            conn.execute("ALTER TABLE sensitive_terms ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'system'")
            conn.execute("ALTER TABLE sensitive_terms ADD COLUMN IF NOT EXISTS notes TEXT")
            conn.execute("ALTER TABLE sensitive_terms ADD COLUMN IF NOT EXISTS created_at TEXT NOT NULL DEFAULT ''")
            conn.execute("ALTER TABLE sensitive_terms ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                UPDATE sensitive_terms
                SET normalized_term = lower(regexp_replace(COALESCE(term, ''), '\\s+', ' ', 'g'))
                WHERE normalized_term = ''
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sensitive_terms_enabled ON sensitive_terms(enabled)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sensitive_terms_category ON sensitive_terms(category)")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sensitive_terms_normalized_unique ON sensitive_terms(normalized_term)"
            )
            seed_default_sensitive_terms(conn)
        _sensitive_terms_schema_ready = True


def list_enabled_sensitive_terms() -> list[dict[str, Any]]:
    ensure_sensitive_terms_schema()
    ensure_admin_config_schema()
    with get_pg_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM sensitive_terms
            WHERE enabled = 1
            ORDER BY length(term) DESC, term ASC
            """
        ).fetchall()
    return [sensitive_term_row_to_api(row) for row in rows]


def list_sensitive_terms(*, enabled: bool | None = None, category: str | None = None) -> list[dict[str, Any]]:
    ensure_sensitive_terms_schema()
    clauses: list[str] = []
    params: list[Any] = []
    if enabled is not None:
        clauses.append("enabled = %s")
        params.append(1 if enabled else 0)
    if category:
        clauses.append("category = %s")
        params.append(category)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_pg_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM sensitive_terms
            {where_sql}
            ORDER BY category ASC, length(term) DESC, term ASC
            """,
            params,
        ).fetchall()
    return [sensitive_term_row_to_api(row) for row in rows]


def upsert_app_setting(
    *,
    key: str,
    value: str,
    category: str = "general",
    label: str = "",
    description: str = "",
    is_secret: bool = False,
    updated_by: str | None = None,
) -> dict[str, Any]:
    clean_key = str(key or "").strip()
    if not clean_key:
        raise ValueError("缺少配置 key")
    now = utc_now_text()
    stored_value = encrypt_secret_value(str(value or ""), enabled=is_secret)
    ensure_admin_config_schema()
    with get_pg_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO app_settings (
                key, value, category, label, description, is_secret, created_at, updated_at, updated_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                category = EXCLUDED.category,
                label = EXCLUDED.label,
                description = EXCLUDED.description,
                is_secret = EXCLUDED.is_secret,
                updated_at = EXCLUDED.updated_at,
                updated_by = EXCLUDED.updated_by
            RETURNING *
            """,
            (
                clean_key,
                stored_value,
                str(category or "general"),
                str(label or ""),
                str(description or ""),
                1 if is_secret else 0,
                now,
                now,
                updated_by,
            ),
        ).fetchone()
    return app_setting_row_to_api(row)


def migrate_plaintext_secrets() -> int:
    migrated_count = 0
    now = utc_now_text()
    with get_pg_connection() as conn:
        setting_rows = conn.execute(
            """
            SELECT key, value
            FROM app_settings
            WHERE is_secret = 1 AND value != '' AND value NOT LIKE 'enc:v1:%'
            """
        ).fetchall()
        for row in setting_rows:
            conn.execute(
                """
                UPDATE app_settings
                SET value = %s, updated_at = %s, updated_by = %s
                WHERE key = %s
                """,
                (encrypt_secret_value(str(row["value"] or ""), enabled=True), now, "secret-migration", row["key"]),
            )
            migrated_count += 1

        credential_rows = conn.execute(
            """
            SELECT id, api_key
            FROM user_api_settings
            WHERE api_key != '' AND api_key NOT LIKE 'enc:v1:%'
            """
        ).fetchall()
        for row in credential_rows:
            conn.execute(
                """
                UPDATE user_api_settings
                SET api_key = %s, updated_at = %s, updated_by = %s
                WHERE id = %s
                """,
                (encrypt_secret_value(str(row["api_key"] or ""), enabled=True), now, "secret-migration", row["id"]),
            )
            migrated_count += 1
    return migrated_count


def read_setting_values(conn: Any | None = None) -> dict[str, str]:
    if conn is not None:
        rows = conn.execute("SELECT key, value, is_secret FROM app_settings").fetchall()
        return {
            row["key"]: decrypt_secret_value(str(row["value"] or "")) if bool(row["is_secret"]) else str(row["value"] or "")
            for row in rows
        }
    with get_pg_connection() as pg_conn:
        rows = pg_conn.execute("SELECT key, value, is_secret FROM app_settings").fetchall()
    return {
        row["key"]: decrypt_secret_value(str(row["value"] or "")) if bool(row["is_secret"]) else str(row["value"] or "")
        for row in rows
    }


def runtime_setting_value(settings: dict[str, str], key: str, fallback_key: str, default: str) -> str:
    value = settings.get(key) or os.getenv(key, "").strip()
    if value:
        return value
    if fallback_key:
        value = (
            settings.get(fallback_key)
            or os.getenv(fallback_key, "").strip()
            or str(getattr(app_config, fallback_key, "") or "")
        )
        if value:
            return value
    return str(getattr(app_config, key, "") or default).strip() or default


def summarize_api_usage_by_user_with_limits(conn: Any) -> list[dict[str, Any]]:
    month_start = current_month_start_text()
    rows = conn.execute(
        """
        SELECT
            users.id AS user_id,
            users.username,
            users.display_name,
            users.role,
            users.manager_user_id,
            manager.username AS manager_username,
            manager.display_name AS manager_display_name,
            teams.id AS team_id,
            teams.name AS team_name,
            COALESCE(SUM(logs.call_count), 0) AS call_count,
            COALESCE(SUM(CASE WHEN logs.status = 'success' THEN logs.call_count ELSE 0 END), 0) AS success_count,
            COALESCE(SUM(CASE WHEN logs.status = 'failed' THEN logs.call_count ELSE 0 END), 0) AS failed_count,
            COALESCE(month_usage.monthly_call_count, 0) AS monthly_call_count,
            COALESCE(limits.monthly_api_call_limit, 0) AS monthly_api_call_limit,
            limits.updated_at AS usage_limit_updated_at,
            MAX(logs.updated_at) AS last_called_at
        FROM users
        LEFT JOIN api_usage_logs AS logs ON logs.user_id = users.id
        LEFT JOIN users AS manager ON manager.id = users.manager_user_id
        LEFT JOIN teams ON teams.admin_user_id = CASE
            WHEN users.role = 'admin' THEN users.id
            ELSE users.manager_user_id
        END
        LEFT JOIN (
            SELECT user_id, COALESCE(SUM(call_count), 0) AS monthly_call_count
            FROM api_usage_logs
            WHERE created_at >= %s
            GROUP BY user_id
        ) AS month_usage ON month_usage.user_id = users.id
        LEFT JOIN user_usage_limits AS limits ON limits.user_id = users.id
        GROUP BY
            users.id, users.username, users.display_name, users.role, users.manager_user_id,
            manager.username, manager.display_name, teams.id, teams.name,
            month_usage.monthly_call_count, limits.monthly_api_call_limit, limits.updated_at
        ORDER BY call_count DESC, users.created_at ASC
        """,
        (month_start,),
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        quota = user_usage_quota_to_api(
            user_id=clean_text(row["user_id"]),
            monthly_api_call_limit=int(row["monthly_api_call_limit"] or 0),
            monthly_call_count=int(row["monthly_call_count"] or 0),
            updated_at=row["usage_limit_updated_at"],
        )
        items.append(
            {
                "userId": clean_text(row["user_id"]),
                "username": clean_text(row["username"]) or "system",
                "displayName": clean_text(row["display_name"]) or clean_text(row["username"]) or "system",
                "role": clean_text(row["role"]) or "system",
                "managerId": clean_text(row["manager_user_id"]),
                "managerName": clean_text(row["manager_display_name"]) or clean_text(row["manager_username"]),
                "teamId": clean_text(row["team_id"]),
                "teamName": clean_text(row["team_name"]) or "unassigned",
                "callCount": int(row["call_count"] or 0),
                "successCount": int(row["success_count"] or 0),
                "failedCount": int(row["failed_count"] or 0),
                "lastCalledAt": row["last_called_at"],
                **quota,
            }
        )
    return items


def summarize_api_usage_by_team(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            CASE
                WHEN users.role = 'admin' THEN users.id
                ELSE users.manager_user_id
            END AS admin_user_id,
            admin.username AS admin_username,
            admin.display_name AS admin_display_name,
            teams.id AS team_id,
            teams.name AS team_name,
            COALESCE(SUM(logs.call_count), 0) AS call_count,
            COALESCE(SUM(CASE WHEN logs.status = 'success' THEN logs.call_count ELSE 0 END), 0) AS success_count,
            COALESCE(SUM(CASE WHEN logs.status = 'failed' THEN logs.call_count ELSE 0 END), 0) AS failed_count,
            COUNT(DISTINCT logs.user_id) AS user_count,
            MAX(logs.updated_at) AS last_called_at
        FROM api_usage_logs AS logs
        LEFT JOIN users ON users.id = logs.user_id
        LEFT JOIN users AS admin ON admin.id = CASE
            WHEN users.role = 'admin' THEN users.id
            ELSE users.manager_user_id
        END
        LEFT JOIN teams ON teams.admin_user_id = admin.id
        GROUP BY
            CASE WHEN users.role = 'admin' THEN users.id ELSE users.manager_user_id END,
            admin.username, admin.display_name, teams.id, teams.name
        ORDER BY call_count DESC
        """
    ).fetchall()
    return [
        {
            "teamId": clean_text(row["team_id"]) or "unassigned",
            "teamName": clean_text(row["team_name"]) or "未归属团队",
            "adminUserId": clean_text(row["admin_user_id"]),
            "adminName": clean_text(row["admin_display_name"]) or clean_text(row["admin_username"]) or "未归属",
            "userCount": int(row["user_count"] or 0),
            "callCount": int(row["call_count"] or 0),
            "successCount": int(row["success_count"] or 0),
            "failedCount": int(row["failed_count"] or 0),
            "lastCalledAt": row["last_called_at"],
        }
        for row in rows
    ]


def summarize_api_usage_by_channel(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            channel_id,
            COALESCE(SUM(call_count), 0) AS call_count,
            COALESCE(SUM(CASE WHEN status = 'success' THEN call_count ELSE 0 END), 0) AS success_count,
            COALESCE(SUM(CASE WHEN status = 'failed' THEN call_count ELSE 0 END), 0) AS failed_count,
            COUNT(DISTINCT user_id) AS user_count,
            MAX(updated_at) AS last_called_at
        FROM api_usage_logs
        GROUP BY channel_id
        ORDER BY call_count DESC
        """
    ).fetchall()
    return [
        {
            "channelId": clean_text(row["channel_id"]) or "global",
            "userCount": int(row["user_count"] or 0),
            "callCount": int(row["call_count"] or 0),
            "successCount": int(row["success_count"] or 0),
            "failedCount": int(row["failed_count"] or 0),
            "lastCalledAt": row["last_called_at"],
        }
        for row in rows
    ]


def summarize_api_usage_by_credential(conn: Any) -> list[dict[str, Any]]:
    parent_rows = conn.execute(
        """
        SELECT
            credential_id,
            credential_name,
            channel_id,
            COALESCE(SUM(call_count), 0) AS call_count,
            COALESCE(SUM(CASE WHEN status = 'success' THEN call_count ELSE 0 END), 0) AS success_count,
            COALESCE(SUM(CASE WHEN status = 'failed' THEN call_count ELSE 0 END), 0) AS failed_count,
            COUNT(DISTINCT NULLIF(user_id, '')) AS user_count,
            MAX(updated_at) AS last_called_at
        FROM api_usage_logs
        WHERE COALESCE(credential_id, '') != ''
        GROUP BY credential_id, credential_name, channel_id
        ORDER BY call_count DESC
        """
    ).fetchall()

    user_rows = conn.execute(
        """
        SELECT
            logs.credential_id,
            logs.credential_name,
            logs.channel_id,
            logs.user_id,
            users.username,
            users.display_name,
            users.role,
            COALESCE(SUM(logs.call_count), 0) AS call_count,
            COALESCE(SUM(CASE WHEN logs.status = 'success' THEN logs.call_count ELSE 0 END), 0) AS success_count,
            COALESCE(SUM(CASE WHEN logs.status = 'failed' THEN logs.call_count ELSE 0 END), 0) AS failed_count,
            MAX(logs.updated_at) AS last_called_at
        FROM api_usage_logs AS logs
        LEFT JOIN users ON users.id = logs.user_id
        WHERE COALESCE(logs.credential_id, '') != ''
        GROUP BY
            logs.credential_id,
            logs.credential_name,
            logs.channel_id,
            logs.user_id,
            users.username,
            users.display_name,
            users.role
        ORDER BY call_count DESC
        """
    ).fetchall()
    children_by_credential: dict[str, list[dict[str, Any]]] = {}
    for row in user_rows:
        credential_id = clean_text(row["credential_id"])
        if not credential_id:
            continue
        children_by_credential.setdefault(credential_id, []).append(
            {
                "credentialId": credential_id,
                "credentialName": clean_text(row["credential_name"]) or credential_id,
                "channelId": clean_text(row["channel_id"]) or "global",
                "userId": clean_text(row["user_id"]) or "system",
                "username": clean_text(row["username"]) or clean_text(row["user_id"]) or "system",
                "displayName": clean_text(row["display_name"]) or clean_text(row["username"]) or clean_text(row["user_id"]) or "System",
                "role": clean_text(row["role"]),
                "userCount": 1 if clean_text(row["user_id"]) else 0,
                "callCount": int(row["call_count"] or 0),
                "successCount": int(row["success_count"] or 0),
                "failedCount": int(row["failed_count"] or 0),
                "lastCalledAt": row["last_called_at"],
            }
        )

    return [
        {
            "credentialId": clean_text(row["credential_id"]),
            "credentialName": clean_text(row["credential_name"]) or clean_text(row["credential_id"]),
            "channelId": clean_text(row["channel_id"]) or "global",
            "userCount": int(row["user_count"] or 0),
            "callCount": int(row["call_count"] or 0),
            "successCount": int(row["success_count"] or 0),
            "failedCount": int(row["failed_count"] or 0),
            "lastCalledAt": row["last_called_at"],
            "children": children_by_credential.get(clean_text(row["credential_id"])) or [],
        }
        for row in parent_rows
    ]


def infer_api_usage_summary(conn: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if pg_table_exists(conn, "product_ai_analysis_cache"):
        rows = conn.execute(
            """
            SELECT model, COUNT(*) AS call_count, MAX(updated_at) AS last_called_at
            FROM product_ai_analysis_cache
            WHERE model != '' AND model != 'rule-fallback'
            GROUP BY model
            """
        ).fetchall()
        for row in rows:
            items.append(
                make_api_usage_summary_item(
                    provider="openai-compatible",
                    api_type="chat",
                    stage="recommendation",
                    model=row["model"],
                    call_count=int(row["call_count"] or 0),
                    success_count=int(row["call_count"] or 0),
                    failed_count=0,
                    last_called_at=row["last_called_at"],
                    source="inferred-cache",
                    is_inferred=True,
                    notes="from product_ai_analysis_cache rows",
                )
            )

    if pg_table_exists(conn, "visual_generation_tasks"):
        items.extend(infer_visual_task_api_usage(conn))
    return items


def infer_visual_task_api_usage(conn: Any) -> list[dict[str, Any]]:
    settings = read_setting_values(conn)
    analysis_model = runtime_setting_value(settings, "OPENAI_VISUAL_ANALYSIS_MODEL", "OPENAI_TEXT_MODEL", "gpt-5.5")
    prompt_model = runtime_setting_value(settings, "OPENAI_VISUAL_PROMPT_MODEL", "OPENAI_TEXT_MODEL", "gpt-5.5")
    image_model = runtime_setting_value(settings, "OPENAI_IMAGE_MODEL", "", "gpt-image-2")
    rows = conn.execute(
        """
        SELECT status, analysis_json, mother_image_path, mother_image_url, updated_at
        FROM visual_generation_tasks
        WHERE status != 'draft'
        """
    ).fetchall()
    counts: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        last_called_at = row["updated_at"]
        analysis = parse_json_text(row["analysis_json"], {})
        if isinstance(analysis, dict) and analysis:
            add_inferred_usage_count(counts, "visual-analysis", analysis_model, last_called_at)
            add_inferred_usage_count(counts, "visual-prompt", prompt_model, last_called_at)
        if row["mother_image_path"] or row["mother_image_url"] or row["status"] in {"split", "completed"}:
            add_inferred_usage_count(counts, "visual-image", image_model, last_called_at, api_type="image")

    return [
        make_api_usage_summary_item(
            provider="openai-compatible",
            api_type=value["apiType"],
            stage=stage,
            model=model,
            call_count=value["callCount"],
            success_count=value["callCount"],
            failed_count=0,
            last_called_at=value["lastCalledAt"],
            source="inferred-visual-task",
            is_inferred=True,
            notes="from visual_generation_tasks state",
        )
        for (stage, model), value in counts.items()
    ]


def add_inferred_usage_count(
    counts: dict[tuple[str, str], dict[str, Any]],
    stage: str,
    model: str,
    last_called_at: str | None,
    *,
    api_type: str = "chat",
) -> None:
    key = (stage, model or "unknown")
    current = counts.setdefault(key, {"apiType": api_type, "callCount": 0, "lastCalledAt": None})
    current["callCount"] += 1
    if last_called_at and (not current["lastCalledAt"] or last_called_at > current["lastCalledAt"]):
        current["lastCalledAt"] = last_called_at


def empty_api_usage_summary() -> dict[str, Any]:
    return {
        "items": [],
        "totalCalls": 0,
        "exactCalls": 0,
        "inferredCalls": 0,
        "byUser": [],
        "byTeam": [],
        "byChannel": [],
        "byCredential": [],
        "keyStats": [],
        "recentLogs": [],
    }


def normalize_api_usage_time_range(value: str | None) -> str:
    clean_value = clean_text(value).lower()
    return clean_value if clean_value in {"1h", "24h", "7d", "all"} else "all"


def api_usage_time_filter_sql(time_range: str) -> str:
    if time_range == "1h":
        return "created_at >= to_char(NOW() - INTERVAL '1 hour', 'YYYY-MM-DD HH24:MI:SS')"
    if time_range == "24h":
        return "created_at >= to_char(NOW() - INTERVAL '24 hours', 'YYYY-MM-DD HH24:MI:SS')"
    if time_range == "7d":
        return "created_at >= to_char(NOW() - INTERVAL '7 days', 'YYYY-MM-DD HH24:MI:SS')"
    return "1 = 1"


def build_api_usage_filter_clause(
    *,
    time_range: str = "all",
    channel_id: str = "",
    credential_id: str = "",
    stage: str = "",
    status: str = "",
) -> tuple[str, tuple[Any, ...]]:
    where = [api_usage_time_filter_sql(normalize_api_usage_time_range(time_range))]
    params: list[Any] = []
    if clean_text(channel_id):
        where.append("channel_id = %s")
        params.append(clean_text(channel_id))
    if clean_text(credential_id):
        where.append("credential_id = %s")
        params.append(clean_text(credential_id))
    if clean_text(stage):
        where.append("stage = %s")
        params.append(clean_text(stage))
    clean_status = clean_text(status).lower()
    if clean_status in {"success", "failed"}:
        where.append("status = %s")
        params.append(clean_status)
    return " AND ".join(where), tuple(params)


def summarize_api_usage_by_key(
    conn: Any,
    *,
    time_range: str = "all",
    channel_id: str = "",
    credential_id: str = "",
    stage: str = "",
    status: str = "",
) -> list[dict[str, Any]]:
    where_sql, params = build_api_usage_filter_clause(
        time_range=time_range,
        channel_id=channel_id,
        credential_id=credential_id,
        stage=stage,
        status=status,
    )
    rows = conn.execute(
        f"""
        SELECT
            channel_id,
            credential_id,
            credential_name,
            provider,
            api_type,
            stage,
            model,
            COALESCE(SUM(call_count), 0) AS call_count,
            COALESCE(SUM(CASE WHEN status = 'success' THEN call_count ELSE 0 END), 0) AS success_count,
            COALESCE(SUM(CASE WHEN status = 'failed' THEN call_count ELSE 0 END), 0) AS failed_count,
            MAX(updated_at) AS last_called_at,
            (
                SELECT error_message
                FROM api_usage_logs AS latest_error
                WHERE latest_error.channel_id = grouped.channel_id
                  AND latest_error.credential_id = grouped.credential_id
                  AND latest_error.provider = grouped.provider
                  AND latest_error.api_type = grouped.api_type
                  AND latest_error.stage = grouped.stage
                  AND latest_error.model = grouped.model
                  AND latest_error.status = 'failed'
                  AND COALESCE(latest_error.error_message, '') != ''
                ORDER BY latest_error.created_at DESC
                LIMIT 1
            ) AS last_error_message
        FROM api_usage_logs AS grouped
        WHERE {where_sql}
        GROUP BY channel_id, credential_id, credential_name, provider, api_type, stage, model
        ORDER BY last_called_at DESC, call_count DESC
        LIMIT 500
        """,
        params,
    ).fetchall()
    return [
        {
            "id": "|".join([
                clean_text(row["channel_id"]) or "global",
                clean_text(row["credential_id"]) or "all-keys",
                clean_text(row["provider"]) or "unknown",
                clean_text(row["api_type"]) or "unknown",
                clean_text(row["stage"]) or "unknown",
                clean_text(row["model"]) or "unknown",
            ]),
            "channelId": clean_text(row["channel_id"]) or "global",
            "credentialId": clean_text(row["credential_id"]),
            "credentialName": clean_text(row["credential_name"]) or clean_text(row["credential_id"]) or "未标记 Key",
            "provider": clean_text(row["provider"]) or "unknown",
            "apiType": clean_text(row["api_type"]) or "unknown",
            "stage": clean_text(row["stage"]) or "unknown",
            "model": clean_text(row["model"]) or "unknown",
            "callCount": int(row["call_count"] or 0),
            "successCount": int(row["success_count"] or 0),
            "failedCount": int(row["failed_count"] or 0),
            "lastCalledAt": row["last_called_at"],
            "lastErrorMessage": clean_text(row["last_error_message"]),
        }
        for row in rows
    ]


def list_recent_api_usage_logs(
    conn: Any,
    *,
    time_range: str = "all",
    channel_id: str = "",
    credential_id: str = "",
    stage: str = "",
    status: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    where_sql, params = build_api_usage_filter_clause(
        time_range=time_range,
        channel_id=channel_id,
        credential_id=credential_id,
        stage=stage,
        status=status,
    )
    rows = conn.execute(
        f"""
        SELECT *
        FROM api_usage_logs
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT %s
        """,
        params + (max(1, min(int(limit or 200), 500)),),
    ).fetchall()
    return [api_usage_log_row_to_api(row) for row in rows]


def get_api_usage_summary(
    scope: str = "all",
    *,
    time_range: str = "all",
    channel_id: str = "",
    credential_id: str = "",
    stage: str = "",
    status: str = "",
) -> dict[str, Any]:
    normalized_scope = str(scope or "all").strip().lower()
    if normalized_scope not in {"all", "models", "groups"}:
        normalized_scope = "all"
    ensure_api_usage_log_schema()
    summary = empty_api_usage_summary()
    with get_pg_connection() as conn:
        if normalized_scope in {"all", "models"}:
            exact_rows = conn.execute(
                """
                SELECT
                    user_id,
                    channel_id,
                    credential_id,
                    credential_name,
                    provider,
                    api_type,
                    stage,
                    model,
                    source,
                    COALESCE(SUM(call_count), 0) AS call_count,
                    COALESCE(SUM(CASE WHEN status = 'success' THEN call_count ELSE 0 END), 0) AS success_count,
                    COALESCE(SUM(CASE WHEN status = 'failed' THEN call_count ELSE 0 END), 0) AS failed_count,
                    MAX(updated_at) AS last_called_at
                FROM api_usage_logs
                GROUP BY user_id, channel_id, credential_id, credential_name, provider, api_type, stage, model, source
                """
            ).fetchall()
            items = [
                make_api_usage_summary_item(
                    user_id=row["user_id"],
                    channel_id=row["channel_id"],
                    credential_id=row["credential_id"],
                    credential_name=row["credential_name"],
                    provider=row["provider"],
                    api_type=row["api_type"],
                    stage=row["stage"],
                    model=row["model"],
                    call_count=int(row["call_count"] or 0),
                    success_count=int(row["success_count"] or 0),
                    failed_count=int(row["failed_count"] or 0),
                    last_called_at=row["last_called_at"],
                    source=row["source"],
                    is_inferred=False,
                )
                for row in exact_rows
            ]
            items.extend(infer_api_usage_summary(conn))
            merged = merge_api_usage_items(items)
            summary["items"] = merged
            summary["totalCalls"] = sum(int(item["callCount"] or 0) for item in merged)
            summary["exactCalls"] = sum(int(item["callCount"] or 0) for item in merged if not item["isInferred"])
            summary["inferredCalls"] = summary["totalCalls"] - summary["exactCalls"]
        if normalized_scope in {"all", "groups"}:
            summary["byUser"] = summarize_api_usage_by_user_with_limits(conn)
            summary["byTeam"] = summarize_api_usage_by_team(conn)
            summary["byChannel"] = summarize_api_usage_by_channel(conn)
            summary["byCredential"] = summarize_api_usage_by_credential(conn)
            summary["keyStats"] = summarize_api_usage_by_key(
                conn,
                time_range=time_range,
                channel_id=channel_id,
                credential_id=credential_id,
                stage=stage,
                status=status,
            )
            summary["recentLogs"] = list_recent_api_usage_logs(
                conn,
                time_range=time_range,
                channel_id=channel_id,
                credential_id=credential_id,
                stage=stage,
                status=status,
            )
    return summary

