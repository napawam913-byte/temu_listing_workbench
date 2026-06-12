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


REFERENCE_FIDELITY_RULE = (
    "Use every attached selected SKU/product reference image as a binding visual reference, not loose inspiration. "
    "Do not change the product subject appearance: preserve exact visible shape, color, material, edge/rim details, "
    "surface texture, quantity, scale logic, and component relationship. For combo SKUs, show all selected components "
    "together and keep each component visually identifiable. Never replace the selected item with a generic category item."
)

COMPARISON_TEXT_POLICY = (
    "Comparison panels are allowed to use more explanatory English callouts than normal panels when useful. "
    "They may show a clear side-by-side comparison between the selected product and a plain generic alternative, "
    "with objective difference points, arrows, small labels, or short feature phrases chosen by the model. "
    "The text amount should be decided by the model based on product category and visual clarity, but it must remain readable, "
    "safe, factual, and not cover the product. Do not make absolute superiority, medical, safety, guarantee, price, discount, "
    "rating, certification, or platform claims."
)


def ensure_reference_fidelity_text(prompt: str) -> str:
    normalized = prompt.lower()
    if "binding visual reference" in normalized and "do not change" in normalized:
        return prompt
    return f"{prompt.rstrip()} {REFERENCE_FIDELITY_RULE}"


