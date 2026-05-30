import { buildWorkbookBuffer } from "./excel_writer.js";
import { calculateProfit, loadConfig, money, parseNumber, percent } from "./calc.js";
import { readJsonRecordsFromFileHandle, writeJsonRecordsToFileHandle } from "./json_file_store.js";
import {
  loadJsonFileHandle,
  loadJsonFileMeta,
  saveJsonFileHandle,
  saveJsonFileMeta
} from "./storage.js";

const JSON_FILE_NAME = "records.json";
const WORKBOOK_FILE_NAME = "records.xlsx";
const AUTO_CALC_FIELDS = ["quotedPrice", "unitPrice", "weight", "quantity", "discountRate"];
const EXTERNAL_IMPORT_COOLDOWN_MS = 15000;
const AUTO_FETCH_RETRY_DELAYS_MS = [0, 400, 1200, 2500];

const state = {
  config: null,
  currentImage: null,
  records: [],
  jsonFileHandle: null,
  jsonFileMeta: null,
  lastProductSignature: "",
  lastTabId: null,
  isSaving: false,
  isPageFetchInFlight: false,
  lastAutoFetchKey: "",
  lastExternalImportAt: 0,
  lastImportedFlag: "",
  lastImportedPayloadSignature: "",
  autoFetchRetryToken: 0
};

const elements = {
  bindJsonButton: document.querySelector("#bindJsonButton"),
  cacheSummaryText: document.querySelector("#cacheSummaryText"),
  statusText: document.querySelector("#statusText"),
  name: document.querySelector("#name"),
  skc: document.querySelector("#skc"),
  quotedPrice: document.querySelector("#quotedPrice"),
  unitPrice: document.querySelector("#unitPrice"),
  weight: document.querySelector("#weight"),
  quantity: document.querySelector("#quantity"),
  discountRate: document.querySelector("#discountRate"),
  url: document.querySelector("#url"),
  imagePreview: document.querySelector("#imagePreview"),
  imagePlaceholder: document.querySelector("#imagePlaceholder"),
  imageDropzone: document.querySelector("#imageDropzone"),
  refreshPageButton: document.querySelector("#refreshPageButton"),
  calculateButton: document.querySelector("#calculateButton"),
  pasteImageButton: document.querySelector("#pasteImageButton"),
  clearImageButton: document.querySelector("#clearImageButton"),
  saveButton: document.querySelector("#saveButton"),
  exportButton: document.querySelector("#exportButton"),
  clearButton: document.querySelector("#clearButton"),
  actualPriceResult: document.querySelector("#actualPriceResult"),
  firstLegFeeResult: document.querySelector("#firstLegFeeResult"),
  firstLegCostResult: document.querySelector("#firstLegCostResult"),
  lastLegCostResult: document.querySelector("#lastLegCostResult"),
  profitResult: document.querySelector("#profitResult"),
  cargoLossResult: document.querySelector("#cargoLossResult"),
  actualProfitResult: document.querySelector("#actualProfitResult"),
  roiResult: document.querySelector("#roiResult"),
  marginResult: document.querySelector("#marginResult")
};

function setStatus(message) {
  elements.statusText.textContent = message;
}

function renderStorageSummary() {
  if (!elements.cacheSummaryText) {
    return;
  }

  if (!state.jsonFileHandle) {
    elements.cacheSummaryText.textContent = "未绑定本地 JSON 文件。第一次保存时会让你选择一个 records.json。";
    return;
  }

  const fileName = state.jsonFileMeta?.name || state.jsonFileHandle.name || JSON_FILE_NAME;
  elements.cacheSummaryText.textContent =
    `已绑定 JSON：${fileName}。当前已保存 ${state.records.length} 条记录。点击“保存到 JSON”会立刻写入本地文件。`;
}

function resetResults() {
  [
    elements.actualPriceResult,
    elements.firstLegFeeResult,
    elements.firstLegCostResult,
    elements.lastLegCostResult,
    elements.profitResult,
    elements.cargoLossResult,
    elements.actualProfitResult,
    elements.roiResult,
    elements.marginResult
  ].forEach((element) => {
    element.textContent = "-";
  });
}

