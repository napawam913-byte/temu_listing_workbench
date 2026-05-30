export const PRODUCT_EXPORT_HEADERS = [
  "NAME",
  "SKC",
  "imageUrl",
  "quotedPrice",
  "1688Url",
  "goodsPrice",
  "shippingFee",
  "unitPrice",
  "weight",
  "quantity",
  "discountRate",
  "profit",
  "actualProfit",
  "roi",
  "margin",
  "status"
];

export function productsToSheetRows(products) {
  return [
    PRODUCT_EXPORT_HEADERS,
    ...products.map(productToRow)
  ];
}

function productToRow(product) {
  const source1688 = product.source1688 ?? {};
  const pricing = product.pricing ?? {};
  return [
    product.name ?? "",
    product.skc ?? "",
    product.imageUrl ?? "",
    product.quotedPrice ?? "",
    source1688.url ?? "",
    source1688.goodsPrice ?? "",
    source1688.shippingFee ?? "",
    source1688.unitPrice ?? "",
    source1688.weight ?? "",
    pricing.quantity ?? "",
    pricing.discountRate ?? "",
    pricing.profit ?? "",
    pricing.actualProfit ?? "",
    pricing.roi ?? "",
    pricing.margin ?? "",
    product.status ?? ""
  ];
}
