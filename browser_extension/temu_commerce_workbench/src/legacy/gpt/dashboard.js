import { readRowsFromBrowserFile } from "../../infrastructure/xlsx/browserXlsxSheetIO.js";
import { importTemplateMainImages } from "../../application/usecases/importTemplateMainImages.js";

const DEFAULT_PLAN_PROMPT = "请先观察这张图片，规划如何把它修改为 Temu 主图。目标市场是美国。要求：不要文字、不要水印、不要违规、不要夸大商品功能、突出商品主体、背景干净、适合作为电商主图。先只输出修改规划，不要生成图片。";
const DEFAULT_EXECUTE_PROMPT = "请按照上一步规划执行图片修改，生成最终 Temu 美国站主图。不要文字，不要水印，不要违规，保持商品真实，背景干净，突出商品主体。";
const CHATGPT_URL = "https://chatgpt.com/";
const WORKBENCH_API_BASE_URL = "http://127.0.0.1:8000";
const WORKBENCH_PROVIDER = "plugin_chatgpt_web";
const MAX_PULL_JOBS = 50;
const IMAGE_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp"]);
const MAX_QUEUE_IMAGES = 500;

const state = {
  items: [],
  running: false,
  processing: false,
  paused: false,
  stopRequested: false,
  activeIndex: -1,
  log: []
};

const els = {
  openChatgpt: document.getElementById("openChatgpt"),
  pullWorkbenchJobs: document.getElementById("pullWorkbenchJobs"),
  selectFolder: document.getElementById("selectFolder"),
  importTemplate: document.getElementById("importTemplate"),
  folderInput: document.getElementById("folderInput"),
  templateInput: document.getElementById("templateInput"),
  startBtn: document.getElementById("startBtn"),
  pauseBtn: document.getElementById("pauseBtn"),
  resumeBtn: document.getElementById("resumeBtn"),
  stopBtn: document.getElementById("stopBtn"),
  exportLogBtn: document.getElementById("exportLogBtn"),
  clearBtn: document.getElementById("clearBtn"),
  planTimeout: document.getElementById("planTimeout"),
  executeTimeout: document.getElementById("executeTimeout"),
  outputSuffix: document.getElementById("outputSuffix"),
  planPrompt: document.getElementById("planPrompt"),
  executePrompt: document.getElementById("executePrompt"),
  totalCount: document.getElementById("totalCount"),
  successCount: document.getElementById("successCount"),
  failedCount: document.getElementById("failedCount"),
  remainingCount: document.getElementById("remainingCount"),
  currentFile: document.getElementById("currentFile"),
  currentStage: document.getElementById("currentStage"),
  progressFill: document.getElementById("progressFill"),
  planPreview: document.getElementById("planPreview"),
  log: document.getElementById("log")
};

init();

async function init() {
  const saved = await chrome.storage.local.get(["planPrompt", "executePrompt", "planTimeout", "executeTimeout", "outputSuffix"]);
  els.planPrompt.value = saved.planPrompt || DEFAULT_PLAN_PROMPT;
  els.executePrompt.value = saved.executePrompt || DEFAULT_EXECUTE_PROMPT;
  els.planTimeout.value = saved.planTimeout || 240;
  els.executeTimeout.value = saved.executeTimeout || 420;
  els.outputSuffix.value = saved.outputSuffix || "_temu_main";

  for (const input of [els.planPrompt, els.executePrompt, els.planTimeout, els.executeTimeout, els.outputSuffix]) {
    input.addEventListener("change", saveSettings);
  }

  els.openChatgpt.addEventListener("click", () => {
    openChatgptTab().catch((error) => {
      addLog("bad", `打开 GPT 失败：${error.message || error}`);
      render();
    });
  });
  els.pullWorkbenchJobs.addEventListener("click", () => {
    pullWorkbenchJobs().catch((error) => {
      addLog("bad", `拉取工作台任务失败：${error.message || error}`);
      render();
    });
  });
  els.selectFolder.addEventListener("click", chooseFolderSafely);
  els.folderInput.addEventListener("change", loadFolder);
  els.importTemplate.addEventListener("click", () => els.templateInput.click());
  els.templateInput.addEventListener("change", loadTemplateWorkbook);
  els.startBtn.addEventListener("click", startQueue);
  els.pauseBtn.addEventListener("click", pauseQueue);
  els.resumeBtn.addEventListener("click", resumeQueue);
  els.stopBtn.addEventListener("click", stopQueue);
  els.clearBtn.addEventListener("click", clearQueue);
  els.exportLogBtn.addEventListener("click", exportLog);
  render();
}

