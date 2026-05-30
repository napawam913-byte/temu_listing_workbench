import { createImportedProduct } from "../../domain/product.js";

export const DEFAULT_T2_MAPPING = Object.freeze({
  infoNameColumn: 1,
  infoImageColumn: 10,
  infoSkcColumn: 56,
  priceSkcColumn: 1,
  priceQuotedPriceColumn: 7
});

export function importT2Products({ infoRows, priceRows, mapping = DEFAULT_T2_MAPPING, idPrefix = "t2" }) {
  const priceMapping = loadPriceMapping(priceRows, mapping);
  const priceBySkc = priceMapping.priceBySkc;
  const infoItems = loadInfoItems(infoRows, mapping);

  const products = [];
  for (const item of infoItems) {
    const quotedPrice = priceBySkc.get(item.skc);
    if (quotedPrice === undefined) continue;

    products.push(createImportedProduct({
      id: `${idPrefix}-${item.skc}`,
      name: item.name,
      skc: item.skc,
      quotedPrice,
      imageUrl: item.imageUrl
    }));
  }

  return {
    products,
    summary: {
      infoRowCount: Math.max(0, infoRows.length - 1),
      infoUniqueSkcCount: infoItems.length,
      priceUniqueSkcCount: priceBySkc.size,
      matchedProductCount: products.length,
      duplicatePriceSkcCount: priceMapping.duplicateSkcCount,
      duplicatePriceRowCount: priceMapping.duplicateSkcRows.length
    },
    duplicatePriceSkcs: priceMapping.duplicateSkcs,
    duplicatePriceSkcRows: priceMapping.duplicateSkcRows,
    priceHeaderRow: priceMapping.priceHeaderRow
  };
}

function loadPriceMapping(rows, mapping) {
  const recordsBySkc = new Map();
  for (const [index, row] of rows.slice(1).entries()) {
    const skc = normalizeSkc(cell(row, mapping.priceSkcColumn));
    const quotedPrice = normalizePrice(cell(row, mapping.priceQuotedPriceColumn));
    if (!skc) continue;

    if (!recordsBySkc.has(skc)) {
      recordsBySkc.set(skc, []);
    }
    recordsBySkc.get(skc).push({
      skc,
      rowNumber: index + 2,
      occurrenceCount: 1,
      rawQuotedPrice: normalizeText(cell(row, mapping.priceQuotedPriceColumn)),
      quotedPrice,
      selectedQuotedPrice: null,
      isSelectedMax: false,
      cells: [...row]
    });
  }

  const priceBySkc = new Map();
  const duplicateSkcs = [];
  const duplicateSkcRows = [];
  let duplicateSkcCount = 0;
  for (const [skc, records] of recordsBySkc.entries()) {
    const validPrices = records
      .map((record) => record.quotedPrice)
      .filter((price) => price !== null);
    const selectedQuotedPrice = validPrices.length ? Math.max(...validPrices) : undefined;
    if (selectedQuotedPrice !== undefined) {
      priceBySkc.set(skc, selectedQuotedPrice);
    }

    if (records.length <= 1) continue;
    duplicateSkcCount += 1;
    duplicateSkcs.push({
      skc,
      occurrenceCount: records.length,
      rowNumbers: records.map((record) => record.rowNumber),
      quotedPrices: records.map((record) => record.quotedPrice),
      rawQuotedPrices: records.map((record) => record.rawQuotedPrice),
      selectedQuotedPrice: selectedQuotedPrice ?? null,
      selectedRowNumbers: records
        .filter((record) => record.quotedPrice !== null && record.quotedPrice === selectedQuotedPrice)
        .map((record) => record.rowNumber)
    });
    for (const record of records) {
      duplicateSkcRows.push({
        ...record,
        occurrenceCount: records.length,
        selectedQuotedPrice: selectedQuotedPrice ?? null,
        isSelectedMax: record.quotedPrice !== null && record.quotedPrice === selectedQuotedPrice
      });
    }
  }

  return {
    priceBySkc,
    duplicateSkcCount,
    duplicateSkcs,
    duplicateSkcRows,
    priceHeaderRow: Array.isArray(rows[0]) ? [...rows[0]] : []
  };
}

function loadInfoItems(rows, mapping) {
  const result = [];
  const seen = new Set();
  for (const row of rows.slice(1)) {
    const skc = normalizeSkc(cell(row, mapping.infoSkcColumn));
    if (!skc || seen.has(skc)) continue;
    seen.add(skc);
    result.push({
      skc,
      name: normalizeText(cell(row, mapping.infoNameColumn)),
      imageUrl: firstImageUrl(cell(row, mapping.infoImageColumn))
    });
  }
  return result;
}

function cell(row, oneBasedIndex) {
  return row[oneBasedIndex - 1];
}

export function normalizeText(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

export function normalizeSkc(value) {
  const text = normalizeText(value);
  if (!text) return "";
  if (/^\d+\.0+$/.test(text)) {
    return text.split(".", 1)[0];
  }
  return text;
}

export function normalizePrice(value) {
  const text = normalizeText(value);
  if (!text) return null;
  const cleaned = text
    .replaceAll("¥", "")
    .replaceAll("$", "")
    .replaceAll(",", "")
    .replaceAll("楼", "")
    .trim();
  const match = cleaned.match(/-?\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : null;
}

export function firstImageUrl(value) {
  const text = normalizeText(value);
  if (!text) return "";
  return text.split("|").map((part) => part.trim()).find(Boolean) ?? "";
}
