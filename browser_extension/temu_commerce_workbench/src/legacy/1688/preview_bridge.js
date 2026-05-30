const BUFFER_SELECTOR = "#data_buffer";
const FLAG_SELECTOR = "#data_buffer_flag";
const READY_EVENT = "product-card-transfer-ready";
const RESULT_EVENT = "product-card-transfer-result";

let lastHandledFlag = "";

function readTransferPayload() {
  const bufferElement = document.querySelector(BUFFER_SELECTOR);
  const flagElement = document.querySelector(FLAG_SELECTOR);
  const flag = (flagElement?.value || "").trim();
  const raw = bufferElement?.value || "";

  if (!flag || !raw) {
    return null;
  }

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (_error) {
    return {
      ok: false,
      flag,
      message: "data_buffer 不是合法 JSON。"
    };
  }

  const normalized = {
    type: String(payload?.type || "").trim(),
    name: String(payload?.name || "").trim(),
    skc: String(payload?.skc || "").trim(),
    quoted_price: String(payload?.quoted_price || "").trim(),
    image_url: String(payload?.image_url || "").trim(),
    source: String(payload?.source || "t2-preview-html").trim(),
    sent_at: String(payload?.sent_at || "").trim()
  };

  if (
    normalized.type !== "product-card-transfer" ||
    !normalized.name ||
    !normalized.skc ||
    !normalized.quoted_price ||
    !normalized.image_url
  ) {
    return {
      ok: false,
      flag,
      message: "传输数据不完整，必须包含名称、SKC、调整后申报价和图片。"
    };
  }

  return {
    ok: true,
    flag,
    payload: normalized
  };
}

function emitTransferResult(detail) {
  document.dispatchEvent(
    new CustomEvent(RESULT_EVENT, {
      detail,
      bubbles: true
    })
  );
}

async function handleReadyEvent() {
  const transfer = readTransferPayload();
  if (!transfer) {
    return;
  }

  if (transfer.flag && transfer.flag === lastHandledFlag) {
    return;
  }
  lastHandledFlag = transfer.flag;

  if (!transfer.ok) {
    emitTransferResult({
      ok: false,
      flag: transfer.flag,
      message: transfer.message
    });
    return;
  }

  try {
    const response = await chrome.runtime.sendMessage({
      type: "bridge-import-product-card",
      flag: transfer.flag,
      payload: transfer.payload
    });

    emitTransferResult({
      ok: Boolean(response?.ok),
      flag: transfer.flag,
      message: response?.message || "传输已处理。"
    });
  } catch (error) {
    emitTransferResult({
      ok: false,
      flag: transfer.flag,
      message: error?.message || "传输失败，请确认插件已启用。"
    });
  }
}

window.addEventListener(READY_EVENT, handleReadyEvent);
document.addEventListener(READY_EVENT, handleReadyEvent);