def build_product_analysis_instruction(context: dict[str, Any] | None = None) -> str:
    context_json = json.dumps(context or {}, ensure_ascii=False, indent=2)
    return f"""
You are a Temu cross-border ecommerce product visual analyst. Analyze first, then execute.

Analyze this ecommerce product image before execution.

Return JSON only. Do not return markdown.

Input context:
{context_json}

Rules:
1. Extract only visible or strongly supported product facts.
2. Do not invent accessories, SKU options, materials, functions, brand names, platform names, or claims.
3. The product title in context is mandatory and must be used as the main text source for product category and intent.
4. SKU information in context contains SKU names only. Do not add price, weight, stock, MOQ, SKU ID, source spec tables, or other sourcing data.
5. Treat every attached reference image as a binding selected SKU/product visual reference, not loose inspiration.
6. For every reference image listed in context.referenceImages, identify the exact product subject appearance: component name, shape, color, material, edge/rim detail, surface texture, quantity, and component relationship.
7. Never replace the selected SKU/product with a generic category item. If the reference image shows a specific bowl, mat, spoon, charm, tray, or other component, preserve that exact visible design language.
8. Identify visual risks that should not appear in generated images: logos, watermark, QR code, price, discount, rating, medical claim, absolute marketing wording, platform UI, unsafe or misleading labels.
9. The result will be used to generate a 2x2 or 3x3 mother image and split it into individual listing images.
10. Keep the product structure, color, material, quantity, and core details stable.
11. Interpret clean as subject-dominant and commercially polished, not plain white-only. Backgrounds may be colorful, poster-like, decorative, or scene-based when they improve click appeal, but they must never overpower or obscure the product.
12. Tasteful short English feature text may appear when useful, as long as it is objective, safe, and does not include prohibited claims.

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
    "referenceImageBinding": [],
    "skuImageBindings": [],
    "mustPreserve": [],
    "doNotChange": [],
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
            {"slotType": "impact-main", "title": "Impact Main Image", "purpose": "high-click hero image with the selected product as the dominant subject"},
            {"slotType": "home-feeding-scene", "title": "Home Feeding Scene", "purpose": "bright realistic lifestyle context that supports the product"},
            {"slotType": "usage-demo", "title": "Usage Demo", "purpose": "natural use or placement demonstration"},
            {"slotType": "detail-texture", "title": "Material Detail", "purpose": "material, texture, edge, gloss, or structure detail"},
            {"slotType": "clean-area-feature", "title": "Feature Atmosphere", "purpose": "objective feature presentation with poster-like visual appeal"},
            {"slotType": "structure-display", "title": "Structure Display", "purpose": "clear product structure, relationship, or top-down arrangement"},
            {"slotType": "comparison", "title": "Comparison Image", "purpose": "safe objective comparison without exaggerated claims"},
            {"slotType": "package-combo", "title": "Combo Content", "purpose": "quantity, bundle, or included-item clarity"},
            {"slotType": "warm-lifestyle", "title": "Warm Lifestyle Value", "purpose": "warm emotional value scene while keeping product dominant"},
        ]
    if rows == 2 and cols == 2:
        return [
            {"slotType": "impact-main", "title": "Impact Main Image", "purpose": "high-click hero image with the selected product as the dominant subject"},
            {"slotType": "usage-demo", "title": "Usage Demo", "purpose": "natural use or placement demonstration"},
            {"slotType": "detail-texture", "title": "Material Detail", "purpose": "material, texture, edge, gloss, or structure detail"},
            {"slotType": "lifestyle-scene", "title": "Lifestyle Scene", "purpose": "bright realistic lifestyle context that supports the product"},
        ]
    return [{"slotType": "single-refine", "title": "Single Refined Image", "purpose": "single image refinement"}]


def label_policy_text(allow_short_labels: bool) -> str:
    if not allow_short_labels:
        return "Do not add readable text inside the image."
    return (
        "Short on-image English labels are allowed only when useful. "
        "Each label must be objective, safe, and 1-4 words. Avoid brand names, platform names, price, "
        "discounts, ratings, QR codes, medical claims, absolute marketing words, guarantee words, "
        "and unsafe claims. "
        f"{COMPARISON_TEXT_POLICY}"
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
You are a Temu cross-border ecommerce product visual analyst. Analyze first, then execute.

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
5. Each panelPrompt must explicitly treat attached selected SKU/product reference images as binding visual references. Do not change product subject appearance, exact component shape, color, material, rim/edge detail, surface texture, quantity, or component relationship.
6. If product_analysis includes referenceImageBinding, skuImageBindings, mustPreserve, or doNotChange, every panelPrompt must use those constraints instead of generic category wording.
7. The whole mother image must have consistent lighting, camera quality, and ecommerce visual direction.
8. Strong visual impact is preferred: each image may use poster-quality composition, richer color accents, decorative shapes, light props, depth, and tasteful short text. Keep the product as the clear visual hero; the background can be vivid but must not overpower, hide, or confuse the product.
9. {label_policy_text(allow_short_labels)}
10. For panelTasks whose slotType is "comparison", plan the image as a practical product difference display: compare the selected product with a simple generic alternative from the same broad category, and let the model decide whether more explanatory text is needed to communicate the difference.
11. Do not include brand logo, platform logo, watermark, QR code, price, discount, star rating, medical claim, absolute claim, platform UI, SKU ID, stock, weight, MOQ, or sourcing data.

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
                "Use bright high-conversion ecommerce photography with poster-like visual appeal, "
                "vivid but controlled background design, clean subject-dominant composition, "
                "clear product visibility, and realistic lighting. "
                "No brand logo, no platform logo, no watermark, no QR code, no price, no discount, "
                "no star rating, no medical claim, no absolute marketing claim."
            )
        prompt = ensure_reference_fidelity_text(prompt)
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
You are a Temu cross-border ecommerce product visual analyst. Analyze first, then execute.

Create one single {key} ecommerce mother image. It must be a strict grid with {rows * cols} equal square panels.
Each panel is an independent 1:1 product listing image. Use clean white grid gutters between panels.
No product or text may cross panel boundaries. Do not merge cells.

Product facts to preserve:
{product_json}

Reference image fidelity:
{REFERENCE_FIDELITY_RULE}

Global style:
Bright high-conversion US Temu-style ecommerce poster photography: strong visual impact, realistic product texture,
consistent lighting, clear subject visibility, polished commercial composition, vivid but controlled background design.
Clean means the product is the unmistakable hero, not that the background must be plain white. Backgrounds may be colorful,
scene-based, graphic, or decorative, but they must support the product and never overpower it.
Do not show the Temu word, platform UI, brand logo, watermark, QR code, price, discount, star rating,
medical claims, absolute claims, or misleading safety/certification claims.
{label_policy_text(allow_short_labels)}
{COMPARISON_TEXT_POLICY}

Panel instructions:
{chr(10).join(panel_lines)}

Final output must be one complete grid mother image, suitable for precise slicing into separate square ecommerce listing images.
""".strip()


