const API_BASE_URL = "http://127.0.0.1:8000";
const RETRY_DELAYS_MS = [0, 400, 1200, 2500];
const SITE_CONFIGS = [
  {
    sourceSite: "1688",
    label: "1688",
    pageName: "1688 商品详情页",
    messageType: "COLLECT_1688_PRODUCT",
    contentScript: "content.js",
    matches: (url) => /(^|\.)1688\.com$/i.test(safeUrl(url).hostname),
  },
  {
    sourceSite: "temu",
    label: "Temu",
    pageName: "Temu 商品详情页",
    messageType: "COLLECT_TEMU_PRODUCT_V2",
    contentScript: "temu_content.js",
    matches: (url) => /(^|\.)temu\.com$/i.test(safeUrl(url).hostname),
  },
];
const MODE_UI = {
  temu: {
    title: "Temu 商品采集",
    activeLabel: "当前监听商品",
    activeText: "未绑定，前端打开商品详情后会自动绑定",
    statusText: "打开 Temu 商品详情页后，采集标题、图片和 SKU，加入下方 Temu 商品素材。",
    addButtonText: "加入商品素材",
    listTitle: "商品素材",
    emptyText: "还没有采集商品素材。打开 Temu 或 1688 商品页后点击加入。",
    pageHint: "请先打开 Temu 商品详情页",
  },
  "1688": {
    title: "1688 货源采集",
    activeLabel: "当前监听商品",
    activeText: "未绑定，前端打开商品详情后会自动绑定",
    statusText: "打开 1688 商品详情页后，先预抓并加入采集列表，再从列表里选择加入位置。",
    addButtonText: "加入采集列表",
    listTitle: "商品素材",
    emptyText: "还没有采集商品素材。打开 Temu 或 1688 商品页后点击加入。",
    pageHint: "请先打开 1688 商品详情页",
  },
};

const statusEl = document.getElementById("status");
const titleEl = document.querySelector("h1");
const modeButtons = Array.from(document.querySelectorAll(".mode-tab"));
const activeProductLabelEl = document.getElementById("activeProductLabel");
const activeProductTextEl = document.getElementById("activeProductText");
const previewButtonEl = document.getElementById("previewButton");
const addCaptureListButtonEl = document.getElementById("addCaptureListButton");
const refreshListButtonEl = document.getElementById("refreshListButton");
const addSelectedProductButtonEl = document.getElementById("addSelectedProductButton");
const addSelectedMaterialButtonEl = document.getElementById("addSelectedMaterialButton");
const clearSelectionButtonEl = document.getElementById("clearSelectionButton");
const captureListTitleEl = document.getElementById("captureListTitle");
const captureListCountEl = document.getElementById("captureListCount");
const previewEl = document.getElementById("preview");
const captureListEl = document.getElementById("captureList");
const batchActionsEl = document.querySelector(".batch-actions");

let latestPayload = null;
let activeCollectToken = 0;
let activeSession = null;
let captureMaterials = [];
let selectedMaterialIds = new Set();
let processingMaterialIds = new Set();
let globalBusy = false;
let activeMode = "temu";

modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    void setActiveMode(button.dataset.mode || "temu", { refresh: true, manual: true });
  });
});

previewButtonEl.addEventListener("click", () => {
  void previewCurrentPage({ reason: "manual" });
});

addCaptureListButtonEl.addEventListener("click", () => {
  void addCurrentPageToCaptureList();
});

refreshListButtonEl.addEventListener("click", () => {
  void refreshCaptureList();
});

addSelectedProductButtonEl.addEventListener("click", () => {
  void addSelectedToProductList();
});

addSelectedMaterialButtonEl.addEventListener("click", () => {
  void assignSelectedToActiveProduct();
});

clearSelectionButtonEl.addEventListener("click", () => {
  selectedMaterialIds = new Set();
  renderCaptureList();
});

captureListEl.addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || !input.dataset.materialId) return;

  if (input.checked) {
    selectedMaterialIds.add(input.dataset.materialId);
  } else {
    selectedMaterialIds.delete(input.dataset.materialId);
  }
  updateBatchState();
});

captureListEl.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const button = event.target.closest("button[data-action][data-material-id]");
  if (!button) return;

  const materialId = button.dataset.materialId;
  if (!materialId) return;

  if (button.dataset.action === "add-product") {
    void runSingleMaterialAction(materialId, "加入商品列表", addMaterialToProductList, { refreshWorkbench: true });
  }
  if (button.dataset.action === "assign") {
    void runSingleMaterialAction(materialId, "加入商品货源素材", assignMaterialToActiveProduct);
  }
  if (button.dataset.action === "delete") {
    void deleteMaterialFromCaptureList(materialId);
  }
});

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type !== "ACTIVE_MARKETPLACE_TAB_CHANGED" && message?.type !== "ACTIVE_1688_TAB_CHANGED") return;

  void (async () => {
    if (message.sourceSite) {
      await setActiveMode(message.sourceSite, { refresh: false });
    }
    await previewCurrentPage({
      reason: "tab-changed",
      tab: {
        id: message.tabId,
        url: message.url || "",
        sourceSite: message.sourceSite || "",
      },
    });
  })();
});

document.addEventListener("DOMContentLoaded", () => {
  void initializePanel();
});

async function initializePanel() {
  await syncModeFromActiveTab();
  configureMode();
  await loadActiveSession();
  await previewCurrentPage({ reason: "init" });
  await loadCaptureList();
}

async function syncModeFromActiveTab() {
  const activeTab = await getActiveTab();
  const site = getSiteConfig(activeTab?.url || "");
  if (site) {
    activeMode = site.sourceSite;
  }
}

async function setActiveMode(mode, { refresh = false } = {}) {
  const nextMode = mode === "1688" ? "1688" : "temu";
  const changed = nextMode !== activeMode;
  activeMode = nextMode;
  configureMode();

  if (!changed && !refresh) return;

  latestPayload = null;
  selectedMaterialIds = new Set();
  processingMaterialIds = new Set();
  previewEl.hidden = true;
  await loadActiveSession();
  await loadCaptureList();

  if (refresh) {
    await previewCurrentPage({ reason: "manual" });
  }
}

