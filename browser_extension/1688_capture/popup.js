const API_BASE_URL = "http://127.0.0.1:8000";
const RETRY_DELAYS_MS = [0, 400, 1200, 2500];

const statusEl = document.getElementById("status");
const previewButtonEl = document.getElementById("previewButton");
const captureButtonEl = document.getElementById("captureButton");
const previewEl = document.getElementById("preview");

let latestPayload = null;
let latestTabUrl = "";
let activeCollectToken = 0;

previewButtonEl.addEventListener("click", () => {
  void previewCurrentPage({ reason: "manual" });
});

captureButtonEl.addEventListener("click", async () => {
  setBusy(true);
  setStatus("正在采集并发送到工作台...", false);

  try {
    const payload = await collectCurrentPageWithRetry();
    const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "发送到工作台失败");
    }

    const saved = await response.json();
    latestPayload = saved;
    renderPreview(saved);
    setStatus("采集成功，工作台抽屉会自动刷新。", false);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "采集失败", true);
  } finally {
    setBusy(false);
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
  void previewCurrentPage({ reason: "init" });
});

async function previewCurrentPage({ reason, tab = null } = {}) {
  const token = Date.now();
  activeCollectToken = token;

  try {
    const payload = await collectCurrentPageWithRetry({ tab, token });
    latestPayload = payload;
    latestTabUrl = payload.product_url;
    renderPreview(payload);
    const completeText = getCompletionHint(payload);
    setStatus(
      reason === "manual" ? `已预抓当前页。${completeText}` : `已自动预抓当前 1688 页面。${completeText}`,
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
  previewButtonEl.disabled = isBusy;
  captureButtonEl.disabled = isBusy;
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
      ${candidate.main_image_url ? `<img src="${escapeHtml(candidate.main_image_url)}" alt="">` : ""}
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

  captureButtonEl.textContent =
    latestPayload?.id || candidate.product_url !== latestTabUrl ? "采集到工作台" : "确认采集到工作台";
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
