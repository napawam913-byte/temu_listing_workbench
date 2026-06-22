from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.modules.admin_config.postgres_store import get_app_setting_value, upsert_app_setting


PROMPT_ROOT = Path(__file__).resolve().parents[1] / "prompts"
PROMPT_SETTING_PREFIX = "PROMPT_TEMPLATE_"
VARIABLE_PATTERN = re.compile(r"{{\s*([A-Za-z0-9_.-]+)\s*}}")


@dataclass(frozen=True)
class PromptTemplateDefinition:
    id: str
    stage: str
    title: str
    description: str
    model_key: str
    file_path: str
    input_from: str
    output_to: str
    variables: tuple[str, ...]

    @property
    def setting_key(self) -> str:
        return f"{PROMPT_SETTING_PREFIX}{self.id}"

    @property
    def absolute_path(self) -> Path:
        return PROMPT_ROOT / self.file_path


PROMPT_TEMPLATE_DEFINITIONS: tuple[PromptTemplateDefinition, ...] = (
    PromptTemplateDefinition(
        id="title_split",
        stage="title_split",
        title="标题拆分",
        description="把商品标题压缩成适合 1688 搜索的中文采购关键词。",
        model_key="OPENAI_TITLE_SPLIT_MODEL",
        file_path="sourcing/title_split.md",
        input_from="商品分析标题/商品原始标题、类目",
        output_to="1688 primary_keyword、关键词候选、被移除噪音词",
        variables=("productTitle", "category"),
    ),
    PromptTemplateDefinition(
        id="recommendation",
        stage="recommendation",
        title="智能推荐",
        description="基于标题、类目和主图生成相邻 1688 找货方向。",
        model_key="OPENAI_RECOMMENDATION_MODEL",
        file_path="sourcing/recommendation.md",
        input_from="商品标题、类目、主图 URL",
        output_to="推荐找货策略、关键词方向",
        variables=("title", "category", "mainImageUrl"),
    ),
    PromptTemplateDefinition(
        id="product_attribute",
        stage="product_attribute",
        title="产品属性填写",
        description="根据商品、类目和候选属性字段生成店小秘/TEMU 属性值。",
        model_key="OPENAI_PRODUCT_ATTRIBUTE_MODEL",
        file_path="exports/product_attribute.md",
        input_from="商品标题、SKU、来源标题、类目路径、候选属性字段",
        output_to="导出模板里的产品属性 JSON",
        variables=("productTitle", "productTitleEn", "skuNames", "categoryPath", "fields"),
    ),
    PromptTemplateDefinition(
        id="category_branch",
        stage="product_attribute",
        title="产品类目匹配",
        description="从候选类目分支或叶子类目中选择最贴近商品的路径。",
        model_key="OPENAI_PRODUCT_ATTRIBUTE_MODEL",
        file_path="exports/category_branch.md",
        input_from="商品标题、SKU、参考图、候选类目",
        output_to="selected_index、confidence、reason",
        variables=("task", "product", "currentCategoryPath", "candidates"),
    ),
    PromptTemplateDefinition(
        id="visual_analysis",
        stage="visual_analysis",
        title="图片理解",
        description="分析参考图，抽取后续生图必须保留的产品事实和风险。",
        model_key="OPENAI_VISUAL_ANALYSIS_MODEL",
        file_path="visual/analysis.md",
        input_from="商品标题、SKU、参考图",
        output_to="productUnderstanding",
        variables=("contextJson", "listingTitleRules"),
    ),
    PromptTemplateDefinition(
        id="visual_prompt",
        stage="visual_prompt",
        title="提示词规划",
        description="把图片理解结果转换成批量图片模块规划。",
        model_key="OPENAI_VISUAL_PROMPT_MODEL",
        file_path="visual/prompt_plan.md",
        input_from="productUnderstanding、布局、SKU、候选模块",
        output_to="visualTaskPlan",
        variables=("inputJson", "labelPolicyText", "materialTextureDriftRule"),
    ),
    PromptTemplateDefinition(
        id="visual_panel_prompt",
        stage="visual_prompt",
        title="单格图片提示词",
        description="把图片模块规划转换成每格英文生图提示词。",
        model_key="OPENAI_VISUAL_PROMPT_MODEL",
        file_path="visual/panel_prompt.md",
        input_from="visualTaskPlan、productUnderstanding、SKU 绑定、参考图",
        output_to="panelPromptPlan",
        variables=("inputJson", "labelPolicyText", "materialTextureDriftRule"),
    ),
    PromptTemplateDefinition(
        id="visual_image",
        stage="visual_image",
        title="图片生成",
        description="把规划好的每格 panel prompt 合成为最终母图生图提示词。",
        model_key="OPENAI_IMAGE_MODEL",
        file_path="visual/mother_image.md",
        input_from="panelPromptPlan、productUnderstanding、布局、参考图",
        output_to="母图，再切分为单张商品图",
        variables=("layoutKey", "expectedCount", "gridRules", "productJson", "skuBindingJson", "skuComboJson", "skuReferenceJson", "panelInstructions", "materialTextureDriftRule"),
    ),
)


