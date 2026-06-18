from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_admin_user
from app.core import config as app_config
from app.core.database import (
    create_managed_user,
    delete_managed_users,
    get_api_usage_summary,
    get_app_settings_map,
    get_user_api_credentials_map,
    get_user_usage_limit,
    list_users,
    reset_managed_user_password,
    update_managed_user,
    upsert_user_usage_limit,
    upsert_user_api_credential,
    upsert_app_setting,
)
from app.modules.admin_prompt_configs import list_admin_prompt_configs

router = APIRouter(prefix="/api/admin", tags=["admin"])


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    category: str
    label: str
    description: str
    default: str = ""
    is_secret: bool = False


@dataclass(frozen=True)
class ApiChannelDefinition:
    id: str
    name: str
    description: str
    default_base_url: str = ""
    default_text_model: str = "gpt-5.5"
    default_image_model: str = "gpt-image-2"
    is_common: bool = False


@dataclass(frozen=True)
class ApiRouteStageDefinition:
    id: str
    title: str
    description: str
    api_key_key: str
    base_url_key: str
    model_key: str
    model_type: str = "text"


SETTING_DEFINITIONS: tuple[SettingDefinition, ...] = (
    SettingDefinition("OPENAI_API_KEY", "ai", "通用 API 密钥", "初凡 AI / OpenAI 兼容 API 密钥", is_secret=True),
    SettingDefinition("OPENAI_BASE_URL", "ai", "通用接口地址", "初凡 AI 地址，例如 https://api.aicoming.top/v1"),
    SettingDefinition("OPENAI_TEXT_MODEL", "ai", "文本模型", "用于标题、关键词、提示词分析", "gpt-5.5"),
    SettingDefinition("OPENAI_TITLE_SPLIT_API_KEY", "ai", "标题拆分 API 密钥", "标题拆分专用 API 密钥，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_TITLE_SPLIT_BASE_URL", "ai", "标题拆分接口地址", "标题拆分专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_TITLE_SPLIT_MODEL", "ai", "标题拆分模型", "用于把商品标题拆成 1688 采购搜索关键词", "gpt-5.5"),
    SettingDefinition("OPENAI_RECOMMENDATION_API_KEY", "ai", "智能推荐 API 密钥", "智能推荐专用 API 密钥，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_RECOMMENDATION_BASE_URL", "ai", "智能推荐接口地址", "智能推荐专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_RECOMMENDATION_MODEL", "ai", "智能推荐模型", "用于商品标题、类目、图片分析和推荐关键词", "gpt-5.5"),
    SettingDefinition("OPENAI_PRODUCT_ATTRIBUTE_API_KEY", "ai", "产品属性 API 密钥", "产品属性填写专用 API 密钥，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_PRODUCT_ATTRIBUTE_BASE_URL", "ai", "产品属性接口地址", "产品属性填写专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_PRODUCT_ATTRIBUTE_MODEL", "ai", "产品属性填写模型", "导出时根据商品类目属性库、商品标题和 SKU 信息填写产品属性", "gpt-5.5"),
    SettingDefinition("OPENAI_VISUAL_ANALYSIS_API_KEY", "ai", "图片理解 API 密钥", "图片理解专用 API 密钥，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_VISUAL_ANALYSIS_BASE_URL", "ai", "图片理解接口地址", "图片理解专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_VISUAL_ANALYSIS_MODEL", "ai", "图片理解模型", "生图前分析主体、材质、结构、风险和画风", "gpt-5.5"),
    SettingDefinition("OPENAI_VISUAL_PROMPT_API_KEY", "ai", "提示词规划 API 密钥", "提示词规划专用 API 密钥，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_VISUAL_PROMPT_BASE_URL", "ai", "提示词规划接口地址", "提示词规划专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_VISUAL_PROMPT_MODEL", "ai", "提示词规划模型", "把分析结果转成九宫格或四宫格母图提示词", "gpt-5.5"),
    SettingDefinition("OPENAI_IMAGE_API_KEY", "ai", "图片生成 API 密钥", "图片生成专用 API 密钥，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_IMAGE_BASE_URL", "ai", "图片生成接口地址", "图片生成专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_IMAGE_MODEL", "ai", "生图模型", "用于 API 生图备选方案", "gpt-image-2-1k"),
    SettingDefinition("OPENAI_IMAGE_QUALITY", "ai", "生图质量", "可填 low / medium / high", "medium"),
    SettingDefinition("VISUAL_DEFAULT_MODE", "visual", "默认生图模式", "main-gallery / sku-gallery / single-refine", "main-gallery"),
    SettingDefinition("VISUAL_DEFAULT_LAYOUT", "visual", "默认母图布局", "1x1 / 2x2 / 3x3，对应单图、四宫格、九宫格", "3x3"),
    SettingDefinition("VISUAL_DEFAULT_REQUESTED_COUNT", "visual", "默认模块数量", "创建任务时默认需要生成的图片数量，1-9", "9"),
    SettingDefinition("VISUAL_IMAGE_SIZE", "visual", "母图生成尺寸", "传给生图模型的尺寸，例如 1024x1024", "1024x1024"),
    SettingDefinition("VISUAL_IMAGE_REQUEST_TIMEOUT_SECONDS", "visual", "生图请求超时秒数", "等待第三方生图接口返回的最长秒数，建议 900", "900"),
    SettingDefinition("VISUAL_ALLOW_SHORT_LABELS", "visual", "允许短文案", "1 表示允许图片里出现安全短英文功能词，0 表示不放文字", "1"),
    SettingDefinition("VISUAL_USE_REFERENCE_IMAGE", "visual", "启用图生图参考", "1 表示使用商品原图作为生图参考，0 表示只用文本提示词", "1"),
    SettingDefinition("VISUAL_UPLOAD_TO_OSS_DEFAULT", "visual", "默认上传 OSS", "1 表示切图后默认上传到 OSS，0 表示只保存本地", "0"),
    SettingDefinition("VISUAL_SPLIT_TARGET_SIZE", "visual", "切图输出尺寸", "每个小图输出的方图尺寸，建议 800", "800"),
    SettingDefinition("VISUAL_SPLIT_FORMAT", "visual", "切图输出格式", "webp / jpg / png", "webp"),
    SettingDefinition("VISUAL_SPLIT_QUALITY", "visual", "切图压缩质量", "1-100，webp/jpg 生效", "92"),
    SettingDefinition("VISUAL_SPLIT_SAFE_MARGIN_RATIO", "visual", "切图安全边距", "每个宫格裁切时避开边缘的比例，建议 0.03", "0.03"),
    SettingDefinition("VISUAL_SPLIT_SHARPEN", "visual", "切图锐化强度", "0 表示不锐化，建议 0.7", "0.7"),
    SettingDefinition("REDIS_URL", "visual", "Redis 连接地址", "Redis 队列/缓存连接地址，例如 redis://127.0.0.1:6379/0", is_secret=True),
    SettingDefinition("VISUAL_QUEUE_REDIS_ENABLED", "visual", "启用 Redis 生图队列", "1 表示启用 Redis 生图任务队列；0 表示使用 FastAPI 后台任务兜底", "0"),
    SettingDefinition("VISUAL_QUEUE_NAME", "visual", "生图任务队列名称", "Redis 中保存生图任务的列表键名", "visual:tasks:queue"),
    SettingDefinition("VISUAL_QUEUE_DRAIN_MAX_JOBS", "visual", "单轮拉取任务数", "自动启动的 Worker 每轮最多拉取的任务数量", "10"),
    SettingDefinition("VISUAL_QUEUE_WORKER_LOCK_SECONDS", "visual", "Worker 锁定时长", "单个 Worker 抢占队列锁的保持秒数", "3600"),
    SettingDefinition("VISUAL_QUEUE_POP_TIMEOUT_SECONDS", "visual", "队列取任务超时", "每次从 Redis 队列等待取出任务的秒数", "1"),
    SettingDefinition("VISUAL_QUEUE_RETRY_NAME", "visual", "生图重试队列名称", "Redis 中保存延迟重试生图任务的有序集合键名", "visual:tasks:retry"),
    SettingDefinition("VISUAL_QUEUE_DEAD_NAME", "visual", "生图失败队列名称", "重试耗尽后保存失败生图任务的 Redis 列表键名", "visual:tasks:dead"),
    SettingDefinition("VISUAL_QUEUE_MAX_RETRIES", "visual", "生图最大重试次数", "单个生图任务失败后最多自动重试的次数", "2"),
    SettingDefinition("VISUAL_QUEUE_RETRY_DELAY_SECONDS", "visual", "生图重试等待秒数", "生图任务失败后等待多久再重试", "30"),
    SettingDefinition("VISUAL_USER_CONCURRENCY_LIMIT", "visual", "成员任务并发限制", "单个成员同时运行的生图任务数量，也控制清单导出时商品链接并行处理数；超过后生图进入等待队列；0 表示不限制", "5"),
    SettingDefinition("VISUAL_TEAM_CONCURRENCY_LIMIT", "visual", "团队并发生图限制", "同一管理员团队同时运行的视觉任务数量；超过后新任务进入等待队列；0 表示不限制", "5"),
    SettingDefinition("TMAPI_API_TOKEN", "1688", "1688 搜图 API Token", "TMAPI 或同类 1688 搜图服务 Token", is_secret=True),
    SettingDefinition("TMAPI_BASE_URL", "1688", "1688 API 接口地址", "默认 http://api.tmapi.top", "http://api.tmapi.top"),
    SettingDefinition("ALIYUN_OSS_ENABLED", "oss", "启用 OSS", "1 表示启用，0 表示关闭", "0"),
    SettingDefinition("ALIYUN_OSS_ACCESS_KEY_ID", "oss", "OSS 访问 ID", "阿里云 OSS 访问 ID", is_secret=True),
    SettingDefinition("ALIYUN_OSS_ACCESS_KEY_SECRET", "oss", "OSS 访问密钥", "阿里云 OSS 访问密钥", is_secret=True),
    SettingDefinition("ALIYUN_OSS_ENDPOINT", "oss", "OSS 节点地址", "例如 oss-cn-beijing.aliyuncs.com"),
    SettingDefinition("ALIYUN_OSS_BUCKET", "oss", "OSS 存储桶", "图片存储桶名称"),
    SettingDefinition("ALIYUN_OSS_PUBLIC_BASE_URL", "oss", "OSS 公网 URL", "不填时按 bucket + endpoint 自动生成"),
    SettingDefinition("ALIYUN_OSS_OBJECT_PREFIX", "oss", "OSS 文件前缀", "图片存储目录前缀", "temu-listing"),
)


