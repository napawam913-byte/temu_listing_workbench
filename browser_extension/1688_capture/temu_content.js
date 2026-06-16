(function initTemuPageCollector() {
  const COLLECTOR_VERSION = "2026-06-15-temu-title-price-v4";
  if (globalThis.__marketplaceTemuCollectorVersion === COLLECTOR_VERSION) return;
  globalThis.__marketplaceTemuCollectorLoaded = true;
  globalThis.__marketplaceTemuCollectorVersion = COLLECTOR_VERSION;

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!["COLLECT_TEMU_PRODUCT", "COLLECT_TEMU_PRODUCT_V2"].includes(message?.type)) return false;

    try {
      const payload = collectTemuProduct({
        mainWorldSnapshot: message.mainWorldSnapshot || {},
      });
      sendResponse({ ok: true, payload });
    } catch (error) {
      sendResponse({
        ok: false,
        error: error instanceof Error ? error.message : "Temu 采集失败",
      });
    }

    return true;
  });

  function collectTemuProduct({ mainWorldSnapshot = {} } = {}) {
    const pageSignals = collectPageSignals();
    const parsedContexts = collectParsedContexts(mainWorldSnapshot);
    const deepSignals = collectDeepSignals(parsedContexts);
    const images = uniqueUrls([
      pageSignals.image,
      ...(pageSignals.images || []),
      ...(deepSignals.images || []),
    ]).slice(0, 120);
    const title = cleanTemuTitle(firstText(pageSignals.title, deepSignals.title, pageSignals.metaTitle, document.title));
    if (!title) throw new Error("未识别到 Temu 商品标题");

    const rawSkuList = mergeSkuItems([
      ...(deepSignals.skuList || []),
      ...collectSkuItemsFromDom(),
    ]);
    const skcList = normalizeList(deepSignals.skcList);
    const propertyList = normalizeList(deepSignals.propertyList);
    const selectedOptions = {
      ...(deepSignals.selectedOptions || {}),
      ...(pageSignals.selectedOptions || {}),
    };
    const goodsId = firstText(deepSignals.goods_id, pageSignals.goods_id, extractGoodsIdFromUrl(location.href));
    const price = normalizePrice({
      ...deepSignals.price,
      ...pageSignals.price,
    });
    const skuList = buildTemuSkuList({ rawSkuList, selectedOptions, propertyList, images, price });
    const categoryParts = normalizeCategoryParts([
      ...(deepSignals.category_parts || []),
      ...(pageSignals.category_parts || []),
    ]);

    return {
      source: "temu",
      goods_id: goodsId || null,
      id: goodsId || null,
      product_url: location.href,
      canonical_url: pageSignals.canonical || null,
      title,
      description: firstText(pageSignals.description, deepSignals.description),
      main_image_url: images[0] || null,
      gallery_image_urls: images,
      video_url: firstText(pageSignals.video_url, deepSignals.video_url) || null,
      price,
      sales_count: firstText(deepSignals.sales_count, pageSignals.sales_count),
      rating: toOptionalNumber(firstText(deepSignals.rating, pageSignals.rating)),
      review_count: toOptionalNumber(firstText(deepSignals.review_count, pageSignals.review_count)),
      shop: {
        id: firstText(deepSignals.shop_id, pageSignals.shop_id),
        name: firstText(deepSignals.shop_name, pageSignals.shop_name),
        url: firstText(deepSignals.shop_url, pageSignals.shop_url),
      },
      category_path: categoryParts.join("/") || null,
      category_parts: categoryParts,
      selected_options: selectedOptions,
      sku: {
        variant_count: Number(skuList.length || deepSignals.variant_count || propertyList.length || Object.keys(selectedOptions).length || 1),
        sku_count: Number(skuList.length || deepSignals.sku_count || 0),
        skc_count: Number(deepSignals.skc_count || skcList.length || 0),
        selected: selectedOptions,
        skuList,
        skcList,
        propertyList,
      },
      is_no_attribute: inferNoAttribute({ skuList, propertyList, selectedOptions, variantCount: deepSignals.variant_count }),
      captured_at: new Date().toISOString(),
      raw_data: {
        page_title: document.title,
        url: location.href,
        user_agent: navigator.userAgent,
        page_signals: pageSignals,
        deep_signal_summary: deepSignals.summary,
        main_world_snapshot: summarizeMainWorldSnapshot(mainWorldSnapshot),
      },
    };
  }

  function collectPageSignals() {
    const images = uniqueUrls([
      ...collectVisibleProductImages(),
      ...collectImagesFromDom(),
    ]).slice(0, 120);
    const text = normalizeWhitespace(document.body?.innerText || "");
    const price = normalizePrice({
      ...collectVisiblePrice(text),
      ...collectBuyBoxVisiblePrice(),
    });
    return {
      url: location.href,
      canonical: document.querySelector("link[rel='canonical']")?.href || "",
      title: cleanTemuTitle(collectVisibleProductTitle() || readText("h1") || readMeta("meta[property='og:title']") || document.title),
      metaTitle: readMeta("meta[property='og:title']"),
      description: readMeta("meta[name='description']") || readMeta("meta[property='og:description']"),
      goods_id: extractGoodsIdFromUrl(location.href) || extractGoodsIdFromText(text),
      image: images[0] || readMeta("meta[property='og:image']"),
      images,
      video_url: collectVideoUrls()[0] || "",
      price,
      selectedOptions: collectSelectedOptions(),
      category_parts: collectCategoryPartsFromDom(),
      sales_count: extractValue(text, /([0-9.,]+[Kk万+]*)\s*(?:sold|已售|件已售)/i),
      rating: extractValue(text, /([0-5](?:\.[0-9])?)\s*(?:★|stars?|评分)/i),
      review_count: extractValue(text, /([0-9.,]+[Kk万+]*)\s*(?:reviews?|评价|评论)/i),
      shop_name: collectShopNameFromDom(),
      capturedAt: new Date().toISOString(),
    };
  }

  function collectParsedContexts(mainWorldSnapshot) {
    const contexts = [];
    for (const script of Array.from(document.scripts || [])) {
      const text = script.textContent || "";
      if (!text || !/goods|product|sku|skc|price|image|title/i.test(text)) continue;
      if ((script.type || "").includes("json") || script.id === "__NEXT_DATA__") {
        pushParsed(contexts, script.id || "script-json", text);
      }
      for (const key of ["skuList", "skcList", "propertyList", "goodsInfo", "productInfo", "mallData", "store"]) {
        const snippets = extractBalancedJsonNearKey(text, key, 4);
        snippets.forEach((snippet, index) => pushParsed(contexts, `${key}-${index + 1}`, snippet));
      }
    }

    for (const item of mainWorldSnapshot?.candidates || []) {
      pushParsed(contexts, `main:${item.key || "window"}`, item.json);
    }

    return contexts;
  }

  function collectDeepSignals(contexts) {
    const rootValues = contexts.map((entry) => entry.value).filter(Boolean);
    const skuList = [];
    const skcList = [];
    const propertyList = [];
    const images = [];
    const categories = [];
    const selectedOptions = {};
    const summary = [];

    let title = "";
    let description = "";
    let goodsId = "";
    let videoUrl = "";
    let shopId = "";
    let shopName = "";
    let shopUrl = "";
    let salesCount = "";
    let rating = "";
    let reviewCount = "";
    let variantCount = 0;
    let skuCount = 0;
    let skcCount = 0;
    const price = {};

    for (const entry of contexts) {
      summary.push({
        key: entry.key,
        type: Array.isArray(entry.value) ? "array" : typeof entry.value,
        size: entry.size,
      });
    }

    for (const value of rootValues) {
      title = firstText(title, cleanTemuTitle(findFirstDeep(value, ["title", "goodsName", "productName", "productTitle", "name"])));
      description = firstText(description, findFirstDeep(value, ["description", "desc", "goodsDesc", "productDescription"]));
      goodsId = firstText(goodsId, findFirstDeep(value, ["goods_id", "goodsId", "goodsID", "productId", "product_id", "id"]));
      videoUrl = firstText(videoUrl, findFirstUrlDeep(value, /video|mp4|m3u8/i));
      shopId = firstText(shopId, findFirstDeep(value, ["storeId", "shopId", "mallId", "sellerId"]));
      shopName = firstText(shopName, findFirstDeep(value, ["storeName", "shopName", "mallName", "sellerName"]));
      shopUrl = firstText(shopUrl, findFirstUrlDeep(value, /shop|store|mall/i));
      salesCount = firstText(salesCount, findFirstDeep(value, ["salesCount", "soldCount", "sold", "sales"]));
      rating = firstText(rating, findFirstDeep(value, ["rating", "reviewRating", "star", "score"]));
      reviewCount = firstText(reviewCount, findFirstDeep(value, ["totalReviews", "reviewCount", "reviews", "commentCount"]));
      variantCount = Math.max(variantCount, Number(findFirstDeep(value, ["variant_count", "variantCount"])) || 0);
      skuCount = Math.max(skuCount, Number(findFirstDeep(value, ["sku_count", "skuCount"])) || 0);
      skcCount = Math.max(skcCount, Number(findFirstDeep(value, ["skc_count", "skcCount"])) || 0);

      Object.assign(price, collectPriceFromObject(value));
      images.push(...findUrlsDeep(value, /img|image|cdn|kwcdn|goods|product|scene|thumb/i));
      categories.push(...collectCategoryPartsFromObject(value));
      skuList.push(...collectArraysByKey(value, ["skuList", "sku_list", "skus"]).flat().map(normalizeSkuItem).filter(Boolean));
      skcList.push(...collectArraysByKey(value, ["skcList", "skc_list", "skcs"]).flat());
      propertyList.push(...collectArraysByKey(value, ["propertyList", "properties", "propList", "attrs", "attributes"]).flat());
      Object.assign(selectedOptions, collectSelectedOptionsFromObject(value));
    }

    return {
      title,
      description,
      goods_id: goodsId,
      images: uniqueUrls(images).filter(isLikelyProductImageUrl).slice(0, 120),
      video_url: videoUrl,
      price,
      sales_count: salesCount,
      rating,
      review_count: reviewCount,
      shop_id: shopId,
      shop_name: shopName,
      shop_url: shopUrl,
      category_parts: categories,
      selectedOptions,
      skuList,
      skcList,
      propertyList,
      variant_count: variantCount,
      sku_count: skuCount,
      skc_count: skcCount,
      summary,
    };
  }

  function getTemuProductRoot() {
    return document.querySelector("._2Fkk_bmp, ._2fkk_bmp") || document.body;
  }

  function isStoreOrProfileImage(img) {
    const contextParts = [img.alt, img.getAttribute("aria-label")];
    let ancestor = img;
    for (let index = 0; index < 5 && ancestor; index += 1) {
      contextParts.push(ancestor.innerText || "", ancestor.id || "", String(ancestor.className || ""));
      ancestor = ancestor.parentElement;
    }
    const contextText = contextParts.filter(Boolean).join(" ");
    if (/followers?|follow\b|store|seller|shop|exclusive accessory|customization|store joined temu/i.test(contextText)) return true;

    const rect = img.getBoundingClientRect();
    if (rect.width >= 80 && rect.width <= 140 && rect.height >= 80 && rect.height <= 140) {
      const nearbyText = img.closest("div")?.parentElement?.innerText || "";
      if (/followers?|follow\b|store|seller|shop|customization|store joined temu/i.test(nearbyText)) return true;
      if (/border-radius:\s*50%|clip-path|avatar|logo/i.test(`${img.getAttribute("style") || ""} ${img.className || ""}`)) return true;
    }
    return false;
  }

  function collectVisibleProductImages() {
    const root = getTemuProductRoot();
    const rootRect = root.getBoundingClientRect();
    const images = [];
    root.querySelectorAll("img").forEach((img) => {
      if (isStoreOrProfileImage(img)) return;
      const rect = img.getBoundingClientRect();
      const area = rect.width * rect.height;
      const src = normalizeUrl(img.currentSrc || img.src || img.getAttribute("data-src"));
      const insideRoot = rect.left >= rootRect.left - 4 && rect.right <= rootRect.right + 4;
      const leftMediaZone = rect.left < rootRect.left + rootRect.width * 0.62;
      const productSized = rect.width >= 48 && rect.height >= 48 && area >= 2500;
      if (insideRoot && leftMediaZone && productSized && isLikelyProductImageUrl(src)) images.push(src);
    });
    return uniqueUrls([readMeta("meta[property='og:image']"), ...images]).filter(isLikelyProductImageUrl).slice(0, 60);
  }

  function collectVisibleProductTitle() {
    const root = getTemuProductRoot();
    const rootRect = root.getBoundingClientRect();
    const candidates = [];
    root.querySelectorAll("h1,h2,div,span").forEach((node) => {
      const rect = node.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;
      const inRightBuyBox = rect.left > rootRect.left + rootRect.width * 0.32 && rect.top >= rootRect.top && rect.top < rootRect.top + 260;
      if (!inRightBuyBox) return;
      const text = cleanTemuTitle(node.innerText || node.textContent || "");
      if (text.length < 24 || text.length > 340) return;
      if (/popular right now|add to cart|free shipping|best-selling|review|rating|coupon|summer sale|sourced from/i.test(text)) return;
      if (/(?:US\$|\$|USD|￥|¥)\s*\d|LAST DAY|Est\.|OFF|Pay\s*\$|after applying promos|promo|Klarna|Afterpay/i.test(text)) return;
      if (!/[a-zA-Z]{6,}|[\u4e00-\u9fff]{4,}/.test(text)) return;
      candidates.push({
        text,
        score: text.length - Math.abs(rect.top - rootRect.top) * 0.2 - rect.height * 0.1,
      });
    });
    candidates.sort((a, b) => b.score - a.score);
    return candidates[0]?.text || "";
  }

  function collectBuyBoxVisiblePrice() {
    const root = getTemuProductRoot();
    const rootRect = root.getBoundingClientRect();
    const candidates = [];
    const priceRegex = /(?:US\$|\$|USD|￥|¥|CN¥)\s*\d+(?:[.,]\d{1,2})?/g;

    function pickPrices(text) {
      const normalized = normalizeWhitespace(text);
      if (!normalized || /min\.?\s*order|credit for delay|free shipping|coupon ends|klarna|afterpay/i.test(normalized)) return {};
      const matches = Array.from(normalized.matchAll(priceRegex)).map((match) => ({
        value: match[0].replace(/\s+/g, ""),
        index: match.index || 0,
      }));
      if (!matches.length) return {};
      const estimated = (normalized.match(/Est\.?\s*((?:US\$|\$|USD|￥|¥|CN¥)\s*\d+(?:[.,]\d{1,2})?)/i) || [])[1]?.replace(/\s+/g, "") || "";
      const current = matches.find((match) => {
        const before = normalized.slice(Math.max(0, match.index - 16), match.index);
        if (estimated && match.value === estimated) return false;
        if (/Est\.?\s*$/i.test(before) || /Pay\s*$/i.test(before)) return false;
        return true;
      })?.value || "";
      return { current, estimated };
    }

    root.querySelectorAll("div,span,strong,b").forEach((node) => {
      const rect = node.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;
      const inRightBuyBox = rect.left > rootRect.left + rootRect.width * 0.32 && rect.top > rootRect.top + 120 && rect.top < rootRect.top + 620;
      if (!inRightBuyBox) return;
      const text = normalizeWhitespace(node.innerText || node.textContent || "");
      const picked = pickPrices(text);
      if (!picked.current && !picked.estimated) return;
      const hasPromoEstimate = /LAST DAY|Est\.|after applying promos/i.test(text);
      candidates.push({
        current: picked.current,
        estimated: picked.estimated,
        displayText: cleanPriceDisplayText(picked.current || picked.estimated),
        score: (picked.current ? 200 : 0) + (hasPromoEstimate ? 100 : 0) + rect.height + rect.width * 0.01 - Math.abs(rect.top - (rootRect.top + 300)) * 0.05,
      });
    });
    candidates.sort((a, b) => b.score - a.score);
    return candidates[0] || {};
  }

  function collectImagesFromDom() {
    const imageUrls = [readMeta("meta[property='og:image']")];
    for (const image of Array.from(document.images || [])) {
      imageUrls.push(image.currentSrc, image.src, image.getAttribute("data-src"));
      imageUrls.push(...extractUrlsFromSrcset(image.srcset || ""));
      const lazyValue = image.getAttribute("data-original") || image.getAttribute("data-lazy") || "";
      imageUrls.push(lazyValue);
    }
    for (const source of Array.from(document.querySelectorAll("source[srcset]"))) {
      imageUrls.push(...extractUrlsFromSrcset(source.getAttribute("srcset") || ""));
    }
    for (const element of Array.from(document.querySelectorAll("[style*='background']"))) {
      imageUrls.push(...extractUrlsFromText(element.getAttribute("style") || ""));
    }
    for (const script of Array.from(document.scripts || [])) {
      const text = script.textContent || "";
      if (/image|img|pic|kwcdn|cdn/i.test(text)) {
        imageUrls.push(...extractUrlsFromText(text));
      }
    }
    return uniqueUrls(imageUrls).filter(isLikelyProductImageUrl).slice(0, 120);
  }

  function collectVideoUrls() {
    const urls = [];
    for (const video of Array.from(document.querySelectorAll("video, video source"))) {
      urls.push(video.currentSrc, video.src, video.getAttribute("src"));
    }
    for (const script of Array.from(document.scripts || [])) {
      urls.push(...extractUrlsFromText(script.textContent || "").filter((url) => /\.(mp4|m3u8)(?:\?|$)/i.test(url)));
    }
    return uniqueUrls(urls);
  }

  function collectVisiblePrice(text) {
    const priceRegex = /(?:US\$|\$|USD|￥|¥|CN¥)\s*[0-9]+(?:[.,][0-9]{1,2})?/gi;
    const prices = Array.from(String(text || "").matchAll(priceRegex)).map((match) => match[0].replace(/\s+/g, ""));
    const estimated = extractValue(text, /Est\.?\s*((?:US\$|\$|USD|￥|¥|CN¥)\s*[0-9]+(?:[.,][0-9]{1,2})?)/i);
    const original = extractValue(text, /(?:was|原价|list price)\s*((?:US\$|\$|USD|￥|¥|CN¥)\s*[0-9]+(?:[.,][0-9]{1,2})?)/i);
    const current = prices.find((value) => value !== estimated && value !== original) || prices[0] || "";
    return {
      current,
      original,
      estimated,
      displayText: cleanPriceDisplayText(current || estimated || original || prices[0]),
      currency: inferCurrency(current || estimated || original),
    };
  }

  function collectSelectedOptions() {
    const selected = {};
    const lines = String(document.body?.innerText || "")
      .split(/\n+/)
      .map(normalizeWhitespace)
      .filter(Boolean);
    const pattern = /^(Color|Colour|Style|Size|Material|Type|Model|Pattern|Quantity|Qty|尺码|颜色|风格|材质|型号|数量|容量|款式|规格)\s*[:：]\s*(.+)$/i;
    for (const line of lines) {
      const match = line.match(pattern);
      if (!match) continue;
      addSelectedOption(selected, match[1], match[2]);
    }
    for (const node of Array.from(document.querySelectorAll("[aria-selected='true'], [data-selected='true'], .selected, [class*='selected']"))) {
      const line = normalizeWhitespace(node.innerText || node.textContent || node.getAttribute("aria-label") || "");
      if (line.length > 1 && line.length < 120) {
        addSelectedOption(selected, "selected", line);
      }
    }
    return selected;
  }

  function collectSkuItemsFromDom() {
    const rows = Array.from(document.querySelectorAll("[class*='sku'], [class*='Sku'], [data-sku-id], [data-skc-id]"));
    const items = [];
    rows.slice(0, 300).forEach((row, index) => {
      const text = normalizeWhitespace(row.innerText || row.textContent || "");
      const imageUrl = pickImageFromElement(row);
      const price = extractValue(text, /(?:US\$|\$|USD|￥|¥|CN¥)\s*([0-9]+(?:[.,][0-9]{1,2})?)/i);
      const stock = extractValue(text, /(?:stock|库存|剩余)\D*([0-9]+)/i);
      if (!text && !imageUrl) return;
      if (/sku|skc/i.test(text) && text.length < 6 && !imageUrl) return;
      items.push({
        sku_id: row.getAttribute("data-sku-id") || row.getAttribute("data-skc-id") || `dom-${index + 1}`,
        specs: { option: cleanOptionText(text).slice(0, 120) || `SKU ${index + 1}` },
        price: price ? Number(String(price).replace(",", ".")) : undefined,
        stock: stock ? Number(stock) : undefined,
        image_url: imageUrl || undefined,
      });
    });
    return items;
  }

  function collectCategoryPartsFromDom() {
    const candidates = [];
    for (const selector of ["nav", "[aria-label*='breadcrumb' i]", "[class*='bread' i]", "[class*='category' i]"]) {
      for (const element of Array.from(document.querySelectorAll(selector)).slice(0, 12)) {
        candidates.push(...splitCategoryText(element.innerText || element.textContent || ""));
      }
    }
    return normalizeCategoryParts(candidates);
  }

  function collectShopNameFromDom() {
    const candidates = [];
    for (const selector of ["[class*='store' i]", "[class*='shop' i]", "[class*='seller' i]", "a[href*='store']", "a[href*='shop']"]) {
      for (const element of Array.from(document.querySelectorAll(selector)).slice(0, 20)) {
        const text = normalizeWhitespace(element.innerText || element.textContent || element.getAttribute("aria-label") || "");
        if (text && text.length >= 2 && text.length <= 80 && !/follow|followers|coupon|cart|search|category/i.test(text)) {
          candidates.push(text);
        }
      }
    }
    return candidates[0] || "";
  }

  function collectPriceFromObject(value) {
    const output = {};
    const current = findFirstDeep(value, ["current", "currentPrice", "salePrice", "price", "priceStr", "priceText"]);
    const original = findFirstDeep(value, ["original", "originalPrice", "marketPrice", "listPrice"]);
    const estimated = findFirstDeep(value, ["estimated", "estimatedPrice", "estPrice"]);
    const currency = findFirstDeep(value, ["currency", "currencyCode", "currencySymbol"]);
    if (current !== "") output.current = current;
    if (original !== "") output.original = original;
    if (estimated !== "") output.estimated = estimated;
    if (currency !== "") output.currency = currency;
    return output;
  }

  function normalizePrice(price) {
    const current = cleanPriceDisplayText(firstText(price.current, price.salePrice, price.price));
    const original = cleanPriceDisplayText(firstText(price.original, price.originalPrice, price.marketPrice));
    const estimated = cleanPriceDisplayText(firstText(price.estimated, price.estimatedPrice));
    const displayText = cleanPriceDisplayText(firstText(current, estimated, original, price.displayText));
    return {
      current,
      original,
      estimated,
      displayText,
      currency: firstText(price.currency, inferCurrency(displayText)),
    };
  }

  function cleanPriceDisplayText(value) {
    const text = normalizeWhitespace(String(value ?? ""));
    if (!text) return "";
    const match = text.match(/(?:US\$|\$|USD|￥|¥|CN¥|CN楼|楼)\s*[0-9]+(?:[.,][0-9]{1,2})?/i);
    if (!match) return "";
    return match[0].replace(/\s+/g, "");
  }

  function normalizeSkuItem(item) {
    if (!item || typeof item !== "object") return null;
    const specs = {};
    const rawSpecs = item.specs || item.properties || item.attrs || item.attributes || item.selected || {};
    if (rawSpecs && typeof rawSpecs === "object" && !Array.isArray(rawSpecs)) {
      for (const [key, value] of Object.entries(rawSpecs)) {
        if (value == null || typeof value === "object") continue;
        specs[normalizeWhitespace(key)] = normalizeWhitespace(value);
      }
    }
    for (const key of ["name", "specName", "propertyName", "optionName", "color", "size", "style"]) {
      if (item[key] && typeof item[key] !== "object") specs[key] = normalizeWhitespace(item[key]);
    }
    const value = firstText(item.value, item.specValue, item.propertyValue, item.optionValue, item.label);
    if (value) specs.value = value;
    const imageUrl = firstText(
      item.image_url,
      item.imageUrl,
      item.imgUrl,
      item.thumbUrl,
      item.skuImageUrl,
      item.skcImageUrl,
      findFirstUrlDeep(item, /image|img|pic|thumb/i)
    );
    const cleaned = {
      sku_id: firstText(item.sku_id, item.skuId, item.skcId, item.id, item.specId) || undefined,
      specs,
      price: toOptionalNumber(firstText(item.price, item.salePrice, item.currentPrice)),
      stock: toOptionalNumber(firstText(item.stock, item.quantity, item.inventory)),
      image_url: imageUrl || undefined,
    };
    if (!Object.keys(cleaned.specs).length && !cleaned.image_url && cleaned.price == null && cleaned.stock == null) return null;
    return cleaned;
  }

  function mergeSkuItems(items) {
    const merged = new Map();
    for (const item of items.map(normalizeSkuItem).filter(Boolean)) {
      const key = JSON.stringify(item.specs || {}) || item.image_url || item.sku_id || Math.random().toString(36);
      const existing = merged.get(key) || {};
      merged.set(key, {
        sku_id: existing.sku_id || item.sku_id,
        specs: { ...(existing.specs || {}), ...(item.specs || {}) },
        price: existing.price ?? item.price,
        stock: existing.stock ?? item.stock,
        image_url: existing.image_url || item.image_url,
      });
    }
    return Array.from(merged.values()).slice(0, 500);
  }

  function buildTemuSkuList({ rawSkuList = [], selectedOptions = {}, propertyList = [], images = [], price = {} } = {}) {
    const selectedSkuItem = buildSelectedSkuItem({ selectedOptions, images, price });
    if (selectedSkuItem && rawSkuList.length && rawSkuList.every(isLowConfidenceDomSkuItem)) {
      return [selectedSkuItem];
    }
    if (rawSkuList.length) return rawSkuList;

    const propertySkuItems = normalizeList(propertyList).map(normalizeSkuItem).filter(Boolean);
    if (propertySkuItems.length) return propertySkuItems.slice(0, 200);
    if (selectedSkuItem) return [selectedSkuItem];

    return buildFallbackSkuItems({ selectedOptions, propertyList: [], images, price });
  }

  function buildSelectedSkuItem({ selectedOptions = {}, images = [], price = {} } = {}) {
    const specs = getSelectedOptionSpecs(selectedOptions);
    const optionText = uniqueTextValues(Object.values(specs)).join(" / ");
    if (!optionText) return null;
    return {
      sku_id: optionText,
      specs,
      price: toOptionalNumber(firstText(price.current, price.estimated)),
      image_url: images[0] || undefined,
    };
  }

  function getSelectedOptionSpecs(selectedOptions = {}) {
    const specs = {};
    for (const [key, value] of Object.entries(selectedOptions || {})) {
      const cleanValue = cleanOptionText(value);
      const specKey = normalizeTemuSpecKey(key);
      if (!specKey || !cleanValue) continue;
      if (specKey === "__purchase_qty") continue;
      if (specKey !== "规格" && specs["规格"] === cleanValue) delete specs["规格"];
      if (specKey === "规格" && Object.keys(specs).length) continue;
      specs[specKey] = cleanValue;
    }
    return specs;
  }

  function normalizeTemuSpecKey(key) {
    const raw = normalizeWhitespace(key).replace(/[：:]/g, "");
    const normalized = raw.toLowerCase().replace(/[\s_-]+/g, "_");
    if (!normalized) return "";
    if (/^qty$/.test(normalized)) return "__purchase_qty";
    if (/^(quantity|容量)$/.test(normalized)) return "规格";
    if (/^(color|colour|颜色|顏色)$/.test(normalized)) return "颜色";
    if (/^(size|尺码|尺寸)$/.test(normalized)) return "尺码";
    if (/^(style|款式|风格)$/.test(normalized)) return "款式";
    if (/^(material|材质)$/.test(normalized)) return "材质";
    if (/^(model|型号)$/.test(normalized)) return "型号";
    if (/^(pattern|图案|花色)$/.test(normalized)) return "图案";
    if (/^(type|option|selected|value|规格)$/.test(normalized)) return "规格";
    return raw.replace(/_/g, " ");
  }

  function isLowConfidenceDomSkuItem(item) {
    const skuId = String(item?.sku_id || "");
    if (!/^dom-\d+$/i.test(skuId)) return false;
    const specs = item?.specs && typeof item.specs === "object" ? item.specs : {};
    const keys = Object.keys(specs);
    const values = Object.values(specs).map(cleanOptionText).filter(Boolean);
    if (!keys.length && !values.length) return true;
    const genericKeys = keys.every((key) => ["规格", "option", "value", "name", "label"].includes(key));
    const genericValues = values.every((value) => /^sku\s*\d+$/i.test(value) || value.length <= 3);
    return genericKeys && genericValues;
  }

  function uniqueTextValues(values) {
    const seen = new Set();
    const result = [];
    for (const value of values || []) {
      const clean = normalizeWhitespace(value);
      if (!clean || seen.has(clean)) continue;
      seen.add(clean);
      result.push(clean);
    }
    return result;
  }

  function buildFallbackSkuItems({ selectedOptions = {}, propertyList = [], images = [], price = {} } = {}) {
    const propertySkuItems = normalizeList(propertyList).map(normalizeSkuItem).filter(Boolean);
    if (propertySkuItems.length) return propertySkuItems.slice(0, 200);

    const specs = getSelectedOptionSpecs(selectedOptions);

    return [{
      sku_id: "temu-default",
      specs: Object.keys(specs).length ? specs : { 规格: "默认款" },
      price: toOptionalNumber(firstText(price.current, price.estimated)),
      image_url: images[0] || undefined,
    }];
  }

  function inferNoAttribute({ skuList, propertyList, selectedOptions, variantCount }) {
    const optionCount = Object.keys(selectedOptions || {}).filter((key) => key !== "qty" && selectedOptions[key]).length;
    if (optionCount > 0) return false;
    return Number(variantCount || skuList.length || propertyList.length || 1) <= 1;
  }

  function collectArraysByKey(value, keys, seen = new WeakSet(), depth = 0) {
    if (!value || typeof value !== "object" || seen.has(value) || depth > 7) return [];
    seen.add(value);
    const arrays = [];
    if (!Array.isArray(value)) {
      for (const [key, child] of Object.entries(value)) {
        if (keys.includes(key) && Array.isArray(child)) arrays.push(child);
        arrays.push(...collectArraysByKey(child, keys, seen, depth + 1));
      }
    } else {
      for (const child of value.slice(0, 300)) {
        arrays.push(...collectArraysByKey(child, keys, seen, depth + 1));
      }
    }
    return arrays;
  }

  function findFirstDeep(value, keys, seen = new WeakSet(), depth = 0) {
    if (!value || typeof value !== "object" || seen.has(value) || depth > 7) return "";
    seen.add(value);
    if (!Array.isArray(value)) {
      for (const key of keys) {
        const child = value[key];
        if (child != null && typeof child !== "object" && String(child).trim()) return normalizeWhitespace(child);
      }
      for (const child of Object.values(value)) {
        const found = findFirstDeep(child, keys, seen, depth + 1);
        if (found) return found;
      }
    } else {
      for (const child of value.slice(0, 300)) {
        const found = findFirstDeep(child, keys, seen, depth + 1);
        if (found) return found;
      }
    }
    return "";
  }

  function findUrlsDeep(value, keyPattern, seen = new WeakSet(), depth = 0) {
    if (value == null || depth > 7) return [];
    if (typeof value === "string") return extractUrlsFromText(value);
    if (typeof value !== "object" || seen.has(value)) return [];
    seen.add(value);
    const urls = [];
    if (Array.isArray(value)) {
      value.slice(0, 300).forEach((item) => urls.push(...findUrlsDeep(item, keyPattern, seen, depth + 1)));
      return urls;
    }
    for (const [key, child] of Object.entries(value)) {
      if (typeof child === "string" && keyPattern.test(key)) urls.push(...extractUrlsFromText(child));
      urls.push(...findUrlsDeep(child, keyPattern, seen, depth + 1));
    }
    return urls;
  }

  function findFirstUrlDeep(value, keyPattern) {
    return findUrlsDeep(value, keyPattern).find(Boolean) || "";
  }

  function collectSelectedOptionsFromObject(value) {
    const selected = {};
    const objects = collectArraysByKey(value, ["selectedOptions", "selected", "selection"]).flat();
    objects.forEach((item) => {
      if (!item || typeof item !== "object") return;
      for (const [key, child] of Object.entries(item)) {
        if (child != null && typeof child !== "object") addSelectedOption(selected, key, child);
      }
    });
    return selected;
  }

  function collectCategoryPartsFromObject(value) {
    const raw = [
      findFirstDeep(value, ["categoryPath", "category_path", "catPath", "breadcrumb"]),
      findFirstDeep(value, ["categoryName", "catName", "leafCategoryName"]),
    ];
    return normalizeCategoryParts(raw.flatMap(splitCategoryText));
  }

  function pushParsed(contexts, key, text) {
    const parsed = safeJsonParse(text);
    if (parsed === null) return;
    contexts.push({
      key,
      value: parsed,
      size: String(text || "").length,
    });
  }

  function safeJsonParse(text) {
    const raw = String(text || "").trim();
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch (_error) {
      const decoded = decodeJsonStringLiteral(raw);
      if (decoded !== raw) {
        try {
          return JSON.parse(decoded);
        } catch (__error) {
          return null;
        }
      }
      return null;
    }
  }

  function extractBalancedJsonNearKey(source, key, limit) {
    const snippets = [];
    let fromIndex = 0;
    while (snippets.length < limit) {
      const keyIndex = source.indexOf(key, fromIndex);
      if (keyIndex < 0) break;
      const start = findContainerStart(source, keyIndex);
      if (start >= 0) {
        const snippet = readBalancedContainer(source, start);
        if (snippet) snippets.push(snippet);
      }
      fromIndex = keyIndex + key.length;
    }
    return snippets;
  }

  function findContainerStart(source, fromIndex) {
    const left = Math.max(0, fromIndex - 12000);
    for (let index = fromIndex; index >= left; index -= 1) {
      const char = source[index];
      if (char === "{" || char === "[") return index;
    }
    return -1;
  }

  function readBalancedContainer(source, startIndex) {
    const open = source[startIndex];
    const close = open === "{" ? "}" : "]";
    let depth = 0;
    let inString = false;
    let escape = false;
    for (let index = startIndex; index < source.length; index += 1) {
      const char = source[index];
      if (inString) {
        if (escape) {
          escape = false;
        } else if (char === "\\") {
          escape = true;
        } else if (char === '"') {
          inString = false;
        }
        continue;
      }
      if (char === '"') {
        inString = true;
      } else if (char === open) {
        depth += 1;
      } else if (char === close) {
        depth -= 1;
        if (depth === 0) return source.slice(startIndex, index + 1);
      }
    }
    return "";
  }

  function summarizeMainWorldSnapshot(snapshot) {
    return {
      href: snapshot?.href || "",
      title: snapshot?.title || "",
      keys: Array.isArray(snapshot?.keys) ? snapshot.keys : [],
      candidate_count: Array.isArray(snapshot?.candidates) ? snapshot.candidates.length : 0,
      capturedAt: snapshot?.capturedAt || "",
    };
  }

  function readText(selector) {
    return normalizeWhitespace(document.querySelector(selector)?.textContent || "");
  }

  function readMeta(selector) {
    return normalizeWhitespace(document.querySelector(selector)?.getAttribute("content") || "");
  }

  function extractGoodsIdFromUrl(url) {
    try {
      const parsed = new URL(url);
      return (
        parsed.searchParams.get("goods_id") ||
        parsed.searchParams.get("goodsId") ||
        parsed.searchParams.get("_oak_goods_id") ||
        (parsed.pathname.match(/(?:goods|product)[/_-]?([0-9]{8,})/i) || [])[1] ||
        ""
      );
    } catch (_error) {
      return "";
    }
  }

  function extractGoodsIdFromText(text) {
    return (
      extractValue(text, /["']goods[_-]?id["']\s*[:=]\s*["']?([0-9]{8,})/i) ||
      extractValue(text, /\bgoodsId=([0-9]{8,})/i) ||
      extractValue(text, /\b60[0-9]{8,}\b/)
    );
  }

  function addSelectedOption(target, key, value) {
    const cleanKey = normalizeWhitespace(key).replace(/[：:]/g, "");
    const cleanValue = cleanOptionText(value);
    if (!cleanKey || !cleanValue) return;
    const normalizedKey = cleanKey.toLowerCase().replace(/\s+/g, "_");
    if (/^(stock|sold|review|rating)$/i.test(normalizedKey)) return;
    target[normalizedKey] = cleanValue;
  }

  function pickImageFromElement(element) {
    const image = element.querySelector?.("img");
    return normalizeUrl(image?.currentSrc || image?.src || image?.getAttribute("data-src") || "");
  }

  function isLikelyProductImageUrl(url) {
    return (
      /^https?:\/\//i.test(url || "") &&
      /img|image|cdn|kwcdn|product|goods|scene|fancy|jpg|jpeg|png|webp/i.test(url) &&
      !/avatar|logo|icon|badge|footer|recommend|search_result|chat|message|coupon/i.test(url)
    );
  }

  function extractUrlsFromSrcset(srcset) {
    return String(srcset || "")
      .split(",")
      .map((part) => part.trim().split(/\s+/)[0])
      .filter(Boolean)
      .map(normalizeUrl);
  }

  function extractUrlsFromText(text) {
    const urls = [];
    const pattern = /https?:\\?\/\\?\/[^"'\s\\)]+/gi;
    for (const match of String(text || "").matchAll(pattern)) {
      urls.push(normalizeUrl(match[0].replaceAll("\\/", "/")));
    }
    return urls;
  }

  function uniqueUrls(urls) {
    const seen = new Set();
    const result = [];
    for (const raw of urls || []) {
      const url = normalizeUrl(raw);
      if (!url || seen.has(url)) continue;
      seen.add(url);
      result.push(url);
    }
    return result;
  }

  function normalizeUrl(url) {
    const clean = String(url || "").trim().replaceAll("\\/", "/");
    if (!clean) return "";
    try {
      return new URL(clean, location.href).href;
    } catch (_error) {
      return "";
    }
  }

  function normalizeList(value) {
    return Array.isArray(value) ? value.filter(Boolean).slice(0, 500) : [];
  }

  function normalizeCategoryParts(parts) {
    const blocked = new Set(["temu", "home", "search", "all", "category", "首页", "商品详情"]);
    const result = [];
    for (const part of parts || []) {
      const clean = normalizeWhitespace(part).replace(/^>|>$/g, "");
      if (!clean || clean.length > 60 || blocked.has(clean.toLowerCase())) continue;
      if (!result.includes(clean)) result.push(clean);
    }
    return result.slice(0, 8);
  }

  function splitCategoryText(value) {
    return String(value || "")
      .replace(/[›»]/g, ">")
      .split(/[>\n/]+/)
      .map(normalizeWhitespace)
      .filter(Boolean);
  }

  function cleanTemuTitle(value) {
    const original = normalizeWhitespace(value);
    if (!original) return "";
    const cleaned = normalizeWhitespace(original)
      .replace(/\s*\|\s*Temu.*$/i, "")
      .replace(/^Temu\s*\|\s*/i, "")
      .replace(/^(?:No import charges\s*)?(?:Local warehouse\s*[-–—]\s*)?Fastest delivery:\s*\d+\s*BUSINESS\s*DAYS?\s*/i, "")
      .replace(/^Fastest delivery:\s*\d+\s*BUSINESS\s*DAYS?\s*/i, "")
      .replace(/^(?:No import charges\s*)?Local warehouse\s*[-–—]\s*/i, "")
      .replace(/\s*(?:US\$|\$|USD|CNY|CN¥)\s*[0-9]+(?:[.,][0-9]{1,2})?.*$/i, "")
      .replace(/\s*(?:LAST DAY|ALMOST SOLD OUT|after applying promos|Pay\s*\$|OFF\b|Klarna|Afterpay).*$/i, "");
    return normalizeWhitespace(cleaned) || original;
  }

  function cleanOptionText(value) {
    return normalizeWhitespace(value)
      .replace(/\s+(?:Qty|QTY)\s*[:：]?\s*\d+.*$/i, "")
      .replace(/\s+[0-9][0-9.,Kk+]*\s*sold.*$/i, "")
      .replace(/\s*(Add to cart|Buy now|Free shipping|Order guarantee).*$/i, "")
      .slice(0, 180);
  }

  function firstText(...values) {
    for (const value of values) {
      const text = normalizeWhitespace(value);
      if (text) return text;
    }
    return "";
  }

  function normalizeWhitespace(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim();
  }

  function extractValue(text, pattern) {
    const match = String(text || "").match(pattern);
    return normalizeWhitespace(match?.[1] || match?.[0] || "");
  }

  function inferCurrency(text) {
    const value = String(text || "");
    if (/US\$|\$|USD/i.test(value)) return "USD";
    if (/CN¥|￥|¥|CNY/i.test(value)) return "CNY";
    return "";
  }

  function toOptionalNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    const number = Number(String(value).replace(/[^0-9.-]+/g, ""));
    return Number.isFinite(number) ? number : null;
  }

  function decodeJsonStringLiteral(value) {
    try {
      if (!/^["']/.test(value)) return value;
      return JSON.parse(value);
    } catch (_error) {
      return value;
    }
  }
})();
