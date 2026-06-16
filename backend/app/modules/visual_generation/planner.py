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
    "Comparison panels may use explanatory English copy when useful. They may show a clear side-by-side comparison "
    "between the selected product and a plain generic alternative, with objective difference points, arrows, labels, "
    "or short sentences chosen by the model. The text amount should be decided by the model based on product category "
    "and visual clarity, but it must remain readable, safe, factual, and not cover the product. Do not make absolute "
    "superiority, medical, safety, guarantee, price, discount, rating, certification, or platform claims."
)


def ensure_reference_fidelity_text(prompt: str) -> str:
    normalized = prompt.lower()
    if "binding visual reference" in normalized and "do not change" in normalized:
        return prompt
    return f"{prompt.rstrip()} {REFERENCE_FIDELITY_RULE}"


def build_product_analysis_instruction(context: dict[str, Any] | None = None) -> str:
    context_json = json.dumps(context or {}, ensure_ascii=False, indent=2)
    return f"""
Analyze the attached ecommerce product reference images.

Return JSON only. Do not return markdown.

Input context:
{context_json}

Rules:
1. Extract only visible or strongly supported product facts.
2. Use productTitle, skuNames, skuBindings, and skuCombinationBindings only as text hints for category, option names, source-product binding, and possible colors/specs.
3. Do not invent accessories, SKU options, materials, functions, brand names, platform names, claims, price, stock, weight, MOQ, SKU ID, or source spec tables.
4. Treat all attached reference images as equal product reference images. Do not rank them as main image versus material image.
5. For each reference image, use the image itself, its label/title, and skuBindings to identify the exact visible subject: product category, shape, color, material, quantity, surface texture, edge/rim details, printed pattern, and component relationship.
6. If multiple products or SKU components are shown across the reference images, analyze each one separately and preserve the image-to-product binding.
7. If SKU/component names are quantity-like or ambiguous, such as 1pc and 6pc, keep the sourceTitle and referenceImageIndex binding from skuBindings. Do not merge or swap components across source products.
8. If uncertain, use "unknown" or an empty array.
9. Mark only visual facts that future generation must preserve or must not change.
10. Mark visible risks in the source image: logo, watermark, QR code, price, discount, rating, platform UI, or unsafe/unsupported claims.

Return this JSON shape:
{{
  "productUnderstanding": {{
    "productTitle": "",
    "skuNames": [],
    "skuBindings": [],
    "skuCombinationBindings": [],
    "overallCategory": "",
    "referenceAnalyses": [
      {{
        "index": 1,
        "label": "",
        "role": "",
        "subject": "",
        "category": "",
        "shape": "",
        "colors": [],
        "materials": [],
        "quantity": "",
        "surfaceTexture": "",
        "edgeOrRimDetails": "",
        "printedPattern": "",
        "visibleComponents": [],
        "componentRelationship": "",
        "mustPreserve": [],
        "doNotChange": [],
        "visibleRisks": [],
        "uncertain": []
      }}
    ],
    "globalMustPreserve": [],
    "globalDoNotChange": [],
    "globalVisibleRisks": []
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
        "On-image English copy is allowed when useful. It can be a concise phrase or a short sentence "
        "when the image needs clearer feature, benefit, usage, component, comparison, bundle, or SKU explanation. "
        "Copy must be objective, purchase-oriented, safe, and supported by productTitle, skuNames, or visible product facts. "
        "Avoid brand names, platform names, price, discounts, ratings, QR codes, medical claims, absolute promises, "
        "certification claims, stock claims, shipping-time claims, and unverifiable claims. Text must not cover the product "
        "or cross panel boundaries. "
        f"{COMPARISON_TEXT_POLICY}"
    )


def context_sku_names(context: dict[str, Any] | None, product_understanding: dict[str, Any] | None = None) -> list[str]:
    candidates: list[Any] = []
    if isinstance(context, dict):
        candidates.extend(context.get("skuNames") if isinstance(context.get("skuNames"), list) else [])
    if isinstance(product_understanding, dict):
        candidates.extend(product_understanding.get("skuNames") if isinstance(product_understanding.get("skuNames"), list) else [])
    seen: set[str] = set()
    result: list[str] = []
    for value in candidates:
        name = str(value or "").strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def context_sku_bindings(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(context, dict):
        return []
    bindings = context.get("skuBindings")
    if not isinstance(bindings, list):
        return []
    return [item for item in bindings if isinstance(item, dict)]


def context_sku_combination_bindings(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(context, dict):
        return []
    bindings = context.get("skuCombinationBindings")
    if isinstance(bindings, list):
        return [item for item in bindings if isinstance(item, dict)]
    return [
        item
        for item in context_sku_bindings(context)
        if item.get("skuKind") == "combo" or len(item.get("components") or []) > 1
    ]


def context_reference_images(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(context, dict):
        return []
    references = context.get("referenceImages")
    if not isinstance(references, list):
        return []
    return [item for item in references if isinstance(item, dict)]


def build_prompt_plan_instruction(
    *,
    product_analysis: dict[str, Any],
    layout: str,
    allow_short_labels: bool = True,
    requested_count: int | None = None,
    context: dict[str, Any] | None = None,
    candidate_modules: list[dict[str, Any]] | None = None,
) -> str:
    rows, cols = parse_layout(layout)
    key = layout_key(rows, cols)
    expected = requested_count or rows * cols
    modules = candidate_modules or default_slot_blueprints(layout)
    product_json = json.dumps(product_analysis, ensure_ascii=False, indent=2)
    sku_json = json.dumps(context_sku_names(context, product_analysis), ensure_ascii=False, indent=2)
    sku_binding_json = json.dumps(context_sku_bindings(context), ensure_ascii=False, indent=2)
    sku_combo_json = json.dumps(context_sku_combination_bindings(context), ensure_ascii=False, indent=2)
    module_json = json.dumps(modules, ensure_ascii=False, indent=2)
    return f"""