function getFormValues() {
  return {
    name: elements.name.value.trim(),
    skc: elements.skc.value.trim(),
    quotedPrice: parseNumber(elements.quotedPrice.value, "核价"),
    unitPrice: parseNumber(elements.unitPrice.value, "单件"),
    weight: parseNumber(elements.weight.value, "重量"),
    quantity: parseNumber(elements.quantity.value || "1", "倍数"),
    discountRatePercent: parseNumber(elements.discountRate.value, "折扣率"),
    url: elements.url.value.trim()
  };
}

function calculateAndRender({ quiet = false } = {}) {
  if (!state.config) {
    return null;
  }

  try {
    const values = getFormValues();
    const result = calculateProfit({
      quotedPrice: values.quotedPrice,
      unitPrice: values.unitPrice,
      weight: values.weight,
      quantity: values.quantity,
      discountRate: values.discountRatePercent / 100,
      config: state.config
    });

    elements.actualPriceResult.textContent = money(result.actualPrice);
    elements.firstLegFeeResult.textContent = money(result.firstLegFee);
    elements.firstLegCostResult.textContent = money(result.firstLegCost);
    elements.lastLegCostResult.textContent = money(result.lastLegCost);
    elements.profitResult.textContent = money(result.profit);
    elements.cargoLossResult.textContent = money(result.cargoLoss);
    elements.actualProfitResult.textContent = money(result.actualProfit);
    elements.roiResult.textContent = percent(result.roi);
    elements.marginResult.textContent = percent(result.margin);

    if (!quiet) {
      setStatus("已完成计算。");
    }

    return { values, result };
  } catch (error) {
    resetResults();
    if (!quiet) {
      setStatus(error.message);
    }
    return null;
  }
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
}

function buildTabFetchKey(tabId, url) {
  return `${tabId || ""}|${url || ""}`;
}

async function sendExtractMessage(tabId) {
  try {
    return await chrome.tabs.sendMessage(tabId, { type: "extract-product-data" });
  } catch (_error) {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["src/legacy/1688/content.js"]
    });
    return chrome.tabs.sendMessage(tabId, { type: "extract-product-data" });
  }
}

function buildProductSignature(data) {
  return [
    data?.name || "",
    data?.skc || "",
    data?.quotedPrice || data?.quoted_price || "",
    data?.unitPrice || "",
    data?.weight || "",
    data?.goodsPrice || "",
    data?.shippingFee || "",
    data?.sent_at || ""
  ].join("|");
}

function isExternalImportCoolingDown() {
  return Date.now() - state.lastExternalImportAt < EXTERNAL_IMPORT_COOLDOWN_MS;
}

function hasUsefulProductData(data) {
  return Boolean(data && (data.unitPrice || data.weight || data.url || data.goodsPrice || data.shippingFee));
}

function isProductDataComplete(data) {
  return Boolean(data && data.unitPrice && data.weight);
}

function getImageExtension(blob) {
  const mime = blob.type || "image/png";
  if (mime.includes("jpeg") || mime.includes("jpg")) {
    return "jpg";
  }
  if (mime.includes("webp")) {
    return "webp";
  }
  return "png";
}

async function setCurrentImage(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const objectUrl = URL.createObjectURL(blob);

  if (state.currentImage?.objectUrl) {
    URL.revokeObjectURL(state.currentImage.objectUrl);
  }

  state.currentImage = {
    blob,
    bytes,
    extension: getImageExtension(blob),
    mimeType: blob.type || "image/png",
    objectUrl
  };

  elements.imagePreview.src = objectUrl;
  elements.imagePreview.hidden = false;
  elements.imagePlaceholder.hidden = true;
}

function clearImage() {
  if (state.currentImage?.objectUrl) {
    URL.revokeObjectURL(state.currentImage.objectUrl);
  }

  state.currentImage = null;
  elements.imagePreview.removeAttribute("src");
  elements.imagePreview.hidden = true;
  elements.imagePlaceholder.hidden = false;
}