async function saveSettings() {
  await chrome.storage.local.set({
    planPrompt: els.planPrompt.value.trim() || DEFAULT_PLAN_PROMPT,
    executePrompt: els.executePrompt.value.trim() || DEFAULT_EXECUTE_PROMPT,
    planTimeout: Number(els.planTimeout.value) || 240,
    executeTimeout: Number(els.executeTimeout.value) || 420,
    outputSuffix: els.outputSuffix.value.trim() || "_temu_main"
  });
}

async function chooseFolderSafely() {
  if ("showDirectoryPicker" in window) {
    await loadDirectoryWithPicker();
    return;
  }

  addLog("info", "当前浏览器不支持安全文件夹选择，改用多文件选择。");
  els.folderInput.click();
}

async function loadDirectoryWithPicker() {
  try {
    const rootHandle = await window.showDirectoryPicker({ mode: "read" });
    const items = [];
    let truncated = false;
    addLog("info", "正在扫描图片文件，请稍等。");
    render();

    for await (const entry of walkDirectory(rootHandle)) {
      if (!IMAGE_EXTENSIONS.has(getExtension(entry.name))) continue;
      items.push(makeQueueItem({
        id: `${Date.now()}-${items.length}`,
        file: null,
        handle: entry.handle,
        name: entry.name,
        path: entry.path
      }));

      if (items.length >= MAX_QUEUE_IMAGES) {
        truncated = true;
        break;
      }
    }

    items.sort((a, b) => a.path.localeCompare(b.path, "zh-Hans-CN"));
    resetQueue(items);
    if (truncated) {
      addLog("bad", `图片数量超过 ${MAX_QUEUE_IMAGES} 张，已只载入前 ${MAX_QUEUE_IMAGES} 张，避免浏览器崩溃。`);
    }
    addLog("info", `已安全载入 ${state.items.length} 张图片。`);
    render();
  } catch (error) {
    if (error && error.name === "AbortError") {
      addLog("info", "已取消选择文件夹。");
    } else {
      addLog("bad", `文件夹选择失败：${error.message || error}`);
    }
    render();
  }
}

async function* walkDirectory(directoryHandle, prefix = "") {
  let scanned = 0;
  for await (const [name, handle] of directoryHandle.entries()) {
    const path = prefix ? `${prefix}/${name}` : name;
    if (handle.kind === "file") {
      yield { name, path, handle };
    } else if (handle.kind === "directory") {
      yield* walkDirectory(handle, path);
    }

    scanned += 1;
    if (scanned % 25 === 0) {
      await delay(0);
    }
  }
}

function loadFolder(event) {
  const files = Array.from(event.target.files || [])
    .filter((file) => IMAGE_EXTENSIONS.has(getExtension(file.name)))
    .slice(0, MAX_QUEUE_IMAGES)
    .sort((a, b) => getDisplayPath(a).localeCompare(getDisplayPath(b), "zh-Hans-CN"));

  const items = files.map((file, index) => makeQueueItem({
    id: `${Date.now()}-${index}`,
    file,
    handle: null,
    name: file.name,
    path: getDisplayPath(file)
  }));
  resetQueue(items);
  addLog("info", `已载入 ${state.items.length} 张图片。`);
  render();
}

