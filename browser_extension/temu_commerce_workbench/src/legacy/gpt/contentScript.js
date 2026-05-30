(() => {
  if (globalThis.__temuGptAutomatorLoaded) {
    return;
  }
  globalThis.__temuGptAutomatorLoaded = true;

  const state = {
    busy: false,
    cancelled: false,
    baselineImageKeys: new Set()
  };

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    handleMessage(message)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));
    return true;
  });

  async function handleMessage(message) {
    if (!message || message.type === "ping") {
      return { ok: true };
    }

    if (message.type === "stopRun") {
      state.cancelled = true;
      clickStopButton();
      return { ok: true };
    }

    if (state.busy) {
      return { ok: false, error: "页面正在处理上一张图片" };
    }

    state.busy = true;
    try {
      if (message.type === "runPlan") {
        return await runPlan(message);
      }
      if (message.type === "runExecute") {
        return await runExecute(message);
      }
      return { ok: false, error: `未知消息类型：${message.type}` };
    } finally {
      state.busy = false;
    }
  }

  async function runPlan(message) {
    state.cancelled = false;
    await waitForComposer(message.timeoutMs);
    state.baselineImageKeys = collectImageKeys();
    await attachImage(message.file);
    await setPromptAndSend(message.prompt);
    const planText = await waitForAssistantText(message.timeoutMs || 240000);
    if (!planText || planText.length < 8) {
      throw new Error("规划文本过短或为空");
    }
    return { ok: true, planText };
  }

  async function runExecute(message) {
    state.cancelled = false;
    await waitForComposer(message.timeoutMs);
    state.baselineImageKeys = collectImageKeys();
    await setPromptAndSend(message.prompt);
    const imageUrl = await waitForNewImage(message.timeoutMs || 420000);
    if (!imageUrl) {
      throw new Error("没有检测到新生成图片");
    }
    return { ok: true, imageUrl };
  }

  async function attachImage(filePayload) {
    if (!filePayload || !filePayload.dataUrl) {
      throw new Error("缺少图片数据");
    }

    const input = await findFileInput();
    const file = dataUrlToFile(filePayload.dataUrl, filePayload.name, filePayload.type);
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await delay(2500);
  }

  async function findFileInput() {
    let input = findUsableFileInput();
    if (input) return input;

    const buttons = Array.from(document.querySelectorAll("button, [role='button']"));
    const attachButton = buttons.find((button) => {
      const label = `${button.getAttribute("aria-label") || ""} ${button.textContent || ""}`.toLowerCase();
      return label.includes("attach") || label.includes("upload") || label.includes("添加") || label.includes("上传") || label.includes("附件");
    });
    if (attachButton) {
      attachButton.click();
      await delay(800);
    }

    input = findUsableFileInput();
    if (!input) {
      throw new Error("没有找到 GPT 的图片上传入口，请确认页面已登录且输入框可用。");
    }
    return input;
  }

  function findUsableFileInput() {
    const inputs = Array.from(document.querySelectorAll("input[type='file']"));
    return inputs.find((input) => {
      const accept = String(input.accept || "").toLowerCase();
      return !input.disabled && (!accept || accept.includes("image") || accept.includes("*"));
    }) || inputs.find((input) => !input.disabled);
  }

  async function setPromptAndSend(prompt) {
    const composer = await waitForComposer();
    focusAndSetText(composer, prompt);
    await delay(250);
    const sendButton = await waitForSendButton();
    sendButton.click();
  }

  async function waitForComposer(timeoutMs = 30000) {
    return await waitFor(() => {
      const editable = Array.from(document.querySelectorAll("[contenteditable='true']")).find(isVisible);
      if (editable) return editable;
      return Array.from(document.querySelectorAll("textarea")).find(isVisible);
    }, timeoutMs, "没有找到 GPT 输入框");
  }

  function focusAndSetText(element, text) {
    element.focus();
    if (element.matches("textarea")) {
      element.value = text;
      element.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }

    element.textContent = "";
    const textNode = document.createTextNode(text);
    element.appendChild(textNode);
    element.dispatchEvent(new InputEvent("input", {
      bubbles: true,
      inputType: "insertText",
      data: text
    }));
  }

  async function waitForSendButton(timeoutMs = 30000) {
    return await waitFor(() => {
      const candidates = Array.from(document.querySelectorAll("button"));
      return candidates.find((button) => {
        if (!isVisible(button) || button.disabled || button.getAttribute("aria-disabled") === "true") return false;
        const label = `${button.getAttribute("aria-label") || ""} ${button.getAttribute("data-testid") || ""} ${button.textContent || ""}`.toLowerCase();
        return label.includes("send") || label.includes("发送") || label.includes("submit") || label.includes("composer-send");
      });
    }, timeoutMs, "发送按钮不可用");
  }

  async function waitForAssistantText(timeoutMs) {
    await waitUntilGeneratingStarts();
    await waitUntilGenerationSettles(timeoutMs);
    const messages = getAssistantMessages();
    const last = messages[messages.length - 1];
    return normalizeText(last ? last.innerText || last.textContent || "" : "");
  }

  async function waitForNewImage(timeoutMs) {
    await waitUntilGeneratingStarts();
    const started = Date.now();
    let lastFound = "";

    while (Date.now() - started < timeoutMs) {
      throwIfCancelled();
      const image = findNewestGeneratedImage();
      if (image) {
        lastFound = image;
      }

      const settled = !isGenerating();
      if (settled && lastFound) {
        return await normalizeImageUrl(lastFound);
      }

      await delay(1200);
    }

    if (lastFound) {
      return await normalizeImageUrl(lastFound);
    }
    throw new Error("等待生成图片超时");
  }

  async function waitUntilGeneratingStarts() {
    const started = Date.now();
    while (Date.now() - started < 12000) {
      throwIfCancelled();
      if (isGenerating()) return;
      await delay(300);
    }
  }

  async function waitUntilGenerationSettles(timeoutMs) {
    const started = Date.now();
    let stableSince = 0;
    let lastText = "";

    while (Date.now() - started < timeoutMs) {
      throwIfCancelled();
      const messages = getAssistantMessages();
      const last = messages[messages.length - 1];
      const text = normalizeText(last ? last.innerText || last.textContent || "" : "");

      if (text && text === lastText && !isGenerating()) {
        if (!stableSince) stableSince = Date.now();
        if (Date.now() - stableSince > 2200) return;
      } else {
        stableSince = 0;
        lastText = text;
      }

      await delay(700);
    }
    throw new Error("等待 GPT 回复超时");
  }

  function isGenerating() {
    const buttons = Array.from(document.querySelectorAll("button"));
    return buttons.some((button) => {
      if (!isVisible(button)) return false;
      const label = `${button.getAttribute("aria-label") || ""} ${button.getAttribute("data-testid") || ""} ${button.textContent || ""}`.toLowerCase();
      return label.includes("stop") || label.includes("停止") || label.includes("streaming");
    });
  }

  function clickStopButton() {
    const buttons = Array.from(document.querySelectorAll("button"));
    const stopButton = buttons.find((button) => {
      if (!isVisible(button) || button.disabled || button.getAttribute("aria-disabled") === "true") return false;
      const label = `${button.getAttribute("aria-label") || ""} ${button.getAttribute("data-testid") || ""} ${button.textContent || ""}`.toLowerCase();
      return label.includes("stop") || label.includes("停止");
    });
    if (stopButton) {
      stopButton.click();
    }
  }

  function throwIfCancelled() {
    if (state.cancelled) {
      throw new Error("已停止");
    }
  }

  function getAssistantMessages() {
    const assistantNodes = Array.from(document.querySelectorAll("[data-message-author-role='assistant']")).filter(isVisible);
    if (assistantNodes.length) {
      return assistantNodes;
    }

    return Array.from(document.querySelectorAll("[data-testid*='conversation-turn']"))
      .filter((node) => isVisible(node) && !String(node.textContent || "").includes("You said:"));
  }

  function collectImageKeys() {
    return new Set(Array.from(document.images).map(getImageKey).filter(Boolean));
  }

  function findNewestGeneratedImage() {
    const images = Array.from(document.images).filter(isVisible);
    for (let i = images.length - 1; i >= 0; i -= 1) {
      const img = images[i];
      const key = getImageKey(img);
      if (!key || state.baselineImageKeys.has(key)) continue;
      if (img.naturalWidth < 128 || img.naturalHeight < 128) continue;
      if (isLikelyAvatarOrIcon(img)) continue;
      return img.currentSrc || img.src;
    }
    return "";
  }

  function getImageKey(img) {
    return img.currentSrc || img.src || img.getAttribute("src") || "";
  }

  function isLikelyAvatarOrIcon(img) {
    const src = String(img.currentSrc || img.src || "").toLowerCase();
    const alt = String(img.alt || "").toLowerCase();
    if (src.startsWith("data:image/svg")) return true;
    if (alt.includes("avatar") || alt.includes("user")) return true;
    const rect = img.getBoundingClientRect();
    return rect.width < 128 || rect.height < 128;
  }

  async function normalizeImageUrl(url) {
    if (!url) return "";
    if (url.startsWith("data:")) return url;
    if (url.startsWith("blob:")) {
      const response = await fetch(url);
      const blob = await response.blob();
      return await blobToDataUrl(blob);
    }
    if (/^https?:/i.test(url)) {
      try {
        const response = await fetch(url, { credentials: "include" });
        const blob = await response.blob();
        if (blob && blob.size && String(blob.type || "").startsWith("image/")) {
          return await blobToDataUrl(blob);
        }
      } catch (_error) {
        // Fall back to the page URL; the backend may still be able to mirror it.
      }
    }
    return url;
  }

  function dataUrlToFile(dataUrl, name, type) {
    const parts = dataUrl.split(",");
    const header = parts[0] || "";
    const mime = type || (header.match(/data:([^;]+)/) || [])[1] || "image/png";
    const binary = atob(parts[1] || "");
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return new File([bytes], name || "image.png", { type: mime });
  }

  function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("图片转换失败"));
      reader.onload = () => resolve(reader.result);
      reader.readAsDataURL(blob);
    });
  }

  function normalizeText(text) {
    return String(text || "").replace(/\s+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function isVisible(element) {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  }

  async function waitFor(predicate, timeoutMs, errorMessage) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const result = predicate();
      if (result) return result;
      await delay(250);
    }
    throw new Error(errorMessage || "等待超时");
  }

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

})();
