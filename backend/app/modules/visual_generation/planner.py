from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.visual_generation.clients import (
    VisualGenerationError,
    extract_response_text,
    image_file_to_data_url,
    parse_json_from_text,
    request_json,
    request_text_json,
)
from app.modules.visual_generation.splitter import POSITION_NAMES, layout_key, parse_layout


def build_product_analysis_instruction(context: dict[str, Any] | None = None) -> str:
    context_json = json.dumps(context or {}, ensure_ascii=False, indent=2)
    return f"""
Analyze this ecommerce product image before execution.

Return JSON only. Do not return markdown.

Input context:
{context_json}

Rules:
1. Extract only visible or strongly supported product facts.
2. Do not invent accessories, SKU options, materials, functions, brand names, platform names, or claims.
3. Identify visual risks that should not appear in generated images: logos, watermark, QR code, price, discount, rating, medical claim, absolute marketing wording, platform UI, unsafe or misleading labels.
4. The result will be used to generate a 2x2 or 3x3 mother image and split it into individual listing images.
5. Keep the product structure, color, material, quantity, and core details stable.

JSON format:
{{
  "productAnalysis": {{
    "productName": "",
    "category": "",
    "mainObject": "",
    "colors": [],
    "materials": [],
    "shape": "",
    "visibleFeatures": [],
    "possibleUseCases": [],
    "skuAttributes": [],
    "detailFocus": [],
    "sceneOpportunities": [],
    "safeMarketingPhrases": [],
    "labelSuitability": "",
    "temuVisualDirection": "",
    "valuePresentation": "",
    "visualImpactPoints": [],
    "sensitiveRisk": [],
    "avoid": []
  }}
}}
""".strip()


def default_slot_blueprints(layout: str) -> list[dict[str, str]]:
    rows, cols = parse_layout(layout)
    if rows == 3 and cols == 3:
        return [
            {"slotType": "white-sku", "title": "White SKU Image", "purpose": "clean factual product display"},
            {"slotType": "impact-main", "title": "Impact Main Image", "purpose": "high-conversion hero image"},
            {"slotType": "detail-texture", "title": "Detail Image", "purpose": "material, texture, edge, or structure detail"},
            {"slotType": "lifestyle-scene", "title": "Lifestyle Scene", "purpose": "realistic usage context"},
            {"slotType": "comparison", "title": "Comparison Image", "purpose": "angle, size, quantity, or state comparison"},
            {"slotType": "usage-demo", "title": "Usage Demo", "purpose": "natural effect or placement demonstration"},
            {"slotType": "package-combo", "title": "Package Or Combo", "purpose": "quantity, bundle, or included-item clarity"},
            {"slotType": "gift-scene", "title": "Gift Or Value Scene", "purpose": "strong emotional value scene"},
            {"slotType": "secondary-angle", "title": "Secondary Angle", "purpose": "extra useful product angle"},
        ]
    if rows == 2 and cols == 2:
        return [
            {"slotType": "white-sku", "title": "White SKU Image", "purpose": "clean factual product display"},
            {"slotType": "impact-main", "title": "Impact Main Image", "purpose": "high-conversion hero image"},
            {"slotType": "detail-texture", "title": "Detail Image", "purpose": "material, texture, edge, or structure detail"},
            {"slotType": "lifestyle-scene", "title": "Lifestyle Or Usage Scene", "purpose": "realistic usage context"},
        ]
    return [{"slotType": "single-refine", "title": "Single Refined Image", "purpose": "single image refinement"}]


def label_policy_text(allow_short_labels: bool) -> str:
    if not allow_short_labels:
        return "Do not add readable text inside the image."
    return (
        "Short on-image English labels are allowed only when useful. "
        "Each label must be objective, safe, and 1-4 words. Avoid brand names, platform names, price, "
        "discounts, ratings, QR codes, medical claims, absolute marketing words, guarantee words, "
        "and unsafe claims."
    )


def build_prompt_plan_instruction(
    *,
    product_analysis: dict[str, Any],
    layout: str,
    allow_short_labels: bool = True,
) -> str:
    rows, cols = parse_layout(layout)
    key = layout_key(rows, cols)
    positions = POSITION_NAMES[key]
    blueprints = default_slot_blueprints(layout)
    product_json = json.dumps(product_analysis, ensure_ascii=False, indent=2)
    blueprint_json = json.dumps(blueprints, ensure_ascii=False, indent=2)
    position_lines = "\n".join(f"{index + 1}. {position}" for index, position in enumerate(positions))
    return f"""
Plan a {key} ecommerce mother image for a Temu-style product listing.

Product analysis JSON:
{product_json}

Default module blueprint:
{blueprint_json}

Grid positions:
{position_lines}

Rules:
1. Return JSON only. Do not return markdown.
2. Output exactly {rows * cols} panelTasks in the same order as the grid positions.
3. Each panelPrompt must be a complete executable English image prompt.
4. Every prompt must preserve the real product structure, color, material, quantity, and key details.
5. The whole mother image must have consistent lighting, camera quality, and ecommerce visual direction.
6. Strong visual impact is preferred, but do not add prohibited content.
7. {label_policy_text(allow_short_labels)}
8. Do not include brand logo, platform logo, watermark, QR code, price, discount, star rating, medical claim, absolute claim, or platform UI.

JSON format:
{{
  "panelTasks": [
    {{
      "panelIndex": 1,
      "position": "{positions[0]}",
      "slotType": "{blueprints[0]['slotType']}",
      "title": "{blueprints[0]['title']}",
      "purpose": "{blueprints[0]['purpose']}",
      "safeLabels": [],
      "riskControl": "",
      "panelPrompt": ""
    }}
  ]
}}
""".strip()