You are an ecommerce listing image task planner.

Plan the image modules for one product image batch.

Return JSON only. Do not return markdown.

Input:
{{
  "productUnderstanding": {product_json},
  "requestedCount": {expected},
  "layout": "{key}",
  "skuNames": {sku_json},
  "skuBindings": {sku_binding_json},
  "skuCombinationBindings": {sku_combo_json},
  "candidateModules": {module_json}
}}

Rules:
1. The requestedCount is fixed by the user/system. Return exactly {expected} modules.
2. Do not decide a different image count.
3. Choose, replace, and order modules from the candidateModules according to the product title, visible product facts, SKU bindings, and commercial listing needs.
4. Do not invent SKU details, price, weight, stock, MOQ, SKU ID, source specification tables, brand names, certifications, platform names, or unsupported claims.
5. Use skuNames as option/category/color/spec text hints, but use skuBindings and reference image labels/titles as the authority for which SKU/component belongs to which source product and reference image.
6. Treat all reference images as equal product references. Do not prioritize "main image" over "material image"; infer the product shown in each image from the image content and label/title.
7. If the product has multiple SKU names or combo SKU components, plan whether the batch should show one selected SKU, multiple SKU color options, bundle/combination value, or SKU-specific detail images.
8. If SKU/component names are quantity-like or ambiguous, such as 1pc and 6pc, never interpret them by name alone. Preserve each component's sourceTitle and referenceImageIndex binding.
9. For combo SKUs, every component listed in skuCombinationBindings must be represented in combo/package/option panels unless the component is explicitly marked unsafe or visually unavailable.
10. Each module must preserve productUnderstanding.globalMustPreserve and avoid productUnderstanding.globalDoNotChange.
11. Each module may plan whether on-image copy is useful.
12. On-image copy intent can include feature introduction, benefit emphasis, usage scene, component explanation, comparison, bundle value, or SKU option clarification.
13. Do not write the final full on-image copy here. Only define copyIntent and textPolicy.
14. Text must be objective, safe, purchase-oriented, and supported by productTitle, skuNames, skuBindings, reference image labels/titles, or visible product facts.
15. Do not use medical claims, absolute promises, certification claims, platform names, brand names, price, discount, rating, stock, shipping time, or unverifiable claims.
16. Keep the overall batch visually coherent: consistent product identity, lighting family, marketplace polish, and non-conflicting backgrounds.
17. Text availability rule: {label_policy_text(allow_short_labels)}

