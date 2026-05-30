export function createMemoryProductRepository(initialProducts = []) {
  const productsById = new Map(initialProducts.map((product) => [product.id, structuredClone(product)]));

  return {
    async list() {
      return Array.from(productsById.values()).map((product) => structuredClone(product));
    },

    async get(id) {
      const product = productsById.get(id);
      return product ? structuredClone(product) : null;
    },

    async save(product) {
      productsById.set(product.id, structuredClone(product));
    },

    async update(id, updater) {
      const existing = productsById.get(id);
      if (!existing) {
        throw new Error(`Product not found: ${id}`);
      }
      const next = typeof updater === "function"
        ? updater(structuredClone(existing))
        : { ...existing, ...updater };
      productsById.set(id, structuredClone(next));
      return structuredClone(next);
    }
  };
}
