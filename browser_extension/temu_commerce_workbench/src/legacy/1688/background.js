const DETAIL_URL_PATTERN = /^https:\/\/(?:detail\.)?1688\.com\//i;
const IMPORT_STORAGE_KEY = "latestImportedProductCard";
const NOTIFY_COOLDOWN_MS = 250;

const lastNotifyByTab = new Map();

function is1688DetailPage(url) {
  return DETAIL_URL_PATTERN.test(url || "");
}

function normalizeImportedPayload(payload) {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const normalized = {
    type: "product-card-transfer",
    name: String(payload.name || "").trim(),
    skc: String(payload.skc || "").trim(),
    quoted_price: String(payload.quoted_price || "").trim(),
    image_url: String(payload.image_url || "").trim(),
    source: String(payload.source || "t2-preview-html").trim(),
    sent_at: String(payload.sent_at || new Date().toISOString()).trim()
  };

  if (!normalized.name || !normalized.skc || !normalized.quoted_price || !normalized.image_url) {
    return null;
  }

  return normalized;
}

function normalizeImportEntry(message) {
  const flag = String(message?.flag || "").trim();
  const payload = normalizeImportedPayload(message?.payload);
  if (!flag || !payload) {
    return null;
  }

  return { flag, payload };
}

async function saveLatestImportedEntry(entry) {
  await chrome.storage.local.set({
    [IMPORT_STORAGE_KEY]: entry
  });
}

async function getLatestImportedEntry() {
  const result = await chrome.storage.local.get(IMPORT_STORAGE_KEY);
  return result[IMPORT_STORAGE_KEY] ?? null;
}

async function notifyImportedEntry(entry) {
  try {
    await chrome.runtime.sendMessage({
      type: "import-product-card",
      entry
    });
  } catch (_error) {
    // Side panel may not be open yet. The latest entry remains in storage.
  }
}

async function enableSidePanel(tabId) {
  try {
    await chrome.sidePanel.setOptions({
      tabId,
      path: "popup.html",
      enabled: true
    });
  } catch (_error) {
    // Ignore tabs that reject side panel options.
  }
}

async function notifyPanel(tabId, url) {
  if (!is1688DetailPage(url)) {
    return;
  }

  const key = `${tabId}:${url || ""}`;
  const now = Date.now();
  const lastAt = lastNotifyByTab.get(key) || 0;
  if (now - lastAt < NOTIFY_COOLDOWN_MS) {
    return;
  }
  lastNotifyByTab.set(key, now);

  await enableSidePanel(tabId);

  try {
    await chrome.runtime.sendMessage({
      type: "active-tab-changed",
      tabId,
      is1688DetailPage: is1688DetailPage(url),
      url: url || ""
    });
  } catch (_error) {
    // Side panel may not be open yet.
  }
}

async function initializeSidePanel() {
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

  try {
    const tabs = await chrome.tabs.query({});
    await Promise.all(tabs.map((tab) => enableSidePanel(tab.id)));
  } catch (_error) {
    // Best effort only.
  }
}

chrome.action.onClicked.addListener(async (tab) => {
  if (tab?.id) {
    await enableSidePanel(tab.id);
  }

  try {
    await chrome.sidePanel.open({ windowId: tab.windowId });
  } catch (_error) {
    // openPanelOnActionClick already handles the normal flow.
  }

  if (tab?.id) {
    await notifyPanel(tab.id, tab.url || "");
  }
});

chrome.runtime.onInstalled.addListener(() => {
  initializeSidePanel();
});

chrome.runtime.onStartup.addListener(() => {
  initializeSidePanel();
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (typeof changeInfo.url === "string") {
    notifyPanel(tabId, changeInfo.url);
    return;
  }

  if (changeInfo.status === "complete") {
    notifyPanel(tabId, tab.url || "");
  }
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try {
    const tab = await chrome.tabs.get(tabId);
    await notifyPanel(tabId, tab.url || "");
  } catch (_error) {
    // Ignore transient tab lookup errors.
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "bridge-import-product-card") {
    const entry = normalizeImportEntry(message);
    if (!entry) {
      sendResponse({ ok: false, message: "传输数据不完整，无法导入计算器。" });
      return false;
    }

    saveLatestImportedEntry(entry)
      .then(() => notifyImportedEntry(entry))
      .then(() => {
        sendResponse({ ok: true, message: "商品已发送到计算器。", entry });
      })
      .catch((error) => {
        sendResponse({ ok: false, message: error?.message || "保存导入数据失败。" });
      });

    return true;
  }

  if (message?.type === "get-latest-imported-product-card") {
    getLatestImportedEntry().then((entry) => {
      sendResponse({ ok: true, entry });
    });
    return true;
  }

  return false;
});