Return this JSON shape:
{{
  "visualTaskPlan": {{
    "requestedCount": {expected},
    "layout": "{key}",
    "batchGoal": "",
    "globalStyleDirection": "",
    "globalTextPolicy": "",
    "modules": [
      {{
        "position": 1,
        "slotType": "",
        "title": "",
        "purpose": "",
        "targetSkuName": "",
        "targetSkuBinding": "",
        "referenceIndexes": [],
        "visualFocus": [],
        "compositionBrief": "",
        "sceneBrief": "",
        "copyRequired": true,
        "copyIntent": "",
        "textPolicy": "",
        "mustPreserve": [],
        "doNotChange": [],
        "allowedVariation": [],
        "safetyAvoid": [],
        "reason": ""
      }}
    ]
  }}
}}
""".strip()


def build_panel_prompt_instruction(
    *,
    product_understanding: dict[str, Any],
    visual_task_plan: dict[str, Any],
    layout: str,
    allow_short_labels: bool = True,
    context: dict[str, Any] | None = None,
) -> str:
    product_json = json.dumps(product_understanding, ensure_ascii=False, indent=2)
    plan_json = json.dumps(visual_task_plan, ensure_ascii=False, indent=2)
    sku_json = json.dumps(context_sku_names(context, product_understanding), ensure_ascii=False, indent=2)
    sku_binding_json = json.dumps(context_sku_bindings(context), ensure_ascii=False, indent=2)
    sku_combo_json = json.dumps(context_sku_combination_bindings(context), ensure_ascii=False, indent=2)
    reference_json = json.dumps(context_reference_images(context), ensure_ascii=False, indent=2)
    rows, cols = parse_layout(layout)
    key = layout_key(rows, cols)
    return f"""
You are an ecommerce image prompt writer.

Write complete English prompts for each planned square product image panel.

Return JSON only. Do not return markdown.

Input:
{{
  "productUnderstanding": {product_json},
  "visualTaskPlan": {plan_json},
  "layout": "{key}",
  "skuNames": {sku_json},
  "skuBindings": {sku_binding_json},
  "skuCombinationBindings": {sku_combo_json},
  "referenceImages": {reference_json}
}}

Rules:
1. Create one panel prompt for each module in visualTaskPlan.modules.
2. Each panel prompt must be written in English and ready for an image generation model.
3. Preserve the exact product facts from productUnderstanding: product category, shape, color, material, quantity, texture, rim/edge details, printed pattern, visible components, and component relationship.
4. Treat reference images as equal binding product references, not loose inspiration. Do not rank them as main image versus material image.
5. Do not replace the selected SKU/product with a generic category item.
6. Use targetSkuName and skuNames as option/category/color/spec hints, but use skuBindings plus reference image labels/titles as the authority for component-to-source-product and reference-image binding. Do not add hidden SKU data.
7. If SKU/component names are quantity-like or ambiguous, such as 1pc and 6pc, write the prompt so each component remains tied to its sourceTitle and referenceImageIndex. Do not swap, merge, or treat them as generic quantities.
8. For combo/package/option panels, include every component listed in the target SKU binding. If the user supplied images and titles for multiple components, the prompt must ask for all those components in the same panel when the SKU represents a combo.
9. Add composition, camera angle, lighting, background, scene, props, text placement, and ecommerce style only when they support the module purpose.
10. On-image copy is allowed when useful for purchase motivation, feature introduction, usage explanation, component explanation, comparison, bundle value, or SKU clarification.
11. On-image copy does not have to be extremely short. It may be a concise phrase or a short sentence when the module needs clearer selling-point explanation.
12. On-image copy must be objective, safe, and supported by productTitle, skuNames, skuBindings, reference image labels/titles, or visible product facts.
13. Do not include medical claims, absolute promises, certification claims, brand names, platform names, price, discount, rating, stock, shipping time, QR code, watermark, or platform UI.
14. Text must not cover the product subject, must not dominate the product, and must stay inside the panel.
15. Keep all panels visually coherent as one listing batch: consistent product identity, lighting family, color temperature, marketplace polish, and compatible background language.
16. Make every prompt self-contained enough for the image generation model to produce the intended panel.
17. Text availability rule: {label_policy_text(allow_short_labels)}