async function loadTemplateWorkbook(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  try {
    addLog("info", `正在读取模板 Excel：${file.name}`);
    render();

    const rows = await readRowsFromBrowserFile(file);
    const result = importTemplateMainImages(rows, {
      idPrefix: `template-${Date.now()}`
    });

    const items = result.items
      .slice(0, MAX_QUEUE_IMAGES)
      .map((item) => makeQueueItem({
        id: item.id,
        file: null,
        handle: null,
        name: item.name,
        path: `${file.name} 第 ${item.rowNumber} 行`,
        remoteUrl: item.imageUrl,
        uploadName: item.uploadName,
        meta: {
          sourceColumn: item.sourceColumn,
          identifier: item.identifier,
          title: item.title,
          rowNumber: item.rowNumber
        }
      }));

    if (!items.length) {
      throw new Error("模板中没有识别到可用的首张轮播图链接");
    }

    resetQueue(items);

    if (result.items.length > MAX_QUEUE_IMAGES) {
      addLog("bad", `模板中识别到 ${result.items.length} 张图片，已只载入前 ${MAX_QUEUE_IMAGES} 张。`);
    }

    addLog(
      "info",
      `模板导入完成：使用 ${result.summary.primaryImageColumn || result.summary.fallbackImageColumn}，共提取 ${items.length} 张首图。`
    );
  } catch (error) {
    addLog("bad", `模板导入失败：${error.message || error}`);
  } finally {
    els.templateInput.value = "";
    render();
  }
}

