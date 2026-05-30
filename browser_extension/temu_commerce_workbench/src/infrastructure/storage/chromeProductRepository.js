const DEFAULT_STORAGE_KEY = "temuWorkbenchProducts";

export function createChromeProductRepository(storageKey = DEFAULT_STORAGE_KEY) {
  return {
    async list() {
      return await loadProducts(storageKey);
    },

    async get(id) {
      const products = await loadProducts(storageKey);
      return products.find((product) => product.id === id) ?? null;
    },

    async save(product) {
      const products = await loadProducts(storageKey);
      const index = products.findIndex((entry) => entry.id === product.id);
      if (index === -1) {
        products.push(product);
      } else {
        products[index] = product;
      }
      await saveProducts(storageKey, products);
    },

    async update(id, updater) {
      const products = await loadProducts(storageKey);
      const index = products.findIndex((product) => product.id === id);
      if (index === -1) {
        throw new Error(`Product not found: ${id}`);
      }
      const next = typeof updater === "function" ? updater(structuredClone(products[index])) : {
        ...products[index],
        ...updater
      };
      products[index] = next;
      await saveProducts(storageKey, products);
      return structuredClone(next);
    },

    async replaceAll(products) {
      await saveProducts(storageKey, products);
    },

    async clear() {
      await saveProducts(storageKey, []);
    }
  };
}

async function loadProducts(storageKey) {
  const result = await chrome.storage.local.get(storageKey);
  const products = result[storageKey];
  return Array.isArray(products) ? structuredClone(products) : [];
}

async function saveProducts(storageKey, products) {
  await chrome.storage.local.set({
    [storageKey]: structuredClone(products)
  });
}
