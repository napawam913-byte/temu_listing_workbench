const DOWNLOAD_DIR = "temu-gpt-listing-v2-images";

chrome.runtime.onInstalled.addListener(() => {
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  }
});

chrome.action.onClicked.addListener(async (tab) => {
  if (!chrome.sidePanel || !chrome.sidePanel.open) {
    return;
  }

  try {
    if (tab && tab.id) {
      await chrome.sidePanel.open({ tabId: tab.id });
    } else {
      await chrome.sidePanel.open({});
    }
  } catch (error) {
    console.warn("Failed to open side panel", error);
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "downloadImage") {
    return false;
  }

  downloadImage(message)
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));

  return true;
});

async function downloadImage(message) {
  if (!message.url) {
    throw new Error("Missing image URL");
  }

  const filename = `${DOWNLOAD_DIR}/${sanitizeFilename(message.filename || "temu_main.png")}`;
  const downloadId = await chrome.downloads.download({
    url: message.url,
    filename,
    conflictAction: "uniquify",
    saveAs: false
  });

  return { downloadId, filename };
}

function sanitizeFilename(name) {
  return String(name)
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 180);
}
