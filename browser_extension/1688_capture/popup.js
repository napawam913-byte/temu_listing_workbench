const API_BASE_URL = "http://127.0.0.1:8000";
const RETRY_DELAYS_MS = [0, 400, 1200, 2500];

const statusEl = document.getElementById("status");
const activeProductTextEl = document.getElementById("activeProductText");
const previewButtonEl = document.getElementById("previewButton");
const addCaptureListButtonEl = document.getElementById("addCaptureListButton");
const refreshListButtonEl = document.getElementById("refreshListButton");
const addSelectedProductButtonEl = document.getElementById("addSelectedProductButton");
const addSelectedMaterialButtonEl = document.getElementById("addSelectedMaterialButton");
const clearSelectionButtonEl = document.getElementById("clearSelectionButton");
const captureListCountEl = document.getElementById("captureListCount");
const previewEl = document.getElementById("preview");
const captureListEl = document.getElementById("captureList");

let latestPayload = null;
let activeCollectToken = 0;
let activeSession = null;
let captureMaterials = [];
let selectedMaterialIds = new Set();
let processingMaterialIds = new Set();
let globalBusy = false;

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
  if (message?.type !== "ACTIVE_1688_TAB_CHANGED") return;

  void previewCurrentPage({
    reason: "tab-changed",
    tab: {
      id: message.tabId,
      url: message.url || "",
    },
  });
});

document.addEventListener("DOMContentLoaded", () => {
  void loadActiveSession();
  void previewCurrentPage({ reason: "init" });
  void loadCaptureList();
});

async function loadActiveSession() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/active-session`);
    if (!response.ok) throw new Error("读取当前商品失败");
    const body = await response.json();
    activeSession = body?.temu_product_id ? body : null;
    activeProductTextEl.textContent = activeSession?.title || "未绑定，前端打开商品详情后会自动绑定";
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
    setStatus(
      reason === "manual"
        ? `已预抓当前页。${completeText} 可以加入采集列表。`
        : `已自动预抓当前 1688 页面。${completeText} 可以加入采集列表。`,
      false
    );
  } catch (error) {
    if (reason === "tab-changed" || reason === "init") {
      setStatus("请打开 1688 商品详情页，侧边栏会自动预抓数据。", false);
      return;
    }
    setStatus(error instanceof Error ? error.message : "预抓失败", true);
  }
}

async function addCurrentPageToCaptureList() {
  setBusy(true);
  setStatus("正在加入采集列表...", false);

  try {
    const payload = await collectCurrentPageWithRetry();
    const material = await postJson(`${API_BASE_URL}/api/sourcing/1688/materials`, payload);
    latestPayload = material;
    selectedMaterialIds.add(material.id);
    renderPreview(material);
    await loadCaptureList();
    setStatus("已加入采集列表。可以在列表中勾选后加入商品列表或货源素材。", false);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "加入采集列表失败", true);
  } finally {
    setBusy(false);
  }
}

async function refreshCaptureList() {
  setBusy(true);
  setStatus("正在刷新采集列表...", false);
  try {
    await loadCaptureList();
    setStatus("采集列表已刷新。", false);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "刷新采集列表失败", true);
  } finally {
    setBusy(false);
  }
}

async function loadCaptureList() {
  try {
    const body = await getJson(`${API_BASE_URL}/api/sourcing/1688/materials?limit=100`);
    captureMaterials = Array.isArray(body?.items) ? body.items : [];
    const existingIds = new Set(captureMaterials.map((item) => item.id));
    selectedMaterialIds = new Set([...selectedMaterialIds].filter((id) => existingIds.has(id)));
    renderCaptureList();
  } catch (error) {
    captureMaterials = [];
    renderCaptureList(error instanceof Error ? error.message : "读取采集列表失败");
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
    setStatus("已从采集列表删除。", false);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "删除采集商品失败", true);
  } finally {
    processingMaterialIds.delete(materialId);
    setBusy(false);
  }
}

async function collectCurrentPageWithRetry({ tab = null, token = null } = {}) {
  const activeTab = tab ?? (await getActiveTab());
  if (!activeTab?.id || !activeTab.url?.includes("1688.com")) {
    throw new Error("请先打开 1688 商品详情页");
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
      const payload = await collectFromTab(activeTab.id);
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

async function collectFromTab(tabId) {
  try {
    return await sendCollectMessage(tabId);
  } catch {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    return sendCollectMessage(tabId);
  }
}

function sendCollectMessage(tabId) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, { type: "COLLECT_1688_PRODUCT" }, (response) => {
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

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "工作台接口请求失败");
  }
  return response.json();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
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
  const response = await fetch(url, { method: "DELETE" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "工作台接口请求失败");
  }
  return response.json();
}

function isPayloadComplete(payload) {
  const raw = payload?.raw_data || {};
  return Boolean(payload?.title && (payload?.price || raw.unit_price_with_shipping) && raw.weight_kg);
}

function getCompletionHint(payload) {
  const raw = payload?.raw_data || {};
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
  previewEl.hidden = false;
  previewEl.innerHTML = `
    <div class="preview-layout">
      ${candidate.main_image_url ? `<img src="${escapeHtml(candidate.main_image_url)}" alt="">` : `<div class="preview-image-empty">1688</div>`}
      <div>
        <div class="preview-title">${escapeHtml(candidate.title || "1688 商品")}</div>
        <div class="preview-meta">货值：${escapeHtml(formatMoney(candidate.price ?? raw.goods_price))}</div>
        <div class="preview-meta">运费：${escapeHtml(formatMoney(raw.shipping_fee))}</div>
        <div class="preview-meta">含运费单件：${escapeHtml(formatMoney(raw.unit_price_with_shipping))}</div>
        <div class="preview-meta">重量：${escapeHtml(formatWeight(raw.weight_kg))}</div>
        <div class="preview-meta">商品图片：${escapeHtml(raw.product_image_count || raw.gallery_image_urls?.length || (candidate.main_image_url ? 1 : 0))}</div>
        <div class="preview-meta">SKU：${candidate.sku_list?.length || 0}</div>
        <div class="preview-meta">SKU 图片：${candidate.sku_list?.filter((sku) => sku.image_url).length || 0}</div>
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
    captureListEl.innerHTML = `<div class="empty">还没有采集商品。打开 1688 商品页后点击“加入采集列表”。</div>`;
    return;
  }

  captureListEl.innerHTML = captureMaterials.map(renderCaptureListItem).join("");
}