Return this JSON shape:
{{
  "panelPromptPlan": {{
    "globalConsistency": "",
    "panels": [
      {{
        "position": 1,
        "slotType": "",
        "targetSkuName": "",
        "targetSkuBinding": "",
        "onImageCopy": [],
        "panelPrompt": "",
        "negativePrompt": "",
        "safetyNotes": []
      }}
    ]
  }}
}}
""".strip()


def normalized_visual_task_plan(
    parsed: dict[str, Any],
    layout: str,
    requested_count: int | None = None,
    candidate_modules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows, cols = parse_layout(layout)
    key = layout_key(rows, cols)
    expected = requested_count or rows * cols
    blueprints = candidate_modules or default_slot_blueprints(layout)
    source = parsed.get("visualTaskPlan") if isinstance(parsed.get("visualTaskPlan"), dict) else parsed
    raw_modules = source.get("modules") if isinstance(source, dict) and isinstance(source.get("modules"), list) else []
    modules: list[dict[str, Any]] = []
    for index in range(expected):
        raw = raw_modules[index] if index < len(raw_modules) and isinstance(raw_modules[index], dict) else {}
        blueprint = blueprints[min(index, len(blueprints) - 1)]
        modules.append(
            {
                "position": index + 1,
                "slotType": str(raw.get("slotType") or blueprint.get("slotType") or "product-image"),
                "title": str(raw.get("title") or blueprint.get("title") or f"Panel {index + 1}"),
                "purpose": str(raw.get("purpose") or blueprint.get("purpose") or "clear ecommerce product image"),
                "targetSkuName": str(raw.get("targetSkuName") or ""),
                "targetSkuBinding": str(raw.get("targetSkuBinding") or ""),
                "referenceIndexes": raw.get("referenceIndexes") if isinstance(raw.get("referenceIndexes"), list) else [],
                "visualFocus": raw.get("visualFocus") if isinstance(raw.get("visualFocus"), list) else [],
                "compositionBrief": str(raw.get("compositionBrief") or ""),
                "sceneBrief": str(raw.get("sceneBrief") or ""),
                "copyRequired": bool(raw.get("copyRequired")) if "copyRequired" in raw else True,
                "copyIntent": str(raw.get("copyIntent") or ""),
                "textPolicy": str(raw.get("textPolicy") or ""),
                "mustPreserve": raw.get("mustPreserve") if isinstance(raw.get("mustPreserve"), list) else [],
                "doNotChange": raw.get("doNotChange") if isinstance(raw.get("doNotChange"), list) else [],
                "allowedVariation": raw.get("allowedVariation") if isinstance(raw.get("allowedVariation"), list) else [],
                "safetyAvoid": raw.get("safetyAvoid") if isinstance(raw.get("safetyAvoid"), list) else [],
                "reason": str(raw.get("reason") or ""),
            }
        )
    return {
        "requestedCount": expected,
        "layout": key,
        "batchGoal": str(source.get("batchGoal") or "") if isinstance(source, dict) else "",
        "globalStyleDirection": str(source.get("globalStyleDirection") or "") if isinstance(source, dict) else "",
        "globalTextPolicy": str(source.get("globalTextPolicy") or "") if isinstance(source, dict) else "",
        "modules": modules,
    }


def _panel_prompt_fallback(
    *,
    module: dict[str, Any],
    product_understanding: dict[str, Any],
    allow_short_labels: bool = True,
) -> str:
    product_hint = json.dumps(compact_json_value(product_understanding, max_items=5, max_chars=120), ensure_ascii=False)
    target_sku = str(module.get("targetSkuName") or "").strip()
    sku_line = f" Target SKU option: {target_sku}." if target_sku else ""
    target_binding = str(module.get("targetSkuBinding") or "").strip()
    binding_line = f" SKU/component binding: {target_binding}." if target_binding else ""
    copy_line = (
        f" On-image copy intent: {module.get('copyIntent')}. Text policy: {module.get('textPolicy')}. "
        if module.get("copyRequired")
        else " Do not add readable on-image text. "
    )
    return ensure_reference_fidelity_text(
        "Create a square 1:1 ecommerce product image. "
        f"Module: {module.get('title')}. Purpose: {module.get('purpose')}.{sku_line}{binding_line} "
        f"Product facts to preserve: {product_hint}. "
        f"Composition: {module.get('compositionBrief')}. Scene: {module.get('sceneBrief')}. "
        f"{copy_line}{label_policy_text(allow_short_labels)} "
        "Use polished commercial lighting, clear product visibility, realistic texture, and a coherent listing style. "
        "No brand logo, platform logo, watermark, QR code, price, discount, rating, medical claim, certification claim, "
        "stock claim, shipping-time claim, or platform UI."
    )


def normalized_panel_prompt_plan(
    parsed: dict[str, Any],
    *,
    product_understanding: dict[str, Any],
    visual_task_plan: dict[str, Any],
    layout: str,
    allow_short_labels: bool = True,
) -> dict[str, Any]:
    source = parsed.get("panelPromptPlan") if isinstance(parsed.get("panelPromptPlan"), dict) else parsed
    raw_panels = source.get("panels") if isinstance(source, dict) and isinstance(source.get("panels"), list) else []
    panels: list[dict[str, Any]] = []
    modules = visual_task_plan.get("modules") if isinstance(visual_task_plan.get("modules"), list) else []
    for index, module in enumerate(modules):
        raw = raw_panels[index] if index < len(raw_panels) and isinstance(raw_panels[index], dict) else {}
        on_image_copy = raw.get("onImageCopy") if isinstance(raw.get("onImageCopy"), list) else []
        safety_notes = raw.get("safetyNotes") if isinstance(raw.get("safetyNotes"), list) else []
        panel_prompt = str(raw.get("panelPrompt") or "").strip()
        if not panel_prompt:
            panel_prompt = _panel_prompt_fallback(
                module=module,
                product_understanding=product_understanding,
                allow_short_labels=allow_short_labels,
            )
        else:
            panel_prompt = ensure_reference_fidelity_text(panel_prompt)
        panels.append(
            {
                "position": index + 1,
                "slotType": str(raw.get("slotType") or module.get("slotType") or ""),
                "targetSkuName": str(raw.get("targetSkuName") or module.get("targetSkuName") or ""),
                "targetSkuBinding": str(raw.get("targetSkuBinding") or module.get("targetSkuBinding") or ""),
                "onImageCopy": on_image_copy,
                "panelPrompt": panel_prompt,
                "negativePrompt": str(raw.get("negativePrompt") or ""),
                "safetyNotes": safety_notes,
            }
        )
    return {
        "globalConsistency": str(source.get("globalConsistency") or "") if isinstance(source, dict) else "",
        "panels": panels,
    }


def normalized_panel_tasks(plan: dict[str, Any], layout: str, allow_short_labels: bool = True) -> list[dict[str, Any]]:
    rows, cols = parse_layout(layout)
    key = layout_key(rows, cols)
    expected = rows * cols
    positions = POSITION_NAMES[key]
    blueprints = default_slot_blueprints(layout)
    raw_tasks = plan.get("panelTasks")
    if not isinstance(raw_tasks, list):
        raw_tasks = []
    if not raw_tasks:
        visual_task_plan = plan.get("visualTaskPlan") if isinstance(plan.get("visualTaskPlan"), dict) else {}
        panel_prompt_plan = plan.get("panelPromptPlan") if isinstance(plan.get("panelPromptPlan"), dict) else {}
        modules = visual_task_plan.get("modules") if isinstance(visual_task_plan.get("modules"), list) else []
        panels = panel_prompt_plan.get("panels") if isinstance(panel_prompt_plan.get("panels"), list) else []
        for index in range(expected):
            module = modules[index] if index < len(modules) and isinstance(modules[index], dict) else {}
            panel = panels[index] if index < len(panels) and isinstance(panels[index], dict) else {}
            safety_notes = panel.get("safetyNotes") if isinstance(panel.get("safetyNotes"), list) else []
            on_image_copy = panel.get("onImageCopy") if isinstance(panel.get("onImageCopy"), list) else []
            raw_tasks.append(
                {
                    "panelIndex": index + 1,
                    "position": positions[index],
                    "slotType": panel.get("slotType") or module.get("slotType"),
                    "title": module.get("title"),
                    "purpose": module.get("purpose"),
                    "targetSkuName": panel.get("targetSkuName") or module.get("targetSkuName"),
                    "targetSkuBinding": panel.get("targetSkuBinding") or module.get("targetSkuBinding"),
                    "safeLabels": on_image_copy,
                    "riskControl": "; ".join(str(note) for note in safety_notes),
                    "panelPrompt": panel.get("panelPrompt"),
                    "negativePrompt": panel.get("negativePrompt"),
                }
            )

    product_analysis = plan.get("productUnderstanding") or plan.get("productAnalysis") or {}
    product_name = ""
    if isinstance(product_analysis, dict):
        product_name = str(
            product_analysis.get("productName")
            or product_analysis.get("mainObject")
            or product_analysis.get("overallCategory")
            or product_analysis.get("productTitle")
            or ""
        ).strip()
    product_name = product_name or "the product"

    tasks: list[dict[str, Any]] = []
    for index in range(expected):
        raw = raw_tasks[index] if index < len(raw_tasks) and isinstance(raw_tasks[index], dict) else {}
        blueprint = blueprints[min(index, len(blueprints) - 1)]
        prompt = str(raw.get("panelPrompt") or raw.get("prompt") or "").strip()
        if not prompt:
            prompt = (
                f"Create a square 1:1 ecommerce image for {product_name}. "
                f"Module: {blueprint['title']}. Purpose: {blueprint['purpose']}. "
                "Keep product structure, color, material, quantity, and key details accurate. "
                "Use bright high-conversion ecommerce photography with clear purchase motivation, "
                "vivid but controlled background design, clean subject-dominant composition, "
                "clear product visibility, and realistic lighting. "
                "No brand logo, no platform logo, no watermark, no QR code, no price, no discount, "
                "no star rating, no medical claim, no certification claim, no stock claim, no shipping-time claim, "
                "no absolute marketing claim."
            )
        prompt = ensure_reference_fidelity_text(prompt)
        tasks.append(
            {
                "panelIndex": index + 1,
                "position": positions[index],
                "slotType": str(raw.get("slotType") or blueprint["slotType"]),
                "title": str(raw.get("title") or blueprint["title"]),
                "purpose": str(raw.get("purpose") or blueprint["purpose"]),
                "targetSkuName": str(raw.get("targetSkuName") or ""),
                "targetSkuBinding": str(raw.get("targetSkuBinding") or ""),
                "safeLabels": raw.get("safeLabels") if allow_short_labels and isinstance(raw.get("safeLabels"), list) else [],
                "riskControl": str(raw.get("riskControl") or ""),
                "negativePrompt": str(raw.get("negativePrompt") or ""),
                "panelPrompt": prompt,
            }
        )
    return tasks


def build_mother_prompt_from_plan(plan: dict[str, Any], layout: str, allow_short_labels: bool = True) -> str:
    rows, cols = parse_layout(layout)
    key = layout_key(rows, cols)
    tasks = normalized_panel_tasks(plan, layout, allow_short_labels)
    expected = rows * cols
    product_json = json.dumps(plan.get("productUnderstanding") or plan.get("productAnalysis") or {}, ensure_ascii=False, indent=2)
    sku_binding_json = json.dumps(plan.get("skuBindings") or [], ensure_ascii=False, indent=2)
    sku_combo_json = json.dumps(plan.get("skuCombinationBindings") or [], ensure_ascii=False, indent=2)
    panel_lines = []
    for task in tasks:
        labels = task.get("safeLabels") or []
        label_line = f" Planned on-image copy: {', '.join(str(label) for label in labels)}." if labels else ""
        risk_line = f" Risk control: {task['riskControl']}." if task.get("riskControl") else ""
        sku_line = f" Target SKU: {task['targetSkuName']}." if task.get("targetSkuName") else ""
        binding_line = f" SKU/component binding: {task['targetSkuBinding']}." if task.get("targetSkuBinding") else ""
        negative_line = f" Negative prompt: {task['negativePrompt']}." if task.get("negativePrompt") else ""
        panel_lines.append(
            f"Panel {task['panelIndex']} - {task['position']} ({task['title']} / {task['slotType']}): "
            f"Purpose: {task['purpose']}.{sku_line}{binding_line}{label_line}{risk_line}{negative_line}\n"
            f"{task['panelPrompt']}"
        )

    return f"""
