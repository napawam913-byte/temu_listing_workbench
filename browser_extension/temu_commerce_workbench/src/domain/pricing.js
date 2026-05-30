export const DEFAULT_PRICING_CONFIG = Object.freeze({
  firstLegSurcharge: 7.5,
  firstLegPricePerKg: 80,
  lastLegFee: 23,
  lastLegSubsidy: 21,
  afterSalesRate: 0.05,
  discountRate: 1
});

export function calculatePricing(input, config = DEFAULT_PRICING_CONFIG) {
  const quotedPrice = requirePositiveNumber(input.quotedPrice, "quotedPrice");
  const unitPrice = requirePositiveNumber(input.unitPrice, "unitPrice");
  const weight = requireNonNegativeNumber(input.weight, "weight");
  const quantity = requirePositiveNumber(input.quantity ?? 1, "quantity");
  const discountRate = requirePositiveNumber(input.discountRate ?? config.discountRate, "discountRate");

  const afterSalesRate = requireRate(config.afterSalesRate, "afterSalesRate");
  const firstLegSurcharge = requireNonNegativeNumber(config.firstLegSurcharge, "firstLegSurcharge");
  const firstLegPricePerKg = requireNonNegativeNumber(config.firstLegPricePerKg, "firstLegPricePerKg");
  const lastLegFee = requireNonNegativeNumber(config.lastLegFee, "lastLegFee");
  const lastLegSubsidy = requireNonNegativeNumber(config.lastLegSubsidy, "lastLegSubsidy");

  const actualPrice = quotedPrice * discountRate * quantity;
  const totalWeight = weight * quantity;
  const firstLegFee = firstLegSurcharge + firstLegPricePerKg * totalWeight;
  const firstLegCost = unitPrice * quantity + firstLegFee;
  const lastLegCost = (lastLegFee - lastLegSubsidy) * quantity;
  const profit = actualPrice - firstLegCost - lastLegCost;
  const cargoLoss = firstLegCost + lastLegFee * quantity;
  const actualProfit = profit * (1 - afterSalesRate) - cargoLoss * afterSalesRate;
  const roiBase = firstLegCost + lastLegCost;

  if (roiBase === 0) {
    throw new Error("roiBase must not be zero");
  }

  return {
    actualPrice: roundMoney(actualPrice),
    firstLegFee: roundMoney(firstLegFee),
    firstLegCost: roundMoney(firstLegCost),
    lastLegCost: roundMoney(lastLegCost),
    profit: roundMoney(profit),
    cargoLoss: roundMoney(cargoLoss),
    actualProfit: roundMoney(actualProfit),
    roi: profit / roiBase,
    margin: profit / actualPrice
  };
}

function requirePositiveNumber(value, fieldName) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    throw new Error(`${fieldName} must be a positive number`);
  }
  return number;
}

function requireNonNegativeNumber(value, fieldName) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) {
    throw new Error(`${fieldName} must be a non-negative number`);
  }
  return number;
}

function requireRate(value, fieldName) {
  const number = requireNonNegativeNumber(value, fieldName);
  if (number > 1) {
    throw new Error(`${fieldName} must be between 0 and 1`);
  }
  return number;
}

function roundMoney(value) {
  return Number(value.toFixed(2));
}
