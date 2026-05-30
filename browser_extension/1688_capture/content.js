chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "COLLECT_1688_PRODUCT") return false;

  try {
    sendResponse({ ok: true, payload: collect1688Product() });
  } catch (error) {
    sendResponse({
      ok: false,
      error: error instanceof Error ? error.message : "采集失败",
    });
  }

  return true;
});

function collect1688Product() {
  const productUrl = location.href;
  const title = pickTitle();
  if (!title) throw new Error("未识别到商品标题");

  const selectedQuantity = findSelectedQuantity();
  const goodsPrice = findGoodsPrice();
  const shippingFee = findShippingFee();
  const unitPriceWithShipping = computeUnitPrice(goodsPrice, shippingFee, selectedQuantity);
  const weightKg = findWeight();
  const priceRange = pickPriceRange(goodsPrice);
  const galleryImageUrls = pickGalleryImages();
  const mainImageUrl = galleryImageUrls[0] || null;
  const skuList = enrichSkuImages(pickSkuList(), galleryImageUrls);
  const skuImageCount = skuList.filter((sku) => sku.image_url).length;
  const categoryParts = pickCategoryParts();
  const categoryPath = categoryParts.join("/");

  return {
    offer_id: pickOfferId(productUrl),
    product_url: productUrl,
    title,
    main_image_url: mainImageUrl,
    price: toOptionalNumber(goodsPrice) ?? pickPrice(),
    price_range: priceRange,
    moq: pickMoq(),
    shop_name: pickShopName(),
    shop_url: pickShopUrl(),
    sku_list: skuList,
    captured_at: new Date().toISOString().slice(0, 19).replace("T", " "),
    raw_data: {
      page_title: document.title,
      url: productUrl,
      user_agent: navigator.userAgent,
      goods_price: toOptionalNumber(goodsPrice),
      shipping_fee: toOptionalNumber(shippingFee),
      unit_price_with_shipping: toOptionalNumber(unitPriceWithShipping),
      selected_quantity: selectedQuantity,
      weight_kg: toPositiveOptionalNumber(weightKg),
      price_text: pickPriceText(),
      category_path: categoryPath || null,
      category_parts: categoryParts,
      gallery_image_urls: galleryImageUrls,
      product_image_count: galleryImageUrls.length,
      sku_text_count: skuList.length,
      sku_image_count: skuImageCount,
    },
  };
}

function pickTitle() {
  const candidates = [
    document.querySelector("meta[property='og:title']")?.getAttribute("content"),
    document.querySelector("meta[name='title']")?.getAttribute("content"),
    cleanPageTitle(document.title),
    queryText([
      "[class*='offer-title']",
      "[class*='product-title']",
      "[class*='main-title']",
      "[class*='detail-title']",
      "[data-module*='title'] h1",
      "h1",
    ]),
  ]
    .map(cleanPageTitle)
    .filter(Boolean);

  return candidates.find(isLikelyProductTitle) || candidates[0] || "";
}

function pickOfferId(url) {
  const match = url.match(/offer\/(\d+)\.html/i) || url.match(/[?&]offerId=(\d+)/i);
  return match?.[1] || null;
}

function pickMainImage() {
  return pickGalleryImages()[0] || null;
}

function pickGalleryImages() {
  const metaImage =
    document.querySelector("meta[property='og:image']")?.getAttribute("content") ||
    document.querySelector("meta[name='og:image']")?.getAttribute("content");
  const imageUrls = [metaImage];
  const selectors = [
    "#dt-tab img",
    "#dt-tab source",
    "[class*='thumb'] img",
    "[class*='Thumb'] img",
    "[class*='preview'] img",
    "[class*='Preview'] img",
    "[class*='main'] img",
    "[class*='gallery'] img",
    "[class*='image'] img",
  ];

  for (const selector of selectors) {
    for (const element of document.querySelectorAll(selector)) {
      imageUrls.push(...pickImageUrlsFromElement(element));
    }
  }

  imageUrls.push(...extractImageUrlsFromText(getInlineContextScriptText()));

  return uniqueImageUrls(imageUrls).filter(isLikelyProductImageUrl).slice(0, 30);
}

function pickPrice() {
  const text = pickPriceText();
  const numbers = parseNumbers(text);
  return numbers[0] ?? null;
}

function pickPriceRange(fallbackPrice = "") {
  const scriptText = getInlineContextScriptText();
  const priceDisplay = extractValueByPatterns(scriptText, [
    /"priceDisplay"\s*:\s*"([^"]+)"/,
    /"rangePrice"\s*:\s*"([^"]+)"/,
  ]);
  if (priceDisplay) return addYuanPrefix(priceDisplay);

  const text = pickPriceText();
  const numbers = parseNumbers(text);
  if (numbers.length >= 2) return `¥${numbers[0]}-¥${numbers[1]}`;
  if (numbers.length === 1) return `¥${numbers[0]}`;
  if (fallbackPrice) return `¥${fallbackPrice}`;
  return null;
}

function pickPriceText() {
  return cleanText(
    getFirstVisibleText([
      "#skuSelection .expand-view-item .item-price-stock",
      ".module-od-sku-selection .expand-view-item .item-price-stock",
      "#mainPrice .price-info:last-child",
      ".module-od-main-price .price-info:last-child",
      "[class*='price']",
      "[class*='Price']",
      "[class*='amount']",
      "[class*='Amount']",
    ]) || document.body.innerText.match(/[¥￥]\s*\d+(?:\.\d+)?(?:\s*[-~]\s*\d+(?:\.\d+)?)?/)?.[0]
  );
}

function pickMoq() {
  const text = document.body.innerText;
  const match =
    text.match(/(\d+)\s*(?:件|个|只|套)\s*起(?:批|订|定)/) ||
    text.match(/起(?:批|订|定)\s*(\d+)/) ||
    text.match(/MOQ\s*[:：]?\s*(\d+)/i);
  return match ? Number(match[1]) : null;
}

