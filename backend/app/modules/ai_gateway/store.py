from __future__ import annotations

import json
import hmac
import hashlib
import random
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from app.core.database import get_connection, utc_now_text
from app.core.secrets import decrypt_secret_value, encrypt_secret_value, get_encryption_key_material, is_encrypted_text


DEFAULT_ROUTE_STAGES: tuple[dict[str, str], ...] = (
    {"stage": "title", "title": "安全标题生成", "model_type": "text"},
    {"stage": "variant_translation", "title": "SKU 文案翻译", "model_type": "text"},
    {"stage": "title_split", "title": "标题拆分", "model_type": "text"},
    {"stage": "recommendation", "title": "智能推荐", "model_type": "text"},
    {"stage": "product_attribute", "title": "产品属性填写", "model_type": "text"},
    {"stage": "visual_analysis", "title": "图片理解", "model_type": "text"},
    {"stage": "visual_prompt", "title": "提示词规划", "model_type": "text"},
    {"stage": "image", "title": "图片生成", "model_type": "image"},
)

DEFAULT_TEXT_MODEL = "gpt-5.5"
DEFAULT_IMAGE_MODEL = "gpt-image-2-1k"
AI_GATEWAY_CLOUD_SETTING_KEY = "AI_GATEWAY_CONFIG_JSON"
DEFAULT_CIRCUIT_OPEN_SECONDS = 120
TRANSIENT_CIRCUIT_OPEN_SECONDS = 30
RATE_LIMIT_CIRCUIT_OPEN_SECONDS = 90
AUTH_CIRCUIT_OPEN_SECONDS = 86400
CLOUD_CONFIG_CACHE_TTL_SECONDS = 20
_cloud_config_cache: dict[str, Any] | None = None
_cloud_config_cache_loaded_at = 0.0
POSTGRES_TRANSIENT_ERROR_CODES = {"40P01", "40001", "55P03"}