def prompt_definition(template_id: str) -> PromptTemplateDefinition:
    for definition in PROMPT_TEMPLATE_DEFINITIONS:
        if definition.id == template_id:
            return definition
    raise KeyError(f"Unknown prompt template: {template_id}")


@lru_cache(maxsize=128)
def read_default_prompt_template(template_id: str) -> str:
    definition = prompt_definition(template_id)
    return definition.absolute_path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=128)
def read_prompt_template(template_id: str) -> str:
    definition = prompt_definition(template_id)
    override = get_app_setting_value(definition.setting_key, "").strip()
    if override:
        return override
    return read_default_prompt_template(template_id)


def clear_prompt_template_cache() -> None:
    read_default_prompt_template.cache_clear()
    read_prompt_template.cache_clear()


def render_template_text(template: str, variables: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = variables.get(key)
        if value is None:
            return match.group(0)
        return str(value)

    return VARIABLE_PATTERN.sub(replace, template).strip()


def render_prompt_template(template_id: str, variables: dict[str, Any] | None = None) -> str:
    return render_template_text(read_prompt_template(template_id), variables or {})


def list_prompt_templates() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for definition in PROMPT_TEMPLATE_DEFINITIONS:
        default_content = read_default_prompt_template(definition.id)
        current_content = read_prompt_template(definition.id)
        items.append(
            {
                "id": definition.id,
                "stage": definition.stage,
                "title": definition.title,
                "description": definition.description,
                "modelKey": definition.model_key,
                "source": str(definition.absolute_path),
                "inputFrom": definition.input_from,
                "outputTo": definition.output_to,
                "variables": list(definition.variables),
                "content": current_content,
                "defaultContent": default_content,
                "overridden": current_content != default_content,
                "settingKey": definition.setting_key,
                "readOnly": False,
            }
        )
    return items


def upsert_prompt_template(template_id: str, content: str, *, updated_by: str | None = None) -> dict[str, Any]:
    definition = prompt_definition(template_id)
    upsert_app_setting(
        key=definition.setting_key,
        value=content,
        category="prompt",
        label=f"{definition.title}提示词模板",
        description=definition.description,
        is_secret=False,
        updated_by=updated_by,
    )
    clear_prompt_template_cache()
    return next(item for item in list_prompt_templates() if item["id"] == template_id)


def restore_prompt_template_default(template_id: str, *, updated_by: str | None = None) -> dict[str, Any]:
    definition = prompt_definition(template_id)
    default_content = read_default_prompt_template(template_id)
    upsert_app_setting(
        key=definition.setting_key,
        value="",
        category="prompt",
        label=f"{definition.title}提示词模板",
        description=f"使用默认文件模板：{definition.file_path}",
        is_secret=False,
        updated_by=updated_by,
    )
    clear_prompt_template_cache()
    item = next(item for item in list_prompt_templates() if item["id"] == template_id)
    item["content"] = default_content
    item["overridden"] = False
    return item
