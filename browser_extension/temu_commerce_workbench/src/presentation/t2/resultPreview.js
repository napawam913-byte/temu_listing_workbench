import {
  listenForT2IntersectionResultChanges,
  loadT2IntersectionResult
} from "../../infrastructure/storage/t2ResultStore.js";

const els = {
  summaryText: document.getElementById("summaryText"),
  refreshButton: document.getElementById("refreshButton"),
  grid: document.getElementById("grid"),
  emptyState: document.getElementById("emptyState")
};

els.refreshButton.addEventListener("click", renderFromStorage);
listenForT2IntersectionResultChanges(renderFromStorage);
renderFromStorage();

async function renderFromStorage() {
  const { products, summary } = await loadT2IntersectionResult();
  els.summaryText.textContent = buildSummaryText(products, summary);
  els.grid.innerHTML = "";
  els.emptyState.classList.toggle("is-visible", products.length === 0);

  for (const product of products) {
    els.grid.appendChild(createCard(product));
  }
}

function buildSummaryText(products, summary) {
  if (!products.length) return "等待 T2 交集结果。";
  if (!summary) return `共 ${products.length} 条商品。`;
  return `共 ${products.length} 条商品。信息表 SKC ${summary.infoUniqueSkcCount} 个，价格表 SKC ${summary.priceUniqueSkcCount} 个，交集 ${summary.matchedProductCount} 个。`;
}

function createCard(product) {
  const card = document.createElement("article");
  card.className = "card";

  const imageUrl = String(product.imageUrl || "").trim();
  const searchUrl = imageUrl
    ? `https://s.1688.com/youyuan/index.htm?tab=imageSearch&imageAddress=${encodeURIComponent(imageUrl)}`
    : "#";

  card.innerHTML = `
    <div class="image-wrap">
      <a class="image-link" href="${escapeAttribute(imageUrl || "#")}" target="_blank" rel="noopener noreferrer">
        ${imageUrl
          ? `<img class="product-image" src="${escapeAttribute(imageUrl)}" alt="${escapeAttribute(product.name || "")}" loading="eager" referrerpolicy="no-referrer">`
          : `<div class="image-placeholder">无图片</div>`}
      </a>
    </div>
    <div class="meta">
      <div class="label">标题</div>
      <div class="value name">${escapeHtml(product.name || "")}</div>
      <div class="label">SKC</div>
      <div class="value">${escapeHtml(product.skc || "")}</div>
      <div class="label">调整后申报价</div>
      <div class="value">${escapeHtml(product.quotedPrice ?? "")}</div>
      <div class="label">图片 URL</div>
      <div class="value url">
        <a class="url-link" href="${escapeAttribute(imageUrl || "#")}" target="_blank" rel="noopener noreferrer">${escapeHtml(imageUrl || "-")}</a>
      </div>
      <div class="action-row">
        <a class="search-button" href="${escapeAttribute(searchUrl)}" target="_blank" rel="noopener noreferrer">1688搜图</a>
        <button class="transfer-button" type="button">传输到计算器</button>
      </div>
    </div>
  `;

  const transferButton = card.querySelector(".transfer-button");
  transferButton.addEventListener("click", () => transferProduct(product, transferButton));
  return card;
}

async function transferProduct(product, button) {
  const flag = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  setButtonState(button, "写入缓存中...", true);

  try {
    const response = await chrome.runtime.sendMessage({
      type: "bridge-import-product-card",
      flag,
      payload: {
        type: "product-card-transfer",
        name: String(product.name || ""),
        skc: String(product.skc || ""),
        quoted_price: String(product.quotedPrice ?? ""),
        image_url: String(product.imageUrl || ""),
        source: "t2-preview-page",
        sent_at: new Date().toISOString()
      }
    });

    if (response?.ok) {
      setButtonState(button, "已传输到计算器", true, "is-success");
    } else {
      setButtonState(button, "传输失败", true, "is-error");
      if (response?.message) alert(response.message);
    }
  } catch (error) {
    setButtonState(button, "传输失败", true, "is-error");
    alert(error?.message || String(error));
  } finally {
    window.setTimeout(() => {
      setButtonState(button, "传输到计算器", false);
    }, 1800);
  }
}

function setButtonState(button, text, disabled, stateClass = "") {
  button.textContent = text;
  button.disabled = disabled;
  button.classList.remove("is-success", "is-error");
  if (stateClass) button.classList.add(stateClass);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}
