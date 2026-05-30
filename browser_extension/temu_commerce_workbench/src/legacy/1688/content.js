(function () {
  const WEIGHT_LABEL_PATTERN = /(?:\u5546\u54c1\u4ef6\u91cd\u5c3a|\u5546\u54c1\u4ef6\u91cd|\u4ef6\u91cd|\u91cd\u91cf|\u51c0\u91cd|\u6bdb\u91cd)/i;

  function normalizeWhitespace(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim();
  }

  function parseMoney(text) {
    const normalized = normalizeWhitespace(text).replace(/,/g, "");
    const currencyMatch = normalized.match(/(?:[锟ヂ]|rmb|cny)\s*([0-9]+(?:\.[0-9]+)?)/i);
    if (currencyMatch) {
      return currencyMatch[1];
    }

    const plainMatch = normalized.match(/([0-9]+(?:\.[0-9]+)?)/);
    return plainMatch ? plainMatch[1] : "";
  }

  function isVisible(element) {
    if (!element) return false;
    if (typeof window?.getComputedStyle !== "function") return true;

    const style = window.getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden";
  }

  function readElementText(element) {
    if (!isVisible(element)) return "";
    return normalizeWhitespace(element.textContent || element.value || "");
  }

  function formatWeightKg(value) {
    return String(Number(value.toFixed(3)));
  }

  function normalizeWeightUnit(value) {
    const text = normalizeWhitespace(value).toLowerCase();
    if (!text) return "";

    if (text.includes("kg") || text.includes("\u5343\u514b") || text.includes("\u516c\u65a4")) {
      return "kg";
    }

    if (text.includes("(g)") || text.includes(" g") || /^g$/.test(text) || text.includes("\u514b")) {
      return "g";
    }

    return "";
  }

  function parseWeightValue(rawValue, unitHint = "") {
    const normalized = normalizeWhitespace(rawValue).toLowerCase();
    const numeric = normalized.match(/([0-9]+(?:\.[0-9]+)?)/);
    if (!numeric) return "";

    const value = Number(numeric[1]);
    if (!(value > 0)) return "";

    const unit = normalizeWeightUnit(`${normalized} ${unitHint}`);
    if (unit === "kg") return formatWeightKg(value);
    if (unit === "g") return formatWeightKg(value / 1000);
    return String(value);
  }

  function getFirstVisibleText(selectors) {
    for (const selector of selectors) {
      const elements = document.querySelectorAll(selector);
      for (const element of elements) {
        const text = readElementText(element);
        if (text) return text;
      }
    }

    return "";
  }

  function getInlineContextScriptText() {
    const scripts = document.scripts || [];
    const matches = [];
    for (const script of scripts) {
      const text = script.textContent || "";
      if (text.includes("window.context=") || text.includes('"tradeModel"') || text.includes('"unitWeight"')) {
        matches.push(text);
      }
    }

    return matches.join("\n");
  }

  function extractValueByPatterns(sourceText, patterns) {
    const text = String(sourceText || "");
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match?.[1]) {
        return normalizeWhitespace(match[1]);
      }
    }

    return "";
  }

  function findFirstWeightInText(sourceText, { allowLooseMatch = false } = {}) {
    const text = normalizeWhitespace(sourceText);
    if (!text) return "";

    const patterns = [
      /(?:\u5546\u54c1\u4ef6\u91cd\u5c3a|\u5546\u54c1\u4ef6\u91cd|\u4ef6\u91cd|\u91cd\u91cf|\u51c0\u91cd|\u6bdb\u91cd)\s*[:\uff1a]?\s*([0-9]+(?:\.[0-9]+)?)\s*(kg|g|\u5343\u514b|\u516c\u65a4|\u514b)/i
    ];

    if (allowLooseMatch) {
      patterns.push(/([0-9]+(?:\.[0-9]+)?)\s*(kg|g|\u5343\u514b|\u516c\u65a4|\u514b)/i);
    }

    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (!match) continue;

      const parsed = parseWeightValue(match[1], match[2]);
      if (parsed) return parsed;
    }

    return "";
  }

  function findWeightFromWeightHeaderText(sourceText) {
    const text = normalizeWhitespace(sourceText);
    if (!text) return "";

    const patterns = [
      /(?:\u5546\u54c1\u4ef6\u91cd\u5c3a[\s\S]{0,80}?)?\u91cd\u91cf\s*[\(锛圿?\s*(kg|g|\u5343\u514b|\u516c\u65a4|\u514b)\s*[\)锛塢?[^\d]{0,30}([0-9]+(?:\.[0-9]+)?)/i,
      /(?:\u5546\u54c1\u4ef6\u91cd\u5c3a|\u5546\u54c1\u4ef6\u91cd)[\s\S]{0,120}?([0-9]+(?:\.[0-9]+)?)\s*(kg|g|\u5343\u514b|\u516c\u65a4|\u514b)/i
    ];

    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (!match) continue;

      const unit = pattern === patterns[0] ? match[1] : match[2];
      const value = pattern === patterns[0] ? match[2] : match[1];
      const parsed = parseWeightValue(value, unit);
      if (parsed) return parsed;
    }

    return "";
  }

  function findWeightFromStructuredPackInfo(scriptText) {
    if (!String(scriptText || "").includes('"pieceWeightScale"')) return "";

    const rawWeight = extractValueByPatterns(scriptText, [
      /"pieceWeightScale"[\s\S]{0,2000}?"pieceWeightScaleInfo":\s*\[\s*\{[\s\S]*?"weight":\s*([0-9]+(?:\.[0-9]+)?)/,
      /"pieceWeightScaleInfo":\s*\[\s*\{[\s\S]*?"weight":\s*([0-9]+(?:\.[0-9]+)?)/
    ]);
    if (!(Number(rawWeight) > 0)) return "";

    const unit = extractValueByPatterns(scriptText, [
      /"pieceWeightScale"[\s\S]{0,2000}?"columnList":\s*\[[\s\S]*?"label":"[^"]*\((kg|g)\)"/i,
      /"pieceWeightScale"[\s\S]{0,2000}?"columnList":\s*\[[\s\S]*?"label":"[^"]*(\u5343\u514b|\u516c\u65a4|\u514b)"/,
      /"columnList":\s*\[[\s\S]*?"label":"[^"]*\((kg|g)\)"/i
    ]);
    if (!normalizeWeightUnit(unit)) return "";

    return parseWeightValue(rawWeight, unit);
  }

  function findWeightFromNumericScriptFields(scriptText) {
    const rawWeight = extractValueByPatterns(scriptText, [
      /"unitWeight":\s*([0-9]+(?:\.[0-9]+)?)/,
      /"minWeight":\s*([0-9]+(?:\.[0-9]+)?)/,
      /"skuWeight":\s*\{\s*"[^"]*":\s*([0-9]+(?:\.[0-9]+)?)\s*\}/
    ]);
    if (!(Number(rawWeight) > 0)) return "";

    return parseWeightValue(rawWeight, "kg");
  }

  function getRowCells(row) {
    if (!row || typeof row.querySelectorAll !== "function") return [];
    return Array.from(row.querySelectorAll("th,td") || []);
  }

  function findWeightColumnIndex(rowTexts) {
    return rowTexts.findIndex((text) => WEIGHT_LABEL_PATTERN.test(text));
  }

  function findWeightFromPackInfoTable() {
    const rootSelectors = [
      "#productPackInfo",
      ".module-od-product-pack-info",
      "[data-module='od_product_pack_info']"
    ];

    for (const rootSelector of rootSelectors) {
      const roots = Array.from(document.querySelectorAll(rootSelector) || []);
      for (const root of roots) {
        if (!isVisible(root) || typeof root.querySelectorAll !== "function") continue;

        const rows = Array.from(root.querySelectorAll("tr") || []);
        for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
          const headerCells = getRowCells(rows[rowIndex]);
          const headerTexts = headerCells.map(readElementText);
          const weightIndex = findWeightColumnIndex(headerTexts);
          if (weightIndex < 0) continue;

          const unitHint = headerTexts[weightIndex];
          for (let valueRowIndex = rowIndex + 1; valueRowIndex < rows.length; valueRowIndex += 1) {
            const valueCells = getRowCells(rows[valueRowIndex]);
            if (valueCells.length <= weightIndex) continue;

            const parsed = parseWeightValue(readElementText(valueCells[weightIndex]), unitHint);
            if (parsed) return parsed;
          }
        }
      }
    }

    return "";
  }

  function findGoodsPrice() {
    const priceText = getFirstVisibleText([
      "#submitOrder .total-price strong",
      ".module-od-submit-order .total-price strong",
      "#skuSelection .expand-view-item .item-price-stock",
      ".module-od-sku-selection .expand-view-item .item-price-stock",
      "#mainPrice .price-info:last-child",
      ".module-od-main-price .price-info:last-child"
    ]);
    if (priceText) {
      return parseMoney(priceText);
    }

    const scriptText = getInlineContextScriptText();
    return extractValueByPatterns(scriptText, [
      /"maxPrice":"([0-9]+(?:\.[0-9]+)?)"/,
      /"priceDisplay":"[0-9]+(?:\.[0-9]+)?-([0-9]+(?:\.[0-9]+)?)"/,
      /"discountPrice":"([0-9]+(?:\.[0-9]+)?)"/
    ]);
  }

  function findShippingFee() {
    const shippingText = getFirstVisibleText([
      "#submitOrder .total-freight-fee strong",
      "#shippingServices .service-item.split-border b",
      ".module-od-submit-order .total-freight-fee strong",
      ".module-od-shipping-services .service-item.split-border b",
      "#shippingServices b"
    ]);
    if (shippingText) {
      return parseMoney(shippingText);
    }

    const scriptText = getInlineContextScriptText();
    return (
      extractValueByPatterns(scriptText, [
        /"postFeeValue":([0-9]+(?:\.[0-9]+)?)/,
        /"totalCost":([0-9]+(?:\.[0-9]+)?)/,
        /"price":"([0-9]+(?:\.[0-9]+)?)","deliveryLimitText"/
      ]) || "0"
    );
  }

  function findWeight() {
    const scriptText = getInlineContextScriptText();

    const structuredWeight = findWeightFromStructuredPackInfo(scriptText);
    if (structuredWeight) return structuredWeight;

    const numericScriptWeight = findWeightFromNumericScriptFields(scriptText);
    if (numericScriptWeight) return numericScriptWeight;

    const tableWeight = findWeightFromPackInfoTable();
    if (tableWeight) return tableWeight;

    const packInfoText = getFirstVisibleText([
      "#productPackInfo",
      ".module-od-product-pack-info",
      "[data-module='od_product_pack_info']"
    ]);
    const packInfoHeaderWeight = findWeightFromWeightHeaderText(packInfoText);
    if (packInfoHeaderWeight) return packInfoHeaderWeight;

    const packInfoWeight = findFirstWeightInText(packInfoText, { allowLooseMatch: true });
    if (packInfoWeight) return packInfoWeight;

    const pageHeaderWeight = findWeightFromWeightHeaderText(document.body?.innerText || "");
    if (pageHeaderWeight) return pageHeaderWeight;

    return findFirstWeightInText(document.body?.innerText || "");
  }

  function computeUnitPrice(goodsPrice, shippingFee) {
    const goods = Number(goodsPrice || 0);
    const shipping = Number(shippingFee || 0);
    if (goods <= 0) {
      return "";
    }

    return (goods + shipping).toFixed(2);
  }

  function extractProductData() {
    const goodsPrice = findGoodsPrice();
    const shippingFee = findShippingFee();

    return {
      url: window.location.href,
      unitPrice: computeUnitPrice(goodsPrice, shippingFee),
      weight: findWeight(),
      goodsPrice,
      shippingFee
    };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "extract-product-data") {
      return false;
    }

    sendResponse(extractProductData());
    return false;
  });
})();
