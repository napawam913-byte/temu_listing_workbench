const STALE_FILE_STATE_TEXT = "state cached in an interface object";
const STALE_FILE_STATE_MESSAGE =
  "本地 JSON 文件刚被外部程序或同步工具改动，浏览器缓存已失效。请点击“绑定 JSON”重新选择 records.json 后再试。";

export function isStaleFileStateError(error) {
  const message = String(error?.message || error || "");
  return message.includes(STALE_FILE_STATE_TEXT);
}

export async function readJsonRecordsFromFileHandle(handle) {
  const text = await withFreshFileStateRetry(async () => {
    const file = await handle.getFile();
    return file.text();
  });

  if (!text.trim()) {
    return [];
  }

  let data;
  try {
    data = JSON.parse(text);
  } catch (error) {
    throw new Error(`JSON 文件解析失败：${error.message}`);
  }

  if (!Array.isArray(data)) {
    throw new Error("JSON 文件格式不正确，根节点必须是数组。");
  }

  return data;
}

export async function writeJsonRecordsToFileHandle(handle, records) {
  const text = `${JSON.stringify(records, null, 2)}\n`;
  await withFreshFileStateRetry(async () => {
    const writable = await handle.createWritable();
    let closed = false;

    try {
      await writable.write(text);
      await writable.close();
      closed = true;
    } catch (error) {
      if (!closed && typeof writable.abort === "function") {
        try {
          await writable.abort();
        } catch (_abortError) {
          // Ignore abort failures; the original write/close error is more useful.
        }
      }
      throw error;
    }
  });
}

async function withFreshFileStateRetry(operation) {
  let staleError = null;

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      if (!isStaleFileStateError(error)) {
        throw error;
      }
      staleError = error;
      await Promise.resolve();
    }
  }

  const error = new Error(STALE_FILE_STATE_MESSAGE);
  error.cause = staleError;
  throw error;
}
