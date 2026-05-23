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

  const payload = {
    offer_id: pickOfferId(productUrl),
    product_url: productUrl,
    title,
    main_image_url: pickMainImage(),
    price: pickPrice(),
    price_range: pickPriceRange(),
    moq: pickMoq(),
    shop_name: pickShopName(),
    shop_url: pickShopUrl(),
    sku_list: pickSkuList(),
    captured_at: new Date().toISOString().slice(0, 19).replace("T", " "),
    raw_data: {
      page_title: document.title,
      url: productUrl,
      user_agent: navigator.userAgent,
    },
  };

  return payload;
}

function pickTitle() {
  return cleanText(
    queryText([
      "h1",
      "[class*='title'] h1",
      "[class*='Title']",
      "[class*='offer-title']",
      "[class*='product-title']",
    ]) || document.title.replace(/[-_].*1688.*/i, "")
  );
}

function pickOfferId(url) {
  const match = url.match(/offer\/(\d+)\.html/i) || url.match(/[?&]offerId=(\d+)/i);
  return match?.[1] || null;
}

function pickMainImage() {
  const metaImage =
    document.querySelector("meta[property='og:image']")?.getAttribute("content") ||
    document.querySelector("meta[name='og:image']")?.getAttribute("content");
  if (metaImage) return normalizeUrl(metaImage);

  const image = [
    "[class*='main'] img",
    "[class*='gallery'] img",
    "[class*='image'] img",
    "img",
  ]
    .flatMap((selector) => Array.from(document.querySelectorAll(selector)))
    .map((img) => img.currentSrc || img.src || img.getAttribute("data-src"))
    .map(normalizeUrl)
    .find((src) => src && !src.includes("data:image") && !src.includes("icon"));

  return image || null;
}

function pickPrice() {
  const text = pickPriceText();
  const numbers = parseNumbers(text);
  return numbers[0] ?? null;
}

function pickPriceRange() {
  const text = pickPriceText();
  const numbers = parseNumbers(text);
  if (numbers.length >= 2) return `¥${numbers[0]}-¥${numbers[1]}`;
  if (numbers.length === 1) return `¥${numbers[0]}`;
  return null;
}

function pickPriceText() {
  return cleanText(
    queryText([
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
    text.match(/(\d+)\s*(?:件|个|只|套)\s*起批/) ||
    text.match(/起批\s*(\d+)/) ||
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

function pickSkuList() {
  const containers = Array.from(
    document.querySelectorAll("[class*='sku'], [class*='Sku'], [class*='prop'], [class*='spec']")
  );
  const texts = containers
    .flatMap((container) => Array.from(container.querySelectorAll("button, li, span, div")))
    .map((element) => cleanText(element.textContent))
    .filter((text) => text && text.length <= 40 && !/价格|库存|起批|采购|数量/.test(text));

  return Array.from(new Set(texts)).slice(0, 40).map((text, index) => ({
    sku_id: String(index + 1),
    specs: { 规格: text },
  }));
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
  return String(value || "").replace(/\s+/g, " ").trim();
}

function parseNumbers(value) {
  return Array.from(String(value || "").matchAll(/\d+(?:\.\d+)?/g))
    .map((match) => Number(match[0]))
    .filter((number) => Number.isFinite(number));
}

function normalizeUrl(url) {
  if (!url) return null;
  if (url.startsWith("//")) return `https:${url}`;
  if (url.startsWith("/")) return `${location.origin}${url}`;
  return url;
}