Create one single {key} ecommerce mother image.

This mother image contains {expected} independent square listing-image panels.

Grid rules:
1. Use a strict {key} grid.
2. Every panel must be an equal square.
3. Use clean white gutters between panels.
4. Do not merge panels.
5. Do not let products, text, props, shadows, or backgrounds cross panel boundaries.
6. Do not add panel numbers.
7. Do not add extra panels.
8. Do not leave any panel blank.
9. The final image must be suitable for precise programmatic slicing into separate square ecommerce listing images.

Global product consistency:
1. Use the analyzed reference image facts, reference image labels/titles, and SKU/component binding facts as binding product references.
2. Treat all reference images as equal product references; do not prioritize a "main" image over other supplied product images.
3. Preserve product shape, color, material, quantity, structure, component relationship, surface texture, rim/edge details, and printed pattern for every SKU/component with supplied visual facts.
4. For combo SKUs, include every component listed in the combo binding when a panel is about combo/package/option contents.
5. Do not replace the selected product/SKU with a generic category item.
6. Keep all panels visually coherent as one commercial listing batch.

Product facts to preserve:
{product_json}

SKU/component binding facts:
{sku_binding_json}

Combo SKU composition facts:
{sku_combo_json}

Global safety:
No brand logo, platform logo, watermark, QR code, price, discount, rating, certification badge, medical claim, absolute claim, stock claim, shipping-time claim, or platform UI.