API_CHANNEL_DEFINITIONS: tuple[ApiChannelDefinition, ...] = (
    ApiChannelDefinition(
        "chufan_ai",
        "初凡AI",
        "OpenAI / Claude / Gemini 兼容聚合渠道",
        "https://api.aicoming.top/v1",
        "gpt-5.5",
        "gpt-image-2-1k",
    ),
)

API_ROUTE_STAGE_DEFINITIONS: tuple[ApiRouteStageDefinition, ...] = (
    ApiRouteStageDefinition(
        "title_split",
        "标题拆分",
        "把商品标题拆成 1688 采购搜索关键词",
        "OPENAI_TITLE_SPLIT_API_KEY",
        "OPENAI_TITLE_SPLIT_BASE_URL",
        "OPENAI_TITLE_SPLIT_MODEL",
    ),
    ApiRouteStageDefinition(
        "recommendation",
        "智能推荐",
        "商品标题、类目、图片分析和推荐关键词",
        "OPENAI_RECOMMENDATION_API_KEY",
        "OPENAI_RECOMMENDATION_BASE_URL",
        "OPENAI_RECOMMENDATION_MODEL",
    ),
    ApiRouteStageDefinition(
        "product_attribute",
        "产品属性填写",
        "导出时根据类目属性库和商品信息填写属性",
        "OPENAI_PRODUCT_ATTRIBUTE_API_KEY",
        "OPENAI_PRODUCT_ATTRIBUTE_BASE_URL",
        "OPENAI_PRODUCT_ATTRIBUTE_MODEL",
    ),
    ApiRouteStageDefinition(
        "visual_analysis",
        "图片理解",
        "生图前分析主体、材质、结构、风险和画风",
        "OPENAI_VISUAL_ANALYSIS_API_KEY",
        "OPENAI_VISUAL_ANALYSIS_BASE_URL",
        "OPENAI_VISUAL_ANALYSIS_MODEL",
    ),
    ApiRouteStageDefinition(
        "visual_prompt",
        "提示词规划",
        "把分析结果转成九宫格或四宫格母图提示词",
        "OPENAI_VISUAL_PROMPT_API_KEY",
        "OPENAI_VISUAL_PROMPT_BASE_URL",
        "OPENAI_VISUAL_PROMPT_MODEL",
    ),
    ApiRouteStageDefinition(
        "image",
        "图片生成",
        "实际生成母图、单图精修和 SKU 适配图",
        "OPENAI_IMAGE_API_KEY",
        "OPENAI_IMAGE_BASE_URL",
        "OPENAI_IMAGE_MODEL",
        "image",
    ),
)


