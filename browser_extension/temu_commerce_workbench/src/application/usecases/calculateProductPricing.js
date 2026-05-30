import { calculatePricing } from "../../domain/pricing.js";
import { ProductStatus } from "../../domain/product.js";
import { transitionProduct } from "../../domain/workflow.js";

export async function calculateProductPricing({
  productId,
  productRepository,
  config,
  quantity = 1,
  discountRate
}) {
  const product = await productRepository.get(productId);
  if (!product) {
    throw new Error(`Product not found: ${productId}`);
  }

  const source1688 = product.source1688 ?? {};
  const pricing = calculatePricing({
    quotedPrice: product.quotedPrice,
    unitPrice: source1688.unitPrice,
    weight: source1688.weight,
    quantity,
    discountRate
  }, config);

  const priced = transitionProduct(
    {
      ...product,
      pricing: {
        quantity,
        discountRate: discountRate ?? config?.discountRate ?? 1,
        ...pricing
      }
    },
    ProductStatus.Priced,
    "Pricing calculated"
  );

  await productRepository.save(priced);
  return priced;
}
