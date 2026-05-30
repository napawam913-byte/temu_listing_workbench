const T2_RESULT_PRODUCTS_KEY = "t2IntersectionProducts";
const T2_RESULT_SUMMARY_KEY = "t2IntersectionSummary";

export async function saveT2IntersectionResult({ products, summary }) {
  await chrome.storage.local.set({
    [T2_RESULT_PRODUCTS_KEY]: products,
    [T2_RESULT_SUMMARY_KEY]: summary
  });
}

export async function loadT2IntersectionResult() {
  const result = await chrome.storage.local.get([T2_RESULT_PRODUCTS_KEY, T2_RESULT_SUMMARY_KEY]);
  return {
    products: Array.isArray(result[T2_RESULT_PRODUCTS_KEY]) ? result[T2_RESULT_PRODUCTS_KEY] : [],
    summary: result[T2_RESULT_SUMMARY_KEY] || null
  };
}

export function listenForT2IntersectionResultChanges(callback) {
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local") return;
    if (changes[T2_RESULT_PRODUCTS_KEY] || changes[T2_RESULT_SUMMARY_KEY]) {
      callback();
    }
  });
}