async function pullWorkbenchJobs() {
  if (state.processing) {
    addLog("bad", "当前队列正在处理，完成或停止后再拉取工作台任务。");
    render();
    return;
  }

  const items = [];
  for (let index = 0; index < MAX_PULL_JOBS; index += 1) {
    const response = await fetch(`${WORKBENCH_API_BASE_URL}/api/creative/plugin/jobs/next?provider=${encodeURIComponent(WORKBENCH_PROVIDER)}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const body = await response.json();
    const job = body.item;
    if (!job) break;
    if (!job.inputImageUrl) {
      await reportWorkbenchJobFailure(job.id, "任务缺少源图地址");
      continue;
    }

    items.push(makeQueueItem({
      id: job.id,
      file: null,
      handle: null,
      name: `${job.recordTitle || job.productId || job.recordId}-${job.imageIndex}-${job.imageLabel}.png`,
      path: `workbench/${job.recordId}/${job.imageKind}`,
      remoteUrl: job.inputImageUrl,
      uploadName: `${job.recordId}-${job.imageKind}.png`,
      meta: {
        source: "temu-listing-workbench",
        pluginJobId: job.id,
        recordId: job.recordId,
        imageKind: job.imageKind,
        imageLabel: job.imageLabel,
        imageIndex: job.imageIndex,
        prompt: job.prompt
      }
    }));
  }

  if (!items.length) {
    addLog("info", "暂无可处理的工作台生图任务。");
    render();
    return;
  }

  resetQueue(items);
  addLog("info", `已拉取 ${items.length} 个工作台生图任务。`);
  render();
}

function resetQueue(items) {
  state.items = items;
  state.running = false;
  state.paused = false;
  state.stopRequested = false;
  state.activeIndex = -1;
  state.log = [];
}

function makeQueueItem({ id, file, handle, name, path, remoteUrl = "", uploadName = "", meta = null }) {
  return {
    id,
    file,
    handle,
    name,
    path,
    remoteUrl,
    uploadName,
    meta,
    stage: "pending_plan",
    attempts: { plan: 0, execute: 0, download: 0 },
    planText: "",
    error: ""
  };
}

async function startQueue() {
  if (!state.items.length || state.running) return;
  state.running = true;
  state.paused = false;
  state.stopRequested = false;
  await saveSettings();
  render();
  processQueue();
}

function pauseQueue() {
  state.paused = true;
  addLog("info", "已请求暂停，当前图片处理完或失败后暂停。");
  render();
}

function resumeQueue() {
  if (!state.items.length) return;
  state.paused = false;
  state.running = true;
  state.stopRequested = false;
  addLog("info", "继续队列。");
  render();
  if (!state.processing) {
    processQueue();
  }
}

async function stopQueue() {
  state.stopRequested = true;
  state.running = false;
  state.paused = false;
  addLog("bad", "已请求停止，正在中断 GPT 当前生成。");
  render();

  try {
    const tab = await getChatgptTab();
    await sendToTab(tab.id, { type: "stopRun" }, 3000);
  } catch (error) {
    addLog("bad", `停止 GPT 生成时未收到确认：${error.message || error}`);
  }
  render();
}

function clearQueue() {
  if (state.processing) return;
  state.items = [];
  state.running = false;
  state.processing = false;
  state.paused = false;
  state.stopRequested = false;
  state.activeIndex = -1;
  state.log = [];
  els.folderInput.value = "";
  els.templateInput.value = "";
  render();
}

async function processQueue() {
  if (state.processing) return;

  state.processing = true;
  try {
    while (state.running && !state.paused && !state.stopRequested) {
      const nextIndex = state.items.findIndex((item) => item.stage !== "completed" && item.stage !== "failed");
      if (nextIndex === -1) {
        state.running = false;
        state.activeIndex = -1;
        addLog("ok", "队列完成。");
        render();
        return;
      }

      state.activeIndex = nextIndex;
      const item = state.items[nextIndex];
      await processItem(item);
      render();
    }
  } finally {
    state.processing = false;
    render();
  }
}

async function processItem(item) {
  try {
    await runPlanStage(item);
    if (state.paused || state.stopRequested) return;
    await runExecuteStage(item);
  } catch (error) {
    if (state.stopRequested) {
      item.stage = item.planText ? "planned" : "pending_plan";
      item.error = "";
      addLog("bad", `${item.name} 已停止，保留为未完成状态。`);
      return;
    }
    item.stage = "failed";
    item.error = String(error && error.message ? error.message : error);
    if (item.meta?.pluginJobId) {
      await reportWorkbenchJobFailure(item.meta.pluginJobId, item.error).catch(() => {});
    }
    addLog("bad", `${item.name} 失败：${item.error}`);
  }
}

function buildPlanPrompt(item) {
  const basePrompt = els.planPrompt.value.trim() || DEFAULT_PLAN_PROMPT;
  const jobPrompt = item.meta?.prompt ? `\n\n工作台任务要求：\n${item.meta.prompt}` : "";
  return `${basePrompt}${jobPrompt}`;
}

function buildExecutePrompt(item) {
  const basePrompt = els.executePrompt.value.trim() || DEFAULT_EXECUTE_PROMPT;
  const jobPrompt = item.meta?.prompt ? `\n\n请严格按这个工作台任务生成：\n${item.meta.prompt}` : "";
  return `${basePrompt}${jobPrompt}`;
}

async function runPlanStage(item) {
  for (;;) {
    if (state.stopRequested) throw new Error("已停止");
    try {
      item.stage = "planning";
      item.attempts.plan += 1;
      addLog("info", `${item.name} 开始规划，第 ${item.attempts.plan} 次。`);
      render();

      const tab = await prepareChatgptTab();
      const file = await getItemFile(item);
      const dataUrl = await fileToDataUrl(file);
      const response = await sendToTab(tab.id, {
        type: "runPlan",
        file: {
          name: file.name,
          type: file.type || guessMime(file.name),
          dataUrl
        },
        prompt: buildPlanPrompt(item),
        timeoutMs: Number(els.planTimeout.value) * 1000
      });

      if (!response || !response.ok || !response.planText) {
        throw new Error(response && response.error ? response.error : "规划没有返回文本");
      }

      item.stage = "planned";
      item.planText = response.planText;
      addLog("ok", `${item.name} 规划完成。`);
      render();
      return;
    } catch (error) {
      if (state.stopRequested) throw error;
      if (item.attempts.plan <= 1) {
        addLog("bad", `${item.name} 规划失败，准备重试：${error.message || error}`);
        continue;
      }
      throw new Error(`规划失败：${error.message || error}`);
    }
  }
}

async function runExecuteStage(item) {
  let imageUrl = "";

  for (;;) {
    if (state.stopRequested) throw new Error("已停止");
    try {
      item.stage = "executing";
      item.attempts.execute += 1;
      addLog("info", `${item.name} 开始执行，第 ${item.attempts.execute} 次。`);
      render();

      const tab = await getChatgptTab();
      const response = await sendToTab(tab.id, {
        type: "runExecute",
        prompt: buildExecutePrompt(item),
        timeoutMs: Number(els.executeTimeout.value) * 1000
      });

      if (!response || !response.ok || !response.imageUrl) {
        throw new Error(response && response.error ? response.error : "执行完成但没有检测到图片");
      }

      imageUrl = response.imageUrl;
      break;
    } catch (error) {
      if (state.stopRequested) throw error;
      if (item.attempts.execute <= 1) {
        addLog("bad", `${item.name} 执行失败，准备重试：${error.message || error}`);
        continue;
      }
      throw new Error(`执行失败：${error.message || error}`);
    }
  }

  await downloadResult(item, imageUrl);
  item.stage = "completed";
  addLog("ok", item.meta?.pluginJobId ? `${item.name} 已完成并回传工作台。` : `${item.name} 已完成并下载。`);
}

async function downloadResult(item, imageUrl) {
  for (;;) {
    if (state.stopRequested) throw new Error("已停止");
    try {
      item.stage = "downloading";
      item.attempts.download += 1;
      render();
      if (item.meta?.pluginJobId) {
        await uploadResultToWorkbench(item.meta.pluginJobId, imageUrl);
        return;
      }

      const filename = makeOutputFilename(item.name);
      const response = await chrome.runtime.sendMessage({
        type: "downloadImage",
        url: imageUrl,
        filename
      });

      if (!response || !response.ok) {
        throw new Error(response && response.error ? response.error : "下载失败");
      }
      return;
    } catch (error) {
      if (state.stopRequested) throw error;
      if (item.attempts.download <= 1) {
        addLog("bad", `${item.name} 下载失败，准备重试：${error.message || error}`);
        continue;
      }
      throw new Error(`下载失败：${error.message || error}`);
    }
  }
}

async function uploadResultToWorkbench(jobId, imageUrl) {
  const payload = String(imageUrl || "").startsWith("data:")
    ? { image_data_url: imageUrl }
    : { image_url: imageUrl };
  const response = await fetch(`${WORKBENCH_API_BASE_URL}/api/creative/plugin/jobs/${encodeURIComponent(jobId)}/result`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const message = await readWorkbenchError(response);
    throw new Error(`回传工作台失败：${message}`);
  }
  return await response.json();
}

async function reportWorkbenchJobFailure(jobId, errorMessage) {
  const response = await fetch(`${WORKBENCH_API_BASE_URL}/api/creative/plugin/jobs/${encodeURIComponent(jobId)}/result`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ error_message: String(errorMessage || "插件处理失败") })
  });
  if (!response.ok) {
    throw new Error(await readWorkbenchError(response));
  }
  return await response.json();
}

async function readWorkbenchError(response) {
  try {
    const body = await response.json();
    return body.detail || response.statusText;
  } catch {
    return response.statusText;
  }
}

async function openChatgptTab() {
  const tab = await prepareChatgptTab();
  await safeUpdateTab(tab.id, { active: true });
}

async function prepareChatgptTab() {
  const existing = await getChatgptTab().catch(() => null);
  const tab = existing || await chrome.tabs.create({ url: CHATGPT_URL, active: true });

  if (existing) {
    await safeUpdateTab(tab.id, { active: true });
  } else {
    await safeUpdateTab(tab.id, { url: CHATGPT_URL, active: true });
  }

  await waitForTabComplete(tab.id);
  await ensureContentScript(tab.id);
  await waitForContentReady(tab.id);
  return await safeGetTab(tab.id);
}

async function getChatgptTab() {
  const tabs = await chrome.tabs.query({ url: ["https://chatgpt.com/*", "https://chat.openai.com/*"] });
  if (!tabs.length) {
    throw new Error("未找到 GPT 页面，请先打开并登录 ChatGPT。");
  }
  return tabs[0];
}

function waitForTabComplete(tabId) {
  return new Promise((resolve) => {
    const timer = setTimeout(done, 15000);

    function done() {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }

    function listener(updatedTabId, info) {
      if (updatedTabId === tabId && info.status === "complete") {
        done();
      }
    }

    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError) {
        done();
        return;
      }
      if (tab && tab.status === "complete") {
        done();
      }
    });
  });
}

async function ensureContentScript(tabId) {
  try {
    await sendToTab(tabId, { type: "ping" }, 1500);
  } catch {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["src/legacy/gpt/contentScript.js"]
    });
  }
}

async function waitForContentReady(tabId) {
  const started = Date.now();
  while (Date.now() - started < 30000) {
    try {
      const response = await sendToTab(tabId, { type: "ping" }, 1500);
      if (response && response.ok) return;
    } catch {
      await delay(500);
    }
  }
  throw new Error("GPT 页面脚本未就绪。");
}

function sendToTab(tabId, message, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("页面响应超时")), timeoutMs || (message.timeoutMs || 30000) + 15000);
    chrome.tabs.sendMessage(tabId, message, (response) => {
      clearTimeout(timer);
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
        return;
      }
      resolve(response);
    });
  });
}

async function safeGetTab(tabId) {
  try {
    return await chrome.tabs.get(tabId);
  } catch (error) {
    throw new Error(`GPT 标签页不可用，请重新打开 GPT：${error.message || error}`);
  }
}

async function safeUpdateTab(tabId, updateInfo) {
  try {
    return await chrome.tabs.update(tabId, updateInfo);
  } catch (error) {
    throw new Error(`GPT 标签页已关闭或不可用，请重新打开 GPT：${error.message || error}`);
  }
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("读取图片失败"));
    reader.onload = () => resolve(reader.result);
    reader.readAsDataURL(file);
  });
}

async function getItemFile(item) {
  if (item.file) return item.file;
  if (item.remoteUrl) {
    const file = await fetchRemoteImageAsFile(item);
    item.file = file;
    return file;
  }
  if (!item.handle || !item.handle.getFile) {
    throw new Error("图片文件句柄不可用，请重新选择文件夹。");
  }
  const file = await item.handle.getFile();
  item.name = file.name || item.name;
  item.file = file;
  return file;
}

async function fetchRemoteImageAsFile(item) {
  const response = await fetch(item.remoteUrl, {
    credentials: "omit",
    referrerPolicy: "no-referrer"
  });
  if (!response.ok) {
    throw new Error(`下载源图片失败：HTTP ${response.status}`);
  }

  const blob = await response.blob();
  if (!blob.size) {
    throw new Error("下载源图片失败：返回内容为空");
  }

  if (needsImageConversion(blob.type, item.remoteUrl)) {
    return await convertBlobToPngFile(blob, item.name);
  }

  const fileName = item.uploadName || buildFetchedImageName(item.name, blob.type, item.remoteUrl);
  const fileType = blob.type || guessMime(fileName);
  return new File([blob], fileName, { type: fileType });
}

function makeOutputFilename(name) {
  const suffix = els.outputSuffix.value.trim() || "_temu_main";
  const dot = name.lastIndexOf(".");
  if (dot === -1) return `${name}${suffix}.png`;
  return `${name.slice(0, dot)}${suffix}${name.slice(dot)}`;
}

function getDisplayPath(file) {
  return file.webkitRelativePath || file.name;
}

function getExtension(name) {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
}

function guessMime(name) {
  const ext = getExtension(name);
  if (ext === "jpg" || ext === "jpeg") return "image/jpeg";
  if (ext === "webp") return "image/webp";
  if (ext === "gif") return "image/gif";
  if (ext === "avif") return "image/avif";
  return "image/png";
}

function buildFetchedImageName(baseName, mimeType, url) {
  const extension = extensionFromMime(mimeType) || getExtensionFromUrl(url) || "png";
  const normalizedBaseName = String(baseName || "template_image")
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\.[a-z0-9]{2,5}$/i, "")
    .trim() || "template_image";
  return `${normalizedBaseName}.${extension}`;
}

function extensionFromMime(mimeType) {
  const normalized = String(mimeType || "").toLowerCase();
  if (normalized.includes("jpeg")) return "jpg";
  if (normalized.includes("png")) return "png";
  if (normalized.includes("webp")) return "webp";
  if (normalized.includes("gif")) return "gif";
  if (normalized.includes("avif")) return "avif";
  return "";
}

function getExtensionFromUrl(url) {
  try {
    const parsed = new URL(url);
    return getExtension(parsed.pathname);
  } catch {
    return getExtension(String(url || "").split(/[?#]/, 1)[0]);
  }
}

function needsImageConversion(mimeType, url) {
  const extension = extensionFromMime(mimeType) || getExtensionFromUrl(url);
  return Boolean(extension && !["jpg", "jpeg", "png", "webp", "gif"].includes(extension));
}

async function convertBlobToPngFile(blob, baseName) {
  const bitmap = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;

  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("图片转换失败：无法创建画布上下文");
  }

  context.drawImage(bitmap, 0, 0);
  bitmap.close();

  const pngBlob = await new Promise((resolve, reject) => {
    canvas.toBlob((result) => {
      if (!result) {
        reject(new Error("图片转换失败：无法导出 PNG"));
        return;
      }
      resolve(result);
    }, "image/png");
  });

  return new File([pngBlob], buildFetchedImageName(baseName, "image/png", ""), { type: "image/png" });
}

function addLog(level, text) {
  state.log.unshift({
    level,
    text,
    time: new Date().toLocaleTimeString()
  });
}

function exportLog() {
  const rows = state.items.map((item) => ({
    name: item.name,
    path: item.path,
    remoteUrl: item.remoteUrl || "",
    sourceColumn: item.meta?.sourceColumn || "",
    stage: item.stage,
    planAttempts: item.attempts.plan,
    executeAttempts: item.attempts.execute,
    downloadAttempts: item.attempts.download,
    error: item.error,
    planText: item.planText
  }));
  const payload = JSON.stringify({ exportedAt: new Date().toISOString(), rows, log: state.log }, null, 2);
  const url = URL.createObjectURL(new Blob([payload], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `temu-gpt-log-${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function render() {
  const total = state.items.length;
  const success = state.items.filter((item) => item.stage === "completed").length;
  const failed = state.items.filter((item) => item.stage === "failed").length;
  const remaining = total - success - failed;
  const current = state.items[state.activeIndex];

  els.totalCount.textContent = total;
  els.successCount.textContent = success;
  els.failedCount.textContent = failed;
  els.remainingCount.textContent = remaining;
  els.currentFile.textContent = current ? current.name : "未开始";
  els.currentStage.textContent = current ? stageLabel(current.stage) : (total ? "等待开始" : "等待选择文件夹");
  els.progressFill.style.width = total ? `${Math.round(((success + failed) / total) * 100)}%` : "0";
  els.planPreview.textContent = current && current.planText ? current.planText : "暂无规划。";

  els.startBtn.disabled = !total || state.running;
  els.pullWorkbenchJobs.disabled = state.processing;
  els.pauseBtn.disabled = !state.running || state.paused;
  els.resumeBtn.disabled = !total || !state.paused;
  els.stopBtn.disabled = !state.running && !state.processing && !state.paused;
  els.clearBtn.disabled = !total || state.processing;
  els.exportLogBtn.disabled = !total && !state.log.length;

  els.log.innerHTML = "";
  for (const entry of state.log.slice(0, 120)) {
    const row = document.createElement("div");
    row.className = `log-entry ${entry.level === "ok" ? "ok" : entry.level === "bad" ? "bad" : ""}`;
    row.innerHTML = `<strong>${entry.time}</strong><span></span>`;
    row.querySelector("span").textContent = entry.text;
    els.log.appendChild(row);
  }
}

function stageLabel(stage) {
  const labels = {
    pending_plan: "等待规划",
    planning: "规划中",
    planned: "规划完成",
    executing: "执行中",
    downloading: "下载中",
    completed: "已完成",
    failed: "失败"
  };
  return labels[stage] || stage;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
