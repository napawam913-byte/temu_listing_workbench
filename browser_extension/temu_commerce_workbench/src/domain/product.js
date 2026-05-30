export const ProductStatus = Object.freeze({
  Imported: "imported",
  Enriched1688: "enriched_1688",
  Priced: "priced",
  ImageGenerated: "image_generated",
  Exported: "exported",
  Failed: "failed"
});

export function createImportedProduct({ id, name, skc, quotedPrice, imageUrl }) {
  if (!id) throw new Error("Product id is required");
  if (!skc) throw new Error("Product SKC is required");
  if (!Number.isFinite(Number(quotedPrice))) throw new Error("Product quotedPrice must be numeric");

  return {
    id,
    name: String(name ?? "").trim(),
    skc: String(skc).trim(),
    quotedPrice: Number(quotedPrice),
    imageUrl: String(imageUrl ?? "").trim(),
    source1688: {},
    pricing: null,
    mainImage: {
      status: "pending"
    },
    status: ProductStatus.Imported,
    logs: []
  };
}
