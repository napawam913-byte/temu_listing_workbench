const DB_NAME = "recorder-local-store";
const STORE_NAME = "settings";
const JSON_FILE_HANDLE_KEY = "json-file-handle";
const JSON_FILE_META_KEY = "json-file-meta";

function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);

    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("打开本地设置数据库失败。"));
  });
}

async function withStore(mode, callback) {
  const db = await openDatabase();

  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, mode);
    const store = transaction.objectStore(STORE_NAME);

    let result;
    try {
      result = callback(store);
    } catch (error) {
      reject(error);
      return;
    }

    transaction.oncomplete = () => resolve(result);
    transaction.onerror = () => reject(transaction.error ?? new Error("本地设置写入失败。"));
  });
}

async function saveValue(key, value) {
  await withStore("readwrite", (store) => {
    store.put(value, key);
  });
}

async function loadValue(key, fallbackValue) {
  try {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, "readonly");
      const store = transaction.objectStore(STORE_NAME);
      const request = store.get(key);

      request.onsuccess = () => resolve(request.result ?? fallbackValue);
      request.onerror = () => reject(request.error ?? new Error("读取本地设置失败。"));
    });
  } catch (_error) {
    return fallbackValue;
  }
}

export async function saveJsonFileHandle(handle) {
  await saveValue(JSON_FILE_HANDLE_KEY, handle ?? null);
}

export async function loadJsonFileHandle() {
  return loadValue(JSON_FILE_HANDLE_KEY, null);
}

export async function clearJsonFileHandle() {
  await saveJsonFileHandle(null);
}

export async function saveJsonFileMeta(meta) {
  await saveValue(JSON_FILE_META_KEY, meta ?? null);
}

export async function loadJsonFileMeta() {
  return loadValue(JSON_FILE_META_KEY, null);
}