LEGACY_TITLE_SETTING_KEYS = {
    "OPENAI_TITLE_API_KEY",
    "OPENAI_TITLE_BASE_URL",
    "OPENAI_TITLE_MODEL",
}
LEGACY_TITLE_STAGE_IDS = {"title"}


def visible_setting_definitions() -> tuple[SettingDefinition, ...]:
    return tuple(definition for definition in SETTING_DEFINITIONS if definition.key not in LEGACY_TITLE_SETTING_KEYS)


def active_api_route_stage_definitions() -> tuple[ApiRouteStageDefinition, ...]:
    return tuple(definition for definition in API_ROUTE_STAGE_DEFINITIONS if definition.id not in LEGACY_TITLE_STAGE_IDS)


class AdminUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2)
    password: str = Field(..., min_length=6)
    displayName: str | None = None
    role: str = "user"
    status: str = "active"
    managerId: str | None = None


class AdminUserUpdateRequest(BaseModel):
    displayName: str | None = None
    role: str | None = None
    status: str | None = None
    managerId: str | None = None


class AdminPasswordResetRequest(BaseModel):
    password: str = Field(..., min_length=6)


class AdminUserUsageLimitUpdateRequest(BaseModel):
    monthlyApiCallLimit: int = Field(0, ge=0)