function pickShopName() {
  return cleanText(
    queryText([
      "[class*='shop-name']",
      "[class*='company']",
      "[class*='seller']",
      "[class*='store']",
      "a[href*='shop']",
    ])
  );
}

function pickShopUrl() {
  const link = Array.from(document.querySelectorAll("a[href]"))
    .map((a) => a.href)
    .find((href) => /shop|winport|supplier|company/i.test(href));
  return link || null;
}

function pickCategoryParts() {
  const domParts = pickCategoryPartsFromDom();
  if (domParts.length > 0) return domParts;

  const scriptParts = pickCategoryPartsFromScript();
  return scriptParts;
}

function pickCategoryPartsFromDom() {
  const selectors = [
    "[class*='breadcrumb']",
    "[class*='Breadcrumb']",
    "[class*='crumb']",
    "[class*='Crumb']",
    "[class*='category']",
    "[class*='Category']",
  ];

  for (const selector of selectors) {
    for (const container of document.querySelectorAll(selector)) {
      const elementParts = Array.from(container.querySelectorAll("a, span, li"))
        .map((element) => normalizeCategoryText(element.textContent))
        .filter(isLikelyCategoryPart);
      const parts = normalizeCategoryParts(
        elementParts.length >= 2 ? elementParts : splitCategoryText(container.textContent)
      );
      if (parts.length >= 2) return parts.slice(0, 5);
    }
  }

  return [];
}

function pickCategoryPartsFromScript() {
  const scriptText = getInlineContextScriptText();
  const categoryPath = extractValueByPatterns(scriptText, [
    /"categoryPath"\s*:\s*"([^"]+)"/,
    /"catPath"\s*:\s*"([^"]+)"/,
    /"catePath"\s*:\s*"([^"]+)"/,
  ]);
  const pathParts = normalizeCategoryParts(splitCategoryText(categoryPath));
  if (pathParts.length >= 2) return pathParts.slice(0, 5);

  const categoryNames = Array.from(
    scriptText.matchAll(/"(?:categoryName|catName|cateName)"\s*:\s*"([^"]+)"/g)
  )
    .map((match) => normalizeCategoryText(decodeJsonString(match[1])))
    .filter(isLikelyCategoryPart);
  return normalizeCategoryParts(categoryNames).slice(0, 5);
}

function splitCategoryText(value) {
  return String(value || "")
    .split(/\s*(?:>|›|»|\/|\\|｜|\|)\s*/g)
    .map(normalizeCategoryText);
}

function normalizeCategoryParts(parts) {
  const seen = new Set();
  const normalized = [];
  for (const part of parts) {
    const text = normalizeCategoryText(part);
    if (!isLikelyCategoryPart(text) || seen.has(text)) continue;
    seen.add(text);
    normalized.push(text);
  }
  return normalized;
}

function normalizeCategoryText(value) {
  return cleanText(decodeJsonString(value))
    .replace(/^[当前位置所在类目分类：:\s]+/g, "")
    .replace(/\s*批发价格.*$/g, "")
    .trim();
}

function isLikelyCategoryPart(value) {
  const text = cleanText(value);
  if (!text || text.length < 2 || text.length > 24) return false;
  if (/^\d+$/.test(text)) return false;
  if (/[¥￥$]\s*\d/.test(text)) return false;
  if (/首页|阿里巴巴|1688|商品详情|全部商品|所有分类|找工厂|找供应商|找服务|找代发|工业品|搜索|店铺|旺铺|公司/.test(text)) {
    return false;
  }
  return true;
}

function pickSkuList() {
  const contextItems = pickSkuListFromContext();
  const strongContextItems = contextItems.filter(isStrongSkuItem);
  if (strongContextItems.length > 0) {
    return mergeSkuItems(strongContextItems).slice(0, 80);
  }

  const weakContextItems = contextItems.filter(hasUsefulSpecValue);
  if (weakContextItems.length > 0 && hasExplicitSkuChoiceSignal()) {
    return mergeSkuItems(weakContextItems).slice(0, 80);
  }

  const rowItems = pickSkuRowsFromDom();
  const strongRowItems = rowItems.filter(isStrongSkuItem);
  if (strongRowItems.length > 0) {
    return mergeSkuItems(strongRowItems).slice(0, 80);
  }

  const fallbackSkuTexts = hasExplicitSkuChoiceSignal() ? pickFallbackSkuTexts() : [];
  const textItems = fallbackSkuTexts.map((text, index) => ({
    sku_id: `text-${index + 1}`,
    specs: { 规格: text },
  }));
  const mergedTextItems = mergeSkuItems(textItems).slice(0, 40);
  return mergedTextItems.length > 0 ? mergedTextItems : [buildDefaultQuantitySku()];
}

function enrichSkuImages(skuList, galleryImageUrls) {
  const imageLookup = buildSkuImageLookupFromPage();
  return skuList.map((sku) => {
    if (sku.image_url) return sku;

    const specValues = Object.values(sku.specs || {}).map(normalizeWhitespace).filter(Boolean);
    const matchedImage = specValues.map((value) => imageLookup.get(value)).find(Boolean);
    if (matchedImage) {
      return { ...sku, image_url: matchedImage };
    }

    return sku;
  });
}

function buildSkuImageLookupFromPage() {
  const lookup = new Map();
  const rows = Array.from(
    document.querySelectorAll(
      "#skuSelection .expand-view-item, .module-od-sku-selection .expand-view-item, [class*='sku'] .expand-view-item, [class*='Sku'] .expand-view-item"
    )
  );

  for (const row of rows) {
    const imageUrl = pickImageFromElement(row);
    if (!imageUrl) continue;

    const label =
      cleanText(row.querySelector(".item-label")?.getAttribute("title")) ||
      cleanText(row.querySelector(".item-label")?.textContent) ||
      cleanSkuText(row.innerText || row.textContent);

    if (label && !lookup.has(label)) lookup.set(label, imageUrl);

    const tokens = Array.from(row.querySelectorAll("button, li, span, div, td"))
      .map((element) => cleanText(element.textContent))
      .filter(isUsefulSkuText);

    for (const token of tokens) {
      if (!lookup.has(token)) lookup.set(token, imageUrl);
    }
  }

  return lookup;
}