def compact_text(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def compact_json_value(value: Any, *, max_items: int = 8, max_chars: int = 180, depth: int = 0) -> Any:
    if depth > 3:
        return compact_text(value, max_chars)
    if isinstance(value, dict):
        return {
            str(key): compact_json_value(item, max_items=max_items, max_chars=max_chars, depth=depth + 1)
            for key, item in value.items()
            if item not in ("", None, [], {})
        }
    if isinstance(value, list):
        return [
            compact_json_value(item, max_items=max_items, max_chars=max_chars, depth=depth + 1)
            for item in value[:max_items]
            if item not in ("", None, [], {})
        ]
    if isinstance(value, str):
        return compact_text(value, max_chars)
    return value


def build_compact_mother_prompt_from_plan(plan: dict[str, Any], layout: str, allow_short_labels: bool = True) -> str:
    rows, cols = parse_layout(layout)
    key = layout_key(rows, cols)
    tasks = normalized_panel_tasks(plan, layout, allow_short_labels)
    product_json = json.dumps(
        compact_json_value(plan.get("productAnalysis") or {}, max_items=6, max_chars=140),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    panel_lines = []
    for task in tasks:
        labels = task.get("safeLabels") or []
        label_line = f" Labels: {', '.join(str(label) for label in labels[:3])}." if labels else ""
        risk_line = f" Avoid: {compact_text(task.get('riskControl'), 120)}." if task.get("riskControl") else ""
        panel_lines.append(
            f"{task['position']} ({task['title']} / {task['slotType']}): "
            f"{compact_text(task['purpose'], 160)}.{label_line}{risk_line}\n"
            f"{compact_text(task['panelPrompt'], 900)}"
        )

    return f"""
You are a Temu cross-border ecommerce product visual analyst. Analyze first, then execute.

Create one single {key} ecommerce mother image. It must be a strict grid with {rows * cols} equal square panels.
Each panel is an independent 1:1 product listing image. Use clean white grid gutters between panels.
No product or text may cross panel boundaries. Do not merge cells.

Product facts to preserve:
{product_json}

Reference image fidelity:
{REFERENCE_FIDELITY_RULE}

Global style:
Bright high-conversion US Temu-style ecommerce poster photography with strong visual impact, realistic product texture,
consistent lighting, clear subject visibility, polished commercial composition, vivid but controlled background design.
Clean means the product is the unmistakable hero. Backgrounds may be colorful or decorative, but must not overpower it.
Do not show Temu word, platform UI, brand logo, watermark, QR code, price, discount, star rating,
medical claims, absolute claims, or misleading safety/certification claims.
{label_policy_text(allow_short_labels)}
{COMPARISON_TEXT_POLICY}

Panel instructions:
{chr(10).join(panel_lines)}

Final output must be one complete grid mother image, suitable for precise slicing into separate square ecommerce listing images.
""".strip()


def request_product_analysis(
    *,
    api_url: str,
    api_key: str,
    model: str,
    product_image_path: Path | None = None,
    product_image_paths: list[Path] | None = None,
    context: dict[str, Any] | None = None,
    image_max_side: int | None = None,
    image_quality: int = 86,
) -> dict[str, Any]:
    instruction = build_product_analysis_instruction(context)
    image_paths = [path for path in (product_image_paths or []) if path and path.exists()]
    if not image_paths and product_image_path and product_image_path.exists():
        image_paths = [product_image_path]
    if not image_paths:
        raise VisualGenerationError("product analysis requires at least one reference image")
    if api_url.rstrip("/").endswith("/chat/completions"):
        content: list[dict[str, Any]] = [{"type": "text", "text": instruction}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": image_file_to_data_url(path, max_side=image_max_side, quality=image_quality)},
            }
            for path in image_paths
        )
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
        }
    else:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": instruction}]
        content.extend(
            {
                "type": "input_image",
                "image_url": image_file_to_data_url(path, max_side=image_max_side, quality=image_quality),
            }
            for path in image_paths
        )
        payload = {
            "model": model,
            "input": [{"role": "user", "content": content}],
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