class AdminSettingUpdateItem(BaseModel):
    key: str
    value: str | None = None
    clear: bool = False


class AdminSettingsUpdateRequest(BaseModel):
    items: list[AdminSettingUpdateItem]


class AdminApiChannelUpdateItem(BaseModel):
    id: str
    name: str | None = None
    enabled: bool | None = None
    apiKey: str | None = None
    clearApiKey: bool = False
    baseUrl: str | None = None
    textModel: str | None = None
    imageModel: str | None = None


class AdminApiChannelsUpdateRequest(BaseModel):
    items: list[AdminApiChannelUpdateItem]


class AdminUserApiCredentialUpdateItem(BaseModel):
    channelId: str
    enabled: bool | None = None
    apiKey: str | None = None
    clearApiKey: bool = False
    baseUrl: str | None = None
    textModel: str | None = None
    imageModel: str | None = None


class AdminUserApiCredentialsUpdateRequest(BaseModel):
    items: list[AdminUserApiCredentialUpdateItem]


class AdminUsersBatchDeleteRequest(BaseModel):
    userIds: list[str]


class AdminApiRouteApplyRequest(BaseModel):
    stage: str
    channelId: str
    model: str | None = None


class AdminApiRoutesApplyRequest(BaseModel):
    channelId: str
    textModel: str | None = None
    imageModel: str | None = None


@router.get("/users")
def admin_list_users(_admin: dict[str, Any] = Depends(require_admin_user)):
    return {"items": list_users()}


