const DETAIL_URL_PATTERN = /^https?:\/\/(?:detail\.)?1688\.com\//i;
const NOTIFY_COOLDOWN_MS = 250;

const lastNotifyByTab = new Map();

function is1688DetailPage(url) {
  return DETAIL_URL_PATTERN.test(url || "");
}

async function enableSidePanel(tabId) {
  try {
    await chrome.sidePanel.setOptions({
      tabId,
      path: "popup.html",
      enabled: true,
    });
  } catch {
    // Some browser tabs reject side panel options. It is safe to ignore them.
  }
}

async function notifyPanel(tabId, url) {
  if (!is1688DetailPage(url)) return;

  const key = `${tabId}:${url || ""}`;
  const now = Date.now();
  const lastAt = lastNotifyByTab.get(key) || 0;
  if (now - lastAt < NOTIFY_COOLDOWN_MS) return;
  lastNotifyByTab.set(key, now);

  await enableSidePanel(tabId);

  try {
    await chrome.runtime.sendMessage({
      type: "ACTIVE_1688_TAB_CHANGED",
      tabId,
      url: url || "",
    });
  } catch {
    // The side panel may not be open yet.
  }
}

async function initializeSidePanel() {
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

  try {
    const tabs = await chrome.tabs.query({});
    await Promise.all(tabs.map((tab) => (tab.id ? enableSidePanel(tab.id) : Promise.resolve())));
  } catch {
    // Best effort only.
  }
}

chrome.action.onClicked.addListener(async (tab) => {
  if (tab?.id) await enableSidePanel(tab.id);

  try {
    await chrome.sidePanel.open({ windowId: tab.windowId });
  } catch {
    // openPanelOnActionClick handles the normal flow.
  }

  if (tab?.id) {
    await notifyPanel(tab.id, tab.url || "");
  }
});

chrome.runtime.onInstalled.addListener(() => {
  void initializeSidePanel();
});

chrome.runtime.onStartup.addListener(() => {
  void initializeSidePanel();
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (typeof changeInfo.url === "string") {
    void notifyPanel(tabId, changeInfo.url);
    return;
  }

  if (changeInfo.status === "complete") {
    void notifyPanel(tabId, tab.url || "");
  }
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try {
    const tab = await chrome.tabs.get(tabId);
    await notifyPanel(tabId, tab.url || "");
  } catch {
    // Ignore transient tab lookup errors.
  }
});