async function loadImageFromUrl(imageUrl) {
  const response = await fetch(imageUrl, {
    credentials: "omit",
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error(`图片下载失败，状态码 ${response.status}`);
  }

  const blob = await response.blob();
  if (!blob.type.startsWith("image/")) {
    throw new Error("图片地址返回的不是有效图片。");
  }

  await setCurrentImage(blob);
}

async function pasteImageFromClipboard() {
  try {
    const items = await navigator.clipboard.read();
    for (const item of items) {
      const imageType = item.types.find((type) => type.startsWith("image/"));
      if (imageType) {
        await setCurrentImage(await item.getType(imageType));
        setStatus("图片已粘贴。");
        return;
      }
    }

    setStatus("剪贴板里没有图片。");
  } catch (error) {
    setStatus(`粘贴失败，请先聚焦图片区后再尝试 Ctrl+V。${error.message ? ` ${error.message}` : ""}`);
  }
}

async function handlePaste(event) {
  const item = Array.from(event.clipboardData?.items || []).find((entry) => entry.type.startsWith("image/"));
  if (!item) {
    return;
  }

  const blob = item.getAsFile();
  if (blob) {
    await setCurrentImage(blob);
    setStatus("图片已粘贴。");
  }
}

async function applyImportedProductCard(entry, { force = false } = {}) {
  const flag = String(entry?.flag || "").trim();
  const payload = entry?.payload;
  if (!payload) {
    return false;
  }

  const signature = buildProductSignature(payload);
  if (!force && flag && flag === state.lastImportedFlag && signature === state.lastImportedPayloadSignature) {
    return false;
  }

  state.lastImportedFlag = flag;
  state.lastImportedPayloadSignature = signature;
  state.lastExternalImportAt = Date.now();

  elements.name.value = payload.name || "";
  elements.skc.value = payload.skc || "";
  elements.quotedPrice.value = payload.quoted_price || "";
  elements.url.value = "";

  if (!elements.quantity.value) {
    elements.quantity.value = "1";
  }

  let imageLoaded = false;
  let imageErrorMessage = "";
  if (payload.image_url) {
    try {
      await loadImageFromUrl(payload.image_url);
      imageLoaded = true;
    } catch (error) {
      imageErrorMessage = error?.message || "图片加载失败，请手动补图。";
    }
  }

  calculateAndRender({ quiet: true });
  if (imageLoaded) {
    setStatus(`已从预览页导入商品：${payload.name || payload.skc}，图片已自动载入。`);
  } else if (imageErrorMessage) {
    setStatus(`已从预览页导入商品：${payload.name || payload.skc}，但${imageErrorMessage}`);
  } else {
    setStatus(`已从预览页导入商品：${payload.name || payload.skc}。`);
  }

  return true;
}

function applyProductData(data, { force = false, source = "1688-page" } = {}) {
  if (!hasUsefulProductData(data)) {
    return false;
  }

  const signature = buildProductSignature(data);
  if (!force && signature === state.lastProductSignature) {
    return false;
  }

  state.lastProductSignature = signature;
  if (data.unitPrice) {
    elements.unitPrice.value = data.unitPrice;
  }
  if (data.weight) {
    elements.weight.value = data.weight;
  }
  if (data.url) {
    elements.url.value = data.url;
  }
  if (!elements.quantity.value) {
    elements.quantity.value = "1";
  }

  calculateAndRender({ quiet: true });
  const shippingText = data.shippingFee ? `，含运费 ${data.shippingFee}` : "";
  const weightText = data.weight ? `，重量 ${data.weight}` : "";
  setStatus(`已抓取当前 1688 页面：单价+运费 ${data.unitPrice || "-"}${shippingText}${weightText}。`);
  return true;
}

async function fillFromPage({ force = false, tab = null } = {}) {
  const activeTab = tab ?? (await getActiveTab());
  state.lastTabId = activeTab?.id ?? null;

  if (!activeTab?.id || !/^https:\/\/(?:detail\.)?1688\.com\//i.test(activeTab.url || "")) {
    if (!isExternalImportCoolingDown()) {
      setStatus("请打开 1688 商品详情页，侧边栏会自动抓取单件和重量。");
    }
    return;
  }

  const fetchKey = buildTabFetchKey(activeTab.id, activeTab.url || "");
  if (!force && (state.isPageFetchInFlight || fetchKey === state.lastAutoFetchKey)) {
    return { applied: false, complete: false, data: null, skipped: true };
  }

  state.isPageFetchInFlight = true;
  try {
    const data = await sendExtractMessage(activeTab.id);
    const applied = applyProductData(data, { force, source: "1688-page" });
    const complete = isProductDataComplete(data);

    if (complete) {
      state.lastAutoFetchKey = fetchKey;
    }

    if (!complete && hasUsefulProductData(data) && !isExternalImportCoolingDown()) {
      if (data.unitPrice && !data.weight) {
        setStatus("已抓到价格，正在继续等待 1688 页面重量数据。");
      } else {
        setStatus("1688 页面已打开，但价格/运费/重量还没渲染完成，正在重试。");
      }
    }

    return { applied, complete, data, skipped: false };
  } catch (error) {
    setStatus(`抓取失败：${error.message}`);
    return { applied: false, complete: false, data: null, skipped: false };
  } finally {
    state.isPageFetchInFlight = false;
  }
}

async function fillFromPageWithRetry({ tab = null, reason = "auto" } = {}) {
  const retryToken = Date.now();
  state.autoFetchRetryToken = retryToken;

  for (let index = 0; index < AUTO_FETCH_RETRY_DELAYS_MS.length; index += 1) {
    const delay = AUTO_FETCH_RETRY_DELAYS_MS[index];
    if (delay > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, delay));
    }

    if (state.autoFetchRetryToken !== retryToken) {
      return false;
    }

    const result = await fillFromPage({
      force: true,
      tab
    });

    if (result?.complete) {
      return true;
    }
  }

  const currentWeight = elements.weight?.value?.trim() || "";
  const currentUnitPrice = elements.unitPrice?.value?.trim() || "";
  if (!isExternalImportCoolingDown()) {
    if (currentUnitPrice && !currentWeight) {
      setStatus("价格已经抓到，但重量还没有抓到。你可以停留当前商品页 1 到 2 秒后再试一次。");
    } else {
      setStatus(`已尝试自动抓取 1688 页面，但还没有拿到有效的价格/运费/重量。${reason === "manual" ? "" : "你也可以点一次“刷新页面数据”。"}`);
    }
  }
  return false;
}

