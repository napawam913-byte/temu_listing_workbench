export async function loadConfig() {
  const response = await fetch(chrome.runtime.getURL("config.json"));
  if (!response.ok) {
    throw new Error("读取 config.json 失败。");
  }

  const config = await response.json();
  validateConfig(config);
  return config;
}

export function validateConfig(config) {
  const requiredKeys = [
    "first_leg_surcharge",
    "first_leg_price_per_kg",
    "last_leg_fee",
    "last_leg_subsidy",
    "after_sales_rate",
    "discount_rate"
  ];

  for (const key of requiredKeys) {
    if (!(key in config)) {
      throw new Error(`config.json 缺少字段: ${key}`);
    }

    const value = Number(config[key]);
    if (!Number.isFinite(value)) {
      throw new Error(`config.json 字段 ${key} 必须是数字。`);
    }
  }

  if (config.after_sales_rate < 0 || config.after_sales_rate > 1) {
    throw new Error("after_sales_rate 必须在 0 到 1 之间。");
  }

  if (config.discount_rate < 0) {
    throw new Error("discount_rate 不能为负数。");
  }
}

export function parseNumber(value, fieldName) {
  const text = String(value ?? "").trim();
  if (!text) {
    throw new Error(`${fieldName} 不能为空。`);
  }

  const numeric = Number(text);
  if (!Number.isFinite(numeric)) {
    throw new Error(`${fieldName} 必须是数字。`);
  }

  if (numeric < 0) {
    throw new Error(`${fieldName} 不能为负数。`);
  }

  return numeric;
}

export function money(value) {
  return Number(value).toFixed(2);
}

export function percent(value) {
  return `${money(value * 100)}%`;
}

export function calculateProfit({
  quotedPrice,
  unitPrice,
  weight,
  quantity = 1,
  discountRate,
  config
}) {
  if (discountRate <= 0) {
    throw new Error("折扣率必须大于 0。");
  }

  if (quantity <= 0) {
    throw new Error("倍数必须大于 0。");
  }

  const actualPrice = quotedPrice * discountRate * quantity;
  if (actualPrice <= 0) {
    throw new Error("核价必须大于 0。");
  }

  const totalWeight = weight * quantity;
  const firstLegFee = Number(config.first_leg_surcharge) + Number(config.first_leg_price_per_kg) * totalWeight;
  const firstLegCost = unitPrice * quantity + firstLegFee;
  const lastLegCost = (Number(config.last_leg_fee) - Number(config.last_leg_subsidy)) * quantity;
  const profit = actualPrice - firstLegCost - lastLegCost;
  const cargoLoss = firstLegCost + Number(config.last_leg_fee) * quantity;
  const actualProfit = profit * (1 - Number(config.after_sales_rate)) - cargoLoss * Number(config.after_sales_rate);
  const roiBase = firstLegCost + lastLegCost;

  if (roiBase === 0) {
    throw new Error("成本不能为 0。");
  }

  return {
    actualPrice,
    firstLegFee,
    firstLegCost,
    lastLegCost,
    profit,
    cargoLoss,
    actualProfit,
    roi: profit / roiBase,
    margin: profit / actualPrice
  };
}
