import { ProductStatus } from "../../domain/product.js";
import { transitionProduct } from "../../domain/workflow.js";

export async function enrichProductFrom1688({ productId, productRepository, productSource1688 }) {
  const product = await productRepository.get(productId);
  if (!product) {
    throw new Error(`Product not found: ${productId}`);
  }

  const extracted = await productSource1688.extractCurrentPage();
  const source1688 = normalize1688Data(extracted);
  const enriched = transitionProduct(
    {
      ...product,
      source1688: {
        ...(product.source1688 ?? {}),
        ...source1688
      }
    },
    ProductStatus.Enriched1688,
    "1688 data enriched"
  );

  await productRepository.save(enriched);
  return enriched;
}

function normalize1688Data(data) {
  if (!data || typeof data !== "object") {
    throw new Error("1688 source returned no data");
  }

  const goodsPrice = optionalNumber(data.goodsPrice);
  const shippingFee = optionalNumber(data.shippingFee) ?? 0;
  const unitPrice = optionalNumber(data.unitPrice) ?? (
    goodsPrice === null ? null : goodsPrice + shippingFee
  );
  const weight = optionalNumber(data.weight);

  if (unitPrice === null) {
    throw new Error("当前 1688 页面没有可用单价，请手动填写。");
  }
  if (weight === null) {
    throw new Error("当前 1688 页面没有可用重量，请手动填写。");
  }

  return {
    url: String(data.url ?? "").trim(),
    goodsPrice,
    shippingFee,
    unitPrice,
    weight
  };
}

function optionalNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) {
    throw new Error(`Expected numeric 1688 value, got ${value}`);
  }
  return number;
}