def normalized_panel_tasks(plan: dict[str, Any], layout: str, allow_short_labels: bool = True) -> list[dict[str, Any]]:
    rows, cols = parse_layout(layout)
    key = layout_key(rows, cols)
    expected = rows * cols
    positions = POSITION_NAMES[key]
    blueprints = default_slot_blueprints(layout)
    raw_tasks = plan.get("panelTasks")
    if not isinstance(raw_tasks, list):
        raw_tasks = []

    product_analysis = plan.get("productAnalysis") or {}
    product_name = ""
    if isinstance(product_analysis, dict):
        product_name = str(product_analysis.get("productName") or product_analysis.get("mainObject") or "").strip()
    product_name = product_name or "the product"

    tasks: list[dict[str, Any]] = []
    for index in range(expected):
        raw = raw_tasks[index] if index < len(raw_tasks) and isinstance(raw_tasks[index], dict) else {}
        blueprint = blueprints[min(index, len(blueprints) - 1)]
        prompt = str(raw.get("panelPrompt") or raw.get("prompt") or "").strip()
        if not prompt:
            prompt = (
                f"Create a square 1:1 Temu-style ecommerce image for {product_name}. "
                f"Module: {blueprint['title']}. Purpose: {blueprint['purpose']}. "
                "Keep product structure, color, material, quantity, and key details accurate. "
                "Use bright high-conversion ecommerce photography, strong but safe visual impact, "
                "clean composition, clear product visibility, and realistic lighting. "
                "No brand logo, no platform logo, no watermark, no QR code, no price, no discount, "
                "no star rating, no medical claim, no absolute marketing claim."
            )
        tasks.append(
            {
                "panelIndex": index + 1,
                "position": positions[index],
                "slotType": str(raw.get("slotType") or blueprint["slotType"]),
                "title": str(raw.get("title") or blueprint["title"]),
                "purpose": str(raw.get("purpose") or blueprint["purpose"]),
                "safeLabels": raw.get("safeLabels") if allow_short_labels and isinstance(raw.get("safeLabels"), list) else [],
                "riskControl": str(raw.get("riskControl") or ""),
                "panelPrompt": prompt,
            }
        )
    return tasks


def build_mother_prompt_from_plan(plan: dict[str, Any], layout: str, allow_short_labels: bool = True) -> str:
    rows, cols = parse_layout(layout)
    key = layout_key(rows, cols)
    tasks = normalized_panel_tasks(plan, layout, allow_short_labels)
    product_json = json.dumps(plan.get("productAnalysis") or {}, ensure_ascii=False, indent=2)
    panel_lines = []
    for task in tasks:
        labels = task.get("safeLabels") or []
        label_line = f" Optional safe labels: {', '.join(str(label) for label in labels)}." if labels else ""
        risk_line = f" Risk control: {task['riskControl']}." if task.get("riskControl") else ""
        panel_lines.append(
            f"{task['position']} ({task['title']} / {task['slotType']}): "
            f"Purpose: {task['purpose']}.{label_line}{risk_line}\n{task['panelPrompt']}"
        )

    return f"""
Create one single {key} ecommerce mother image. It must be a strict grid with {rows * cols} equal square panels.
Each panel is an independent 1:1 product listing image. Use clean white grid gutters between panels.
No product or text may cross panel boundaries. Do not merge cells.

Product facts to preserve:
{product_json}

Global style:
Bright high-conversion US Temu-style ecommerce photography, strong visual impact, realistic product texture,
consistent lighting, clear subject visibility, polished commercial composition.
Do not show the Temu word, platform UI, brand logo, watermark, QR code, price, discount, star rating,
medical claims, absolute claims, or misleading safety/certification claims.
{label_policy_text(allow_short_labels)}

Panel instructions:
{chr(10).join(panel_lines)}
""".strip()


def request_product_analysis(
    *,
    api_url: str,
    api_key: str,
    model: str,
    product_image_path: Path,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    instruction = build_product_analysis_instruction(context)
    if api_url.rstrip("/").endswith("/chat/completions"):
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {"type": "image_url", "image_url": {"url": image_file_to_data_url(product_image_path)}},
                    ],
                }
            ],
            "temperature": 0.1,
        }
    else:
        payload = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": instruction},
                        {"type": "input_image", "image_url": image_file_to_data_url(product_image_path)},
                    ],
                }
            ],
        }
    response_json = request_json(api_url, api_key, payload)
    parsed = parse_json_from_text(extract_response_text(response_json))
    product_analysis = parsed.get("productAnalysis", parsed)
    if not isinstance(product_analysis, dict):
        raise VisualGenerationError("product analysis result is missing productAnalysis")
    return product_analysis


def request_prompt_plan(
    *,
    api_url: str,
    api_key: str,
    model: str,
    product_analysis: dict[str, Any],
    layout: str,
    allow_short_labels: bool = True,
) -> dict[str, Any]:
    parsed = request_text_json(
        api_url=api_url,
        api_key=api_key,
        model=model,
        instruction=build_prompt_plan_instruction(
            product_analysis=product_analysis,
            layout=layout,
            allow_short_labels=allow_short_labels,
        ),
        temperature=0.45,
    )
    tasks = normalized_panel_tasks(
        {"productAnalysis": product_analysis, "panelTasks": parsed.get("panelTasks") or []},
        layout,
        allow_short_labels,
    )
    return {
        "productAnalysis": product_analysis,
        "panelTasks": tasks,
        "modelRouting": {
            "analysisStage": "vision-analysis",
            "promptStage": "prompt-planning",
            "allowShortLabels": allow_short_labels,
        },
    }