function pickSkuListFromContext() {
  const scriptText = getInlineContextScriptText();
  const skuInfoMap = parseObjectAfterKey(scriptText, "skuInfoMap");
  const skuMap = parseObjectAfterKey(scriptText, "skuMap");
  const skuProps = parseObjectAfterKey(scriptText, "skuProps");
  const skuWeightMap = parseObjectAfterKey(scriptText, "skuWeight");
  const propMeta = collectSkuPropMeta(skuProps);
  const skuItems = [];

  if (Array.isArray(skuMap)) {
    for (const skuInfo of skuMap) {
      if (!skuInfo || typeof skuInfo !== "object") continue;
      const specValue = readFirstString(skuInfo, ["specAttrs", "spec", "name", "value", "title"]);
      const price = readFirstNumber(skuInfo, [
        "discountPrice",
        "price",
        "retailPrice",
        "salePrice",
        "currentPrice",
        "skuPrice",
      ]);
      const stock = readFirstNumber(skuInfo, [
        "canBookCount",
        "stock",
        "inventory",
        "amountOnSale",
        "saleCount",
        "quantity",
      ]);
      const weightFromInfo = readFirstNumber(skuInfo, ["weight", "unitWeight", "skuWeight"]);
      const skuId = String(readFirstString(skuInfo, ["skuId", "sku_id", "offerSkuId", "id"]) || "");
      const specId = String(readFirstString(skuInfo, ["specId", "spec_id"]) || "");
      const weightFromMap =
        skuWeightMap && typeof skuWeightMap === "object"
          ? toOptionalNumber(skuWeightMap[skuId] ?? skuWeightMap[specId] ?? skuWeightMap[specValue])
          : null;
      const imageUrl =
        readFirstImageUrl(skuInfo, [
          "imageUrl",
          "image",
          "imgUrl",
          "skuImageUrl",
          "picUrl",
          "pic",
          "url",
          "originalImageURI",
          "imageURI",
          "imageUrlWebp",
          "skuImage",
          "skuPicUrl",
        ]) || findImageForSkuValue(specValue, propMeta);

      if (specValue || imageUrl || price !== null || stock !== null) {
        skuItems.push(
          cleanSkuItem({
            sku_id: skuId || specId || specValue,
            specs: specValue ? { [propMeta.propNames[0] || "规格"]: specValue } : {},
            price,
            stock,
            image_url: imageUrl,
            weight_kg: normalizeWeightNumber(weightFromInfo ?? weightFromMap),
          })
        );
      }
    }
  }

  if (skuItems.length > 0) return skuItems;

  if (skuInfoMap && typeof skuInfoMap === "object" && !Array.isArray(skuInfoMap)) {
    for (const [rawKey, rawInfo] of Object.entries(skuInfoMap)) {
      const info = rawInfo && typeof rawInfo === "object" ? rawInfo : {};
      const keyParts = splitSkuKey(rawKey);
      const specs = {};
      let imageUrl = readFirstImageUrl(info, [
        "imageUrl",
        "image",
        "imgUrl",
        "skuImageUrl",
        "picUrl",
        "pic",
        "url",
        "originalImageURI",
        "imageURI",
        "imageUrlWebp",
        "skuImage",
        "skuPicUrl",
      ]);

      keyParts.forEach((part, index) => {
        const valueMeta = propMeta.valuesById.get(part) || propMeta.valuesByName.get(part);
        const label = valueMeta?.propName || propMeta.propNames[index] || "规格";
        const value = valueMeta?.name || part;
        specs[label] = value;
        imageUrl = imageUrl || valueMeta?.imageUrl || null;
      });

      if (Object.keys(specs).length === 0) {
        const fallbackName = readFirstString(info, ["name", "value", "spec", "title"]);
        if (fallbackName) specs["规格"] = fallbackName;
      }

      const price = readFirstNumber(info, [
        "price",
        "discountPrice",
        "retailPrice",
        "salePrice",
        "currentPrice",
        "skuPrice",
      ]);
      const stock = readFirstNumber(info, [
        "canBookCount",
        "stock",
        "inventory",
        "amountOnSale",
        "saleCount",
        "quantity",
      ]);
      const weightFromInfo = readFirstNumber(info, ["weight", "unitWeight", "skuWeight"]);
      const weightFromMap = skuWeightMap && typeof skuWeightMap === "object" ? toOptionalNumber(skuWeightMap[rawKey]) : null;

      if (Object.keys(specs).length > 0 || imageUrl || price !== null || stock !== null) {
        skuItems.push(
          cleanSkuItem({
            sku_id: String(readFirstString(info, ["skuId", "sku_id", "offerSkuId", "id"]) || rawKey),
            specs: Object.keys(specs).length > 0 ? specs : { 规格: rawKey },
            price,
            stock,
            image_url: imageUrl,
            weight_kg: normalizeWeightNumber(weightFromInfo ?? weightFromMap),
          })
        );
      }
    }
  }

  if (skuItems.length > 0) return skuItems;

  return collectSkuValueItemsFromProps(propMeta);
}

function pickSkuRowsFromDom() {
  const selectors = [
    "#skuSelection .expand-view-item",
    ".module-od-sku-selection .expand-view-item",
    "[class*='sku'] [class*='row']",
    "[class*='Sku'] [class*='row']",
    "[class*='sku'] tr",
    "[class*='Sku'] tr",
    "[class*='sku'] li",
    "[class*='Sku'] li",
  ];
  const rows = uniqueElements(selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector))));

  return rows
    .map((row, index) => parseSkuRow(row, index))
    .filter(Boolean);
}

