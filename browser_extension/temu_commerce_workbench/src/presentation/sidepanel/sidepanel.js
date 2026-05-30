import { importT2Products } from "../../application/usecases/importT2Products.js";
import { calculateProductPricing } from "../../application/usecases/calculateProductPricing.js";
import { enrichProductFrom1688 } from "../../application/usecases/enrichProductFrom1688.js";
import { createChromeProductRepository } from "../../infrastructure/storage/chromeProductRepository.js";
import { readRowsFromBrowserFile, writeRowsToXlsxBlob } from "../../infrastructure/xlsx/browserXlsxSheetIO.js";
import { productsToSheetRows } from "../../infrastructure/xlsx/productSheetRows.js";
import { createCurrentTab1688Source } from "../../infrastructure/chrome/currentTab1688Source.js";

const productRepository = createChromeProductRepository();
const productSource1688 = createCurrentTab1688Source();

const state = {
  products: [],
  selectedId: "",
  log: []
};

const els = {
  infoFile: document.getElementById("infoFile"),
  priceFile: document.getElementById("priceFile"),
  importButton: document.getElementById("importButton"),
  clearQueue: document.getElementById("clearQueue"),
  selectedProductText: document.getElementById("selectedProductText"),
  capture1688Button: document.getElementById("capture1688Button"),
  manualUnitPrice: document.getElementById("manualUnitPrice"),
  manualWeight: document.getElementById("manualWeight"),
  saveManual1688Button: document.getElementById("saveManual1688Button"),
  quantity: document.getElementById("quantity"),
  discountRate: document.getElementById("discountRate"),
  calculateButton: document.getElementById("calculateButton"),
  exportButton: document.getElementById("exportButton"),
  queueSummary: document.getElementById("queueSummary"),
  productRows: document.getElementById("productRows"),
  log: document.getElementById("log")
};

init();

async function init() {
  bindEvents();
  await refreshProducts();
  addLog("工作台已就绪。");
}

function bindEvents() {
  els.importButton.addEventListener("click", importQueue);
  els.clearQueue.addEventListener("click", clearQueue);
  els.capture1688Button.addEventListener("click", capture1688ForSelected);
  els.saveManual1688Button.addEventListener("click", saveManual1688ForSelected);
  els.calculateButton.addEventListener("click", calculateAll);
  els.exportButton.addEventListener("click", exportQueue);
  els.productRows.addEventListener("change", (event) => {
    if (event.target?.name === "selectedProduct") {
      state.selectedId = event.target.value;
      syncSelectedControls();
      render();
    }
  });
}

async function importQueue() {
  const infoFile = els.infoFile.files?.[0];
  const priceFile = els.priceFile.files?.[0];
  if (!infoFile || !priceFile) {
    addLog("请先选择信息表和价格表。");
    return;
  }

  try {
    const infoRows = await readRowsFromBrowserFile(infoFile);
    const priceRows = await readRowsFromBrowserFile(priceFile);
    const result = importT2Products({ infoRows, priceRows });
    await productRepository.replaceAll(result.products);
    state.selectedId = result.products[0]?.id ?? "";
    await refreshProducts();
    addLog(`导入完成：信息表去重 ${result.summary.infoUniqueSkcCount} 个 SKC，交集 ${result.summary.matchedProductCount} 个商品。`);
  } catch (error) {
    addLog(`导入失败：${error.message || error}`);
  }
}

async function clearQueue() {
  await productRepository.clear();
  state.selectedId = "";
  await refreshProducts();
  addLog("商品队列已清空。");
}

async function capture1688ForSelected() {
  if (!state.selectedId) {
    addLog("请先在商品队列里选中一个商品。");
    return;
  }

  try {
    const product = await enrichProductFrom1688({
      productId: state.selectedId,
      productRepository,
      productSource1688
    });
    await refreshProducts();
    addLog(`已抓取 1688 数据：${product.name || product.skc}，单件 ${product.source1688.unitPrice}，重量 ${product.source1688.weight}kg。`);
  } catch (error) {
    addLog(`抓取失败：${error.message || error}`);
  }
}

