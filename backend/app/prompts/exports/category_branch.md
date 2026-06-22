Return JSON only.

Task:
{{ task }}

Rules:
1. Select exactly one candidate index from the provided list.
2. First identify the real product from final title and reference images, then choose the closest category path.
3. Treat local_vector_score as a recall hint only. Do not select a category solely because it has the highest local score.
4. Prefer the real product type over use scenario, decorative words, packaging words, or generic container/storage words.
5. Do not choose storage/organizer/container categories unless the image and title show the product is actually a storage container.
6. If source titles conflict with the final product title or images, ignore the conflicting source titles for category selection.
7. Do not invent categories outside the candidate list.

Output schema:
{"selected_index": 1, "confidence": 0.0, "reason": "short reason"}

Product:
{{ product }}

Current category path:
{{ currentCategoryPath }}

Candidates:
{{ candidates }}