function parseSkuRow(row, index) {
  const rowText = cleanText(row.innerText || row.textContent);
  const imageUrl = pickImageFromElement(row);
  const price = parsePriceFromText(rowText) ?? parsePriceFromElements(row);
  const stock = parseStockFromText(rowText);
  const { propName, value } = extractSkuSpecFromRow(row, rowText);

  if (!value && !imageUrl && price === null && stock === null) return null;
  if (value && /sku列表|sku list|价格待采集/i.test(value)) return null;

  return cleanSkuItem({
    sku_id: row.getAttribute("data-sku-id") || row.getAttribute("data-id") || `row-${index + 1}`,
    specs: { [propName || "规格"]: value || `SKU ${index + 1}` },
    price,
    stock,
    image_url: imageUrl,
  });
}

function extractSkuSpecFromRow(row, rowText) {
  const tokens = Array.from(row.querySelectorAll("button, li, span, div, td"))
    .map((element) => cleanText(element.textContent))
    .filter(isUsefulSkuText);
  const uniqueTokens = Array.from(new Set(tokens));
  const knownProp = uniqueTokens.find(isLikelyPropName);
  const value = uniqueTokens.find((token) => token !== knownProp && !isLikelyPropName(token)) || "";

  if (value) {
    return { propName: knownProp || "规格", value };
  }

  const cleaned = cleanSkuText(rowText);
  if (!cleaned) return { propName: "规格", value: "" };

  const parts = cleaned.split(/\s+/).filter(isUsefulSkuText);
  if (parts.length >= 2 && isLikelyPropName(parts[0])) {
    return { propName: parts[0], value: parts[1] };
  }

  return { propName: "规格", value: parts[0] || cleaned };
}

function pickFallbackSkuTexts() {
  const containers = Array.from(
    document.querySelectorAll("[class*='sku'], [class*='Sku']")
  );
  const visibleTexts = containers
    .flatMap((container) => Array.from(container.querySelectorAll("button, li, span, div")))
    .map((element) => cleanText(element.textContent))
    .filter(isUsefulSkuText);

  const scriptText = getInlineContextScriptText();
  const contextTexts = Array.from(scriptText.matchAll(/"name"\s*:\s*"([^"]{1,40})"/g))
    .map((match) => decodeJsonString(match[1]))
    .filter(isUsefulSkuText);

  return Array.from(new Set([...visibleTexts, ...contextTexts]));
}

function buildDefaultQuantitySku() {
  const quantity = findSelectedQuantity() || pickMoq();
  return cleanSkuItem({
    sku_id: "quantity-default",
    specs: { 规格: quantity ? `默认款（${quantity}件起订）` : "默认款" },
  });
}

function hasUsefulSpecValue(item) {
  const values = Object.values(item?.specs || {});
  return values.length > 0 && values.some(isUsefulSkuText);
}

function hasExplicitSkuChoiceSignal() {
  const selectors = [
    "#skuSelection .expand-view-item",
    ".module-od-sku-selection .expand-view-item",
    "[class*='sku'] [data-sku-id]",
    "[class*='Sku'] [data-sku-id]",
    "[class*='sku'] button",
    "[class*='Sku'] button",
    "[class*='sku'] li",
    "[class*='Sku'] li",
  ];

  return selectors.some((selector) =>
    Array.from(document.querySelectorAll(selector)).some((element) => {
      const text = cleanText(element.innerText || element.textContent);
      if (!text && !pickImageFromElement(element)) return false;
      return isUsefulSkuText(text) || Boolean(pickImageFromElement(element));
    })
  );
}

function collectSkuPropMeta(skuProps) {
  const propNames = [];
  const valuesById = new Map();
  const valuesByName = new Map();
  const imageValues = [];

  if (!Array.isArray(skuProps)) {
    return { propNames, valuesById, valuesByName, imageValues };
  }

  for (const prop of skuProps) {
    if (!prop || typeof prop !== "object") continue;
    const propName = readFirstString(prop, ["prop", "propName", "name", "label"]) || "规格";
    propNames.push(propName);
    const values = readFirstArray(prop, ["value", "values", "skuPropertyValues", "child", "children"]) || [];
    for (const valueItem of values) {
      if (!valueItem || typeof valueItem !== "object") continue;
      const name = readFirstString(valueItem, ["name", "value", "valueName", "specValue", "text"]);
      const id = String(readFirstString(valueItem, ["id", "valueId", "vid", "valueID"]) || name || "");
      const imageUrl = readFirstImageUrl(valueItem, [
        "imageUrl",
        "image",
        "imgUrl",
        "skuImageUrl",
        "picUrl",
        "pic",
        "url",
        "originalImageURI",
        "imageURI",
        "imageUrlWebp",
        "skuImage",
        "skuPicUrl",
      ]);
      if (!name) continue;
      const meta = { propName, name, imageUrl };
      valuesByName.set(name, meta);
      if (id) valuesById.set(id, meta);
      if (imageUrl) imageValues.push(meta);
    }
  }

  return { propNames, valuesById, valuesByName, imageValues };
}

function collectSkuValueItemsFromProps(propMeta) {
  return Array.from(propMeta.valuesByName.values()).map((value, index) =>
    cleanSkuItem({
      sku_id: `prop-${index + 1}`,
      specs: { [value.propName || "规格"]: value.name },
      image_url: value.imageUrl || findImageForSkuValue(value.name, propMeta),
    })
  );
}

function findImageForSkuValue(value, propMeta) {
  const text = normalizeWhitespace(value);
  if (!text) return null;

  const exactMeta = propMeta.valuesByName.get(text);
  if (exactMeta?.imageUrl) return exactMeta.imageUrl;

  const skuKey = skuImageMatchKey(text);
  if (!skuKey) return null;

  const matchedMeta = (propMeta.imageValues || []).find((meta) => skuImageMatchKey(meta.name) === skuKey);
  return matchedMeta?.imageUrl || null;
}

function skuImageMatchKey(value) {
  const firstPart = normalizeWhitespace(value).split(/[+＋/／,，、|]/)[0] || "";
  return firstPart
    .replace(/不含链|含链|链条|项链|吊坠|挂坠|坠子/g, "")
    .replace(/\s+/g, "")
    .trim();
}