async function hydrateImportedProductCard() {
  try {
    const response = await chrome.runtime.sendMessage({
      type: "get-latest-imported-product-card"
    });
    if (response?.ok && response.entry) {
      await applyImportedProductCard(response.entry, { force: true });
    }
  } catch (_error) {
    // Best effort only.
  }
}

function ensureReadyToSave() {
  if (!state.currentImage) {
    throw new Error("请先准备图片，再保存记录。");
  }

  const calculated = calculateAndRender({ quiet: true });
  if (!calculated) {
    throw new Error("请先补全参数，确保当前商品可以计算。");
  }

  return calculated;
}

function getJsonPickerOptions() {
  return {
    suggestedName: JSON_FILE_NAME,
    types: [
      {
        description: "JSON 文件",
        accept: {
          "application/json": [".json"]
        }
      }
    ]
  };
}

async function verifyFilePermission(handle, write = false) {
  if (!handle) {
    return false;
  }

  const options = write ? { mode: "readwrite" } : {};
  if ((await handle.queryPermission(options)) === "granted") {
    return true;
  }

  if ((await handle.requestPermission(options)) === "granted") {
    return true;
  }

  return false;
}

async function hasFilePermission(handle, write = false) {
  if (!handle) {
    return false;
  }

  const options = write ? { mode: "readwrite" } : {};
  return (await handle.queryPermission(options)) === "granted";
}

