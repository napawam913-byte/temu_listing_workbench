import { ProductStatus } from "./product.js";

const ALLOWED_TRANSITIONS = Object.freeze({
  [ProductStatus.Imported]: new Set([ProductStatus.Enriched1688, ProductStatus.Failed]),
  [ProductStatus.Enriched1688]: new Set([ProductStatus.Enriched1688, ProductStatus.Priced, ProductStatus.Failed]),
  [ProductStatus.Priced]: new Set([ProductStatus.Enriched1688, ProductStatus.Priced, ProductStatus.ImageGenerated, ProductStatus.Exported, ProductStatus.Failed]),
  [ProductStatus.ImageGenerated]: new Set([ProductStatus.Exported, ProductStatus.Failed]),
  [ProductStatus.Exported]: new Set([]),
  [ProductStatus.Failed]: new Set([ProductStatus.Imported, ProductStatus.Enriched1688, ProductStatus.Priced])
});

export function transitionProduct(product, nextStatus, message = "") {
  const allowed = ALLOWED_TRANSITIONS[product.status];
  if (!allowed || !allowed.has(nextStatus)) {
    throw new Error(`Cannot transition product from ${product.status} to ${nextStatus}`);
  }

  return {
    ...product,
    status: nextStatus,
    logs: [
      ...(product.logs ?? []),
      {
        at: new Date().toISOString(),
        status: nextStatus,
        message
      }
    ]
  };
}