async function saveManual1688ForSelected() {
  if (!state.selectedId) {
    addLog("请先在商品队列里选中一个商品。");
    return;
  }

  const unitPrice = Number(els.manualUnitPrice.value);
  const weight = Number(els.manualWeight.value);
  if (!Number.isFinite(unitPrice) || unitPrice <= 0 || !Number.isFinite(weight) || weight < 0) {
    addLog("请填写有效的单件和重量。");
    return;
  }

  await productRepository.update(state.selectedId, (product) => ({
    ...product,
    source1688: {
      ...(product.source1688 ?? {}),
      unitPrice,
      weight
    },
    status: "enriched_1688",
    logs: [
      ...(product.logs ?? []),
      {
        at: new Date().toISOString(),
        status: "enriched_1688",
        message: "Manual 1688 data saved"
      }
    ]
  }));
  await refreshProducts();
  addLog("已保存手动 1688 数据。");
}

async function calculateAll() {
  const quantity = Number(els.quantity.value || 1);
  const discountRate = Number(els.discountRate.value || 1);
  let calculated = 0;
  let skipped = 0;

  for (const product of state.products) {
    if (!product.source1688?.unitPrice || product.source1688?.weight === undefined || product.source1688?.weight === "") {
      skipped += 1;
      continue;
    }
    try {
      await calculateProductPricing({
        productId: product.id,
        productRepository,
        quantity,
        discountRate
      });
      calculated += 1;
    } catch (error) {
      skipped += 1;
      addLog(`${product.name || product.skc} 核价失败：${error.message || error}`);
    }
  }

  await refreshProducts();
  addLog(`核价完成：成功 ${calculated} 个，跳过 ${skipped} 个。`);
}

async function exportQueue() {
  const products = await productRepository.list();
  if (!products.length) {
    addLog("没有可导出的商品。");
    return;
  }

  const blob = writeRowsToXlsxBlob(productsToSheetRows(products), { sheetName: "Products" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `temu-products-${Date.now()}.xlsx`;
  anchor.click();
  URL.revokeObjectURL(url);
  addLog(`已导出 ${products.length} 个商品。`);
}

async function refreshProducts() {
  state.products = await productRepository.list();
  if (!state.selectedId || !state.products.some((product) => product.id === state.selectedId)) {
    state.selectedId = state.products[0]?.id ?? "";
  }
  syncSelectedControls();
  render();
}

function syncSelectedControls() {
  const selected = state.products.find((product) => product.id === state.selectedId);
  els.selectedProductText.textContent = selected ? `${selected.name || "-"} / ${selected.skc}` : "未选择商品";
  els.manualUnitPrice.value = selected?.source1688?.unitPrice ?? "";
  els.manualWeight.value = selected?.source1688?.weight ?? "";
}

function render() {
  els.queueSummary.textContent = `${state.products.length} 个商品`;
  els.productRows.innerHTML = "";

  for (const product of state.products) {
    const row = document.createElement("tr");
    if (product.id === state.selectedId) {
      row.classList.add("is-selected");
    }

    row.innerHTML = `
      <td><input type="radio" name="selectedProduct" value="${escapeHtml(product.id)}" ${product.id === state.selectedId ? "checked" : ""}></td>
      <td class="name">${escapeHtml(product.name || "")}</td>
      <td>${escapeHtml(product.skc || "")}</td>
      <td>${formatNumber(product.quotedPrice)}</td>
      <td>${formatNumber(product.source1688?.unitPrice)}</td>
      <td>${formatNumber(product.source1688?.weight)}</td>
      <td>${formatNumber(product.pricing?.profit)}</td>
      <td>${escapeHtml(product.status || "")}</td>
    `;
    els.productRows.appendChild(row);
  }

  els.capture1688Button.disabled = !state.selectedId;
  els.saveManual1688Button.disabled = !state.selectedId;
  els.calculateButton.disabled = !state.products.length;
  els.exportButton.disabled = !state.products.length;

  els.log.innerHTML = "";
  for (const entry of state.log.slice(0, 80)) {
    const row = document.createElement("div");
    row.className = "log-entry";
    row.innerHTML = `<strong>${escapeHtml(entry.time)}</strong><span>${escapeHtml(entry.text)}</span>`;
    els.log.appendChild(row);
  }
}

function addLog(text) {
  state.log.unshift({
    time: new Date().toLocaleTimeString(),
    text: String(text)
  });
  render();
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "";
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  return Number(number.toFixed(4)).toString();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