async function chooseJsonFile() {
  if (!window.showSaveFilePicker) {
    throw new Error("当前浏览器环境不支持直接绑定本地 JSON 文件。");
  }

  const handle = await window.showSaveFilePicker(getJsonPickerOptions());
  const granted = await verifyFilePermission(handle, true);
  if (!granted) {
    throw new Error("未授予 JSON 文件读写权限。");
  }

  let records = [];
  try {
    records = await readJsonRecordsFromFileHandle(handle);
  } catch (error) {
    if (error.message.startsWith("JSON 文件解析失败")) {
      throw error;
    }
    records = [];
  }

  if (records.length === 0) {
    await writeJsonRecordsToFileHandle(handle, []);
  }

  state.jsonFileHandle = handle;
  state.jsonFileMeta = {
    name: handle.name,
    boundAt: new Date().toISOString()
  };
  state.records = records;

  await saveJsonFileHandle(handle);
  await saveJsonFileMeta(state.jsonFileMeta);
  renderStorageSummary();
  return handle;
}

async function ensureJsonFileReady({ interactive = false, write = false } = {}) {
  if (!state.jsonFileHandle) {
    if (!interactive) {
      throw new Error("请先绑定本地 JSON 文件。");
    }
    await chooseJsonFile();
  }

  const granted = await verifyFilePermission(state.jsonFileHandle, write);
  if (!granted) {
    if (interactive) {
      throw new Error("没有拿到本地 JSON 文件权限，请重新绑定文件。");
    }
    throw new Error("本地 JSON 文件当前不可访问。");
  }

  return state.jsonFileHandle;
}

async function loadRecordsFromJson({ interactive = false } = {}) {
  const handle = await ensureJsonFileReady({ interactive, write: false });
  const records = await readJsonRecordsFromFileHandle(handle);
  state.records = records;
  renderStorageSummary();
  return records;
}

async function hydrateJsonFileState() {
  state.jsonFileHandle = await loadJsonFileHandle();
  state.jsonFileMeta = await loadJsonFileMeta();

  if (!state.jsonFileHandle) {
    renderStorageSummary();
    return;
  }

  try {
    if (await hasFilePermission(state.jsonFileHandle, false)) {
      state.records = await readJsonRecordsFromFileHandle(state.jsonFileHandle);
    }
  } catch (_error) {
    state.records = [];
  }

  renderStorageSummary();
}

function downloadArrayBuffer(fileName, arrayBuffer, mimeType) {
  return new Promise((resolve, reject) => {
    const blob = new Blob([arrayBuffer], { type: mimeType });
    const url = URL.createObjectURL(blob);

    chrome.downloads.download(
      {
        url,
        filename: fileName,
        saveAs: true,
        conflictAction: "overwrite"
      },
      (downloadId) => {
        window.setTimeout(() => URL.revokeObjectURL(url), 30000);
        const error = chrome.runtime.lastError;
        if (error) {
          reject(new Error(error.message));
          return;
        }
        resolve(downloadId);
      }
    );
  });
}

function buildCurrentRecord() {
  const { values, result } = ensureReadyToSave();
  const imageFile = `${Date.now()}_${values.skc || "image"}.${state.currentImage.extension}`;

  return {
    ...values,
    imageFile,
    imageBytes: Array.from(state.currentImage.bytes),
    imageExtension: state.currentImage.extension,
    imageMimeType: state.currentImage.mimeType,
    result,
    savedAt: new Date().toISOString()
  };
}

async function saveCurrentRecord() {
  if (state.isSaving) {
    return;
  }

  state.isSaving = true;
  elements.saveButton.disabled = true;

  try {
    const record = buildCurrentRecord();
    const records = await loadRecordsFromJson({ interactive: true });
    const nextRecords = [...records, record];
    await writeJsonRecordsToFileHandle(state.jsonFileHandle, nextRecords);
    state.records = nextRecords;
    renderStorageSummary();
    clearImage();
    setStatus(`已写入本地 JSON。当前共 ${state.records.length} 条记录。`);
  } catch (error) {
    setStatus(error.message);
  } finally {
    state.isSaving = false;
    elements.saveButton.disabled = false;
  }
}

