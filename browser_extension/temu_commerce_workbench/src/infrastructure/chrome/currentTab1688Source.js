const DETAIL_URL_PATTERN = /^https:\/\/(?:detail\.)?1688\.com\//i;

export function createCurrentTab1688Source() {
  return {
    async extractCurrentPage() {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab?.id || !DETAIL_URL_PATTERN.test(tab.url || "")) {
        throw new Error("请先切换到 1688 商品详情页。");
      }

      return await sendExtractMessage(tab.id);
    }
  };
}

async function sendExtractMessage(tabId) {
  try {
    const response = await chrome.tabs.sendMessage(tabId, { type: "extract-1688-product-data" });
    if (isValidExtractedData(response)) {
      return response;
    }
  } catch {
    // Fall through to a forced injection of the active extractor.
  }

  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["src/infrastructure/content/1688Content.js"]
  });

  const response = await chrome.tabs.sendMessage(tabId, { type: "extract-1688-product-data" });
  if (isValidExtractedData(response)) {
    return response;
  }

  throw new Error("Unable to extract 1688 data from the current page.");
}

function isValidExtractedData(value) {
  if (!value || typeof value !== "object") return false;
  const hasUnitPrice = Number.isFinite(Number(value.unitPrice));
  const hasWeight = Number.isFinite(Number(value.weight));
  return hasUnitPrice && hasWeight;
}