function parseObjectAfterKey(sourceText, key) {
  const source = String(sourceText || "");
  const keyIndex = source.indexOf(`"${key}"`);
  const fallbackIndex = keyIndex >= 0 ? keyIndex : source.indexOf(key);
  if (fallbackIndex < 0) return null;

  const objectStart = findNextContainerStart(source, fallbackIndex);
  if (objectStart < 0) return null;

  const objectText = readBalancedContainer(source, objectStart);
  if (!objectText) return null;

  try {
    return JSON.parse(objectText);
  } catch {
    try {
      return JSON.parse(objectText.replace(/'/g, '"'));
    } catch {
      return null;
    }
  }
}

function findNextContainerStart(source, fromIndex) {
  const braceIndex = source.indexOf("{", fromIndex);
  const bracketIndex = source.indexOf("[", fromIndex);
  if (braceIndex < 0) return bracketIndex;
  if (bracketIndex < 0) return braceIndex;
  return Math.min(braceIndex, bracketIndex);
}

function readBalancedContainer(source, startIndex) {
  const openChar = source[startIndex];
  const closeChar = openChar === "{" ? "}" : "]";
  let depth = 0;
  let inString = false;
  let quoteChar = "";
  let escaped = false;

  for (let index = startIndex; index < source.length; index += 1) {
    const char = source[index];

    if (inString) {
      if (escaped) {
        escaped = false;
        continue;
      }
      if (char === "\\") {
        escaped = true;
        continue;
      }
      if (char === quoteChar) {
        inString = false;
        quoteChar = "";
      }
      continue;
    }

    if (char === '"' || char === "'") {
      inString = true;
      quoteChar = char;
      continue;
    }

    if (char === openChar) depth += 1;
    if (char === closeChar) depth -= 1;
    if (depth === 0) return source.slice(startIndex, index + 1);
  }

  return "";
}

function splitSkuKey(rawKey) {
  return String(rawKey || "")
    .split(/[>;|,，/]+/)
    .map((part) => cleanText(part))
    .filter(Boolean);
}

function cleanSkuItem(item) {
  const cleaned = {
    sku_id: item.sku_id ? String(item.sku_id) : undefined,
    specs: normalizeSpecObject(item.specs || {}),
  };
  if (item.price !== null && item.price !== undefined) cleaned.price = Number(item.price);
  if (item.stock !== null && item.stock !== undefined) cleaned.stock = Number(item.stock);
  if (item.image_url) cleaned.image_url = normalizeUrl(item.image_url);
  if (item.weight_kg !== null && item.weight_kg !== undefined) {
    const weight = toPositiveOptionalNumber(item.weight_kg);
    if (weight !== null) cleaned.weight_kg = weight;
  }
  return cleaned;
}

function mergeSkuItems(items) {
  const merged = new Map();
  for (const item of items) {
    if (!item) continue;
    const key = buildSkuMergeKey(item);
    const existing = merged.get(key) || { sku_id: item.sku_id, specs: item.specs || {} };
    merged.set(key, {
      ...existing,
      ...item,
      specs: mergeSpecObjects(existing.specs || {}, item.specs || {}),
      image_url: existing.image_url || item.image_url,
      price: existing.price ?? item.price,
      stock: existing.stock ?? item.stock,
      weight_kg: existing.weight_kg ?? item.weight_kg,
    });
  }

  return normalizeSkuPropLabels(Array.from(merged.values()).map(cleanSkuItem));
}

function buildSkuMergeKey(item) {
  const specText = Object.entries(item.specs || {})
    .map(([key, value]) => `${normalizeSpecKeyForMerge(key)}:${normalizeWhitespace(value)}`)
    .sort()
    .join("|");
  return specText || item.image_url || item.sku_id || Math.random().toString(36);
}

function mergeSpecObjects(existingSpecs, incomingSpecs) {
  const merged = normalizeSpecObject(existingSpecs);
  const incoming = normalizeSpecObject(incomingSpecs);

  for (const [incomingKey, incomingValue] of Object.entries(incoming)) {
    const genericKey = "规格";
    const matchingConcreteKey = Object.entries(merged).find(
      ([key, value]) => key !== genericKey && normalizeWhitespace(value) === normalizeWhitespace(incomingValue)
    )?.[0];

    if (incomingKey === genericKey && matchingConcreteKey) {
      continue;
    }

    if (incomingKey !== genericKey && merged[genericKey] === incomingValue) {
      delete merged[genericKey];
    }

    merged[incomingKey] = incomingValue;
  }

  return merged;
}

function normalizeSpecObject(specs) {
  const normalized = {};
  for (const [key, value] of Object.entries(specs || {})) {
    const cleanValue = normalizeWhitespace(value);
    if (!cleanValue) continue;
    normalized[normalizeSpecKey(key)] = cleanValue;
  }
  return normalized;
}

function normalizeSpecKey(key) {
  const text = normalizeWhitespace(key);
  if (/^(color|colour|颜色)$/i.test(text)) return "颜色";
  if (/^(size|尺码|尺寸)$/i.test(text)) return "尺码";
  if (/^(style|款式)$/i.test(text)) return "款式";
  if (/^(model|型号)$/i.test(text)) return "型号";
  return text || "规格";
}

function normalizeSpecKeyForMerge(key) {
  const text = normalizeSpecKey(key);
  return text === "规格" ? "SKU属性" : text;
}

function normalizeSkuPropLabels(items) {
  const labelCounts = new Map();
  for (const item of items) {
    for (const key of Object.keys(item.specs || {})) {
      if (key !== "规格") {
        labelCounts.set(key, (labelCounts.get(key) || 0) + 1);
      }
    }
  }

  const dominantLabel = Array.from(labelCounts.entries()).sort((a, b) => b[1] - a[1])[0]?.[0];
  if (!dominantLabel) return items;

  return items.map((item) => {
    if (!item.specs?.["规格"] || item.specs[dominantLabel]) return item;
    const specs = { ...item.specs, [dominantLabel]: item.specs["规格"] };
    delete specs["规格"];
    return { ...item, specs };
  });
}

function isStrongSkuItem(item) {
  if (!item) return false;
  if (item.image_url) return true;
  if (item.stock !== null && item.stock !== undefined && item.sku_id && !String(item.sku_id).startsWith("text-")) return true;
  if (item.price !== null && item.price !== undefined && Object.keys(item.specs || {}).length > 0) return true;
  return false;
}

function isUsefulSkuText(text) {
  if (!text || text.length > 50) return false;
  if (isProductAttributeText(text)) return false;
  if (/价格|库存|起批|采购|数量|加入进货单|立即订购|order now|add cart|inventory\d*item|已选|selected/i.test(text)) return false;
  if (/^[¥￥]?\d+(?:\.\d+)?$/.test(text)) return false;
  if (/^[+\-−]$/.test(text)) return false;
  return true;
}

function isProductAttributeText(text) {
  const normalized = cleanText(text).replace(/^规格\s*[:：]\s*/, "");
  if (!normalized) return true;
  if (/^TEMPLATED$/i.test(normalized)) return true;
  if (/^(材质|品牌|产品编号|货号|型号|产地|加工定制|是否进口|类别|分类|钥匙配饰分类|包装|用途|风格)$/.test(normalized)) {
    return true;
  }
  if (/^(材质|品牌|产品编号|货号|型号|产地|类别|分类|钥匙配饰分类)\s*[:：]/.test(normalized)) {
    return true;
  }
  return false;
}

function isLikelyPropName(text) {
  return /^(color|colour|颜色|款式|规格|尺码|size|型号|style|type)$/i.test(text);
}

function cleanSkuText(text) {
  return cleanText(text)
    .replace(/[¥￥]\s*\d+(?:\.\d+)?/g, " ")
    .replace(/Inventory\s*\d+\s*item/gi, " ")
    .replace(/库存\s*\d+/g, " ")
    .replace(/\b\d+\b/g, " ")
    .replace(/[+\-−]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function parsePriceFromText(text) {
  const match = String(text || "").replace(/,/g, "").match(/[¥￥]\s*([0-9]+(?:\.[0-9]+)?)/);
  return match ? Number(match[1]) : null;
}

function parsePriceFromElements(row) {
  const priceText = getFirstTextInElement(row, [
    "[class*='price']",
    "[class*='Price']",
    "[class*='amount']",
    "[class*='Amount']",
  ]);
  return parsePriceFromText(priceText);
}

function parseStockFromText(text) {
  const normalized = String(text || "").replace(/,/g, "");
  const match =
    normalized.match(/Inventory\s*([0-9]+)/i) ||
    normalized.match(/库存\s*[:：]?\s*([0-9]+)/) ||
    normalized.match(/([0-9]+)\s*(?:件|item)\b/i);
  return match ? Number(match[1]) : null;
}

function pickImageFromElement(element) {
  return pickImageUrlsFromElement(element)[0] || null;
}

function pickImageUrlsFromElement(element) {
  if (!element) return [];

  const urls = [];
  const imageElements = element.matches?.("img, source") ? [element] : Array.from(element.querySelectorAll("img, source"));
  for (const imageElement of imageElements) {
    urls.push(
      imageElement.currentSrc,
      imageElement.src,
      imageElement.getAttribute("src"),
      imageElement.getAttribute("data-src"),
      imageElement.getAttribute("data-original"),
      imageElement.getAttribute("data-lazy-src"),
      imageElement.getAttribute("data-img"),
      imageElement.getAttribute("data-url"),
      imageElement.getAttribute("data-image"),
      imageElement.getAttribute("data-ks-lazyload"),
      ...extractImageUrlsFromSrcset(imageElement.getAttribute("srcset"))
    );
  }

  const style = element.getAttribute?.("style") || "";
  urls.push(...extractBackgroundImageUrls(style));

  return uniqueImageUrls(urls).filter(isLikelyProductImageUrl);
}

function extractImageUrlsFromSrcset(srcset) {
  if (!srcset) return [];
  return String(srcset)
    .split(",")
    .map((item) => item.trim().split(/\s+/)[0])
    .filter(Boolean);
}

function extractBackgroundImageUrls(styleText) {
  const text = String(styleText || "");
  return Array.from(text.matchAll(/url\((['"]?)(.*?)\1\)/gi)).map((match) => match[2]);
}

function extractImageUrlsFromText(text) {
  const source = String(text || "");
  const matches = [
    ...source.matchAll(/(?:https?:)?\\?\/\\?\/[^"'\s\\]+?\.(?:jpg|jpeg|png|webp)(?:\?[^"'\s\\]*)?/gi),
    ...source.matchAll(/["']([^"']*?(?:alicdn|1688|tbcdn)[^"']*?\.(?:jpg|jpeg|png|webp)[^"']*)["']/gi),
  ];

  return matches.map((match) => match[1] || match[0]).map((url) => url.replaceAll("\\/", "/"));
}

function uniqueImageUrls(urls) {
  const seen = new Set();
  const normalized = [];
  for (const url of urls) {
    const cleanUrl = normalizeUrl(String(url || "").trim());
    if (!cleanUrl || seen.has(cleanUrl)) continue;
    seen.add(cleanUrl);
    normalized.push(cleanUrl);
  }
  return normalized;
}

function isLikelyProductImageUrl(url) {
  const src = String(url || "");
  if (!src || src.startsWith("data:") || src.startsWith("blob:")) return false;
  if (!/\.(jpg|jpeg|png|webp)(?:[?#._-]|$)/i.test(src)) return false;
  if (/icon|sprite|logo|avatar|loading|placeholder|transparent|grey\.gif/i.test(src)) return false;
  return true;
}

function getFirstTextInElement(root, selectors) {
  for (const selector of selectors) {
    const element = root.querySelector(selector);
    const text = cleanText(element?.textContent);
    if (text) return text;
  }
  return "";
}

function uniqueElements(elements) {
  return Array.from(new Set(elements)).filter((element) => {
    const text = cleanText(element.innerText || element.textContent);
    return text || element.querySelector("img");
  });
}

function readFirstString(object, keys) {
  for (const key of keys) {
    const value = object?.[key];
    if (value !== null && value !== undefined && String(value).trim()) return String(value).trim();
  }
  return "";
}

function readFirstNumber(object, keys) {
  for (const key of keys) {
    const number = toOptionalNumber(object?.[key]);
    if (number !== null) return number;
  }
  return null;
}

function readFirstArray(object, keys) {
  for (const key of keys) {
    if (Array.isArray(object?.[key])) return object[key];
  }
  return null;
}

function readFirstImageUrl(object, keys) {
  for (const key of keys) {
    const directUrl = normalizeUrl(object?.[key]);
    if (directUrl && isLikelyProductImageUrl(directUrl)) return directUrl;
  }

  return findFirstImageUrlDeep(object);
}

function findFirstImageUrlDeep(value, seen = new Set(), depth = 0) {
  if (!value || depth > 4) return null;

  if (typeof value === "string") {
    const urls = extractImageUrlsFromText(value);
    return urls.find(isLikelyProductImageUrl) || null;
  }

  if (typeof value !== "object" || seen.has(value)) return null;
  seen.add(value);

  if (Array.isArray(value)) {
    for (const item of value) {
      const imageUrl = findFirstImageUrlDeep(item, seen, depth + 1);
      if (imageUrl) return imageUrl;
    }
    return null;
  }

  const entries = Object.entries(value).sort(([keyA], [keyB]) => {
    const score = (key) => (/image|img|pic|photo|url/i.test(key) ? 0 : 1);
    return score(keyA) - score(keyB);
  });

  for (const [key, nestedValue] of entries) {
    if (!/image|img|pic|photo|url/i.test(key) && typeof nestedValue === "string") continue;
    const imageUrl = findFirstImageUrlDeep(nestedValue, seen, depth + 1);
    if (imageUrl) return imageUrl;
  }

  return null;
}

function normalizeWeightNumber(value) {
  if (value === null || value === undefined) return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  if (number <= 0) return null;
  return number > 20 ? Number((number / 1000).toFixed(3)) : number;
}

function findGoodsPrice() {
  const unitPriceFromText = findUnitPriceFromPageText();
  if (unitPriceFromText) return unitPriceFromText;

  const priceText = getFirstVisibleText([
    "#skuSelection .expand-view-item .item-price-stock",
    ".module-od-sku-selection .expand-view-item .item-price-stock",
    "#mainPrice .price-info:last-child",
    ".module-od-main-price .price-info:last-child",
  ]);
  if (priceText) return parseMoney(priceText);

  const totalPriceText = getFirstVisibleText([
    "#submitOrder .total-price strong",
    ".module-od-submit-order .total-price strong",
  ]);
  const quantity = findSelectedQuantity();
  const totalPrice = toOptionalNumber(parseMoney(totalPriceText));
  if (totalPrice !== null && quantity > 1) return (totalPrice / quantity).toFixed(2);
  if (totalPrice !== null) return String(totalPrice);

  const scriptText = getInlineContextScriptText();
  return extractValueByPatterns(scriptText, [
    /"minPrice"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?/,
    /"priceDisplay"\s*:\s*"([0-9]+(?:\.[0-9]+)?)(?:-[0-9]+(?:\.[0-9]+)?)?"/,
    /"maxPrice"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?/,
    /"discountPrice"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?/,
    /"price"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?/,
  ]);
}

function findUnitPriceFromPageText() {
  const pageText = normalizeWhitespace(document.body.innerText || "").replace(/,/g, "");
  const match =
    pageText.match(/单价\s*[:：]?\s*[¥￥]?\s*([0-9]+(?:\.[0-9]+)?)/) ||
    pageText.match(/价格\s*[¥￥]\s*([0-9]+(?:\.[0-9]+)?)/);
  return match?.[1] || "";
}

function findShippingFee() {
  const shippingText = getFirstVisibleText([
    "#submitOrder .total-freight-fee strong",
    "#shippingServices .service-item.split-border b",
    ".module-od-submit-order .total-freight-fee strong",
    ".module-od-shipping-services .service-item.split-border b",
    "#shippingServices b",
  ]);
  if (shippingText) return parseMoney(shippingText);

  const scriptText = getInlineContextScriptText();
  return (
    extractValueByPatterns(scriptText, [
      /"postFeeValue"\s*:\s*([0-9]+(?:\.[0-9]+)?)/,
      /"totalCost"\s*:\s*([0-9]+(?:\.[0-9]+)?)/,
      /"price"\s*:\s*"([0-9]+(?:\.[0-9]+)?)","deliveryLimitText"/,
    ]) || "0"
  );
}

function findWeight() {
  const scriptText = getInlineContextScriptText();
  const rawWeight = extractValueByPatterns(scriptText, [
    /"unitWeight"\s*:\s*([0-9]+(?:\.[0-9]+)?)/,
    /"minWeight"\s*:\s*([0-9]+(?:\.[0-9]+)?)/,
    /"skuWeight"\s*:\s*\{"[^"]*"\s*:\s*([0-9]+(?:\.[0-9]+)?)\}/,
    /"weight"\s*:\s*([0-9]+(?:\.[0-9]+)?)/,
    /商品件重尺[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)/,
  ]);
  if (rawWeight) return parseWeightValue(`${rawWeight}kg`, "kg");

  const weightText = getFirstVisibleText([
    "#productPackInfo td",
    ".module-od-product-pack-info td",
    "#productPackInfo",
    "[data-module='od_product_pack_info']",
  ]);
  if (weightText) {
    const match = weightText.match(/([0-9]+(?:\.[0-9]+)?)\s*(kg|千克|公斤|g|克)?/i);
    if (match) return parseWeightValue(`${match[1]}${match[2] || "kg"}`, match[2] || "kg");
  }

  const pageText = normalizeWhitespace(document.body.innerText || "");
  const pageMatch = pageText.match(
    /(?:商品件重尺|件重|重量|净重|毛重)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(kg|千克|公斤|g|克)?/i
  );
  if (pageMatch) return parseWeightValue(`${pageMatch[1]}${pageMatch[2] || "kg"}`, pageMatch[2] || "kg");

  return "";
}

function findSelectedQuantity() {
  const inputText = getFirstVisibleText([
    "#submitOrder input[type='number']",
    ".module-od-submit-order input[type='number']",
    "input[aria-label*='数量']",
  ]);
  const inputQuantity = toOptionalNumber(inputText);
  if (inputQuantity !== null && inputQuantity > 0) return inputQuantity;

  const text = normalizeWhitespace(document.body.innerText || "").replace(/,/g, "");
  const match =
    text.match(/已选\s*(\d+)\s*(?:件|个|只|套)/) ||
    text.match(/数量\s*[:：]?\s*(\d+)/) ||
    text.match(/(\d+)\s*(?:件|个|只|套)\s*起(?:批|订|定)/) ||
    text.match(/起(?:批|订|定)\s*(\d+)/);
  const quantity = match ? Number(match[1]) : null;
  return Number.isFinite(quantity) && quantity > 0 ? quantity : null;
}

function computeUnitPrice(goodsPrice, shippingFee, selectedQuantity = null) {
  const goods = Number(goodsPrice || 0);
  const shipping = Number(shippingFee || 0);
  if (goods <= 0) return "";
  const quantity = Number(selectedQuantity || 0);
  const unitShipping = quantity > 1 ? shipping / quantity : shipping;
  return (goods + unitShipping).toFixed(2);
}

function getFirstVisibleText(selectors) {
  for (const selector of selectors) {
    const elements = document.querySelectorAll(selector);
    for (const element of elements) {
      const style = window.getComputedStyle(element);
      if (style.display === "none" || style.visibility === "hidden") continue;

      const text = normalizeWhitespace(element.textContent || element.value || "");
      if (text) return text;
    }
  }

  return "";
}

function getInlineContextScriptText() {
  const matches = [];
  for (const script of document.scripts || []) {
    const text = script.textContent || "";
    if (
      text.includes("window.context=") ||
      text.includes('"tradeModel"') ||
      text.includes('"unitWeight"') ||
      text.includes('"sku"') ||
      text.includes("categoryPath") ||
      text.includes("cateName") ||
      text.includes("catName")
    ) {
      matches.push(text);
    }
  }

  return matches.join("\n");
}

function extractValueByPatterns(sourceText, patterns) {
  const text = String(sourceText || "");
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match?.[1]) return normalizeWhitespace(match[1]);
  }

  return "";
}

function queryText(selectors) {
  for (const selector of selectors) {
    const element = document.querySelector(selector);
    const text = cleanText(element?.textContent);
    if (text) return text;
  }
  return "";
}

function cleanText(value) {
  return normalizeWhitespace(value);
}

function normalizeWhitespace(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function parseMoney(text) {
  const normalized = normalizeWhitespace(text).replace(/,/g, "");
  const currencyMatch = normalized.match(/[￥¥]\s*([0-9]+(?:\.[0-9]+)?)/);
  if (currencyMatch) return currencyMatch[1];

  const plainMatch = normalized.match(/([0-9]+(?:\.[0-9]+)?)/);
  return plainMatch ? plainMatch[1] : "";
}

function parseWeightValue(rawValue, unitHint = "") {
  const normalized = normalizeWhitespace(rawValue).toLowerCase();
  const numeric = normalized.match(/([0-9]+(?:\.[0-9]+)?)/);
  if (!numeric) return "";

  const value = Number(numeric[1]);
  if (!Number.isFinite(value) || value <= 0) return "";
  const unitText = `${normalized} ${unitHint.toLowerCase()}`;

  if (unitText.includes("kg") || unitText.includes("千克") || unitText.includes("公斤")) {
    return String(value);
  }

  if (unitText.includes("g") || unitText.includes("克")) {
    return String((value / 1000).toFixed(3).replace(/\.?0+$/, ""));
  }

  return String(value);
}

function parseNumbers(value) {
  return Array.from(String(value || "").matchAll(/\d+(?:\.\d+)?/g))
    .map((match) => Number(match[0]))
    .filter((number) => Number.isFinite(number));
}

function toOptionalNumber(value) {
  if (value === "" || value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function toPositiveOptionalNumber(value) {
  const number = toOptionalNumber(value);
  return number !== null && number > 0 ? number : null;
}

function normalizeUrl(url) {
  if (!url) return null;
  const cleanUrl = String(url).trim().replaceAll("\\/", "/");
  if (!cleanUrl) return null;
  if (cleanUrl.startsWith("//")) return `https:${cleanUrl}`;
  if (cleanUrl.startsWith("http:\\/\\/") || cleanUrl.startsWith("https:\\/\\/")) {
    return cleanUrl.replaceAll("\\/", "/");
  }
  if (cleanUrl.startsWith("/")) return `${location.origin}${cleanUrl}`;
  return cleanUrl;
}

function addYuanPrefix(value) {
  const text = normalizeWhitespace(value);
  if (!text) return null;
  return /[¥￥]/.test(text) ? text.replace("￥", "¥") : `¥${text}`;
}

function cleanPageTitle(value) {
  return cleanText(value)
    .replace(/[-_|].*?(1688|阿里巴巴|批发网|旺铺).*$/i, "")
    .replace(/\s*-\s*1688.*$/i, "")
    .replace(/\s*_\s*阿里巴巴.*$/i, "")
    .trim();
}

function isLikelyProductTitle(value) {
  const text = cleanText(value);
  if (!text) return false;
  if (/有限公司|有限责任公司|旗舰店|官方店|旺铺|工厂|供应商|贸易商|商行$|店$/.test(text)) return false;
  if (text.length < 6) return false;
  return true;
}

function decodeJsonString(value) {
  try {
    return JSON.parse(`"${value}"`);
  } catch {
    return value;
  }
}