Panel instructions:
{chr(10).join(panel_lines)}

Final output:
One complete {key} mother image only.
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
        compact_json_value(plan.get("productUnderstanding") or plan.get("productAnalysis") or {}, max_items=6, max_chars=140),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    sku_binding_json = json.dumps(
        compact_json_value(plan.get("skuBindings") or [], max_items=10, max_chars=140),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    sku_combo_json = json.dumps(
        compact_json_value(plan.get("skuCombinationBindings") or [], max_items=10, max_chars=140),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    panel_lines = []
    for task in tasks:
        labels = task.get("safeLabels") or []
        label_line = f" Copy: {', '.join(str(label) for label in labels[:3])}." if labels else ""
        risk_line = f" Avoid: {compact_text(task.get('riskControl'), 120)}." if task.get("riskControl") else ""
        sku_line = f" SKU: {compact_text(task.get('targetSkuName'), 80)}." if task.get("targetSkuName") else ""
        binding_line = (
            f" Binding: {compact_text(task.get('targetSkuBinding'), 160)}." if task.get("targetSkuBinding") else ""
        )
        panel_lines.append(
            f"Panel {task['panelIndex']} - {task['position']} ({task['title']} / {task['slotType']}): "
            f"{compact_text(task['purpose'], 160)}.{sku_line}{binding_line}{label_line}{risk_line}\n"
            f"{compact_text(task['panelPrompt'], 900)}"
        )

    return f"""
Create one single {key} ecommerce mother image with {rows * cols} independent square listing-image panels.

Product facts to preserve:
{product_json}

SKU/component binding facts:
{sku_binding_json}

Combo SKU composition facts:
{sku_combo_json}

Grid rules:
Use a strict {key} grid, equal square panels, clean white gutters, no merged panels, no blank panels, no panel numbers,
and no product, text, prop, shadow, or background crossing panel boundaries.

Global product consistency:
Use analyzed reference image facts, reference image labels/titles, and SKU/component binding facts as binding product references.
Treat all supplied images as equal product references, not main-versus-material hierarchy. Preserve product shape, color, material, quantity,
structure, component relationship, surface texture, rim/edge details, and printed pattern for every SKU/component with supplied visual facts.
For combo/package/option panels, include every component listed in the combo binding. Do not replace the selected product/SKU with a generic category item.

Global safety:
No brand logo, platform logo, watermark, QR code, price, discount, rating, certification badge, medical claim,
absolute claim, stock claim, shipping-time claim, or platform UI.

Panel instructions:
{chr(10).join(panel_lines)}

Final output: one complete {key} mother image only, suitable for precise programmatic slicing.
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
    product_analysis = parsed.get("productUnderstanding") or parsed.get("productAnalysis") or parsed
    if not isinstance(product_analysis, dict):
        raise VisualGenerationError("product analysis result is missing productUnderstanding")
    return product_analysis


def request_prompt_plan(
    *,
    api_url: str,
    api_key: str,
    model: str,
    product_analysis: dict[str, Any],
    layout: str,
    allow_short_labels: bool = True,
    requested_count: int | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_modules = default_slot_blueprints(layout)
    sku_bindings = context_sku_bindings(context)
    sku_combination_bindings = context_sku_combination_bindings(context)
    parsed_task_plan = request_text_json(
        api_url=api_url,
        api_key=api_key,
        model=model,
        instruction=build_prompt_plan_instruction(
            product_analysis=product_analysis,
            layout=layout,
            allow_short_labels=allow_short_labels,
            requested_count=requested_count,
            context=context,
            candidate_modules=candidate_modules,
        ),
        temperature=0.6,
    )
    visual_task_plan = normalized_visual_task_plan(
        parsed_task_plan,
        layout,
        requested_count=requested_count,
        candidate_modules=candidate_modules,
    )
    parsed_panel_prompt_plan = request_text_json(
        api_url=api_url,
        api_key=api_key,
        model=model,
        instruction=build_panel_prompt_instruction(
            product_understanding=product_analysis,
            visual_task_plan=visual_task_plan,
            layout=layout,
            allow_short_labels=allow_short_labels,
            context=context,
        ),
        temperature=0.6,
    )
    panel_prompt_plan = normalized_panel_prompt_plan(
        parsed_panel_prompt_plan,
        product_understanding=product_analysis,
        visual_task_plan=visual_task_plan,
        layout=layout,
        allow_short_labels=allow_short_labels,
    )
    raw_plan = {
        "productUnderstanding": product_analysis,
        "productAnalysis": product_analysis,
        "skuBindings": sku_bindings,
        "skuCombinationBindings": sku_combination_bindings,
        "visualTaskPlan": visual_task_plan,
        "panelPromptPlan": panel_prompt_plan,
    }
    tasks = normalized_panel_tasks(
        raw_plan,
        layout,
        allow_short_labels,
    )
    return {
        "productUnderstanding": product_analysis,
        "productAnalysis": product_analysis,
        "skuBindings": sku_bindings,
        "skuCombinationBindings": sku_combination_bindings,
        "visualTaskPlan": visual_task_plan,
        "panelPromptPlan": panel_prompt_plan,
        "panelTasks": tasks,
        "modelRouting": {
            "analysisStage": "vision-analysis",
            "taskPlanStage": "visual-task-planning",
            "panelPromptStage": "panel-prompt-generation",
            "motherPromptStage": "mother-prompt-assembly",
            "taskPlanTemperature": 0.6,
            "panelPromptTemperature": 0.6,
            "allowShortLabels": allow_short_labels,
        },
    }