def ensure_schema() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ai_gateway_channels (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider_type TEXT NOT NULL DEFAULT 'openai_compatible',
                base_url TEXT NOT NULL DEFAULT '',
                text_model TEXT NOT NULL DEFAULT '',
                image_model TEXT NOT NULL DEFAULT '',
                model_templates_json TEXT NOT NULL DEFAULT '{}',
                capabilities_json TEXT NOT NULL DEFAULT '["chat"]',
                enabled INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 100,
                connect_timeout_seconds INTEGER NOT NULL DEFAULT 10,
                read_timeout_seconds INTEGER NOT NULL DEFAULT 60,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT
            );

            CREATE TABLE IF NOT EXISTS ai_gateway_credentials (
                id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                name TEXT NOT NULL,
                api_key TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 100,
                weight INTEGER NOT NULL DEFAULT 1,
                max_concurrency INTEGER NOT NULL DEFAULT 2,
                rpm_limit INTEGER NOT NULL DEFAULT 0,
                daily_limit INTEGER NOT NULL DEFAULT 0,
                monthly_limit INTEGER NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT,
                FOREIGN KEY(channel_id) REFERENCES ai_gateway_channels(id)
            );

            CREATE INDEX IF NOT EXISTS idx_ai_gateway_credentials_channel
                ON ai_gateway_credentials(channel_id, enabled);

            CREATE TABLE IF NOT EXISTS ai_gateway_route_policies (
                stage TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                model_type TEXT NOT NULL DEFAULT 'text',
                channel_order_json TEXT NOT NULL DEFAULT '[]',
                key_selection_policy TEXT NOT NULL DEFAULT 'least_in_flight_weighted',
                max_channel_attempts INTEGER NOT NULL DEFAULT 3,
                allow_cross_channel_fallback INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT
            );

            CREATE TABLE IF NOT EXISTS ai_gateway_circuit_states (
                id TEXT PRIMARY KEY,
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'closed',
                failure_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                opened_until TEXT,
                last_error_type TEXT NOT NULL DEFAULT '',
                last_error_message TEXT NOT NULL DEFAULT '',
                last_http_status INTEGER,
                last_latency_ms INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT,
                UNIQUE(scope_type, scope_id, stage, model)
            );

            CREATE INDEX IF NOT EXISTS idx_ai_gateway_circuit_lookup
                ON ai_gateway_circuit_states(scope_type, scope_id, state);
            """
        )
        ensure_ai_gateway_column(
            conn,
            "ai_gateway_channels",
            "model_templates_json",
            "model_templates_json TEXT NOT NULL DEFAULT '{}'",
        )
        seed_default_routes(conn)


def ensure_ai_gateway_column(conn: Any, table_name: str, column_name: str, ddl: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def cloud_store_available() -> bool:
    try:
        from app.modules.admin_config import postgres_store

        return bool(postgres_store.configured_url())
    except Exception:
        return False


def default_cloud_config() -> dict[str, Any]:
    now = utc_now_text()
    return {
        "channels": [],
        "credentials": [],
        "routes": [
            {
                "stage": route["stage"],
                "title": route["title"],
                "modelType": route["model_type"],
                "channelOrder": [],
                "keySelectionPolicy": "least_in_flight_weighted",
                "maxChannelAttempts": 3,
                "allowCrossChannelFallback": True,
                "enabled": True,
                "createdAt": now,
                "updatedAt": now,
            }
            for route in DEFAULT_ROUTE_STAGES
        ],
        "circuits": [],
    }


def load_cloud_config() -> dict[str, Any]:
    global _cloud_config_cache, _cloud_config_cache_loaded_at
    if not cloud_store_available():
        raise RuntimeError(
            "API 中枢必须使用云数据库，请配置 ADMIN_CONFIG_DATABASE_URL、POSTGRES_DATABASE_URL 或 DATABASE_URL"
        )
    now_timestamp = datetime.utcnow().timestamp()
    if _cloud_config_cache is not None and now_timestamp - _cloud_config_cache_loaded_at < CLOUD_CONFIG_CACHE_TTL_SECONDS:
        return json.loads(json.dumps(_cloud_config_cache))
    from app.modules.admin_config import postgres_store

    try:
        postgres_store.ensure_app_settings_schema()
        raw_value = postgres_store.get_app_setting_value(AI_GATEWAY_CLOUD_SETTING_KEY, "")
    except Exception as exc:
        raise RuntimeError(f"API 中枢云数据库读取失败：{exc}") from exc
    if raw_value:
        try:
            loaded = json.loads(raw_value)
        except json.JSONDecodeError:
            loaded = {}
    else:
        loaded = {}
    config = default_cloud_config()
    if isinstance(loaded, dict):
        for key in ("channels", "credentials", "routes", "circuits"):
            if isinstance(loaded.get(key), list):
                config[key] = loaded[key]
    changed = ensure_default_cloud_routes(config)
    changed = ensure_default_cloud_routes(config) or changed
    changed = disable_duplicate_cloud_credentials(config) or changed
    changed = encrypt_cloud_config_secrets(config) or changed
    if changed or not raw_value:
        save_cloud_config(config, updated_by="cloud-seed", force_insert=not raw_value)
    _cloud_config_cache = json.loads(json.dumps(config))
    _cloud_config_cache_loaded_at = now_timestamp
    return config


def save_cloud_config(config: dict[str, Any], *, updated_by: str | None = None, force_insert: bool = False) -> None:
    global _cloud_config_cache, _cloud_config_cache_loaded_at
    if not cloud_store_available():
        raise RuntimeError(
            "API 中枢必须使用云数据库，请配置 ADMIN_CONFIG_DATABASE_URL、POSTGRES_DATABASE_URL 或 DATABASE_URL"
        )
    from app.modules.admin_config import postgres_store

    if not force_insert and config is None:
        return
    payload = json.dumps(config, ensure_ascii=False)
    try:
        for attempt in range(4):
            try:
                postgres_store.upsert_app_setting(
                    key=AI_GATEWAY_CLOUD_SETTING_KEY,
                    value=payload,
                    category="ai_gateway",
                    label="API 中枢配置",
                    description="云端保存 API 中枢渠道、Key、路由和熔断状态",
                    is_secret=True,
                    updated_by=updated_by,
                )
                break
            except Exception as exc:
                if attempt >= 3 or not is_postgres_transient_error(exc):
                    raise
                time.sleep((0.08 * (2**attempt)) + random.uniform(0, 0.08))
        _cloud_config_cache = json.loads(json.dumps(config))
        _cloud_config_cache_loaded_at = datetime.utcnow().timestamp()
    except Exception as exc:
        raise RuntimeError(f"API 中枢云数据库保存失败：{exc}") from exc


def is_postgres_transient_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        sqlstate = getattr(current, "sqlstate", "") or getattr(current, "pgcode", "")
        if str(sqlstate) in POSTGRES_TRANSIENT_ERROR_CODES:
            return True
        text = str(current).lower()
        if (
            "deadlock detected" in text
            or "could not serialize access" in text
            or "lock not available" in text
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def encrypt_cloud_config_secrets(config: dict[str, Any]) -> bool:
    changed = False
    for credential in config.get("credentials", []):
        raw_api_key = str(credential.get("apiKey") or "")
        if not raw_api_key or is_encrypted_text(raw_api_key):
            continue
        encrypted_api_key = encrypt_secret_value(raw_api_key, enabled=True)
        if encrypted_api_key != raw_api_key:
            credential["apiKey"] = encrypted_api_key
            changed = True
    return changed


def ensure_default_cloud_routes(config: dict[str, Any]) -> bool:
    now = utc_now_text()
    routes = config.setdefault("routes", [])
    existing = {str(route.get("stage") or "") for route in routes}
    changed = False
    for route in DEFAULT_ROUTE_STAGES:
        if route["stage"] in existing:
            continue
        routes.append(
            {
                "stage": route["stage"],
                "title": route["title"],
                "modelType": route["model_type"],
                "channelOrder": [],
                "keySelectionPolicy": "least_in_flight_weighted",
                "maxChannelAttempts": 3,
                "allowCrossChannelFallback": True,
                "enabled": True,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        changed = True
    return changed


def normalize_api_key_for_dedupe(value: str) -> str:
    return "".join(str(value or "").split())


def api_key_fingerprint(value: str) -> str:
    normalized = normalize_api_key_for_dedupe(value)
    if not normalized:
        return ""
    key_material = get_encryption_key_material()
    if key_material is None:
        raise ValueError("CONFIG_ENCRYPTION_KEY is required to fingerprint API keys")
    return hmac.new(key_material, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def find_duplicate_cloud_credential(
    credentials: list[dict[str, Any]],
    *,
    api_key: str,
    current_credential_id: str,
) -> dict[str, Any] | None:
    normalized_api_key = normalize_api_key_for_dedupe(api_key)
    if not normalized_api_key:
        return None
    for credential in credentials:
        credential_id = str(credential.get("id") or "")
        if credential_id == current_credential_id:
            continue
        existing_fingerprint = str(credential.get("apiKeyFingerprint") or "")
        if existing_fingerprint and existing_fingerprint == api_key_fingerprint(normalized_api_key):
            return credential
        existing_key = normalize_api_key_for_dedupe(decrypt_secret_value(str(credential.get("apiKey") or "")))
        if existing_key and existing_key == normalized_api_key:
            return credential
    return None


def duplicate_credential_message(credential: dict[str, Any], config: dict[str, Any]) -> str:
    channel_id = str(credential.get("channelId") or "")
    channel = next((item for item in config.get("channels", []) if item.get("id") == channel_id), None)
    channel_name = str(channel.get("name") or channel_id) if channel else channel_id
    credential_name = str(credential.get("name") or credential.get("id") or "未命名 Key")
    return f"这个 API Key 已存在于渠道「{channel_name}」的 Key「{credential_name}」，请不要重复添加"


def disable_duplicate_cloud_credentials(config: dict[str, Any]) -> bool:
    changed = False
    seen: dict[str, dict[str, Any]] = {}
    for credential in sorted(
        config.get("credentials", []),
        key=lambda item: (str(item.get("createdAt") or ""), str(item.get("id") or "")),
    ):
        normalized_api_key = normalize_api_key_for_dedupe(decrypt_secret_value(str(credential.get("apiKey") or "")))
        if not normalized_api_key:
            continue
        fingerprint = api_key_fingerprint(normalized_api_key)
        if credential.get("apiKeyFingerprint") != fingerprint:
            credential["apiKeyFingerprint"] = fingerprint
            changed = True
        if fingerprint not in seen:
            seen[fingerprint] = credential
            continue
        if credential.get("enabled", True):
            credential["enabled"] = False
            credential["notes"] = (str(credential.get("notes") or "").strip() + "；重复 API Key 已自动停用").strip("；")
            credential["updatedAt"] = utc_now_text()
            changed = True
    return changed


def cloud_channel_to_api(item: dict[str, Any], credentials: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "providerType": str(item.get("providerType") or "openai_compatible"),
        "baseUrl": str(item.get("baseUrl") or ""),
        "textModel": str(item.get("textModel") or ""),
        "imageModel": str(item.get("imageModel") or ""),
        "modelTemplates": normalize_model_templates(item.get("modelTemplates")),
        "capabilities": normalize_capabilities(item.get("capabilities")),
        "enabled": bool(item.get("enabled", True)),
        "priority": int(item.get("priority") or 100),
        "connectTimeoutSeconds": int(item.get("connectTimeoutSeconds") or 10),
        "readTimeoutSeconds": int(item.get("readTimeoutSeconds") or 60),
        "notes": str(item.get("notes") or ""),
        "createdAt": str(item.get("createdAt") or ""),
        "updatedAt": str(item.get("updatedAt") or ""),
        "credentials": credentials or [],
    }


def cloud_credential_to_api(item: dict[str, Any]) -> dict[str, Any]:
    api_key = decrypt_secret_value(str(item.get("apiKey") or ""))
    return {
        "id": str(item.get("id") or ""),
        "channelId": str(item.get("channelId") or ""),
        "name": str(item.get("name") or ""),
        "enabled": bool(item.get("enabled", True)),
        "priority": int(item.get("priority") or 100),
        "weight": int(item.get("weight") or 1),
        "maxConcurrency": int(item.get("maxConcurrency") or 0),
        "rpmLimit": int(item.get("rpmLimit") or 0),
        "dailyLimit": int(item.get("dailyLimit") or 0),
        "monthlyLimit": int(item.get("monthlyLimit") or 0),
        "apiKeyConfigured": bool(api_key),
        "maskedApiKey": mask_secret(api_key),
        "notes": str(item.get("notes") or ""),
        "createdAt": str(item.get("createdAt") or ""),
        "updatedAt": str(item.get("updatedAt") or ""),
    }


def cloud_route_to_api(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": str(item.get("stage") or ""),
        "title": str(item.get("title") or item.get("stage") or ""),
        "modelType": str(item.get("modelType") or "text"),
        "channelOrder": [str(value) for value in item.get("channelOrder", []) if str(value)],
        "keySelectionPolicy": str(item.get("keySelectionPolicy") or "least_in_flight_weighted"),
        "maxChannelAttempts": int(item.get("maxChannelAttempts") or 3),
        "allowCrossChannelFallback": bool(item.get("allowCrossChannelFallback", True)),
        "enabled": bool(item.get("enabled", True)),
        "createdAt": str(item.get("createdAt") or ""),
        "updatedAt": str(item.get("updatedAt") or ""),
    }


def cloud_circuit_to_api(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "scopeType": str(item.get("scopeType") or ""),
        "scopeId": str(item.get("scopeId") or ""),
        "stage": str(item.get("stage") or ""),
        "model": str(item.get("model") or ""),
        "state": str(item.get("state") or "closed"),
        "failureCount": int(item.get("failureCount") or 0),
        "successCount": int(item.get("successCount") or 0),
        "openedUntil": item.get("openedUntil"),
        "lastErrorType": str(item.get("lastErrorType") or ""),
        "lastErrorMessage": str(item.get("lastErrorMessage") or ""),
        "lastHttpStatus": item.get("lastHttpStatus"),
        "lastLatencyMs": item.get("lastLatencyMs"),
        "createdAt": str(item.get("createdAt") or ""),
        "updatedAt": str(item.get("updatedAt") or ""),
    }


def seed_default_routes(conn: Any) -> None:
    now = utc_now_text()
    for route in DEFAULT_ROUTE_STAGES:
        conn.execute(
            """
            INSERT OR IGNORE INTO ai_gateway_route_policies (
                stage, title, model_type, channel_order_json, created_at, updated_at
            )
            VALUES (?, ?, ?, '[]', ?, ?)
            """,
            (route["stage"], route["title"], route["model_type"], now, now),
        )


def parse_json_list(value: str) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def parse_json_object(value: str | None) -> dict[str, str]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(item).strip() for key, item in parsed.items() if str(key).strip() and str(item).strip()}


def mask_secret(value: str) -> str:
    clean = str(value or "")
    if not clean:
        return ""
    if len(clean) <= 8:
        return "****"
    return f"{clean[:4]}****{clean[-4:]}"


def normalize_bool(value: Any) -> int:
    return 1 if bool(value) else 0


def normalize_capabilities(value: Any, *, model_type: str = "text") -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = []
    if not items:
        items = ["image"] if model_type == "image" else ["chat"]
    return sorted(set(items))


def normalize_model_templates(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    known_stages = {item["stage"] for item in DEFAULT_ROUTE_STAGES}
    return {
        str(stage).strip(): str(model).strip()
        for stage, model in value.items()
        if str(stage).strip() in known_stages and str(model).strip()
    }


def resolve_channel_model(channel: Any, stage: str, model_type: str, *, local: bool = False) -> str:
    if local:
        templates = parse_json_object(channel["model_templates_json"])
        default_model = channel["image_model"] if model_type == "image" else channel["text_model"]
    else:
        templates = normalize_model_templates(channel.get("modelTemplates"))
        default_model = channel.get("imageModel") if model_type == "image" else channel.get("textModel")
    return str(templates.get(stage) or default_model or "").strip()


def channel_to_api(row: Any, credentials: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    capabilities = parse_json_list(row["capabilities_json"])
    return {
        "id": row["id"],
        "name": row["name"],
        "providerType": row["provider_type"],
        "baseUrl": row["base_url"],
        "textModel": row["text_model"],
        "imageModel": row["image_model"],
        "modelTemplates": parse_json_object(row["model_templates_json"]),
        "capabilities": capabilities,
        "enabled": bool(row["enabled"]),
        "priority": int(row["priority"] or 0),
        "connectTimeoutSeconds": int(row["connect_timeout_seconds"] or 0),
        "readTimeoutSeconds": int(row["read_timeout_seconds"] or 0),
        "notes": row["notes"] or "",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "credentials": credentials or [],
    }


def credential_to_api(row: Any) -> dict[str, Any]:
    api_key = decrypt_secret_value(str(row["api_key"] or ""))
    return {
        "id": row["id"],
        "channelId": row["channel_id"],
        "name": row["name"],
        "enabled": bool(row["enabled"]),
        "priority": int(row["priority"] or 0),
        "weight": int(row["weight"] or 1),
        "maxConcurrency": int(row["max_concurrency"] or 0),
        "rpmLimit": int(row["rpm_limit"] or 0),
        "dailyLimit": int(row["daily_limit"] or 0),
        "monthlyLimit": int(row["monthly_limit"] or 0),
        "apiKeyConfigured": bool(api_key),
        "maskedApiKey": mask_secret(api_key),
        "notes": row["notes"] or "",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def route_to_api(row: Any) -> dict[str, Any]:
    return {
        "stage": row["stage"],
        "title": row["title"],
        "modelType": row["model_type"],
        "channelOrder": parse_json_list(row["channel_order_json"]),
        "keySelectionPolicy": row["key_selection_policy"],
        "maxChannelAttempts": int(row["max_channel_attempts"] or 0),
        "allowCrossChannelFallback": bool(row["allow_cross_channel_fallback"]),
        "enabled": bool(row["enabled"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def circuit_to_api(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "scopeType": row["scope_type"],
        "scopeId": row["scope_id"],
        "stage": row["stage"],
        "model": row["model"],
        "state": row["state"],
        "failureCount": int(row["failure_count"] or 0),
        "successCount": int(row["success_count"] or 0),
        "openedUntil": row["opened_until"],
        "lastErrorType": row["last_error_type"],
        "lastErrorMessage": row["last_error_message"],
        "lastHttpStatus": row["last_http_status"],
        "lastLatencyMs": row["last_latency_ms"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def list_channels(*, include_credentials: bool = True) -> list[dict[str, Any]]:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        credentials_by_channel: dict[str, list[dict[str, Any]]] = {}
        if include_credentials:
            for item in cloud_config.get("credentials", []):
                credentials_by_channel.setdefault(str(item.get("channelId") or ""), []).append(cloud_credential_to_api(item))
        channels = sorted(
            cloud_config.get("channels", []),
            key=lambda item: (int(item.get("priority") or 0), str(item.get("name") or "")),
        )
        return [cloud_channel_to_api(item, credentials_by_channel.get(str(item.get("id") or ""), [])) for item in channels]

    ensure_schema()
    with get_connection() as conn:
        channels = conn.execute(
            "SELECT * FROM ai_gateway_channels ORDER BY priority ASC, updated_at DESC, name ASC"
        ).fetchall()
        if not include_credentials:
            return [channel_to_api(row) for row in channels]
        credentials_by_channel: dict[str, list[dict[str, Any]]] = {}
        rows = conn.execute(
            "SELECT * FROM ai_gateway_credentials ORDER BY priority ASC, weight DESC, updated_at DESC"
        ).fetchall()
        for row in rows:
            credentials_by_channel.setdefault(row["channel_id"], []).append(credential_to_api(row))
        return [channel_to_api(row, credentials_by_channel.get(row["id"], [])) for row in channels]


def upsert_channel(payload: dict[str, Any], *, admin_id: str | None = None) -> dict[str, Any]:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        now = utc_now_text()
        channel_id = str(payload.get("id") or "").strip() or f"channel_{uuid.uuid4().hex[:12]}"
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("渠道名称不能为空")
        next_item = {
            "id": channel_id,
            "name": name,
            "providerType": str(payload.get("providerType") or "openai_compatible").strip() or "openai_compatible",
            "baseUrl": str(payload.get("baseUrl") or "").strip().rstrip("/"),
            "textModel": str(payload.get("textModel") or DEFAULT_TEXT_MODEL).strip(),
            "imageModel": str(payload.get("imageModel") or DEFAULT_IMAGE_MODEL).strip(),
            "modelTemplates": normalize_model_templates(payload.get("modelTemplates")),
            "capabilities": normalize_capabilities(payload.get("capabilities")),
            "enabled": bool(payload.get("enabled", True)),
            "priority": int(payload.get("priority") or 100),
            "connectTimeoutSeconds": int(payload.get("connectTimeoutSeconds") or 10),
            "readTimeoutSeconds": int(payload.get("readTimeoutSeconds") or 60),
            "notes": str(payload.get("notes") or "").strip(),
            "createdAt": now,
            "updatedAt": now,
        }
        channels = cloud_config.setdefault("channels", [])
        for index, item in enumerate(channels):
            if item.get("id") == channel_id:
                next_item["createdAt"] = item.get("createdAt") or now
                channels[index] = next_item
                break
        else:
            channels.append(next_item)
        save_cloud_config(cloud_config, updated_by=admin_id)
        return cloud_channel_to_api(next_item)

    ensure_schema()
    now = utc_now_text()
    channel_id = str(payload.get("id") or "").strip() or f"channel_{uuid.uuid4().hex[:12]}"
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("渠道名称不能为空")
    model_type = "image" if "image" in normalize_capabilities(payload.get("capabilities")) else "text"
    capabilities = normalize_capabilities(payload.get("capabilities"), model_type=model_type)
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM ai_gateway_channels WHERE id = ?", (channel_id,)).fetchone()
        values = (
            channel_id,
            name,
            str(payload.get("providerType") or "openai_compatible").strip() or "openai_compatible",
            str(payload.get("baseUrl") or "").strip().rstrip("/"),
            str(payload.get("textModel") or DEFAULT_TEXT_MODEL).strip(),
            str(payload.get("imageModel") or DEFAULT_IMAGE_MODEL).strip(),
            json.dumps(normalize_model_templates(payload.get("modelTemplates")), ensure_ascii=False),
            json.dumps(capabilities, ensure_ascii=False),
            normalize_bool(payload.get("enabled", True)),
            int(payload.get("priority") or 100),
            int(payload.get("connectTimeoutSeconds") or 10),
            int(payload.get("readTimeoutSeconds") or (900 if "image" in capabilities else 60)),
            str(payload.get("notes") or "").strip(),
            now,
            str(admin_id or ""),
        )
        if existing:
            conn.execute(
                """
                UPDATE ai_gateway_channels
                SET name = ?, provider_type = ?, base_url = ?, text_model = ?, image_model = ?,
                    model_templates_json = ?, capabilities_json = ?, enabled = ?, priority = ?, connect_timeout_seconds = ?,
                    read_timeout_seconds = ?, notes = ?, updated_at = ?, updated_by = ?
                WHERE id = ?
                """,
                values[1:] + (channel_id,),
            )
        else:
            conn.execute(
                """
                INSERT INTO ai_gateway_channels (
                    id, name, provider_type, base_url, text_model, image_model, model_templates_json, capabilities_json,
                    enabled, priority, connect_timeout_seconds, read_timeout_seconds, notes,
                    created_at, updated_at, updated_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values[:-1] + (now, values[-1]),
            )
        row = conn.execute("SELECT * FROM ai_gateway_channels WHERE id = ?", (channel_id,)).fetchone()
        return channel_to_api(row)


