from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from app.modules.creative_generation.listing_title_optimizer import load_listing_prompt
from app.modules.visual_generation.planner import (
    build_mother_prompt_from_plan,
    build_panel_prompt_instruction,
    build_product_analysis_instruction,
    build_prompt_plan_instruction,
)


@dataclass(frozen=True)
class AdminPromptConfig:
    id: str
    stage: str
    title: str
    description: str
    model_key: str
    source: str
    input_from: str
    output_to: str
    variables: tuple[str, ...]
    content: str


def _json_template(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _title_prompt_content() -> str:
    user_payload = {
        "listing_optimization_rules": "{{ backend/config/prompts/listing_optimization.md }}",
        "task": "Generate one optimized Chinese product title and one optimized English product title for a Dianxiaomi TEMU semi-managed import template.",
        "requirements": [
            "title_cn must be Chinese.",
            "title_en must be English and contain no Chinese characters.",
            "Keep quantity or pack count when the source title clearly includes it.",
            "Remove exact size specs when they are not core SKU identity.",
            "Use differentiated SEO wording so repeated products do not share identical titles.",
            "Keep the meaning faithful to the source product and SKU/bundle structure.",
            "Avoid sensitive words, brand names, platform names, exaggerated claims, and medical claims.",
        ],
        "source": {
            "product_id": "{{ productId }}",
            "current_title_cn": "{{ fallbackTitleCn }}",
            "current_title_en": "{{ fallbackTitleEn }}",
            "source_links": "{{ sourceLinks[:5] }}",
            "sku_entries": "{{ skuEntries[:30] }}",
        },
        "required_json": {
            "title_cn": "optimized Chinese title",
            "title_en": "optimized English title, 50-200 characters preferred",
        },
    }
    return "\n\n".join(
        [
            "System:\n"
            "You are a Temu marketplace listing title optimizer. Follow the user's listing optimization rules. "
            "Return strict JSON only. Do not include markdown. Do not invent brands, platform names, certification claims, "
            "medical claims, absolute guarantees, price or discount words.",
            f"User payload template:\n{_json_template(user_payload)}",
            f"Listing optimization rules file:\n{load_listing_prompt()}",
        ]
    )


def _title_split_prompt_content() -> str:
    payload = {
        "title": "{{ productTitle }}",
        "category": "{{ category }}",
        "translation_requirement": (
            "英文或中英混合标题必须先转成简体中文 1688 采购搜索词，不能原样输出英文连写词、型号词、物流词或营销词。"
        ),
        "must_translate_examples": {
            "3DPaperAirplaneF": "纸飞机玩具",
            "Pale Mini Tote Bags": "迷你托特包",
            "Wood D12 Dice": "木质十二面骰子",
        },
        "required_json": {
            "primary_keyword": "最精准的简体中文 1688 采购搜索词，通常 4-12 个中文字符；英文标题必须翻译成中文，不要原样输出英文",
            "keywords": [
                {
                    "keyword": "简体中文 1688 采购搜索词，不要英文原词",
                    "intent": "precise/core/attribute/broaden",
                    "reason": "short Chinese reason",
                }
            ],
            "removed_terms": ["noise term removed from title"],
        },
    }
    return "\n\n".join(
        [
            "System:\n"
            "You convert noisy marketplace product titles into concise Simplified Chinese 1688 sourcing keywords. "
            "If the title is English or mixed-language, first translate the real product subject, material, shape, "
            "structure, and key attributes into Chinese supplier search terms. Return strict JSON only. "
            "Every keyword must be suitable for 1688 supplier search in Simplified Chinese. "
            "Do not output raw English title fragments, SKU/model codes, logistics text, quantity, marketing copy, "
            "target users, scenes, gift wording, platform names, or broad usage claims. "
            "Examples: '3DPaperAirplaneF' -> '纸飞机玩具'; 'Mini Tote Bags' -> '迷你托特包'; "
            "'Wood D12 Dice' -> '木质十二面骰子'. "
            "Only keep universal English abbreviations when paired with a Chinese product noun, such as '3D纸飞机模型', "
            "'LED灯', or 'USB充电线'.",
            f"User payload template:\n{_json_template(payload)}",
        ]
    )


def _recommendation_prompt_content() -> str:
    payload = {
        "product_title": "{{ title }}",
        "category": "{{ category }}",
        "main_image_url": "{{ optional image input }}",
        "task": (
            "Analyze the product title and image. If the title is English or mixed-language, first translate the real product "
            "subject and key attributes into Simplified Chinese. Then recommend exploratory 1688 sourcing directions for "
            "adjacent categories, complementary products, bundle add-ons, same-scene items, or same-buyer-intent products. "
            "The recommendations are references for product expansion, not exact same-item keyword variants. "
            "For example: if the product is a spoon, recommend bowls, plates, placemats, chopstick holders, or cutlery organizers. "
            "Do not only recommend the original product with suffixes like different款, 批发, 1688, same material, same shape, or same function."
        ),
        "translation_requirement": (
            "所有 keyword 必须是简体中文 1688 采购搜索词。英文/中英混合标题必须转成中文，不能原样输出英文连写词、型号词、物流词、促销词或数量词。"
        ),
        "divergent_recommendation_requirement": (
            "关键词应该发散到相似类目、搭配类目、同使用场景或可组成套装的周边商品；不要只围绕原商品本身扩词。"
        ),
        "good_examples": {
            "勺子": ["陶瓷碗", "餐盘", "餐垫", "筷子筒", "餐具收纳盒"],
            "宠物碗": ["宠物餐垫", "宠物喂食勺", "宠物储粮桶", "宠物饮水器"],
            "纸飞机玩具": ["折纸材料包", "儿童手工材料", "飞机模型玩具", "派对游戏道具"],
        },
        "bad_examples": ["勺子不同款", "勺子批发", "勺子1688", "36pcs 3d paper airplane 不同款"],
        "must_translate_examples": {
            "3DPaperAirplaneF": "纸飞机玩具",
            "Pale Mini Tote Bags": "迷你托特包",
            "Wood D12 Dice": "木质十二面骰子",
        },
        "required_json": {
            "summary": "short Chinese summary of product core use and visual traits",
            "strategy": "short Chinese strategy explaining adjacent category expansion, complementary bundles, or same-scene sourcing",
            "keywords": [
                {
                    "keyword": "简体中文 1688 相邻类目/搭配品/同场景商品搜索词，4-16 个中文字符为主，不要英文原词",
                    "intent": "adjacent-category/complementary-bundle/same-scene/same-buyer-intent",
                    "reason": "why this adjacent product direction is commercially relevant",
                }
            ],
        },
    }
    return "\n\n".join(
        [
            "System:\n"
            "You are a careful 1688 sourcing analyst for Temu listing operations. "
            "Return strict JSON only. Think like a product expansion buyer, not an exact-match keyword splitter. "
            "Recommend adjacent categories, complementary items, bundle add-ons, same-scene products, or same-buyer-intent products. "
            "Avoid same-item variants that merely add different款, 批发, 1688, material, color, size, shape, or quantity to the original product. "
            "Every keyword must be a Simplified Chinese supplier/search phrase for 1688. "
            "Do not output raw English title fragments, SKU/model codes, logistics text, promo text, pack counts, "
            "brand names, medical claims, certification claims, or unsafe marketplace wording. "
            "Only keep universal English abbreviations when paired with a Chinese product noun, such as '3D纸飞机模型', "
            "'LED灯', or 'USB充电线'.",
            f"User payload template:\n{_json_template(payload)}",
        ]
    )


def _product_attribute_prompt_content() -> str:
    instruction = {
        "role": "You are a Dianxiaomi TEMU semi-managed product attribute assistant. Return JSON only, no explanations.",
        "task": (
            "Use the product title, SKU names, category path, and candidate attribute fields to fill every visible product attribute field. "
            "For select fields, use exactly one provided option label and return its vid. For checkbox-group fields, choose at least one provided option. "
            "If the exact value cannot be confidently inferred, choose the safest generic/neutral option from the provided options, such as no/none/not applicable/generic/other. "
            "Do not leave fields blank. Do not invent certifications, brands, medical claims, safety claims, waterproof claims, or unverifiable sensitive attributes."
        ),
        "output_schema": {
            "attributes": [
                {
                    "field_label": "field label",
                    "prop_value": "single selected value for select/input",
                    "prop_values": ["selected values for checkbox-group"],
                    "number_input_value": "numeric input value when needed",
                    "value_unit": "",
                    "vid": "option vid if available",
                }
            ]
        },
        "product": {
            "title": "{{ productTitle }}",
            "title_en": "{{ productTitleEn }}",
            "sku_names": "{{ skuNames }}",
            "source_titles": "{{ sourceTitles }}",
        },
        "category": {
            "category_id": "{{ categoryId }}",
            "category_path": "{{ categoryPath }}",
        },
        "fields": "{{ compact candidate fields with options }}",
    }
    return f"Instruction JSON sent to /chat/completions:\n{_json_template(instruction)}"


def _visual_context_template() -> dict[str, Any]:
    return {
        "productTitle": "{{ productTitle }}",
        "productTitleEn": "{{ productTitleEn }}",
        "skuNames": ["{{ skuName }}"],
        "skuBindings": [
            {
                "skuIndex": 1,
                "skuName": "{{ combo SKU name, for example 1pc + 6pc }}",
                "skuKind": "{{ single/combo }}",
                "compositionText": "{{ component A from source product A + component B from source product B }}",
                "referenceIndexes": [1],
                "components": [
                    {
                        "componentIndex": 1,
                        "componentName": "{{ component SKU name, for example 1pc }}",
                        "sourceTitle": "{{ source product title }}",
                        "specText": "{{ visible/source SKU spec text }}",
                        "optionText": "{{ source SKU option text }}",
                        "referenceImageIndex": 1,
                    }
                ],
            }
        ],
        "skuCombinationBindings": [
            {
                "skuName": "{{ combo SKU name }}",
                "compositionText": "{{ exact combo composition by source product }}",
            }
        ],
        "referenceImages": [
            {
                "index": 1,
                "label": "{{ selected reference image label }}",
                "role": "binding product/SKU reference",
            }
        ],
    }


def _visual_analysis_prompt_content() -> str:
    return build_product_analysis_instruction(_visual_context_template())


def _visual_plan_prompt_content() -> str:
    product_analysis = {
        "productUnderstanding": {
            "productTitle": "{{ productTitle }}",
            "overallCategory": "{{ category inferred from references }}",
            "globalMustPreserve": ["{{ shape/color/material/quantity facts }}"],
            "globalDoNotChange": ["{{ visible risks or identity constraints }}"],
        }
    }
    return build_prompt_plan_instruction(
        product_analysis=product_analysis,
        layout="3x3",
        allow_short_labels=True,
        requested_count=9,
        context=_visual_context_template(),
    )


def _visual_image_prompt_content() -> str:
    sample_plan = {
        "productUnderstanding": {
            "productTitle": "{{ productTitle }}",
            "overallCategory": "{{ product category }}",
            "globalMustPreserve": ["{{ reference-bound product identity facts }}"],
            "globalDoNotChange": ["{{ do not replace SKU/product }}"],
        },
        "visualTaskPlan": {
            "requestedCount": 9,
            "layout": "3x3",
            "batchGoal": "{{ commercial listing image batch goal }}",
            "globalStyleDirection": "{{ coherent ecommerce style direction }}",
            "modules": [
                {
                    "position": 1,
                    "slotType": "impact-main",
                    "title": "Impact Main Image",
                    "purpose": "high-click hero image with the selected product as the dominant subject",
                    "targetSkuName": "{{ target SKU if any }}",
                    "compositionBrief": "{{ composition }}",
                    "sceneBrief": "{{ scene }}",
                    "copyRequired": True,
                    "copyIntent": "{{ safe on-image copy intent }}",
                    "textPolicy": "{{ safe text policy }}",
                }
            ],
        },
        "panelPromptPlan": {
            "globalConsistency": "{{ consistency requirement }}",
            "panels": [
                {
                    "position": 1,
                    "slotType": "impact-main",
                    "targetSkuName": "{{ target SKU if any }}",
                    "onImageCopy": ["{{ safe English copy }}"],
                    "panelPrompt": "{{ final English panel prompt from prompt-planning model }}",
                    "negativePrompt": "{{ negative prompt }}",
                    "safetyNotes": ["{{ safety notes }}"],
                }
            ],
        },
    }
    return build_mother_prompt_from_plan(sample_plan, "3x3", True)


def list_admin_prompt_configs() -> list[dict[str, Any]]:
    items = [
        AdminPromptConfig(
            id="title",
            stage="title",
            title="标题生成",
            description="根据商品标题、SKU、来源链接生成中文标题和英文标题。",
            model_key="OPENAI_TITLE_MODEL",
            source="backend/app/modules/creative_generation/listing_title_optimizer.py + backend/config/prompts/listing_optimization.md",
            input_from="商品池/链接列表记录、SKU、来源商品标题",
            output_to="商品中文标题、英文标题",
            variables=("productId", "fallbackTitleCn", "fallbackTitleEn", "sourceLinks", "skuEntries"),
            content=_title_prompt_content(),
        ),
        AdminPromptConfig(
            id="title_split",
            stage="title_split",
            title="标题拆分",
            description="把商品标题压缩成适合 1688 搜索的中文采购关键词。",
            model_key="OPENAI_TITLE_SPLIT_MODEL",
            source="backend/app/modules/sourcing_1688/title_keywords.py",
            input_from="标题生成/商品原始标题、类目",
            output_to="1688 primary_keyword、关键词候选、被移除噪音词",
            variables=("productTitle", "category"),
            content=_title_split_prompt_content(),
        ),
        AdminPromptConfig(
            id="recommendation",
            stage="recommendation",
            title="智能推荐",
            description="基于标题、类目和主图生成相邻 1688 找货方向。",
            model_key="OPENAI_RECOMMENDATION_MODEL",
            source="backend/app/modules/sourcing_1688/smart_recommendations.py",
            input_from="商品标题、类目、主图 URL",
            output_to="推荐找货策略、关键词方向",
            variables=("title", "category", "mainImageUrl"),
            content=_recommendation_prompt_content(),
        ),
        AdminPromptConfig(
            id="product_attribute",
            stage="product_attribute",
            title="产品属性填写",
            description="根据商品、类目和候选属性字段生成店小秘/TEMU 属性值。",
            model_key="OPENAI_PRODUCT_ATTRIBUTE_MODEL",
            source="backend/app/modules/exports/product_attributes.py",
            input_from="商品标题、SKU、来源标题、类目路径、候选属性字段",
            output_to="导出模板里的产品属性 JSON",
            variables=("productTitle", "productTitleEn", "skuNames", "categoryPath", "fields"),
            content=_product_attribute_prompt_content(),
        ),
        AdminPromptConfig(
            id="visual_analysis",
            stage="visual_analysis",
            title="图片理解",
            description="分析参考图，抽取后续生图必须保留的产品事实和风险。",
            model_key="OPENAI_VISUAL_ANALYSIS_MODEL",
            source="backend/app/modules/visual_generation/planner.py::build_product_analysis_instruction",
            input_from="商品标题、SKU、参考图",
            output_to="productUnderstanding",
            variables=("productTitle", "productTitleEn", "skuNames", "referenceImages"),
            content=_visual_analysis_prompt_content(),
        ),
        AdminPromptConfig(
            id="visual_prompt",
            stage="visual_prompt",
            title="提示词规划",
            description="把图片理解结果转换成批量图片模块规划和每格英文生图提示词。",
            model_key="OPENAI_VISUAL_PROMPT_MODEL",
            source="backend/app/modules/visual_generation/planner.py::build_prompt_plan_instruction / build_panel_prompt_instruction",
            input_from="productUnderstanding、布局、SKU、候选模块",
            output_to="visualTaskPlan、panelPromptPlan",
            variables=("productUnderstanding", "layout", "requestedCount", "skuNames", "candidateModules"),
            content="\n\n--- Prompt plan instruction ---\n\n".join(
                [
                    _visual_plan_prompt_content(),
                    build_panel_prompt_instruction(
                        product_understanding={"productTitle": "{{ productTitle }}"},
                        visual_task_plan={
                            "requestedCount": 9,
                            "layout": "3x3",
                            "modules": [
                                {
                                    "position": 1,
                                    "slotType": "impact-main",
                                    "title": "Impact Main Image",
                                    "purpose": "{{ module purpose }}",
                                }
                            ],
                        },
                        layout="3x3",
                        allow_short_labels=True,
                        context=_visual_context_template(),
                    ),
                ]
            ),
        ),
        AdminPromptConfig(
            id="visual_image",
            stage="visual_image",
            title="图片生成",
            description="把规划好的每格 panel prompt 合成为最终母图生图提示词。",
            model_key="OPENAI_IMAGE_MODEL",
            source="backend/app/modules/visual_generation/planner.py::build_mother_prompt_from_plan",
            input_from="panelPromptPlan、productUnderstanding、布局、参考图",
            output_to="母图，再切分为单张商品图",
            variables=("panelPromptPlan", "productUnderstanding", "layout", "referenceImages"),
            content=_visual_image_prompt_content(),
        ),
    ]
    return [
        {
            **asdict(item),
            "modelKey": item.model_key,
            "inputFrom": item.input_from,
            "outputTo": item.output_to,
            "readOnly": True,
        }
        for item in items
    ]