function configureMode() {
  const ui = getActiveModeUi();
  titleEl.textContent = ui.title;
  activeProductLabelEl.textContent = ui.activeLabel;
  addCaptureListButtonEl.textContent = ui.addButtonText;
  captureListTitleEl.textContent = ui.listTitle;
  modeButtons.forEach((button) => {
    const selected = button.dataset.mode === activeMode;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });

  batchActionsEl.hidden = false;
  clearSelectionButtonEl.hidden = false;
  setStatus(ui.statusText, false);
}

async function loadActiveSession() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/active-session`, { credentials: "include" });
    if (!response.ok) throw new Error("读取当前商品失败");
    const body = await response.json();
    activeSession = body?.temu_product_id ? body : null;
    activeProductTextEl.textContent = activeSession?.title || getActiveModeUi().activeText;
    activeProductTextEl.title = activeSession?.title || "";
  } catch {
    activeSession = null;
    activeProductTextEl.textContent = "后端未连接或未绑定商品";
    activeProductTextEl.title = "";
  }
  updateBatchState();
  renderCaptureList();
}

async function previewCurrentPage({ reason, tab = null } = {}) {
  const token = Date.now();
  activeCollectToken = token;

  try {
    const payload = await collectCurrentPageWithRetry({ tab, token });
    latestPayload = payload;
    renderPreview(payload);
    const completeText = getCompletionHint(payload);
    const siteLabel = getSiteLabel(payload);
    const actionText = activeMode === "temu" ? "加入商品素材" : "加入采集列表";
    setStatus(
      reason === "manual"
        ? `已预抓当前 ${siteLabel} 页面。${completeText} 可以${actionText}。`
        : `已自动预抓当前 ${siteLabel} 页面。${completeText} 可以${actionText}。`,
      false
    );
  } catch (error) {
    if (reason === "tab-changed" || reason === "init") {
      setStatus(`${getActiveModeUi().pageHint}，侧边栏会自动预抓数据。`, false);
      return;
    }
    setStatus(error instanceof Error ? error.message : "预抓失败", true);
  }
}

async function addCurrentPageToCaptureList() {
  setBusy(true);
  setStatus(activeMode === "temu" ? "正在加入 Temu 商品素材..." : "正在加入采集列表...", false);

  try {
    const payload = await collectCurrentPageWithRetry();
    const material = await postJson(`${API_BASE_URL}/api/sourcing/1688/materials`, payload);
    latestPayload = material;
    selectedMaterialIds.add(material.id);
    renderPreview(material);
    await loadCaptureList();
    setStatus(
      activeMode === "temu"
        ? "已加入 Temu 商品素材。可以勾选后加入商品列表或作为货源素材绑定到当前商品。"
        : "已加入采集列表。可以在列表中勾选后加入商品列表或货源素材。",
      false
    );
  } catch (error) {
    setStatus(error instanceof Error ? error.message : getActiveModeUi().addButtonText + "失败", true);
  } finally {
    setBusy(false);
  }
}

async function refreshCaptureList() {
  setBusy(true);
  setStatus("正在刷新商品素材...", false);
  try {
    await loadCaptureList();
    setStatus("商品素材已刷新。", false);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "刷新商品素材失败", true);
  } finally {
    setBusy(false);
  }
}

async function loadCaptureList() {
  try {
    const body = await getJson(`${API_BASE_URL}/api/sourcing/1688/materials?limit=300`);
    captureMaterials = Array.isArray(body?.items) ? body.items : [];
    const existingIds = new Set(captureMaterials.map((item) => item.id));
    selectedMaterialIds = new Set([...selectedMaterialIds].filter((id) => existingIds.has(id)));
    renderCaptureList();
  } catch (error) {
    captureMaterials = [];
    renderCaptureList(error instanceof Error ? error.message : "读取商品素材失败");
  }
}

async function addSelectedToProductList() {
  const ids = [...selectedMaterialIds];
  if (!ids.length) return;
  await processMaterialIds(ids, "加入商品列表", addMaterialToProductList, { refreshWorkbench: true });
}

async function assignSelectedToActiveProduct() {
  const ids = [...selectedMaterialIds];
  if (!ids.length) return;
  await processMaterialIds(ids, "加入商品货源素材", assignMaterialToActiveProduct);
}

async function runSingleMaterialAction(materialId, actionName, worker, options = {}) {
  await processMaterialIds([materialId], actionName, worker, options);
}

async function processMaterialIds(materialIds, actionName, worker, options = {}) {
  setBusy(true);
  let successCount = 0;
  const failures = [];

  for (const materialId of materialIds) {
    processingMaterialIds.add(materialId);
    renderCaptureList();
    try {
      await worker(materialId);
      selectedMaterialIds.delete(materialId);
      successCount += 1;
    } catch (error) {
      failures.push(error instanceof Error ? error.message : `${actionName}失败`);
    } finally {
      processingMaterialIds.delete(materialId);
      renderCaptureList();
    }
  }

  await loadActiveSession();
  await loadCaptureList();
  const refreshedTabs = options.refreshWorkbench && successCount > 0 ? await refreshWorkbenchTabs() : 0;
  setBusy(false);

  if (failures.length) {
    setStatus(`${actionName}完成 ${successCount} 个，失败 ${failures.length} 个：${failures[0]}`, true);
    return;
  }
  setStatus(
    refreshedTabs > 0
      ? `${actionName}成功 ${successCount} 个，已刷新前端商品列表。`
      : `${actionName}成功 ${successCount} 个。`,
    false
  );
}

async function addMaterialToProductList(materialId) {
  await postJson(`${API_BASE_URL}/api/sourcing/1688/materials/${encodeURIComponent(materialId)}/add-to-products`);
}

async function refreshWorkbenchTabs() {
  try {
    const tabs = await chrome.tabs.query({});
    const workbenchTabs = tabs.filter((tab) => {
      const url = tab.url || "";
      return /^http:\/\/(?:127\.0\.0\.1|localhost):5173(?:\/|#|\?|$)/.test(url);
    });

    await Promise.all(
      workbenchTabs.map((tab) => (tab.id ? chrome.tabs.reload(tab.id) : Promise.resolve()))
    );
    return workbenchTabs.length;
  } catch {
    return 0;
  }
}

async function assignMaterialToActiveProduct(materialId) {
  if (!activeSession?.temu_product_id) {
    await loadActiveSession();
  }
  if (!activeSession?.temu_product_id) {
    throw new Error("请先在前端打开一个商品详情，让插件监听当前商品");
  }

  await postJson(`${API_BASE_URL}/api/sourcing/1688/materials/${encodeURIComponent(materialId)}/assign`, {
    temu_product_id: activeSession.temu_product_id,
  });
}

async function deleteMaterialFromCaptureList(materialId) {
  setBusy(true);
  processingMaterialIds.add(materialId);
  renderCaptureList();
  try {
    await deleteJson(`${API_BASE_URL}/api/sourcing/1688/materials/${encodeURIComponent(materialId)}`);
    selectedMaterialIds.delete(materialId);
    await loadCaptureList();
    setStatus("已从商品素材删除。", false);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "删除商品素材失败", true);
  } finally {
    processingMaterialIds.delete(materialId);
    setBusy(false);
  }
}

async function collectCurrentPageWithRetry({ tab = null, token = null } = {}) {
  const activeTab = tab ?? (await getActiveTab());
  const site = getSiteConfig(activeTab?.url || "");
  if (!activeTab?.id || !site || site.sourceSite !== activeMode) {
    throw new Error(getActiveModeUi().pageHint);
  }

  let lastPayload = null;
  let lastError = null;
  for (const delay of RETRY_DELAYS_MS) {
    if (delay > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, delay));
    }
    if (token && activeCollectToken !== token) {
      throw new Error("已切换到新的页面采集任务");
    }

    try {
      const rawPayload = await collectFromTab(activeTab.id, site);
      const enrichedPayload = site.sourceSite === "temu"
        ? await enrichTemuPayloadWithHybridScraper(activeTab.url || "", rawPayload)
        : rawPayload;
      const payload = normalizePayloadForBackend(enrichedPayload, site);
      lastPayload = payload;
      if (isPayloadComplete(payload)) {
        return payload;
      }
    } catch (error) {
      lastError = error;
    }
  }

  if (lastPayload) return lastPayload;
  throw lastError || new Error("当前页面无法采集");
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
}

async function collectFromTab(tabId, site) {
  try {
    return await sendCollectMessage(tabId, site);
  } catch {
    await chrome.scripting.executeScript({ target: { tabId }, files: [site.contentScript] });
    return sendCollectMessage(tabId, site);
  }
}

async function sendCollectMessage(tabId, site) {
  const extra = site.sourceSite === "temu" ? { mainWorldSnapshot: await collectTemuMainWorldSnapshot(tabId) } : {};
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, { type: site.messageType, ...extra }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "当前页面无法采集"));
        return;
      }
      resolve(response.payload);
    });
  });
}

function getSiteConfig(url) {
  return SITE_CONFIGS.find((site) => site.matches(url)) || null;
}

function getActiveModeUi() {
  return MODE_UI[activeMode] || MODE_UI.temu;
}

function normalizePayloadForBackend(payload, site) {
  if (site.sourceSite === "1688") {
    return {
      ...payload,
      raw_data: {
        ...(payload.raw_data || {}),
        source_site: "1688",
      },
    };
  }

  const priceInfo = normalizeMarketplacePriceInfo(
    payload.price && typeof payload.price === "object" ? payload.price : {},
    payload.price,
  );
  const title = cleanTemuTitle(payload.title || payload.productTitle || payload.name || "");
  const galleryImageUrls = Array.isArray(payload.gallery_image_urls)
    ? payload.gallery_image_urls
    : Array.isArray(payload.images?.all)
      ? payload.images.all
      : [];
  const skuList = Array.isArray(payload.sku?.skuList)
    ? payload.sku.skuList
    : Array.isArray(payload.sku_list)
      ? payload.sku_list
      : [];
  const numericPrice = parseMarketplacePrice(priceInfo.current || priceInfo.estimated || payload.price);
  const selectedOptions = payload.selected_options || payload.sku?.selected || {};
  const normalizedSkuList = normalizeTemuSkuListForSelectedOptions(skuList, selectedOptions, {
    price: numericPrice,
    imageUrl: payload.main_image_url || payload.images?.main || galleryImageUrls[0] || null,
  });

  return {
    offer_id: null,
    product_url: payload.product_url || payload.productUrl || payload.url || "",
    title,
    main_image_url: payload.main_image_url || payload.images?.main || galleryImageUrls[0] || null,
    price: numericPrice,
    price_range: priceInfo.current || priceInfo.estimated || null,
    moq: null,
    shop_name: payload.shop?.name || payload.storeName || null,
    shop_url: payload.shop?.url || payload.storeUrl || null,
    sku_list: normalizedSkuList,
    captured_at: payload.captured_at || new Date().toISOString().slice(0, 19).replace("T", " "),
    raw_data: {
      source_site: "temu",
      goods_id: payload.goods_id || payload.id || null,
      price: priceInfo,
      category_path: payload.category_path || null,
      category_parts: payload.category_parts || [],
      gallery_image_urls: galleryImageUrls,
      product_image_count: galleryImageUrls.length,
      sku_text_count: normalizedSkuList.length,
      sku_image_count: normalizedSkuList.filter((sku) => sku?.image_url || sku?.imageUrl).length,
      selected_options: selectedOptions,
      is_no_attribute: payload.is_no_attribute ?? null,
    },
  };
}

function normalizeTemuSkuList(skuList) {
  return skuList.slice(0, 500).map((sku, index) => {
    const specs = normalizeTemuSkuSpecs(sku.specs && typeof sku.specs === "object" ? sku.specs : {});
    const fallbackSpecText = sku.name || sku.label || sku.value || `SKU ${index + 1}`;
    const skuId = sku.sku_id || sku.skuId || sku.skcId || sku.id || Object.values(specs).find(Boolean) || `temu-sku-${index + 1}`;
    return {
      sku_id: skuId,
      specs: Object.keys(specs).length ? specs : { 规格: fallbackSpecText },
      price: parseMarketplacePrice(sku.price || sku.salePrice || sku.currentPrice),
      stock: toOptionalNumber(sku.stock || sku.quantity || sku.inventory),
      image_url: sku.image_url || sku.imageUrl || sku.imgUrl || sku.thumbUrl || undefined,
    };
  });
}

function normalizeTemuSkuListForSelectedOptions(skuList, selectedOptions, context = {}) {
  const normalizedSkuList = normalizeTemuSkuList(skuList);
  const selectedSku = buildSelectedTemuSku(selectedOptions, context);
  if (selectedSku && (!normalizedSkuList.length || normalizedSkuList.every(isLowConfidenceTemuSku))) {
    return [selectedSku];
  }
  return normalizedSkuList;
}

function buildSelectedTemuSku(selectedOptions, context = {}) {
  const specs = normalizeTemuSkuSpecs(selectedOptions);
  const optionText = uniqueStrings(Object.values(specs).map((value) => String(value || "").trim())).join(" / ");
  if (!optionText) return null;
  return {
    sku_id: optionText,
    specs,
    price: context.price ?? undefined,
    image_url: context.imageUrl || undefined,
  };
}

function isLowConfidenceTemuSku(sku) {
  const skuId = String(sku?.sku_id || "");
  const specs = sku?.specs && typeof sku.specs === "object" ? sku.specs : {};
  const specKeys = Object.keys(specs);
  const specValues = Object.values(specs).map((value) => String(value || "").trim()).filter(Boolean);
  const genericId = /^(dom-|temu-sku-)\d+$/i.test(skuId);
  const genericKeys = !specKeys.length || specKeys.every((key) => /^(规格|option|value|name|label)$/i.test(key));
  const genericValues = !specValues.length || specValues.every((value) => /^sku\s*\d+$/i.test(value) || value.length <= 3);
  return genericId && genericKeys && genericValues;
}

function normalizeTemuSkuSpecs(specs) {
  const normalizedSpecs = {};
  for (const [key, value] of Object.entries(specs || {})) {
    const cleanValue = cleanTemuSkuSpecValue(value);
    const specKey = normalizeTemuSpecKey(key);
    if (!specKey || !cleanValue || specKey === "__purchase_qty") continue;
    if (specKey !== "规格" && normalizedSpecs["规格"] === cleanValue) delete normalizedSpecs["规格"];
    if (specKey === "规格" && Object.keys(normalizedSpecs).length) continue;
    normalizedSpecs[specKey] = cleanValue;
  }
  return normalizedSpecs;
}

function cleanTemuSkuSpecValue(value) {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\s+(?:Qty|QTY)\s*[:：]?\s*\d+.*$/i, "")
    .replace(/\s+[0-9][0-9.,Kk+]*\s*sold.*$/i, "")
    .replace(/\s*(Add to cart|Buy now|Free shipping|Order guarantee).*$/i, "")
    .trim();
}

function normalizeTemuSpecKey(key) {
  const raw = String(key ?? "").trim().replace(/[：:]/g, "");
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

function buildLinkListRecord(payload) {
  const raw = payload.raw_data || {};
  const sourceSite = raw.source_site === "temu" ? "temu" : "1688";
  const sourceId = sourceSite === "temu"
    ? (raw.goods_id || payload.offer_id || stableIdFromUrl(payload.product_url))
    : (payload.offer_id || stableIdFromUrl(payload.product_url));
  const recordId = `plugin-${sourceSite}-${sourceId}`;
  const createdAt = new Date().toISOString();
  const title = payload.title || `${getSiteLabel(payload)} 商品`;
  const galleryImageUrls = uniqueStrings([
    payload.main_image_url,
    ...(Array.isArray(raw.gallery_image_urls) ? raw.gallery_image_urls : []),
  ]);
  const mainImageUrl = payload.main_image_url || galleryImageUrls[0] || "";
  const sourceLinkId = `${recordId}-source-1`;
  const skuEntries = buildLinkListSkuEntries(payload, {
    recordId,
    sourceLinkId,
    sourceTitle: title,
    sourceUrl: payload.product_url,
  });
  const productMaterialImages = galleryImageUrls.slice(0, 24).map((imageUrl, index) => ({
    id: `${recordId}-material-image-${index + 1}`,
    role: "product-material",
    sourceUrl: imageUrl,
    displayUrl: imageUrl,
    alt: `${title} 素材图 ${index + 1}`,
  }));

  return {
    schemaVersion: 3,
    id: recordId,
    createdAt,
    productId: `${sourceSite}-${sourceId}`,
    productTitle: title,
    category: raw.category_path || payload.category_path || undefined,
    categoryPath: raw.category_path || payload.category_path || undefined,
    mainImage: {
      id: `${recordId}-main-image`,
      role: "product-main",
      sourceUrl: mainImageUrl,
      displayUrl: mainImageUrl,
      alt: title,
    },
    productMaterialImages,
    productImageUrl: mainImageUrl,
    productSourceUrl: payload.product_url,
    sourceLinks: [
      {
        id: sourceLinkId,
        title,
        productUrl: payload.product_url,
        shopName: payload.shop_name || undefined,
        shopUrl: payload.shop_url || undefined,
        imageUrl: mainImageUrl || undefined,
      },
    ],
    skuEntries,
    componentSkuCount: skuEntries.reduce((total, entry) => total + Math.max(1, entry.componentSkus.length), 0),
    rawCaptureSummary: {
      sourceSite,
      capturedAt: payload.captured_at,
      price: payload.price,
      priceRange: payload.price_range,
      skuCount: skuEntries.length,
      imageCount: galleryImageUrls.length,
    },
  };
}

function buildLinkListSkuEntries(payload, context) {
  const skuList = Array.isArray(payload.sku_list) ? payload.sku_list : [];
  const fallbackImageUrl = payload.main_image_url || payload.raw_data?.gallery_image_urls?.[0] || "";
  const items = skuList.length ? skuList : [{
    sku_id: "default",
    specs: { 规格: "默认款" },
    price: payload.price,
    image_url: fallbackImageUrl,
  }];

  return items.slice(0, 200).map((sku, index) => {
    const rawSpecs = sku.specs && typeof sku.specs === "object" ? stringifySpecObject(sku.specs) : {};
    const specText = specObjectToText(rawSpecs) || `SKU ${index + 1}`;
    const name = cleanSkuName(specText);
    const imageUrl = sku.image_url || fallbackImageUrl;
    const sourceSkuKey = JSON.stringify(rawSpecs) || sku.sku_id || `sku-${index + 1}`;
    const entryId = `${context.recordId}-sku-${index + 1}`;
    return {
      id: entryId,
      order: index + 1,
      kind: "single",
      name,
      imageUrl,
      price: parseMarketplacePrice(sku.price ?? payload.price) ?? undefined,
      weight: toOptionalNumber(sku.weight_kg || payload.raw_data?.weight_kg),
      sourceSkuLinks: [
        {
          sourceId: context.sourceLinkId,
          sourceTitle: context.sourceTitle,
          sourceProductUrl: context.sourceUrl,
          sourceSkuId: sku.sku_id || undefined,
          sourceSkuKey,
          specText,
          optionText: name,
          imageUrl,
        },
      ],
      componentSkus: [
        {
          name,
          specText,
          sourceId: context.sourceLinkId,
          sourceSkuId: sku.sku_id || undefined,
          sourceSkuKey,
          sourceTitle: context.sourceTitle,
          sourceUrl: context.sourceUrl,
          sourceImageUrl: imageUrl,
          imageUrl,
          rawSpecs,
        },
      ],
    };
  });
}

function linkRecordToCaptureItem(record) {
  const source = Array.isArray(record.sourceLinks) ? record.sourceLinks[0] || {} : {};
  const skuEntries = Array.isArray(record.skuEntries) ? record.skuEntries : [];
  const rawSummary = record.rawCaptureSummary || {};
  return {
    id: record.id,
    record_type: "link_record",
    offer_id: null,
    product_url: record.productSourceUrl || source.productUrl || "",
    title: record.productTitle || source.title || "链接列表商品",
    main_image_url: record.mainImage?.displayUrl || record.mainImage?.sourceUrl || record.productImageUrl || source.imageUrl || null,
    price: rawSummary.price ?? skuEntries.map((entry) => entry.price).find((value) => value !== undefined),
    price_range: rawSummary.priceRange || null,
    moq: null,
    shop_name: source.shopName || null,
    shop_url: source.shopUrl || null,
    sku_list: skuEntries.map((entry) => ({
      sku_id: entry.id,
      specs: { 规格: entry.name },
      price: entry.price,
      image_url: entry.imageUrl || entry.imageAsset?.displayUrl || entry.imageAsset?.sourceUrl,
      weight_kg: entry.weight,
    })),
    raw_data: {
      source_site: rawSummary.sourceSite || inferSourceSiteFromRecord(record),
      gallery_image_urls: collectRecordImageUrls(record),
      product_image_count: collectRecordImageUrls(record).length,
      sku_text_count: skuEntries.length,
      sku_image_count: skuEntries.filter((entry) => entry.imageUrl || entry.imageAsset?.displayUrl || entry.imageAsset?.sourceUrl).length,
      price: rawSummary.priceRange ? { displayText: rawSummary.priceRange, current: rawSummary.price } : undefined,
    },
    captured_at: rawSummary.capturedAt || record.createdAt,
    created_at: record.createdAt,
    updated_at: record.updatedAt || record.createdAt,
  };
}

function collectRecordImageUrls(record) {
  return uniqueStrings([
    record.mainImage?.displayUrl,
    record.mainImage?.sourceUrl,
    record.productImageUrl,
    ...(record.productMaterialImages || []).map((asset) => asset.displayUrl || asset.sourceUrl),
    ...(record.sourceLinks || []).map((source) => source.imageUrl),
    ...(record.skuEntries || []).map((entry) => entry.imageUrl || entry.imageAsset?.displayUrl || entry.imageAsset?.sourceUrl),
  ]);
}

function inferSourceSiteFromRecord(record) {
  const url = record.productSourceUrl || record.sourceLinks?.[0]?.productUrl || "";
  return /temu\.com/i.test(url) ? "temu" : "1688";
}

async function collectTemuMainWorldSnapshot(tabId) {
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: () => {
        const keyPattern = /temu|goods|product|sku|skc|apollo|redux|__next|raw|data|store/i;
        const valuePattern = /goods[_-]?id|goodsId|skuList|skcList|propertyList|product|price|image|title/i;
        const candidates = [];
        const keys = [];

        function safePreview(value, depth = 0, seen = new WeakSet()) {
          if (value == null) return value;
          const type = typeof value;
          if (type === "string" || type === "number" || type === "boolean") return value;
          if (type !== "object") return undefined;
          if (seen.has(value) || depth > 4) return undefined;
          seen.add(value);
          if (Array.isArray(value)) return value.slice(0, 60).map((item) => safePreview(item, depth + 1, seen));
          const output = {};
          for (const key of Object.keys(value).slice(0, 120)) {
            if (depth > 1 && !/goods|product|sku|skc|price|image|title|store|category|review|rating/i.test(key)) continue;
            try {
              const preview = safePreview(value[key], depth + 1, seen);
              if (preview !== undefined) output[key] = preview;
            } catch {
              // Ignore unreadable page properties.
            }
          }
          return output;
        }

        for (const key of Object.keys(window)) {
          if (!keyPattern.test(key)) continue;
          keys.push(key);
          try {
            const preview = safePreview(window[key]);
            const json = JSON.stringify(preview);
            if (json && valuePattern.test(json)) candidates.push({ key, json: json.slice(0, 250000) });
          } catch {
            // Ignore cyclic or restricted values.
          }
          if (candidates.length >= 20) break;
        }

        return { href: location.href, title: document.title, keys: keys.slice(0, 80), candidates };
      },
    });
    return result?.result || {};
  } catch {
    return {};
  }
}

async function enrichTemuPayloadWithHybridScraper(url, payload) {
  const pageSignals = payload?.raw_data?.page_signals || {
    url,
    title: payload?.title || "",
    goods_id: payload?.goods_id || payload?.id || "",
    image: payload?.main_image_url || payload?.images?.main || "",
    images: payload?.gallery_image_urls || payload?.images?.all || [],
    price: payload?.price || {},
    selectedOptions: payload?.selected_options || payload?.sku?.selected || {},
  };

  for (const baseUrl of ["http://localhost:3000", "http://127.0.0.1:3000"]) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 2500);
    try {
      const response = await fetch(`${baseUrl}/scrape`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          pageSignals,
          requestedAt: new Date().toISOString(),
          source: "temu_listing_workbench_extension",
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body.ok === false) continue;
      const serverPayload = body.data || body;
      if (serverPayload && typeof serverPayload === "object") {
        return mergeTemuPayload(payload, serverPayload, baseUrl);
      }
    } catch {
      // The optional hybrid scraper server is not required; browser collection still works.
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  return payload;
}

function mergeTemuPayload(localPayload, serverPayload, scraperBaseUrl) {
  const localImages = Array.isArray(localPayload?.gallery_image_urls)
    ? localPayload.gallery_image_urls
    : Array.isArray(localPayload?.images?.all)
      ? localPayload.images.all
      : [];
  const serverImages = Array.isArray(serverPayload?.images?.all)
    ? serverPayload.images.all
    : Array.isArray(serverPayload?.additionalImages)
      ? serverPayload.additionalImages
      : [];
  const images = uniqueStrings([
    serverPayload?.images?.main,
    serverPayload?.imageUrl,
    ...serverImages,
    localPayload?.main_image_url,
    localPayload?.images?.main,
    ...localImages,
  ]);
  const localSkuList = Array.isArray(localPayload?.sku?.skuList) ? localPayload.sku.skuList : [];
  const serverSkuList = Array.isArray(serverPayload?.sku?.skuList)
    ? serverPayload.sku.skuList
    : Array.isArray(serverPayload?.skuList)
      ? serverPayload.skuList
      : [];

  return {
    ...localPayload,
    ...serverPayload,
    title: cleanTemuTitle(textOr(serverPayload?.title, localPayload?.title, serverPayload?.productTitle, serverPayload?.name)),
    product_url: textOr(localPayload?.product_url, localPayload?.productUrl, serverPayload?.productUrl, serverPayload?.url),
    productUrl: textOr(localPayload?.productUrl, localPayload?.product_url, serverPayload?.productUrl, serverPayload?.url),
    main_image_url: images[0] || localPayload?.main_image_url || serverPayload?.imageUrl || "",
    gallery_image_urls: images,
    images: {
      ...(localPayload?.images || {}),
      ...(serverPayload?.images || {}),
      main: images[0] || localPayload?.images?.main || serverPayload?.images?.main || "",
      all: images,
    },
    price: serverPayload?.price || localPayload?.price || {},
    sku: {
      ...(localPayload?.sku || {}),
      ...(serverPayload?.sku || {}),
      skuList: serverSkuList.length ? serverSkuList : localSkuList,
      propertyList: serverPayload?.sku?.propertyList || serverPayload?.propertyList || localPayload?.sku?.propertyList || [],
      skcList: serverPayload?.sku?.skcList || serverPayload?.skcList || localPayload?.sku?.skcList || [],
      selected: serverPayload?.sku?.selected || localPayload?.sku?.selected || localPayload?.selected_options || {},
    },
    raw_data: {
      ...(localPayload?.raw_data || {}),
      hybrid_scraper: {
        used: true,
        base_url: scraperBaseUrl,
        sku_count: serverSkuList.length,
        image_count: images.length,
      },
    },
  };
}

async function getJson(url) {
  const response = await apiFetch(url, { credentials: "include" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "工作台接口请求失败");
  }
  return response.json();
}

async function postJson(url, payload) {
  const response = await apiFetch(url, {
    method: "POST",
    credentials: "include",
    headers: payload ? { "Content-Type": "application/json" } : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "工作台接口请求失败");
  }
  return response.json();
}

async function deleteJson(url) {
  const response = await apiFetch(url, { method: "DELETE", credentials: "include" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "工作台接口请求失败");
  }
  return response.json();
}

async function apiFetch(url, options) {
  try {
    return await fetch(url, options);
  } catch (_error) {
    throw new Error("后端未连接，请先启动 127.0.0.1:8000");
  }
}

function isPayloadComplete(payload) {
  const raw = payload?.raw_data || {};
  if (raw.source_site === "temu") {
    return Boolean(payload?.title && (payload?.main_image_url || raw.gallery_image_urls?.length || raw.goods_id));
  }
  return Boolean(payload?.title && (payload?.price || raw.unit_price_with_shipping) && raw.weight_kg);
}

function getCompletionHint(payload) {
  const raw = payload?.raw_data || {};
  if (raw.source_site === "temu") {
    const imageCount = raw.product_image_count || raw.gallery_image_urls?.length || 0;
    const skuCount = payload?.sku_list?.length || raw.sku_text_count || 0;
    return `Temu 标题、图片${imageCount ? ` ${imageCount} 张` : ""}${skuCount ? `、SKU ${skuCount} 个` : ""}已抓取。`;
  }
  if (raw.unit_price_with_shipping && raw.weight_kg) return "价格、运费和重量都已抓到。";
  if (raw.unit_price_with_shipping && !raw.weight_kg) return "价格已抓到，重量可能需要页面继续渲染后重试。";
  return "如果价格或重量为空，可以停留 1 到 2 秒后点“预抓当前页”。";
}

function setBusy(isBusy) {
  globalBusy = isBusy;
  previewButtonEl.disabled = isBusy;
  addCaptureListButtonEl.disabled = isBusy;
  refreshListButtonEl.disabled = isBusy;
  updateBatchState();
  renderCaptureList();
}

function updateBatchState() {
  const selectedCount = selectedMaterialIds.size;
  captureListCountEl.textContent = String(captureMaterials.length);

  addSelectedProductButtonEl.textContent = selectedCount
    ? `加入选中到商品列表 (${selectedCount})`
    : "加入选中到商品列表";
  addSelectedMaterialButtonEl.textContent = selectedCount
    ? `加入选中为货源素材 (${selectedCount})`
    : "加入选中为货源素材";

  addSelectedProductButtonEl.disabled = globalBusy || selectedCount === 0;
  addSelectedMaterialButtonEl.disabled = globalBusy || selectedCount === 0 || !activeSession?.temu_product_id;
  clearSelectionButtonEl.disabled = globalBusy || selectedCount === 0;
}

function setStatus(text, isError) {
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#dc2626" : "#64748b";
}

function renderPreview(candidate) {
  const raw = candidate.raw_data || {};
  const siteLabel = getSiteLabel(candidate);
  const isTemu = raw.source_site === "temu";
  const imageCount = raw.product_image_count || raw.gallery_image_urls?.length || (candidate.main_image_url ? 1 : 0);
  const skuCount = candidate.sku_list?.length || 0;
  const skuImageCount = candidate.sku_list?.filter((sku) => sku.image_url).length || 0;
  previewEl.hidden = false;
  previewEl.innerHTML = `
    <div class="preview-layout">
      ${candidate.main_image_url ? `<img src="${escapeHtml(candidate.main_image_url)}" alt="">` : `<div class="preview-image-empty">${escapeHtml(siteLabel)}</div>`}
      <div>
        <div class="preview-title">${escapeHtml(candidate.title || `${siteLabel} 商品`)}</div>
        <div class="preview-meta">来源：${escapeHtml(siteLabel)} · 价格：${escapeHtml(formatMarketplaceMoney(candidate.price ?? raw.goods_price, raw))}</div>
        ${isTemu ? "" : `<div class="preview-meta">含运费：${escapeHtml(formatMoney(raw.unit_price_with_shipping))} · 重量：${escapeHtml(formatWeight(raw.weight_kg))}</div>`}
        <div class="preview-meta">图片 ${escapeHtml(imageCount)} · SKU ${escapeHtml(skuCount)} · SKU 图 ${escapeHtml(skuImageCount)}</div>
      </div>
    </div>
  `;
}

function renderCaptureList(errorText = "") {
  updateBatchState();

  if (errorText) {
    captureListEl.innerHTML = `<div class="empty error">${escapeHtml(errorText)}</div>`;
    return;
  }

  if (!captureMaterials.length) {
    captureListEl.innerHTML = `<div class="empty">${escapeHtml(getActiveModeUi().emptyText)}</div>`;
    return;
  }

  const temuMaterials = captureMaterials.filter((item) => getItemSourceSite(item) === "temu");
  const source1688Materials = captureMaterials.filter((item) => getItemSourceSite(item) !== "temu");
  captureListEl.innerHTML = [
    renderMaterialSection("Temu 商品素材", temuMaterials, "temu"),
    renderMaterialSection("1688 货源素材", source1688Materials, "1688"),
  ].filter(Boolean).join("");
}

function renderMaterialSection(title, items, sourceSite) {
  if (!items.length) return "";
  return `
    <section class="material-section material-section-${escapeHtml(sourceSite)}">
      <div class="material-section-head">
        <span>${escapeHtml(title)}</span>
        <span>${escapeHtml(items.length)}</span>
      </div>
      <div class="material-section-list">
        ${items.map(renderCaptureListItem).join("")}
      </div>
    </section>
  `;
}

function renderCaptureListItem(item) {
  const raw = item.raw_data || {};
  const selected = selectedMaterialIds.has(item.id);
  const processing = processingMaterialIds.has(item.id);
  const isLinkRecord = item.record_type === "link_record";
  const showSelect = !isLinkRecord;
  const productAdded = Boolean(item.product_list_product_id);
  const assignedToActive = Boolean(activeSession?.temu_product_id && item.assigned_product_id === activeSession.temu_product_id);
  const assignDisabled = globalBusy || processing || !activeSession?.temu_product_id || assignedToActive;
  const productDisabled = globalBusy || processing || productAdded;
  const deleteDisabled = globalBusy || processing;
  const image = item.main_image_url || raw.gallery_image_urls?.[0] || "";
  const skuCount = item.sku_list?.length || 0;
  const siteLabel = getSiteLabel(item);
  const sourceSite = getItemSourceSite(item);
  const sourceTag = sourceSite === "temu" ? "Temu 商品素材" : "1688 货源素材";

  return `
    <article class="material-card ${showSelect ? "" : "material-card-no-check"} ${selected ? "material-card-selected" : ""}">
      ${showSelect ? `<label class="material-check" title="选择该采集商品">
        <input
          ${selected ? "checked" : ""}
          ${globalBusy ? "disabled" : ""}
          data-material-id="${escapeHtml(item.id)}"
          type="checkbox"
        />
        <span></span>
      </label>` : ""}
      ${image ? `<img src="${escapeHtml(image)}" alt="">` : `<div class="material-image-empty">${escapeHtml(siteLabel)}</div>`}
      <div class="material-copy">
        <div class="material-title">${escapeHtml(item.title || `${siteLabel} 商品`)}</div>
        <div class="preview-meta">${escapeHtml(siteLabel)} · ${escapeHtml(item.shop_name || "未知店铺")} · ${escapeHtml(formatMarketplaceMoney(item.price ?? raw.goods_price, raw))} · SKU ${escapeHtml(skuCount)}</div>
        <div class="material-tags">
          <span class="material-tag ${sourceSite === "temu" ? "material-tag-blue" : ""}">${escapeHtml(sourceTag)}</span>
          ${isLinkRecord ? `<span class="material-tag material-tag-success">已进链接列表</span>` : productAdded ? `<span class="material-tag material-tag-success">已进商品列表</span>` : `<span class="material-tag">待入商品列表</span>`}
          ${isLinkRecord ? `<span class="material-tag material-tag-blue">待 AI 属性</span>` : item.assigned_product_id ? `<span class="material-tag material-tag-blue">${assignedToActive ? "已加当前货源" : "已加货源素材"}</span>` : `<span class="material-tag">待加货源</span>`}
        </div>
        <div class="material-card-actions">
          ${isLinkRecord ? "" : `<button
              ${productDisabled ? "disabled" : ""}
              class="mini-button"
              data-action="add-product"
              data-material-id="${escapeHtml(item.id)}"
              type="button"
            >${productAdded ? "已加入商品" : "加入商品列表"}</button>
            <button
              ${assignDisabled ? "disabled" : ""}
              class="mini-button secondary-mini"
              data-action="assign"
              data-material-id="${escapeHtml(item.id)}"
              type="button"
            >${assignedToActive ? "已加当前货源" : "加入货源素材"}</button>`}
          <button
            ${deleteDisabled ? "disabled" : ""}
            class="mini-button danger-mini"
            data-action="delete"
            data-material-id="${escapeHtml(item.id)}"
            type="button"
          >删除</button>
        </div>
      </div>
    </article>
  `;
}

function formatMoney(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `¥${number.toFixed(2)}` : "待采集";
}

function formatMarketplaceMoney(value, raw = {}) {
  if (raw.source_site === "temu") {
    const display = cleanMarketplacePriceText(raw.price?.current || raw.price?.estimated || raw.price?.displayText);
    if (display) return display;
    const number = Number(value);
    return Number.isFinite(number) ? String(number) : "待采集";
  }
  return formatMoney(value);
}

function formatWeight(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? `${number} kg` : "待采集";
}

function getSiteLabel(candidate) {
  const sourceSite = getItemSourceSite(candidate);
  if (sourceSite === "temu") return "Temu";
  if (sourceSite === "1688") return "1688";
  const url = candidate?.product_url || "";
  const site = getSiteConfig(url);
  return site?.label || "1688";
}

function getItemSourceSite(candidate) {
  const sourceSite = candidate?.raw_data?.source_site || candidate?.source_site || "";
  if (sourceSite === "temu" || sourceSite === "1688") return sourceSite;
  const url = candidate?.product_url || "";
  if (/temu\.com/i.test(url)) return "temu";
  return "1688";
}

function parseMarketplacePrice(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const match = String(value).replace(/,/g, "").match(/([0-9]+(?:\.[0-9]+)?)/);
  return match ? Number(match[1]) : null;
}

function cleanMarketplacePriceText(value) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "number") return Number.isFinite(value) ? `$${value.toFixed(2)}` : "";
  const match = String(value)
    .replace(/\s+/g, " ")
    .match(/(?:US\$|\$|USD|￥|¥|CN¥|CN楼|楼)\s*[0-9]+(?:[.,][0-9]{1,2})?/i);
  return match ? match[0].replace(/\s+/g, "") : "";
}

function cleanTemuTitle(value) {
  const original = normalizeWhitespace(value);
  if (!original) return "";
  const cleaned = original
    .replace(/\s*\|\s*Temu.*$/i, "")
    .replace(/^Temu\s*\|\s*/i, "")
    .replace(/^(?:No import charges\s*)?(?:Local warehouse\s*[-–—]\s*)?Fastest delivery:\s*\d+\s*BUSINESS\s*DAYS?\s*/i, "")
    .replace(/^Fastest delivery:\s*\d+\s*BUSINESS\s*DAYS?\s*/i, "")
    .replace(/^(?:No import charges\s*)?Local warehouse\s*[-–—]\s*/i, "")
    .replace(/\s*(?:US\$|\$|USD|CNY|CN¥)\s*[0-9]+(?:[.,][0-9]{1,2})?.*$/i, "")
    .replace(/\s*(?:LAST DAY|ALMOST SOLD OUT|after applying promos|Pay\s*\$|OFF\b|Klarna|Afterpay).*$/i, "");
  return normalizeWhitespace(cleaned) || original;
}

function normalizeMarketplacePriceInfo(priceInfo = {}, fallbackPrice = undefined) {
  const current = cleanMarketplacePriceText(priceInfo.current || priceInfo.salePrice || priceInfo.price || fallbackPrice);
  const estimated = cleanMarketplacePriceText(priceInfo.estimated || priceInfo.estimatedPrice);
  const original = cleanMarketplacePriceText(priceInfo.original || priceInfo.originalPrice || priceInfo.marketPrice);
  const displayText = current || estimated || original || cleanMarketplacePriceText(priceInfo.displayText);
  return {
    ...priceInfo,
    current,
    original,
    estimated,
    displayText,
  };
}

function stringifySpecObject(specs) {
  const output = {};
  for (const [key, value] of Object.entries(specs || {})) {
    const cleanKey = String(key || "").trim();
    const cleanValue = String(value || "").trim();
    if (cleanKey && cleanValue) output[cleanKey] = cleanValue;
  }
  return output;
}

function specObjectToText(specs) {
  return Object.entries(specs || {})
    .map(([key, value]) => `${key}: ${value}`)
    .join(" / ");
}

function cleanSkuName(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > 120 ? `${text.slice(0, 117)}...` : text || "默认款";
}

function textOr(...values) {
  for (const value of values) {
    const text = normalizeWhitespace(value);
    if (text) return text;
  }
  return "";
}

function normalizeWhitespace(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function uniqueStrings(values) {
  const result = [];
  const seen = new Set();
  for (const value of values || []) {
    const text = String(value || "").trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    result.push(text);
  }
  return result;
}

function stableIdFromUrl(url) {
  const text = String(url || "").trim();
  const temuId = text.match(/[?&](?:goods_id|goodsId)=([0-9A-Za-z_-]+)/)?.[1];
  const offerId = text.match(/offer\/(\d+)\.html/i)?.[1];
  if (temuId || offerId) return temuId || offerId;
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) >>> 0;
  }
  return hash ? String(hash) : String(Date.now());
}

function toOptionalNumber(value) {
  if (value === null || value === undefined || value === "") return undefined;
  const number = Number(String(value).replace(/[^0-9.-]+/g, ""));
  return Number.isFinite(number) ? number : undefined;
}

function safeUrl(url) {
  try {
    return new URL(url || "about:blank");
  } catch {
    return new URL("about:blank");
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