@router.post("/users")
def admin_create_user(payload: AdminUserCreateRequest, admin: dict[str, Any] = Depends(require_admin_user)):
    try:
        user = create_managed_user(
            username=payload.username,
            password=payload.password,
            display_name=payload.displayName,
            role=payload.role,
            status=payload.status,
            manager_user_id=payload.managerId if payload.managerId is not None else admin["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": user}


@router.patch("/users/{user_id}")
def admin_update_user(
    user_id: str,
    payload: AdminUserUpdateRequest,
    _admin: dict[str, Any] = Depends(require_admin_user),
):
    try:
        user = update_managed_user(
            user_id,
            display_name=payload.displayName,
            role=payload.role,
            status=payload.status,
            manager_user_id=payload.managerId,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": user}


@router.post("/users/batch-delete")
def admin_batch_delete_users(
    payload: AdminUsersBatchDeleteRequest,
    admin: dict[str, Any] = Depends(require_admin_user),
):
    try:
        return delete_managed_users(payload.userIds, requested_by_user_id=str(admin["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/users/{user_id}/password")
def admin_reset_user_password(
    user_id: str,
    payload: AdminPasswordResetRequest,
    _admin: dict[str, Any] = Depends(require_admin_user),
):
    try:
        user = reset_managed_user_password(user_id, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": user}


@router.get("/users/{user_id}/usage-limit")
def admin_user_usage_limit(user_id: str, _admin: dict[str, Any] = Depends(require_admin_user)):
    try:
        return {"limit": get_user_usage_limit(user_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/users/{user_id}/usage-limit")
def admin_update_user_usage_limit(
    user_id: str,
    payload: AdminUserUsageLimitUpdateRequest,
    admin: dict[str, Any] = Depends(require_admin_user),
):
    try:
        return {
            "limit": upsert_user_usage_limit(
                user_id=user_id,
                monthly_api_call_limit=payload.monthlyApiCallLimit,
                updated_by=str(admin["id"]),
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/users/{user_id}/api-credentials")
def admin_user_api_credentials(user_id: str, _admin: dict[str, Any] = Depends(require_admin_user)):
    return {"items": serialize_user_api_credentials(user_id)}


@router.put("/users/{user_id}/api-credentials")
def admin_update_user_api_credentials(
    user_id: str,
    payload: AdminUserApiCredentialsUpdateRequest,
    admin: dict[str, Any] = Depends(require_admin_user),
):
    definitions = {definition.id: definition for definition in API_CHANNEL_DEFINITIONS}
    try:
        for item in payload.items:
            channel_id = normalize_api_identifier(item.channelId)
            definition = definitions.get(channel_id)
            if not definition:
                raise HTTPException(status_code=400, detail=f"未知 API 渠道：{item.channelId}")
            upsert_user_api_credential(
                user_id=user_id,
                channel_id=definition.id,
                api_key=item.apiKey,
                clear_api_key=item.clearApiKey,
                base_url=item.baseUrl,
                text_model=normalize_channel_text_model(definition, item.textModel) if item.textModel is not None else None,
                image_model=normalize_channel_image_model(definition, item.imageModel) if item.imageModel is not None else None,
                enabled=item.enabled,
                updated_by=admin["id"],
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": serialize_user_api_credentials(user_id)}


@router.get("/settings")
def admin_list_settings(_admin: dict[str, Any] = Depends(require_admin_user)):
    saved_settings = get_app_settings_map()
    return {"items": [serialize_setting(definition, saved_settings.get(definition.key)) for definition in visible_setting_definitions()]}


@router.get("/api-usage")
def admin_api_usage_summary(_admin: dict[str, Any] = Depends(require_admin_user)):
    return get_api_usage_summary()


@router.get("/api-channels")
def admin_api_channels(_admin: dict[str, Any] = Depends(require_admin_user)):
    return serialize_api_channel_bundle()


@router.get("/prompt-configs")
def admin_prompt_configs(_admin: dict[str, Any] = Depends(require_admin_user)):
    return {"items": list_admin_prompt_configs()}


@router.put("/api-channels")
def admin_update_api_channels(
    payload: AdminApiChannelsUpdateRequest,
    admin: dict[str, Any] = Depends(require_admin_user),
):
    definitions = {definition.id: definition for definition in API_CHANNEL_DEFINITIONS}
    for item in payload.items:
        definition = definitions.get(normalize_api_identifier(item.id))
        if not definition:
            raise HTTPException(status_code=400, detail=f"未知 API 渠道：{item.id}")
        update_api_channel(definition, item, admin["id"])
        if item.enabled is True:
            disable_other_api_channels(definition.id, admin["id"])
    return serialize_api_channel_bundle()


@router.post("/api-channels/apply")
def admin_apply_api_channel(
    payload: AdminApiRouteApplyRequest,
    admin: dict[str, Any] = Depends(require_admin_user),
):
    stage = {definition.id: definition for definition in active_api_route_stage_definitions()}.get(
        normalize_api_identifier(payload.stage)
    )
    if not stage:
        raise HTTPException(status_code=400, detail=f"未知能力：{payload.stage}")

    channel = {definition.id: definition for definition in API_CHANNEL_DEFINITIONS}.get(
        normalize_api_identifier(payload.channelId)
    )
    if not channel:
        raise HTTPException(status_code=400, detail=f"未知 API 渠道：{payload.channelId}")

    saved_settings = get_app_settings_map()
    channel_values = api_channel_runtime_values(channel, saved_settings)
    apply_api_channel_to_stage(stage, channel, channel_values, admin["id"])
    return serialize_api_channel_bundle()


@router.post("/api-channels/apply-all")
def admin_apply_api_channel_to_all(
    payload: AdminApiRoutesApplyRequest,
    admin: dict[str, Any] = Depends(require_admin_user),
):
    channel = {definition.id: definition for definition in API_CHANNEL_DEFINITIONS}.get(
        normalize_api_identifier(payload.channelId)
    )
    if not channel:
        raise HTTPException(status_code=400, detail=f"未知 API 渠道：{payload.channelId}")

    saved_settings = get_app_settings_map()
    channel_values = api_channel_runtime_values(channel, saved_settings)
    for stage in active_api_route_stage_definitions():
        apply_api_channel_to_stage(stage, channel, channel_values, admin["id"])
    return serialize_api_channel_bundle()


@router.put("/settings")
def admin_update_settings(
    payload: AdminSettingsUpdateRequest,
    admin: dict[str, Any] = Depends(require_admin_user),
):
    definitions = {definition.key: definition for definition in visible_setting_definitions()}
    saved_settings = get_app_settings_map()
    updated = []
    for item in payload.items:
        definition = definitions.get(item.key)
        if not definition:
            raise HTTPException(status_code=400, detail=f"未知配置项：{item.key}")

        existing = saved_settings.get(definition.key)
        existing_value = str(existing.get("value", "")) if existing else ""
        if definition.is_secret and item.value in (None, "") and not item.clear:
            continue
        next_value = "" if item.clear else str(item.value or "")
        updated_setting = upsert_app_setting(
            key=definition.key,
            value=next_value,
            category=definition.category,
            label=definition.label,
            description=definition.description,
            is_secret=definition.is_secret,
            updated_by=admin["id"],
        )
        saved_settings[definition.key] = updated_setting
        updated.append(serialize_setting(definition, updated_setting, previous_value=existing_value))

    return {
        "items": [serialize_setting(definition, saved_settings.get(definition.key)) for definition in visible_setting_definitions()],
        "updated": updated,
    }


def serialize_setting(
    definition: SettingDefinition,
    saved: dict[str, Any] | None,
    *,
    previous_value: str = "",
) -> dict[str, Any]:
    saved_value = str(saved.get("value", "")) if saved else ""
    env_value = get_env_config_value(definition.key)
    effective_value = saved_value if saved is not None else env_value or definition.default
    configured = bool(effective_value)
    source = "database" if saved is not None else ("env" if env_value else "default")
    display_value = "" if definition.is_secret else effective_value
    masked_value = mask_secret(effective_value or previous_value) if definition.is_secret and configured else ""
    return {
        "key": definition.key,
        "category": definition.category,
        "label": definition.label,
        "description": definition.description,
        "value": display_value,
        "maskedValue": masked_value,
        "isSecret": definition.is_secret,
        "configured": configured,
        "source": source,
        "updatedAt": saved.get("updatedAt") if saved else None,
    }


def serialize_api_channel_bundle() -> dict[str, Any]:
    saved_settings = get_app_settings_map()
    channels = [serialize_api_channel(definition, saved_settings) for definition in API_CHANNEL_DEFINITIONS]
    routes = [serialize_api_route(stage, saved_settings) for stage in active_api_route_stage_definitions()]
    return {"channels": channels, "routes": routes}


def serialize_api_channel(definition: ApiChannelDefinition, saved_settings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    values = api_channel_runtime_values(definition, saved_settings)
    return {
        "id": definition.id,
        "name": values["name"],
        "description": definition.description,
        "enabled": values["enabled"],
        "baseUrl": values["baseUrl"],
        "textModel": values["textModel"],
        "imageModel": values["imageModel"],
        "apiKeyConfigured": bool(values["apiKey"]),
        "maskedApiKey": mask_secret(values["apiKey"]) if values["apiKey"] else "",
        "isCommon": definition.is_common,
    }


def serialize_user_api_credentials(user_id: str) -> list[dict[str, Any]]:
    saved_credentials = get_user_api_credentials_map(user_id)
    saved_settings = get_app_settings_map()
    items: list[dict[str, Any]] = []
    for definition in API_CHANNEL_DEFINITIONS:
        channel_values = api_channel_runtime_values(definition, saved_settings)
        saved = saved_credentials.get(definition.id) or {}
        api_key = str(saved.get("apiKey") or "")
        use_saved_runtime_values = bool(api_key)
        text_model = normalize_channel_text_model(
            definition,
            str(
                saved.get("textModel")
                if use_saved_runtime_values and saved.get("textModel")
                else channel_values["textModel"]
            ),
        )
        image_model = normalize_channel_image_model(
            definition,
            str(
                saved.get("imageModel")
                if use_saved_runtime_values and saved.get("imageModel")
                else channel_values["imageModel"]
            ),
        )
        items.append(
            {
                "userId": user_id,
                "channelId": definition.id,
                "name": channel_values["name"],
                "description": definition.description,
                "enabled": bool(saved.get("enabled")) and bool(api_key),
                "baseUrl": str(
                    saved.get("baseUrl")
                    if use_saved_runtime_values and saved.get("baseUrl")
                    else channel_values["baseUrl"]
                ).rstrip("/"),
                "textModel": text_model,
                "imageModel": image_model,
                "apiKeyConfigured": bool(api_key),
                "maskedApiKey": mask_secret(api_key) if api_key else "",
                "updatedAt": saved.get("updatedAt"),
            }
        )
    return items


def serialize_api_route(stage: ApiRouteStageDefinition, saved_settings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    common_channel = common_api_runtime_values(saved_settings)
    specific_api_key = setting_runtime_value(saved_settings, stage.api_key_key, "")
    specific_base_url = setting_runtime_value(saved_settings, stage.base_url_key, "")
    specific_model = setting_runtime_value(saved_settings, stage.model_key, "")
    fallback_model = common_channel["imageModel"] if stage.model_type == "image" else common_channel["textModel"]
    effective_model = specific_model or fallback_model
    is_inherited = not (specific_api_key or specific_base_url or specific_model)
    active_channel_definition, active_channel_values = active_admin_api_channel_values(saved_settings)
    if active_channel_definition and active_channel_values:
        return {
            "stage": stage.id,
            "title": stage.title,
            "description": stage.description,
            "modelType": stage.model_type,
            "channelId": active_channel_definition.id,
            "channelName": active_channel_values["name"],
            "model": effective_model,
            "baseUrl": active_channel_values["baseUrl"],
            "apiKeyConfigured": bool(active_channel_values["apiKey"]),
            "isInherited": is_inherited,
        }

    effective_api_key = specific_api_key or common_channel["apiKey"]
    effective_base_url = specific_base_url or common_channel["baseUrl"]
    channel_id = "inherited" if is_inherited else "manual"
    channel_name = "继承运行配置" if is_inherited else "手动配置"

    if not is_inherited:
        for channel_definition in API_CHANNEL_DEFINITIONS:
            channel_values = api_channel_runtime_values(channel_definition, saved_settings)
            if not channel_values["enabled"]:
                continue
            if channel_values["apiKey"] and channel_values["apiKey"] == effective_api_key and channel_values["baseUrl"] == effective_base_url:
                channel_id = channel_definition.id
                channel_name = channel_values["name"]
                break

    return {
        "stage": stage.id,
        "title": stage.title,
        "description": stage.description,
        "modelType": stage.model_type,
        "channelId": channel_id,
        "channelName": channel_name,
        "model": effective_model,
        "baseUrl": effective_base_url,
        "apiKeyConfigured": bool(effective_api_key),
        "isInherited": is_inherited,
    }


def active_admin_api_channel_values(
    saved_settings: dict[str, dict[str, Any]],
) -> tuple[ApiChannelDefinition | None, dict[str, Any] | None]:
    for definition in API_CHANNEL_DEFINITIONS:
        if definition.is_common:
            continue
        values = api_channel_runtime_values(definition, saved_settings)
        if values["enabled"] and values["apiKey"] and values["baseUrl"]:
            return definition, values
    return None, None


def common_api_runtime_values(saved_settings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": "运行配置",
        "enabled": True,
        "apiKey": setting_runtime_value(saved_settings, "OPENAI_API_KEY", ""),
        "baseUrl": setting_runtime_value(saved_settings, "OPENAI_BASE_URL", app_config.OPENAI_BASE_URL),
        "textModel": setting_runtime_value(saved_settings, "OPENAI_TEXT_MODEL", app_config.OPENAI_TEXT_MODEL),
        "imageModel": setting_runtime_value(saved_settings, "OPENAI_IMAGE_MODEL", app_config.OPENAI_IMAGE_MODEL),
    }


def api_channel_runtime_values(
    definition: ApiChannelDefinition,
    saved_settings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if definition.is_common:
        return {
            "name": definition.name,
            "enabled": True,
            "apiKey": setting_runtime_value(saved_settings, "OPENAI_API_KEY", ""),
            "baseUrl": setting_runtime_value(saved_settings, "OPENAI_BASE_URL", app_config.OPENAI_BASE_URL),
            "textModel": setting_runtime_value(saved_settings, "OPENAI_TEXT_MODEL", definition.default_text_model),
            "imageModel": setting_runtime_value(saved_settings, "OPENAI_IMAGE_MODEL", definition.default_image_model),
        }
    values = {
        "name": setting_runtime_value(saved_settings, api_channel_setting_key(definition, "NAME"), definition.name),
        "enabled": parse_enabled(setting_runtime_value(saved_settings, api_channel_setting_key(definition, "ENABLED"), "0")),
        "apiKey": setting_runtime_value(saved_settings, api_channel_setting_key(definition, "API_KEY"), ""),
        "baseUrl": setting_runtime_value(
            saved_settings,
            api_channel_setting_key(definition, "BASE_URL"),
            definition.default_base_url,
        ).rstrip("/"),
        "textModel": setting_runtime_value(
            saved_settings,
            api_channel_setting_key(definition, "TEXT_MODEL"),
            definition.default_text_model,
        ),
        "imageModel": setting_runtime_value(
            saved_settings,
            api_channel_setting_key(definition, "IMAGE_MODEL"),
            definition.default_image_model,
        ),
    }
    values["textModel"] = normalize_channel_text_model(definition, values["textModel"])
    values["imageModel"] = normalize_channel_image_model(definition, values["imageModel"])
    return values


def update_api_channel(
    definition: ApiChannelDefinition,
    item: AdminApiChannelUpdateItem,
    admin_id: str,
) -> None:
    if definition.is_common:
        if item.apiKey:
            upsert_defined_setting("OPENAI_API_KEY", item.apiKey.strip(), admin_id)
        elif item.clearApiKey:
            upsert_defined_setting("OPENAI_API_KEY", "", admin_id)
        if item.baseUrl is not None:
            upsert_defined_setting("OPENAI_BASE_URL", item.baseUrl.strip().rstrip("/"), admin_id)
        if item.textModel is not None:
            upsert_defined_setting("OPENAI_TEXT_MODEL", normalize_channel_text_model(definition, item.textModel), admin_id)
        if item.imageModel is not None:
            upsert_defined_setting("OPENAI_IMAGE_MODEL", normalize_channel_image_model(definition, item.imageModel), admin_id)
        return

    if item.name is not None:
        upsert_app_setting(
            key=api_channel_setting_key(definition, "NAME"),
            value=item.name.strip() or definition.name,
            category="ai_channel",
            label=f"{definition.name} 名称",
            description="管理员后台 API 渠道名称",
            updated_by=admin_id,
        )
    if item.enabled is not None:
        upsert_app_setting(
            key=api_channel_setting_key(definition, "ENABLED"),
            value="1" if item.enabled else "0",
            category="ai_channel",
            label=f"{definition.name} 启用状态",
            description="1 表示启用，0 表示停用",
            updated_by=admin_id,
        )
    if item.apiKey:
        upsert_app_setting(
            key=api_channel_setting_key(definition, "API_KEY"),
            value=item.apiKey.strip(),
            category="ai_channel",
            label=f"{definition.name} API 密钥",
            description="管理员后台 API 渠道密钥",
            is_secret=True,
            updated_by=admin_id,
        )
    elif item.clearApiKey:
        upsert_app_setting(
            key=api_channel_setting_key(definition, "API_KEY"),
            value="",
            category="ai_channel",
            label=f"{definition.name} API 密钥",
            description="管理员后台 API 渠道密钥",
            is_secret=True,
            updated_by=admin_id,
        )
    if item.baseUrl is not None:
        upsert_app_setting(
            key=api_channel_setting_key(definition, "BASE_URL"),
            value=item.baseUrl.strip().rstrip("/"),
            category="ai_channel",
            label=f"{definition.name} 接口地址",
            description="OpenAI 兼容接口地址",
            updated_by=admin_id,
        )
    if item.textModel is not None:
        upsert_app_setting(
            key=api_channel_setting_key(definition, "TEXT_MODEL"),
            value=normalize_channel_text_model(definition, item.textModel),
            category="ai_channel",
            label=f"{definition.name} 文本模型",
            description="该渠道默认文本/视觉理解模型",
            updated_by=admin_id,
        )
    if item.imageModel is not None:
        upsert_app_setting(
            key=api_channel_setting_key(definition, "IMAGE_MODEL"),
            value=normalize_channel_image_model(definition, item.imageModel),
            category="ai_channel",
            label=f"{definition.name} 生图模型",
            description="该渠道默认图片生成模型",
            updated_by=admin_id,
        )


def disable_other_api_channels(active_channel_id: str, admin_id: str) -> None:
    for definition in API_CHANNEL_DEFINITIONS:
        if definition.is_common or definition.id == active_channel_id:
            continue
        upsert_app_setting(
            key=api_channel_setting_key(definition, "ENABLED"),
            value="0",
            category="ai_channel",
            label=f"{definition.name} 启用状态",
            description="1 表示启用，0 表示停用",
            updated_by=admin_id,
        )


def apply_api_channel_to_stage(
    stage: ApiRouteStageDefinition,
    channel: ApiChannelDefinition,
    channel_values: dict[str, Any],
    admin_id: str,
) -> None:
    if channel.is_common:
        upsert_defined_setting(stage.api_key_key, "", admin_id)
        upsert_defined_setting(stage.base_url_key, "", admin_id)
        return

    if not channel_values["apiKey"]:
        raise HTTPException(status_code=400, detail=f"{channel_values['name']} 还没有配置 API 密钥")
    if not channel_values["baseUrl"]:
        raise HTTPException(status_code=400, detail=f"{channel_values['name']} 还没有配置接口地址")

    upsert_defined_setting(stage.api_key_key, channel_values["apiKey"], admin_id)
    upsert_defined_setting(stage.base_url_key, channel_values["baseUrl"], admin_id)


def upsert_defined_setting(key: str, value: str, admin_id: str) -> None:
    definition = {definition.key: definition for definition in SETTING_DEFINITIONS}.get(key)
    if not definition:
        raise HTTPException(status_code=400, detail=f"未知配置项：{key}")
    upsert_app_setting(
        key=definition.key,
        value=value,
        category=definition.category,
        label=definition.label,
        description=definition.description,
        is_secret=definition.is_secret,
        updated_by=admin_id,
    )


def setting_runtime_value(saved_settings: dict[str, dict[str, Any]], key: str, default: str = "") -> str:
    saved = saved_settings.get(key)
    saved_value = str(saved.get("value", "")) if saved else ""
    if saved_value:
        return saved_value
    env_value = get_env_config_value(key)
    if env_value:
        return env_value
    return str(default or "")


def api_channel_setting_key(definition: ApiChannelDefinition, field: str) -> str:
    return f"AI_CHANNEL_{definition.id.upper()}_{field}"


def normalize_api_identifier(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def normalize_channel_text_model(definition: ApiChannelDefinition, model: str) -> str:
    clean_model = str(model or "").strip()
    if definition.id == "chufan_ai" and clean_model == "deepseek-v4-pro":
        return "gpt-5.5"
    return clean_model


def normalize_channel_image_model(definition: ApiChannelDefinition, model: str) -> str:
    clean_model = str(model or "").strip()
    if definition.id == "chufan_ai" and clean_model == "gpt-image-2":
        return "gpt-image-2-1k"
    return clean_model


def parse_enabled(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def get_env_config_value(key: str) -> str:
    if key in os.environ:
        return os.getenv(key, "").strip()
    value = getattr(app_config, key, "")
    if isinstance(value, bool):
        return "1" if value else ""
    return str(value or "").strip()


def mask_secret(value: str) -> str:
    clean_value = str(value or "")
    if not clean_value:
        return ""
    if len(clean_value) <= 8:
        return "••••"
    return f"{clean_value[:4]}••••{clean_value[-4:]}"
