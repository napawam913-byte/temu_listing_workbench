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
    get_app_settings_map,
    list_users,
    reset_managed_user_password,
    update_managed_user,
    upsert_app_setting,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    category: str
    label: str
    description: str
    default: str = ""
    is_secret: bool = False


SETTING_DEFINITIONS: tuple[SettingDefinition, ...] = (
    SettingDefinition("OPENAI_API_KEY", "ai", "OpenAI API Key", "FluAPI / OpenAI 兼容 API 密钥", is_secret=True),
    SettingDefinition("OPENAI_BASE_URL", "ai", "OpenAI Base URL", "FluAPI 地址，例如 https://svip.fluapi.com/v1"),
    SettingDefinition("OPENAI_TEXT_MODEL", "ai", "文本模型", "用于标题、关键词、提示词分析", "gpt-5.5"),
    SettingDefinition("OPENAI_TITLE_API_KEY", "ai", "Title API Key", "标题生成专用 API Key，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_TITLE_BASE_URL", "ai", "Title Base URL", "标题生成专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_TITLE_MODEL", "ai", "标题生成模型", "用于中文标题、英文标题、变种值英文翻译", "gpt-5.5"),
    SettingDefinition("OPENAI_RECOMMENDATION_API_KEY", "ai", "Recommendation API Key", "智能推荐专用 API Key，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_RECOMMENDATION_BASE_URL", "ai", "Recommendation Base URL", "智能推荐专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_RECOMMENDATION_MODEL", "ai", "智能推荐模型", "用于商品标题、类目、图片分析和推荐关键词", "gpt-5.5"),
    SettingDefinition("OPENAI_PRODUCT_ATTRIBUTE_API_KEY", "ai", "Product Attribute API Key", "产品属性填写专用 API Key，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_PRODUCT_ATTRIBUTE_BASE_URL", "ai", "Product Attribute Base URL", "产品属性填写专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_PRODUCT_ATTRIBUTE_MODEL", "ai", "产品属性填写模型", "导出时根据商品类目属性库、商品标题和 SKU 信息填写产品属性", "gpt-5.5"),
    SettingDefinition("OPENAI_VISUAL_ANALYSIS_API_KEY", "ai", "Visual Analysis API Key", "图片理解专用 API Key，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_VISUAL_ANALYSIS_BASE_URL", "ai", "Visual Analysis Base URL", "图片理解专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_VISUAL_ANALYSIS_MODEL", "ai", "图片理解模型", "生图前分析主体、材质、结构、风险和画风", "gpt-5.5"),
    SettingDefinition("OPENAI_VISUAL_PROMPT_API_KEY", "ai", "Prompt Plan API Key", "提示词规划专用 API Key，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_VISUAL_PROMPT_BASE_URL", "ai", "Prompt Plan Base URL", "提示词规划专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_VISUAL_PROMPT_MODEL", "ai", "提示词规划模型", "把分析结果转成九宫格或四宫格母图提示词", "gpt-5.5"),
    SettingDefinition("OPENAI_IMAGE_API_KEY", "ai", "Image API Key", "图片生成专用 API Key，留空继承通用 OPENAI_API_KEY", is_secret=True),
    SettingDefinition("OPENAI_IMAGE_BASE_URL", "ai", "Image Base URL", "图片生成专用接口地址，留空继承通用 OPENAI_BASE_URL"),
    SettingDefinition("OPENAI_IMAGE_MODEL", "ai", "生图模型", "用于 API 生图备选方案", "gpt-image-2"),
    SettingDefinition("OPENAI_IMAGE_QUALITY", "ai", "生图质量", "low / medium / high", "medium"),
    SettingDefinition("VISUAL_DEFAULT_MODE", "visual", "默认生图模式", "main-gallery / sku-gallery / single-refine", "main-gallery"),
    SettingDefinition("VISUAL_DEFAULT_LAYOUT", "visual", "默认母图布局", "1x1 / 2x2 / 3x3，对应单图、四宫格、九宫格", "3x3"),
    SettingDefinition("VISUAL_DEFAULT_REQUESTED_COUNT", "visual", "默认模块数量", "创建任务时默认需要生成的图片数量，1-9", "9"),
    SettingDefinition("VISUAL_IMAGE_SIZE", "visual", "母图生成尺寸", "传给生图模型的尺寸，例如 1024x1024", "1024x1024"),
    SettingDefinition("VISUAL_ALLOW_SHORT_LABELS", "visual", "允许短文案", "1 表示允许图片里出现安全短英文功能词，0 表示不放文字", "1"),
    SettingDefinition("VISUAL_USE_REFERENCE_IMAGE", "visual", "启用图生图参考", "1 表示使用商品原图作为生图参考，0 表示只用文本提示词", "1"),
    SettingDefinition("VISUAL_UPLOAD_TO_OSS_DEFAULT", "visual", "默认上传 OSS", "1 表示切图后默认上传到 OSS，0 表示只保存本地", "0"),
    SettingDefinition("VISUAL_SPLIT_TARGET_SIZE", "visual", "切图输出尺寸", "每个小图输出的方图尺寸，建议 800", "800"),
    SettingDefinition("VISUAL_SPLIT_FORMAT", "visual", "切图输出格式", "webp / jpg / png", "webp"),
    SettingDefinition("VISUAL_SPLIT_QUALITY", "visual", "切图压缩质量", "1-100，webp/jpg 生效", "92"),
    SettingDefinition("VISUAL_SPLIT_SAFE_MARGIN_RATIO", "visual", "切图安全边距", "每个宫格裁切时避开边缘的比例，建议 0.03", "0.03"),
    SettingDefinition("VISUAL_SPLIT_SHARPEN", "visual", "切图锐化强度", "0 表示不锐化，建议 0.7", "0.7"),
    SettingDefinition("TMAPI_API_TOKEN", "1688", "1688 搜图 API Token", "TMAPI 或同类 1688 搜图服务 Token", is_secret=True),
    SettingDefinition("TMAPI_BASE_URL", "1688", "1688 API Base URL", "默认 http://api.tmapi.top", "http://api.tmapi.top"),
    SettingDefinition("ALIYUN_OSS_ENABLED", "oss", "启用 OSS", "1 表示启用，0 表示关闭", "0"),
    SettingDefinition("ALIYUN_OSS_ACCESS_KEY_ID", "oss", "OSS AccessKey ID", "阿里云 OSS 访问 ID", is_secret=True),
    SettingDefinition("ALIYUN_OSS_ACCESS_KEY_SECRET", "oss", "OSS AccessKey Secret", "阿里云 OSS 访问密钥", is_secret=True),
    SettingDefinition("ALIYUN_OSS_ENDPOINT", "oss", "OSS Endpoint", "例如 oss-cn-beijing.aliyuncs.com"),
    SettingDefinition("ALIYUN_OSS_BUCKET", "oss", "OSS Bucket", "图片 Bucket 名称"),
    SettingDefinition("ALIYUN_OSS_PUBLIC_BASE_URL", "oss", "OSS 公网 URL", "不填时按 bucket + endpoint 自动生成"),
    SettingDefinition("ALIYUN_OSS_OBJECT_PREFIX", "oss", "OSS 文件前缀", "图片存储目录前缀", "temu-listing"),
)


class AdminUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2)
    password: str = Field(..., min_length=6)
    displayName: str | None = None
    role: str = "user"
    status: str = "active"


class AdminUserUpdateRequest(BaseModel):
    displayName: str | None = None
    role: str | None = None
    status: str | None = None


class AdminPasswordResetRequest(BaseModel):
    password: str = Field(..., min_length=6)


class AdminSettingUpdateItem(BaseModel):
    key: str
    value: str | None = None
    clear: bool = False


class AdminSettingsUpdateRequest(BaseModel):
    items: list[AdminSettingUpdateItem]


@router.get("/users")
def admin_list_users(_admin: dict[str, Any] = Depends(require_admin_user)):
    return {"items": list_users()}


@router.post("/users")
def admin_create_user(payload: AdminUserCreateRequest, _admin: dict[str, Any] = Depends(require_admin_user)):
    try:
        user = create_managed_user(
            username=payload.username,
            password=payload.password,
            display_name=payload.displayName,
            role=payload.role,
            status=payload.status,
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": user}


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


@router.get("/settings")
def admin_list_settings(_admin: dict[str, Any] = Depends(require_admin_user)):
    saved_settings = get_app_settings_map()
    return {"items": [serialize_setting(definition, saved_settings.get(definition.key)) for definition in SETTING_DEFINITIONS]}


@router.put("/settings")
def admin_update_settings(
    payload: AdminSettingsUpdateRequest,
    admin: dict[str, Any] = Depends(require_admin_user),
):
    definitions = {definition.key: definition for definition in SETTING_DEFINITIONS}
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
        "items": [serialize_setting(definition, saved_settings.get(definition.key)) for definition in SETTING_DEFINITIONS],
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