async function exportWorkbook() {
  if (state.isSaving) {
    return;
  }

  state.isSaving = true;
  elements.exportButton.disabled = true;

  try {
    const records = await loadRecordsFromJson({ interactive: true });
    if (records.length === 0) {
      throw new Error("JSON 里还没有记录，请先保存至少一条商品。");
    }

    const workbookBuffer = await buildWorkbookBuffer(records, async (savedRecord) => ({
      bytes: new Uint8Array(savedRecord.imageBytes),
      extension: savedRecord.imageExtension || "png",
      mimeType: savedRecord.imageMimeType || "image/png"
    }));

    await downloadArrayBuffer(
      WORKBOOK_FILE_NAME,
      workbookBuffer,
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    );

    setStatus(`已根据 ${records.length} 条 JSON 记录导出 Excel。`);
  } catch (error) {
    setStatus(error.message);
  } finally {
    state.isSaving = false;
    elements.exportButton.disabled = false;
  }
}

function clearForm() {
  elements.name.value = "";
  elements.skc.value = "";
  elements.quotedPrice.value = "";
  elements.unitPrice.value = "";
  elements.weight.value = "";
  elements.quantity.value = "1";
  elements.discountRate.value = state.config ? money(Number(state.config.discount_rate) * 100) : "100.00";
  elements.url.value = "";
  state.lastProductSignature = "";
  state.lastAutoFetchKey = "";
  state.lastExternalImportAt = 0;
  state.lastImportedFlag = "";
  state.lastImportedPayloadSignature = "";
  clearImage();
  resetResults();
  setStatus("表单已清空。");
}

async function bindJsonFileManually() {
  try {
    await chooseJsonFile();
    setStatus(`已绑定本地 JSON：${state.jsonFileHandle.name}`);
  } catch (error) {
    if (error?.name === "AbortError") {
      setStatus("已取消绑定 JSON 文件。");
      return;
    }
    setStatus(error.message);
  }
}

function handleActiveTabChangedMessage(message) {
  if (message?.type !== "active-tab-changed") {
    return false;
  }

  fillFromPageWithRetry({
    reason: "tab-changed",
    tab: message.tabId
      ? {
          id: message.tabId,
          url: message.url || ""
        }
      : null
  });
  return true;
}

function bindEvents() {
  elements.bindJsonButton.addEventListener("click", bindJsonFileManually);
  elements.refreshPageButton.addEventListener("click", () => fillFromPageWithRetry({ reason: "manual" }));
  elements.calculateButton.addEventListener("click", () => calculateAndRender());
  elements.pasteImageButton.addEventListener("click", pasteImageFromClipboard);
  elements.clearImageButton.addEventListener("click", clearImage);
  elements.saveButton.addEventListener("click", saveCurrentRecord);
  elements.exportButton.addEventListener("click", exportWorkbook);
  elements.clearButton.addEventListener("click", clearForm);
  elements.imageDropzone.addEventListener("paste", handlePaste);
  document.addEventListener("paste", handlePaste);

  AUTO_CALC_FIELDS.forEach((id) => {
    elements[id].addEventListener("input", () => calculateAndRender({ quiet: true }));
    elements[id].addEventListener("change", () => calculateAndRender({ quiet: true }));
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (handleActiveTabChangedMessage(message)) {
      return;
    }

    if (message?.type === "import-product-card" && message.entry) {
      applyImportedProductCard(message.entry, { force: true });
    }
  });

  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) {
      return;
    }

    handleActiveTabChangedMessage(event.data);
  });
}

async function init() {
  bindEvents();
  state.config = await loadConfig();
  elements.discountRate.value = money(Number(state.config.discount_rate) * 100);
  elements.quantity.value = elements.quantity.value || "1";
  renderStorageSummary();
  await hydrateJsonFileState();
  await hydrateImportedProductCard();
  await fillFromPageWithRetry({ reason: "init" });
}

init().catch((error) => {
  setStatus(error.message);
});
