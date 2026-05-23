const API_BASE_URL = "http://127.0.0.1:8000";

const statusEl = document.getElementById("status");
const buttonEl = document.getElementById("captureButton");
const previewEl = document.getElementById("preview");

buttonEl.addEventListener("click", async () => {
  setStatus("正在采集当前页面...", false);
  buttonEl.disabled = true;

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !tab.url?.includes("1688.com")) {
      throw new Error("请先打开 1688 商品详情页");
    }

    const payload = await collectFromTab(tab.id);
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
    renderPreview(saved);
    setStatus("采集成功，工作台抽屉会自动刷新。", false);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "采集失败", true);
  } finally {
    buttonEl.disabled = false;
  }
});

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

function setStatus(text, isError) {
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#dc2626" : "#64748b";
}

function renderPreview(candidate) {
  previewEl.hidden = false;
  previewEl.innerHTML = `
    ${candidate.main_image_url ? `<img src="${escapeHtml(candidate.main_image_url)}" alt="">` : ""}
    <div class="preview-title">${escapeHtml(candidate.title || "1688 商品")}</div>
    <div class="preview-meta">价格：${escapeHtml(candidate.price_range || candidate.price || "待采集")}</div>
    <div class="preview-meta">SKU：${candidate.sku_list?.length || 0}</div>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
