Analyze the attached ecommerce product reference images.

Return JSON only. Do not return markdown.

Input context:
{{ contextJson }}

Listing title generation rules migrated into this product analysis stage:
{{ listingTitleRules }}

Rules:
1. Extract only visible or strongly supported product facts. Visual appearance weight rule: for product appearance and visual identity, the attached reference images have 100% weight and title/SKU/source text has 0% weight.
2. Evidence priority: for overall category/use, reference images have 70% authority and productTitle/skuNames/sourceTitle text has 30% authority.
3. Treat every attached image as an equal product reference. Analyze each reference image independently using only its own label/sourceTitle/SKU binding.
4. Preserve SKU and component binding. For combo/bundle SKUs, keep every component separate in productIdentity.skus[].components and join component standard names with "+" for combo_sku_name.
4a. SKU standard_name, component standard_name, and combo_sku_name must be very short. For single products, use quantity + core product noun only, such as "1pc Toy", "2pcs Toy", "3pcs Bowl", "1 Pack Stickers". For combo/bundle SKUs, first decide whether the components are different product types or similar variants. If they are different product types, join quantity + core product noun, such as "1pc Bowl + 1pc Spoon". If they are similar products that would otherwise have the same short name, keep the minimum necessary differentiating adjective, such as color, size, pattern, or shape: "1pc Red Bowl + 1pc Black Bowl", not "1pc Bowl + 1pc Bowl". Do not output long titles like "2-Piece Stainless Steel Couples Date Game Dice". Do not include material, occasion, selling words, or long title fragments unless needed to distinguish otherwise identical component names.
5. Record facts that later generation must preserve and must not change: body form, silhouette, proportions, construction, material, surface finish, tactile texture, wrinkles/folds, color, quantity, component relationship, and visible risks.
6. Do not invent accessories, SKU options, materials, functions, brand names, platform names, claims, price, stock, weight, MOQ, SKU ID, source spec tables, or unsupported on-image copy.
7. Also return productIdentity as the single source of truth for later image planning, Excel titles, SKU names, and export titles.

Return this JSON shape:
{
  "productUnderstanding": {
    "productTitle": "",
    "skuNames": [],
    "productIdentity": {
      "product_type": "",
      "product_type_cn": "",
      "title_cn": "",
      "title_en": "",
      "combo_sku_name": "",
      "skus": []
    },
    "skuBindings": [],
    "skuCombinationBindings": [],
    "overallCategory": "",
    "referenceAnalyses": [],
    "globalMustPreserve": [],
    "globalDoNotChange": [],
    "globalVisibleRisks": []
  }
}