function renderCaptureListItem(item) {
  const raw = item.raw_data || {};
  const selected = selectedMaterialIds.has(item.id);
  const processing = processingMaterialIds.has(item.id);
  const productAdded = Boolean(item.product_list_product_id);
  const assignedToActive = Boolean(activeSession?.temu_product_id && item.assigned_product_id === activeSession.temu_product_id);
  const assignDisabled = globalBusy || processing || !activeSession?.temu_product_id || assignedToActive;
  const productDisabled = globalBusy || processing || productAdded;
  const deleteDisabled = globalBusy || processing;
  const image = item.main_image_url || raw.gallery_image_urls?.[0] || "";
  const skuCount = item.sku_list?.length || 0;

  return `
    <article class="material-card ${selected ? "material-card-selected" : ""}">
      <label class="material-check" title="选择该采集商品">
        <input
          ${selected ? "checked" : ""}
          ${globalBusy ? "disabled" : ""}
          data-material-id="${escapeHtml(item.id)}"
          type="checkbox"
        />
        <span></span>
      </label>
      ${image ? `<img src="${escapeHtml(image)}" alt="">` : `<div class="material-image-empty">1688</div>`}
      <div class="material-copy">
        <div class="material-title">${escapeHtml(item.title || "1688 商品")}</div>
        <div class="preview-meta">${escapeHtml(item.shop_name || "未知店铺")} · ${escapeHtml(formatMoney(item.price ?? raw.goods_price))} · SKU ${escapeHtml(skuCount)}</div>
        <div class="material-tags">
          ${productAdded ? `<span class="material-tag material-tag-success">已进商品列表</span>` : `<span class="material-tag">待入商品列表</span>`}
          ${item.assigned_product_id ? `<span class="material-tag material-tag-blue">${assignedToActive ? "已加当前货源" : "已加货源素材"}</span>` : `<span class="material-tag">待加货源</span>`}
        </div>
        <div class="material-card-actions">
          <button
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
          >${assignedToActive ? "已加当前货源" : "加入货源素材"}</button>
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

function formatWeight(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? `${number} kg` : "待采集";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
