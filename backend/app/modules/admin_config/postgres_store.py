from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional runtime dependency
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

from app.core import config as app_config
from app.core.database import (
    clean_text,
    current_month_start_text,
    parse_json_text,
    user_usage_quota_to_api,
    utc_now_text,
)


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
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield conn


def pg_table_exists(conn: Any, table_name: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s) AS table_name", (f"public.{table_name}",)).fetchone()
    return bool(row and row["table_name"])


def app_setting_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": row["key"],
        "value": row["value"],
        "category": row["category"],
        "label": row["label"],
        "description": row["description"],
        "isSecret": bool(row["is_secret"]),
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
    }


def user_api_credential_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "channelId": row["channel_id"],
        "apiKey": row["api_key"],
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
                provider or "unknown",
                api_type or "unknown",
                stage or "unknown",
                model or "unknown",
                source or "unknown",
            ]
        ),
        "userId": user_id,
        "channelId": channel_id,
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
    merged: dict[tuple[str, str, str, str, str, str, str], dict[str, Any]] = {}
    for item in items:
        key = (
            item.get("userId", ""),
            item.get("channelId", ""),
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
    with get_pg_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO api_usage_logs (
                id, user_id, channel_id, provider, api_type, stage, model, call_count, status, source,
                related_id, error_message, metadata_json, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                usage_id,
                clean_text(user_id),
                clean_text(channel_id),
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

        next_api_key = str(existing["api_key"] or "") if existing else ""
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
                next_api_key,
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
    with get_pg_connection() as conn:
        rows = conn.execute("SELECT * FROM app_settings").fetchall()
    return {row["key"]: app_setting_row_to_api(row) for row in rows}


def get_app_setting_value(key: str, default: str = "") -> str:
    clean_key = str(key or "").strip()
    if not clean_key:
        return default
    with get_pg_connection() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = %s", (clean_key,)).fetchone()
    return str(row["value"]) if row else default


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
                str(value or ""),
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


def read_setting_values(conn: Any | None = None) -> dict[str, str]:
    if conn is not None:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        return {row["key"]: str(row["value"] or "") for row in rows}
    with get_pg_connection() as pg_conn:
        rows = pg_conn.execute("SELECT key, value FROM app_settings").fetchall()
    return {row["key"]: str(row["value"] or "") for row in rows}


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


def get_api_usage_summary() -> dict[str, Any]:
    with get_pg_connection() as conn:
        exact_rows = conn.execute(
            """
            SELECT
                user_id,
                channel_id,
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
            GROUP BY user_id, channel_id, provider, api_type, stage, model, source
            """
        ).fetchall()
        items = [
            make_api_usage_summary_item(
                user_id=row["user_id"],
                channel_id=row["channel_id"],
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
        by_user = summarize_api_usage_by_user_with_limits(conn)
        by_team = summarize_api_usage_by_team(conn)
        by_channel = summarize_api_usage_by_channel(conn)

    merged = merge_api_usage_items(items)
    total_calls = sum(int(item["callCount"] or 0) for item in merged)
    exact_calls = sum(int(item["callCount"] or 0) for item in merged if not item["isInferred"])
    inferred_calls = total_calls - exact_calls
    return {
        "items": merged,
        "totalCalls": total_calls,
        "exactCalls": exact_calls,
        "inferredCalls": inferred_calls,
        "byUser": by_user,
        "byTeam": by_team,
        "byChannel": by_channel,
    }
