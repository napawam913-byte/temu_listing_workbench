export function productsToT2JsonRecords(products, now = new Date()) {
  const savedAt = now.toISOString();
  return products.map((product) => ({
    id: product.id ?? `t2-${product.skc}`,
    name: product.name ?? "",
    skc: product.skc ?? "",
    quotedPrice: product.quotedPrice ?? "",
    quoted_price: product.quotedPrice === undefined || product.quotedPrice === null
      ? ""
      : String(product.quotedPrice),
    imageUrl: product.imageUrl ?? "",
    image_url: product.imageUrl ?? "",
    status: product.status ?? "imported",
    source: "t2-intersection",
    savedAt
  }));
}

export function mergeJsonRecordsBySkc(existingRecords, incomingRecords) {
  const incomingSkcs = new Set(incomingRecords.map(recordSkc).filter(Boolean));
  const existingByIncomingSkc = new Map();
  const preservedRecords = [];

  for (const record of existingRecords) {
    const skc = recordSkc(record);
    if (skc && incomingSkcs.has(skc)) {
      existingByIncomingSkc.set(skc, record);
      continue;
    }
    preservedRecords.push(record);
  }

  let addedCount = 0;
  let updatedCount = 0;
  const mergedIncomingRecords = incomingRecords.map((incomingRecord) => {
    const skc = recordSkc(incomingRecord);
    if (!skc) {
      addedCount += 1;
      return incomingRecord;
    }

    const existingRecord = existingByIncomingSkc.get(skc);
    if (!existingRecord) {
      addedCount += 1;
      return incomingRecord;
    }

    updatedCount += 1;
    return {
      ...existingRecord,
      ...incomingRecord,
      updatedAt: incomingRecord.savedAt ?? new Date().toISOString()
    };
  });

  return {
    records: [...preservedRecords, ...mergedIncomingRecords],
    addedCount,
    updatedCount
  };
}

function recordSkc(record) {
  return String(record?.skc ?? "").trim();
}