def delete_channel(channel_id: str) -> bool:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        clean_id = str(channel_id or "").strip()
        original_count = len(cloud_config.get("channels", []))
        cloud_config["channels"] = [item for item in cloud_config.get("channels", []) if item.get("id") != clean_id]
        cloud_config["credentials"] = [
            item for item in cloud_config.get("credentials", []) if item.get("channelId") != clean_id
        ]
        for route in cloud_config.get("routes", []):
            route["channelOrder"] = [item for item in route.get("channelOrder", []) if item != clean_id]
        save_cloud_config(cloud_config)
        return len(cloud_config.get("channels", [])) < original_count

    ensure_schema()
    clean_id = str(channel_id or "").strip()
    with get_connection() as conn:
        conn.execute("DELETE FROM ai_gateway_credentials WHERE channel_id = ?", (clean_id,))
        result = conn.execute("DELETE FROM ai_gateway_channels WHERE id = ?", (clean_id,))
        return result.rowcount > 0


def upsert_credential(payload: dict[str, Any], *, admin_id: str | None = None) -> dict[str, Any]:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        now = utc_now_text()
        credential_id = str(payload.get("id") or "").strip() or f"cred_{uuid.uuid4().hex[:12]}"
        channel_id = str(payload.get("channelId") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not channel_id:
            raise ValueError("缺少渠道 ID")
        if not name:
            raise ValueError("Key 名称不能为空")
        if not any(item.get("id") == channel_id for item in cloud_config.get("channels", [])):
            raise ValueError("渠道不存在")
        credentials = cloud_config.setdefault("credentials", [])
        existing = next((item for item in credentials if item.get("id") == credential_id), None)
        next_api_key = decrypt_secret_value(str(existing.get("apiKey") or "")) if existing else ""
        if payload.get("apiKey"):
            next_api_key = str(payload.get("apiKey") or "").strip()
        if payload.get("clearApiKey"):
            next_api_key = ""
        duplicate = find_duplicate_cloud_credential(
            credentials,
            api_key=next_api_key,
            current_credential_id=credential_id,
        )
        if duplicate:
            raise ValueError(duplicate_credential_message(duplicate, cloud_config))
        next_item = {
            "id": credential_id,
            "channelId": channel_id,
            "name": name,
            "apiKey": encrypt_secret_value(next_api_key, enabled=True),
            "apiKeyFingerprint": api_key_fingerprint(next_api_key) if next_api_key else "",
            "enabled": bool(payload.get("enabled", True)),
            "priority": int(payload.get("priority") or 100),
            "weight": max(1, int(payload.get("weight") or 1)),
            "maxConcurrency": max(0, int(payload.get("maxConcurrency") or 2)),
            "rpmLimit": max(0, int(payload.get("rpmLimit") or 0)),
            "dailyLimit": max(0, int(payload.get("dailyLimit") or 0)),
            "monthlyLimit": max(0, int(payload.get("monthlyLimit") or 0)),
            "notes": str(payload.get("notes") or "").strip(),
            "createdAt": existing.get("createdAt") if existing else now,
            "updatedAt": now,
        }
        for index, item in enumerate(credentials):
            if item.get("id") == credential_id:
                credentials[index] = next_item
                break
        else:
            credentials.append(next_item)
        save_cloud_config(cloud_config, updated_by=admin_id)
        return cloud_credential_to_api(next_item)

    ensure_schema()
    now = utc_now_text()
    credential_id = str(payload.get("id") or "").strip() or f"cred_{uuid.uuid4().hex[:12]}"
    channel_id = str(payload.get("channelId") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not channel_id:
        raise ValueError("缺少渠道 ID")
    if not name:
        raise ValueError("Key 名称不能为空")
    with get_connection() as conn:
        channel = conn.execute("SELECT id FROM ai_gateway_channels WHERE id = ?", (channel_id,)).fetchone()
        if not channel:
            raise ValueError("渠道不存在")
        existing = conn.execute("SELECT * FROM ai_gateway_credentials WHERE id = ?", (credential_id,)).fetchone()
        existing_key = decrypt_secret_value(str(existing["api_key"] or "")) if existing else ""
        next_key = str(payload.get("apiKey") or "").strip() or existing_key
        if payload.get("clearApiKey"):
            next_key = ""
        values = (
            credential_id,
            channel_id,
            name,
            encrypt_secret_value(next_key, enabled=True),
            normalize_bool(payload.get("enabled", True)),
            int(payload.get("priority") or 100),
            max(1, int(payload.get("weight") or 1)),
            max(0, int(payload.get("maxConcurrency") or 2)),
            max(0, int(payload.get("rpmLimit") or 0)),
            max(0, int(payload.get("dailyLimit") or 0)),
            max(0, int(payload.get("monthlyLimit") or 0)),
            str(payload.get("notes") or "").strip(),
            now,
            str(admin_id or ""),
        )
        if existing:
            conn.execute(
                """
                UPDATE ai_gateway_credentials
                SET channel_id = ?, name = ?, api_key = ?, enabled = ?, priority = ?, weight = ?,
                    max_concurrency = ?, rpm_limit = ?, daily_limit = ?, monthly_limit = ?,
                    notes = ?, updated_at = ?, updated_by = ?
                WHERE id = ?
                """,
                values[1:] + (credential_id,),
            )
        else:
            conn.execute(
                """
                INSERT INTO ai_gateway_credentials (
                    id, channel_id, name, api_key, enabled, priority, weight, max_concurrency,
                    rpm_limit, daily_limit, monthly_limit, notes, created_at, updated_at, updated_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values[:-1] + (now, values[-1]),
            )
        row = conn.execute("SELECT * FROM ai_gateway_credentials WHERE id = ?", (credential_id,)).fetchone()
        return credential_to_api(row)


def delete_credential(credential_id: str) -> bool:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        clean_id = str(credential_id or "").strip()
        original_count = len(cloud_config.get("credentials", []))
        cloud_config["credentials"] = [item for item in cloud_config.get("credentials", []) if item.get("id") != clean_id]
        save_cloud_config(cloud_config)
        return len(cloud_config.get("credentials", [])) < original_count

    ensure_schema()
    with get_connection() as conn:
        result = conn.execute("DELETE FROM ai_gateway_credentials WHERE id = ?", (str(credential_id or "").strip(),))
        return result.rowcount > 0


def list_routes() -> list[dict[str, Any]]:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        order = {item["stage"]: index for index, item in enumerate(DEFAULT_ROUTE_STAGES)}
        return [
            cloud_route_to_api(item)
            for item in sorted(cloud_config.get("routes", []), key=lambda item: order.get(str(item.get("stage") or ""), 99))
        ]

    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM ai_gateway_route_policies
            ORDER BY CASE stage
                WHEN 'title_split' THEN 1
                WHEN 'recommendation' THEN 2
                WHEN 'product_attribute' THEN 3
                WHEN 'visual_analysis' THEN 4
                WHEN 'visual_prompt' THEN 5
                WHEN 'image' THEN 6
                ELSE 99
            END
            """
        ).fetchall()
        return [route_to_api(row) for row in rows]


def upsert_route(stage: str, payload: dict[str, Any], *, admin_id: str | None = None) -> dict[str, Any]:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        clean_stage = str(stage or "").strip()
        if not clean_stage:
            raise ValueError("缺少业务阶段")
        now = utc_now_text()
        defaults = {item["stage"]: item for item in DEFAULT_ROUTE_STAGES}.get(clean_stage, {})
        next_item = {
            "stage": clean_stage,
            "title": str(payload.get("title") or defaults.get("title") or clean_stage),
            "modelType": str(payload.get("modelType") or defaults.get("model_type") or "text"),
            "channelOrder": [str(item).strip() for item in payload.get("channelOrder", []) if str(item).strip()],
            "keySelectionPolicy": str(payload.get("keySelectionPolicy") or "least_in_flight_weighted"),
            "maxChannelAttempts": int(payload.get("maxChannelAttempts") or 3),
            "allowCrossChannelFallback": bool(payload.get("allowCrossChannelFallback", True)),
            "enabled": bool(payload.get("enabled", True)),
            "createdAt": now,
            "updatedAt": now,
        }
        routes = cloud_config.setdefault("routes", [])
        for index, item in enumerate(routes):
            if item.get("stage") == clean_stage:
                next_item["createdAt"] = item.get("createdAt") or now
                routes[index] = next_item
                break
        else:
            routes.append(next_item)
        save_cloud_config(cloud_config, updated_by=admin_id)
        return cloud_route_to_api(next_item)

    ensure_schema()
    clean_stage = str(stage or "").strip()
    if not clean_stage:
        raise ValueError("缺少业务阶段")
    now = utc_now_text()
    defaults = {item["stage"]: item for item in DEFAULT_ROUTE_STAGES}.get(clean_stage, {})
    channel_order = [str(item).strip() for item in payload.get("channelOrder", []) if str(item).strip()]
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_gateway_route_policies (
                stage, title, model_type, channel_order_json, key_selection_policy,
                max_channel_attempts, allow_cross_channel_fallback, enabled,
                created_at, updated_at, updated_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stage) DO UPDATE SET
                title = excluded.title,
                model_type = excluded.model_type,
                channel_order_json = excluded.channel_order_json,
                key_selection_policy = excluded.key_selection_policy,
                max_channel_attempts = excluded.max_channel_attempts,
                allow_cross_channel_fallback = excluded.allow_cross_channel_fallback,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (
                clean_stage,
                str(payload.get("title") or defaults.get("title") or clean_stage),
                str(payload.get("modelType") or defaults.get("model_type") or "text"),
                json.dumps(channel_order, ensure_ascii=False),
                str(payload.get("keySelectionPolicy") or "least_in_flight_weighted"),
                int(payload.get("maxChannelAttempts") or 3),
                normalize_bool(payload.get("allowCrossChannelFallback", True)),
                normalize_bool(payload.get("enabled", True)),
                now,
                now,
                str(admin_id or ""),
            ),
        )
        row = conn.execute("SELECT * FROM ai_gateway_route_policies WHERE stage = ?", (clean_stage,)).fetchone()
        return route_to_api(row)


def list_circuits() -> list[dict[str, Any]]:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        state_order = {"open": 1, "half_open": 2, "closed": 3}
        return [
            cloud_circuit_to_api(item)
            for item in sorted(
                cloud_config.get("circuits", []),
                key=lambda item: (state_order.get(str(item.get("state") or "closed"), 9), str(item.get("updatedAt") or "")),
            )
        ]

    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM ai_gateway_circuit_states
            ORDER BY
                CASE state WHEN 'open' THEN 1 WHEN 'half_open' THEN 2 ELSE 3 END,
                updated_at DESC
            """
        ).fetchall()
        return [circuit_to_api(row) for row in rows]


def set_circuit_state(
    *,
    scope_type: str,
    scope_id: str,
    state: str,
    stage: str = "",
    model: str = "",
    updated_by: str | None = None,
    error_message: str = "",
) -> dict[str, Any]:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        clean_state = state if state in {"closed", "open", "half_open"} else "closed"
        now = utc_now_text()
        circuit_id = f"{scope_type}:{scope_id}:{stage}:{model}"
        opened_until = None
        if clean_state == "open" and str(updated_by or "") == "scheduler":
            opened_until = (
                datetime.utcnow() + timedelta(seconds=DEFAULT_CIRCUIT_OPEN_SECONDS)
            ).replace(microsecond=0).isoformat(sep=" ")
        next_item = {
            "id": circuit_id,
            "scopeType": scope_type,
            "scopeId": scope_id,
            "stage": stage,
            "model": model,
            "state": clean_state,
            "failureCount": 0,
            "successCount": 0,
            "openedUntil": opened_until,
            "lastErrorType": "",
            "lastErrorMessage": error_message,
            "lastHttpStatus": None,
            "lastLatencyMs": None,
            "createdAt": now,
            "updatedAt": now,
        }
        circuits = cloud_config.setdefault("circuits", [])
        for index, item in enumerate(circuits):
            if item.get("id") == circuit_id:
                next_item["createdAt"] = item.get("createdAt") or now
                next_item["failureCount"] = 0 if clean_state == "closed" else int(item.get("failureCount") or 0)
                next_item["successCount"] = int(item.get("successCount") or 0)
                circuits[index] = next_item
                break
        else:
            circuits.append(next_item)
        save_cloud_config(cloud_config, updated_by=updated_by)
        return cloud_circuit_to_api(next_item)

    ensure_schema()
    clean_state = state if state in {"closed", "open", "half_open"} else "closed"
    now = utc_now_text()
    circuit_id = f"{scope_type}:{scope_id}:{stage}:{model}"
    opened_until = None
    if clean_state == "open" and str(updated_by or "") == "scheduler":
        opened_until = (
            datetime.utcnow() + timedelta(seconds=DEFAULT_CIRCUIT_OPEN_SECONDS)
        ).replace(microsecond=0).isoformat(sep=" ")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_gateway_circuit_states (
                id, scope_type, scope_id, stage, model, state, failure_count,
                success_count, opened_until, last_error_message, created_at, updated_at, updated_by
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?)
            ON CONFLICT(scope_type, scope_id, stage, model) DO UPDATE SET
                state = excluded.state,
                failure_count = CASE WHEN excluded.state = 'closed' THEN 0 ELSE ai_gateway_circuit_states.failure_count END,
                opened_until = CASE
                    WHEN excluded.state = 'closed' THEN NULL
                    WHEN excluded.opened_until IS NOT NULL THEN excluded.opened_until
                    ELSE ai_gateway_circuit_states.opened_until
                END,
                last_error_message = excluded.last_error_message,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (
                circuit_id,
                scope_type,
                scope_id,
                stage,
                model,
                clean_state,
                opened_until,
                error_message,
                now,
                now,
                str(updated_by or ""),
            ),
        )
        row = conn.execute(
            """
            SELECT * FROM ai_gateway_circuit_states
            WHERE scope_type = ? AND scope_id = ? AND stage = ? AND model = ?
            """,
            (scope_type, scope_id, stage, model),
        ).fetchone()
        return circuit_to_api(row)


def reset_circuit(circuit_id: str, *, updated_by: str | None = None) -> dict[str, Any]:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        now = utc_now_text()
        for item in cloud_config.get("circuits", []):
            if item.get("id") == circuit_id:
                item["state"] = "closed"
                item["failureCount"] = 0
                item["openedUntil"] = None
                item["lastErrorType"] = ""
                item["lastErrorMessage"] = ""
                item["updatedAt"] = now
                save_cloud_config(cloud_config, updated_by=updated_by)
                return cloud_circuit_to_api(item)
        raise ValueError("熔断状态不存在")

    ensure_schema()
    now = utc_now_text()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM ai_gateway_circuit_states WHERE id = ?", (circuit_id,)).fetchone()
        if not row:
            raise ValueError("熔断状态不存在")
        conn.execute(
            """
            UPDATE ai_gateway_circuit_states
            SET state = 'closed', failure_count = 0, opened_until = NULL,
                last_error_type = '', last_error_message = '', updated_at = ?, updated_by = ?
            WHERE id = ?
            """,
            (now, str(updated_by or ""), circuit_id),
        )
        next_row = conn.execute("SELECT * FROM ai_gateway_circuit_states WHERE id = ?", (circuit_id,)).fetchone()
        return circuit_to_api(next_row)


def dry_run(stage: str) -> dict[str, Any]:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        clean_stage = str(stage or "").strip()
        route = next((item for item in cloud_config.get("routes", []) if item.get("stage") == clean_stage), None)
        if not route:
            raise ValueError("未知业务阶段")
        route_api = cloud_route_to_api(route)
        model_type = route_api["modelType"]
        channel_map = {str(item.get("id") or ""): item for item in cloud_config.get("channels", [])}
        ordered_ids = route_api["channelOrder"] or [
            str(item.get("id") or "")
            for item in sorted(
                cloud_config.get("channels", []),
                key=lambda item: (int(item.get("priority") or 0), str(item.get("name") or "")),
            )
        ]
        attempts: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        for channel_id in ordered_ids:
            channel = channel_map.get(channel_id)
            if not channel:
                attempts.append({"channelId": channel_id, "status": "skipped", "reason": "渠道不存在"})
                continue
            capabilities = normalize_capabilities(channel.get("capabilities"))
            required_capability = "image" if model_type == "image" else "chat"
            if not channel.get("enabled", True):
                attempts.append({"channelId": channel_id, "channelName": channel.get("name"), "status": "skipped", "reason": "渠道已停用"})
                continue
            if required_capability not in capabilities:
                attempts.append({"channelId": channel_id, "channelName": channel.get("name"), "status": "skipped", "reason": "能力不匹配"})
                continue
            channel_open = any(
                item.get("scopeType") == "channel"
                and item.get("scopeId") == channel_id
                and item.get("state") == "open"
                and item.get("stage") in ("", clean_stage)
                for item in cloud_config.get("circuits", [])
            )
            if channel_open:
                attempts.append({"channelId": channel_id, "channelName": channel.get("name"), "status": "skipped", "reason": "渠道已熔断"})
                continue
            credentials = sorted(
                [
                    item
                    for item in cloud_config.get("credentials", [])
                    if item.get("channelId") == channel_id and item.get("enabled", True) and item.get("apiKey")
                ],
                key=lambda item: (int(item.get("priority") or 0), -int(item.get("weight") or 1), str(item.get("updatedAt") or "")),
            )
            usable_credentials = []
            for credential in credentials:
                credential_open = any(
                    item.get("scopeType") == "credential"
                    and item.get("scopeId") == credential.get("id")
                    and item.get("state") == "open"
                    and item.get("stage") in ("", clean_stage)
                    for item in cloud_config.get("circuits", [])
                )
                if not credential_open:
                    usable_credentials.append(credential)
            if not usable_credentials:
                attempts.append({"channelId": channel_id, "channelName": channel.get("name"), "status": "skipped", "reason": "没有可用 Key"})
                continue
            credential = usable_credentials[0]
            selected = {
                "channel": cloud_channel_to_api(channel),
                "credential": cloud_credential_to_api(credential),
                "model": resolve_channel_model(channel, clean_stage, model_type),
            }
            attempts.append(
                {
                    "channelId": channel_id,
                    "channelName": channel.get("name"),
                    "credentialId": credential.get("id"),
                    "credentialName": credential.get("name"),
                    "status": "selected",
                    "reason": "可用",
                }
            )
            break
        return {"route": route_api, "selected": selected, "attempts": attempts}

    ensure_schema()
    clean_stage = str(stage or "").strip()
    with get_connection() as conn:
        route = conn.execute("SELECT * FROM ai_gateway_route_policies WHERE stage = ?", (clean_stage,)).fetchone()
        if not route:
            raise ValueError("未知业务阶段")
        route_api = route_to_api(route)
        model_type = route_api["modelType"]
        channel_order = route_api["channelOrder"]
        channels = conn.execute("SELECT * FROM ai_gateway_channels").fetchall()
        channel_map = {row["id"]: row for row in channels}
        ordered_ids = channel_order or [
            row["id"]
            for row in sorted(channels, key=lambda item: (int(item["priority"] or 0), str(item["name"] or "")))
        ]
        attempts: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        for channel_id in ordered_ids:
            channel = channel_map.get(channel_id)
            if not channel:
                attempts.append({"channelId": channel_id, "status": "skipped", "reason": "渠道不存在"})
                continue
            capabilities = parse_json_list(channel["capabilities_json"])
            required_capability = "image" if model_type == "image" else "chat"
            if not channel["enabled"]:
                attempts.append({"channelId": channel_id, "channelName": channel["name"], "status": "skipped", "reason": "渠道已停用"})
                continue
            if required_capability not in capabilities:
                attempts.append({"channelId": channel_id, "channelName": channel["name"], "status": "skipped", "reason": "能力不匹配"})
                continue
            channel_circuit = conn.execute(
                """
                SELECT * FROM ai_gateway_circuit_states
                WHERE scope_type = 'channel' AND scope_id = ? AND stage IN ('', ?) AND state = 'open'
                LIMIT 1
                """,
                (channel_id, clean_stage),
            ).fetchone()
            if channel_circuit:
                attempts.append({"channelId": channel_id, "channelName": channel["name"], "status": "skipped", "reason": "渠道已熔断"})
                continue
            credentials = conn.execute(
                """
                SELECT * FROM ai_gateway_credentials
                WHERE channel_id = ? AND enabled = 1 AND api_key != ''
                ORDER BY priority ASC, weight DESC, updated_at DESC
                """,
                (channel_id,),
            ).fetchall()
            if not credentials:
                attempts.append({"channelId": channel_id, "channelName": channel["name"], "status": "skipped", "reason": "没有可用 Key"})
                continue
            usable_credentials = []
            for credential in credentials:
                credential_circuit = conn.execute(
                    """
                    SELECT * FROM ai_gateway_circuit_states
                    WHERE scope_type = 'credential' AND scope_id = ? AND stage IN ('', ?) AND state = 'open'
                    LIMIT 1
                    """,
                    (credential["id"], clean_stage),
                ).fetchone()
                if not credential_circuit:
                    usable_credentials.append(credential)
            if not usable_credentials:
                attempts.append({"channelId": channel_id, "channelName": channel["name"], "status": "skipped", "reason": "全部 Key 已熔断"})
                continue
            credential = usable_credentials[0]
            selected = {
                "channel": channel_to_api(channel),
                "credential": credential_to_api(credential),
                "model": resolve_channel_model(channel, clean_stage, model_type, local=True),
            }
            attempts.append(
                {
                    "channelId": channel_id,
                    "channelName": channel["name"],
                    "credentialId": credential["id"],
                    "credentialName": credential["name"],
                    "status": "selected",
                    "reason": "可用",
                }
            )
            break
    return {"route": route_api, "selected": selected, "attempts": attempts}


def resolve_candidates(stage: str, *, include_all: bool = False) -> list[dict[str, Any]]:
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        return resolve_cloud_candidates(cloud_config, stage, include_all=include_all)
    return resolve_local_candidates(stage, include_all=include_all)


def resolve_cloud_candidates(config: dict[str, Any], stage: str, *, include_all: bool = False) -> list[dict[str, Any]]:
    clean_stage = str(stage or "").strip()
    route = next((item for item in config.get("routes", []) if item.get("stage") == clean_stage), None)
    if not route or not route.get("enabled", True):
        return []
    route_api = cloud_route_to_api(route)
    model_type = route_api["modelType"]
    required_capability = "image" if model_type == "image" else "chat"
    channel_map = {str(item.get("id") or ""): item for item in config.get("channels", [])}
    ordered_ids = route_api["channelOrder"] or [
        str(item.get("id") or "")
        for item in sorted(config.get("channels", []), key=lambda item: (int(item.get("priority") or 100), str(item.get("name") or "")))
    ]
    candidates: list[dict[str, Any]] = []
    max_attempts = None if include_all else max(1, int(route_api.get("maxChannelAttempts") or 3))
    for channel_id in ordered_ids:
        channel = channel_map.get(channel_id)
        if not channel or not channel.get("enabled", True):
            continue
        if required_capability not in normalize_capabilities(channel.get("capabilities"), model_type=model_type):
            continue
        if is_cloud_scope_open(config, "channel", channel_id, clean_stage):
            continue
        credentials = sorted(
            [
                item
                for item in config.get("credentials", [])
                if item.get("channelId") == channel_id and item.get("enabled", True) and decrypt_secret_value(str(item.get("apiKey") or ""))
            ],
            key=lambda item: (int(item.get("priority") or 100), -int(item.get("weight") or 1), str(item.get("updatedAt") or "")),
        )
        for credential in credentials:
            credential_id = str(credential.get("id") or "")
            if is_cloud_scope_open(config, "credential", credential_id, clean_stage):
                continue
            candidates.append(
                {
                    "stage": clean_stage,
                    "providerType": str(channel.get("providerType") or "openai_compatible"),
                    "channelId": channel_id,
                    "channelName": str(channel.get("name") or channel_id),
                    "credentialId": credential_id,
                    "credentialName": str(credential.get("name") or credential_id),
                    "apiKey": decrypt_secret_value(str(credential.get("apiKey") or "")),
                    "baseUrl": str(channel.get("baseUrl") or "").strip().rstrip("/"),
                    "model": resolve_channel_model(channel, clean_stage, model_type),
                    "modelType": model_type,
                    "priority": int(credential.get("priority") or 100),
                    "weight": max(1, int(credential.get("weight") or 1)),
                    "maxConcurrency": max(0, int(credential.get("maxConcurrency") or 0)),
                    "rpmLimit": max(0, int(credential.get("rpmLimit") or 0)),
                    "dailyLimit": max(0, int(credential.get("dailyLimit") or 0)),
                    "monthlyLimit": max(0, int(credential.get("monthlyLimit") or 0)),
                    "connectTimeoutSeconds": int(channel.get("connectTimeoutSeconds") or 10),
                    "readTimeoutSeconds": int(channel.get("readTimeoutSeconds") or 60),
                }
            )
            if max_attempts and len(candidates) >= max_attempts:
                return candidates
    return candidates


def resolve_local_candidates(stage: str, *, include_all: bool = False) -> list[dict[str, Any]]:
    ensure_schema()
    clean_stage = str(stage or "").strip()
    with get_connection() as conn:
        route = conn.execute("SELECT * FROM ai_gateway_route_policies WHERE stage = ?", (clean_stage,)).fetchone()
        if not route or not route["enabled"]:
            return []
        route_api = route_to_api(route)
        model_type = route_api["modelType"]
        required_capability = "image" if model_type == "image" else "chat"
        channel_order = route_api["channelOrder"]
        channels = conn.execute("SELECT * FROM ai_gateway_channels").fetchall()
        channel_map = {row["id"]: row for row in channels}
        ordered_ids = channel_order or [
            row["id"] for row in sorted(channels, key=lambda item: (int(item["priority"] or 100), str(item["name"] or "")))
        ]
        candidates: list[dict[str, Any]] = []
        max_attempts = None if include_all else max(1, int(route_api.get("maxChannelAttempts") or 3))
        for channel_id in ordered_ids:
            channel = channel_map.get(channel_id)
            if not channel or not channel["enabled"]:
                continue
            if required_capability not in normalize_capabilities(parse_json_list(channel["capabilities_json"]), model_type=model_type):
                continue
            if local_scope_open(conn, "channel", channel_id, clean_stage):
                continue
            credentials = conn.execute(
                """
                SELECT *
                FROM ai_gateway_credentials
                WHERE channel_id = ? AND enabled = 1 AND api_key != ''
                ORDER BY priority ASC, weight DESC, updated_at DESC
                """,
                (channel_id,),
            ).fetchall()
            for credential in credentials:
                credential_id = str(credential["id"] or "")
                if local_scope_open(conn, "credential", credential_id, clean_stage):
                    continue
                api_key = decrypt_secret_value(str(credential["api_key"] or ""))
                if not api_key:
                    continue
                candidates.append(
                    {
                        "stage": clean_stage,
                        "providerType": str(channel["provider_type"] or "openai_compatible"),
                        "channelId": channel_id,
                        "channelName": str(channel["name"] or channel_id),
                        "credentialId": credential_id,
                        "credentialName": str(credential["name"] or credential_id),
                        "apiKey": api_key,
                        "baseUrl": str(channel["base_url"] or "").strip().rstrip("/"),
                        "model": resolve_channel_model(channel, clean_stage, model_type, local=True),
                        "modelType": model_type,
                        "priority": int(credential["priority"] or 100),
                        "weight": max(1, int(credential["weight"] or 1)),
                        "maxConcurrency": max(0, int(credential["max_concurrency"] or 0)),
                        "rpmLimit": max(0, int(credential["rpm_limit"] or 0)),
                        "dailyLimit": max(0, int(credential["daily_limit"] or 0)),
                        "monthlyLimit": max(0, int(credential["monthly_limit"] or 0)),
                        "connectTimeoutSeconds": int(channel["connect_timeout_seconds"] or 10),
                        "readTimeoutSeconds": int(channel["read_timeout_seconds"] or 60),
                    }
                )
                if max_attempts and len(candidates) >= max_attempts:
                    return candidates
        return candidates


def resolve_route_attempt_limit(stage: str) -> int:
    clean_stage = str(stage or "").strip()
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        route = next((item for item in cloud_config.get("routes", []) if item.get("stage") == clean_stage), None)
        if not route:
            return 3
        return max(1, int(cloud_route_to_api(route).get("maxChannelAttempts") or 3))

    ensure_schema()
    with get_connection() as conn:
        route = conn.execute("SELECT * FROM ai_gateway_route_policies WHERE stage = ?", (clean_stage,)).fetchone()
        if not route:
            return 3
        return max(1, int(route_to_api(route).get("maxChannelAttempts") or 3))


def is_cloud_scope_open(config: dict[str, Any], scope_type: str, scope_id: str, stage: str) -> bool:
    now = datetime.utcnow()
    changed = False
    for item in config.get("circuits", []):
        if item.get("scopeType") != scope_type or item.get("scopeId") != scope_id or item.get("stage") not in ("", stage):
            continue
        if item.get("state") != "open":
            continue
        opened_until = parse_datetime_text(item.get("openedUntil"))
        if opened_until and opened_until <= now:
            item["state"] = "half_open"
            item["updatedAt"] = utc_now_text()
            changed = True
            continue
        return True
    if changed:
        save_cloud_config(config, updated_by="circuit-expire")
    return False


def local_scope_open(conn: Any, scope_type: str, scope_id: str, stage: str) -> bool:
    now_text = utc_now_text()
    row = conn.execute(
        """
        SELECT *
        FROM ai_gateway_circuit_states
        WHERE scope_type = ? AND scope_id = ? AND stage IN ('', ?) AND state = 'open'
        LIMIT 1
        """,
        (scope_type, scope_id, stage),
    ).fetchone()
    if not row:
        return False
    opened_until = str(row["opened_until"] or "")
    if opened_until and opened_until <= now_text:
        conn.execute(
            """
            UPDATE ai_gateway_circuit_states
            SET state = 'half_open', updated_at = ?
            WHERE id = ?
            """,
            (now_text, row["id"]),
        )
        return False
    return True


def record_attempt_result(
    candidate: dict[str, Any],
    *,
    success: bool,
    error_message: str = "",
    latency_ms: int | None = None,
) -> None:
    if success:
        close_candidate_circuit(candidate, latency_ms=latency_ms)
        return
    open_candidate_circuit(candidate, error_message=error_message, latency_ms=latency_ms)


def open_candidate_circuit(candidate: dict[str, Any], *, error_message: str, latency_ms: int | None = None) -> None:
    stage = str(candidate.get("stage") or "")
    model = str(candidate.get("model") or "")
    opened_until = (datetime.utcnow() + timedelta(seconds=circuit_open_seconds(error_message))).replace(microsecond=0).isoformat(sep=" ")
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        upsert_cloud_circuit(
            cloud_config,
            scope_type="credential",
            scope_id=str(candidate.get("credentialId") or ""),
            stage=stage,
            model=model,
            state="open",
            error_message=error_message,
            opened_until=opened_until,
            latency_ms=latency_ms,
        )
        save_cloud_config(cloud_config, updated_by="runtime-circuit")
        return
    ensure_schema()
    now = utc_now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_gateway_circuit_states (
                id, scope_type, scope_id, stage, model, state, failure_count,
                success_count, opened_until, last_error_message, last_latency_ms,
                created_at, updated_at, updated_by
            ) VALUES (?, 'credential', ?, ?, ?, 'open', 1, 0, ?, ?, ?, ?, ?, 'runtime-circuit')
            ON CONFLICT(scope_type, scope_id, stage, model) DO UPDATE SET
                state = 'open',
                failure_count = ai_gateway_circuit_states.failure_count + 1,
                opened_until = excluded.opened_until,
                last_error_message = excluded.last_error_message,
                last_latency_ms = excluded.last_latency_ms,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (
                f"credential:{candidate.get('credentialId')}:{stage}:{model}",
                str(candidate.get("credentialId") or ""),
                stage,
                model,
                opened_until,
                str(error_message or "")[:1000],
                latency_ms,
                now,
                now,
            ),
        )


def close_candidate_circuit(candidate: dict[str, Any], *, latency_ms: int | None = None) -> None:
    stage = str(candidate.get("stage") or "")
    model = str(candidate.get("model") or "")
    credential_id = str(candidate.get("credentialId") or "")
    cloud_config = load_cloud_config()
    if cloud_config is not None:
        if not any(
            item.get("scopeType") == "credential"
            and item.get("scopeId") == credential_id
            and item.get("stage") == stage
            and item.get("model") == model
            for item in cloud_config.get("circuits", [])
        ):
            return
        upsert_cloud_circuit(
            cloud_config,
            scope_type="credential",
            scope_id=credential_id,
            stage=stage,
            model=model,
            state="closed",
            error_message="",
            opened_until=None,
            latency_ms=latency_ms,
        )
        save_cloud_config(cloud_config, updated_by="runtime-circuit")
        return
    ensure_schema()
    now = utc_now_text()
    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM ai_gateway_circuit_states
            WHERE scope_type = 'credential' AND scope_id = ? AND stage = ? AND model = ?
            """,
            (credential_id, stage, model),
        ).fetchone()
        if not existing:
            return
        conn.execute(
            """
            INSERT INTO ai_gateway_circuit_states (
                id, scope_type, scope_id, stage, model, state, failure_count,
                success_count, opened_until, last_error_message, last_latency_ms,
                created_at, updated_at, updated_by
            ) VALUES (?, 'credential', ?, ?, ?, 'closed', 0, 1, NULL, '', ?, ?, ?, 'runtime-circuit')
            ON CONFLICT(scope_type, scope_id, stage, model) DO UPDATE SET
                state = 'closed',
                failure_count = 0,
                success_count = ai_gateway_circuit_states.success_count + 1,
                opened_until = NULL,
                last_error_message = '',
                last_latency_ms = excluded.last_latency_ms,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (f"credential:{credential_id}:{stage}:{model}", credential_id, stage, model, latency_ms, now, now),
        )


def upsert_cloud_circuit(
    config: dict[str, Any],
    *,
    scope_type: str,
    scope_id: str,
    stage: str,
    model: str,
    state: str,
    error_message: str,
    opened_until: str | None,
    latency_ms: int | None,
) -> None:
    if not scope_id:
        return
    now = utc_now_text()
    circuit_id = f"{scope_type}:{scope_id}:{stage}:{model}"
    circuits = config.setdefault("circuits", [])
    for item in circuits:
        if item.get("id") == circuit_id:
            item["state"] = state
            item["failureCount"] = 0 if state == "closed" else int(item.get("failureCount") or 0) + 1
            item["successCount"] = int(item.get("successCount") or 0) + (1 if state == "closed" else 0)
            item["openedUntil"] = opened_until
            item["lastErrorMessage"] = str(error_message or "")[:1000]
            item["lastLatencyMs"] = latency_ms
            item["updatedAt"] = now
            return
    circuits.append(
        {
            "id": circuit_id,
            "scopeType": scope_type,
            "scopeId": scope_id,
            "stage": stage,
            "model": model,
            "state": state,
            "failureCount": 0 if state == "closed" else 1,
            "successCount": 1 if state == "closed" else 0,
            "openedUntil": opened_until,
            "lastErrorType": "",
            "lastErrorMessage": str(error_message or "")[:1000],
            "lastHttpStatus": None,
            "lastLatencyMs": latency_ms,
            "createdAt": now,
            "updatedAt": now,
        }
    )


def circuit_open_seconds(error_message: str) -> int:
    text = str(error_message or "").lower()
    if "invalid_api_key" in text or "api key is invalid" in text or "http 401" in text or "permission denied" in text:
        return AUTH_CIRCUIT_OPEN_SECONDS
    if "429" in text or "rate limit" in text or "quota" in text or "too frequent" in text:
        return RATE_LIMIT_CIRCUIT_OPEN_SECONDS
    if "timeout" in text or "timed out" in text or "502" in text or "503" in text or "504" in text:
        return TRANSIENT_CIRCUIT_OPEN_SECONDS
    if "remote end closed" in text or "connection reset" in text or "connection aborted" in text:
        return TRANSIENT_CIRCUIT_OPEN_SECONDS
    return DEFAULT_CIRCUIT_OPEN_SECONDS


def parse_datetime_text(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
