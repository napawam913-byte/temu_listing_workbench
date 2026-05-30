const HEADER_SCAN_LIMIT = 20;

export function importTemplateMainImages(rows, { idPrefix = "template" } = {}) {
  if (!Array.isArray(rows) || !rows.length) {
    throw new Error("模板 Excel 没有可读取的数据");
  }

  const headerRowIndex = findHeaderRowIndex(rows);
  if (headerRowIndex === -1) {
    throw new Error("未找到包含“轮播图”或“产品素材图”的表头行");
  }

  const headerRow = rows[headerRowIndex] ?? [];
  const columns = detectTemplateColumns(headerRow);
  if (columns.primaryImageColumn === -1 && columns.fallbackImageColumn === -1) {
    throw new Error("未找到可用于主图生成的图片列");
  }

  const items = [];
  for (let rowIndex = headerRowIndex + 1; rowIndex < rows.length; rowIndex += 1) {
    const row = rows[rowIndex] ?? [];
    const imageUrl = pickImageUrl(row, columns);
    if (!imageUrl) continue;

    const rowNumber = rowIndex + 1;
    const displayName = buildDisplayName(row, columns, rowNumber);
    items.push({
      id: `${idPrefix}-${items.length + 1}`,
      name: displayName,
      uploadName: buildUploadName(displayName, imageUrl),
      imageUrl,
      rowNumber,
      title: normalizeText(cell(row, columns.titleColumn)),
      identifier: normalizeText(firstNonEmptyCell(row, [columns.skuColumn, columns.productCodeColumn])),
      sourceColumn: resolveSourceColumnLabel(columns, row)
    });
  }

  return {
    items,
    summary: {
      headerRowNumber: headerRowIndex + 1,
      rowsScanned: Math.max(0, rows.length - headerRowIndex - 1),
      matchedImageCount: items.length,
      primaryImageColumn: columnLabel(columns.primaryImageColumn, columns.primaryImageHeader),
      fallbackImageColumn: columnLabel(columns.fallbackImageColumn, columns.fallbackImageHeader)
    }
  };
}

export function detectTemplateColumns(headerRow) {
  const headers = (headerRow ?? []).map(normalizeHeader);
  return {
    primaryImageColumn: headers.findIndex((header) => header.includes("轮播")),
    primaryImageHeader: firstMatchingHeader(headerRow, headers, (header) => header.includes("轮播")),
    fallbackImageColumn: headers.findIndex((header) => header.includes("产品素材图")),
    fallbackImageHeader: firstMatchingHeader(headerRow, headers, (header) => header.includes("产品素材图")),
    titleColumn: findFirstHeaderIndex(headers, ["产品标题", "商品标题", "标题"]),
    englishTitleColumn: findFirstHeaderIndex(headers, ["英文标题"]),
    skuColumn: findFirstHeaderIndex(headers, ["SKU货号", "SKU编码", "SKU"]),
    productCodeColumn: findFirstHeaderIndex(headers, ["产品货号", "货号"])
  };
}

export function findHeaderRowIndex(rows) {
  const limit = Math.min(rows.length, HEADER_SCAN_LIMIT);
  for (let index = 0; index < limit; index += 1) {
    const headers = (rows[index] ?? []).map(normalizeHeader);
    if (headers.some((header) => header.includes("轮播")) || headers.some((header) => header.includes("产品素材图"))) {
      return index;
    }
  }
  return -1;
}

export function firstTemplateImageUrl(value) {
  const text = normalizeText(value);
  if (!text) return "";

  const matches = text.match(/https?:\/\/[^\s"'<>|,;，；]+/gi);
  if (matches?.length) {
    return trimTrailingPunctuation(matches[0]);
  }

  const firstPart = text
    .split(/[\r\n|,;，；]+/g)
    .map((part) => part.trim())
    .find(Boolean);

  return trimTrailingPunctuation(firstPart ?? "");
}

function pickImageUrl(row, columns) {
  const primaryUrl = firstTemplateImageUrl(cell(row, columns.primaryImageColumn));
  if (primaryUrl) return primaryUrl;

  return firstTemplateImageUrl(cell(row, columns.fallbackImageColumn));
}

function buildDisplayName(row, columns, rowNumber) {
  const identifier = normalizeText(firstNonEmptyCell(row, [columns.skuColumn, columns.productCodeColumn]));
  const title = normalizeText(firstNonEmptyCell(row, [columns.titleColumn, columns.englishTitleColumn]));

  if (identifier && title) {
    return compactName(`${identifier}_${title}`, rowNumber);
  }
  if (identifier) {
    return compactName(identifier, rowNumber);
  }
  if (title) {
    return compactName(title, rowNumber);
  }

  return `template_row_${rowNumber}`;
}

function buildUploadName(displayName, imageUrl) {
  const extension = extensionFromUrl(imageUrl);
  return `${displayName}.${extension || "png"}`;
}

function compactName(value, rowNumber) {
  const cleaned = String(value)
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120);

  return cleaned || `template_row_${rowNumber}`;
}

function resolveSourceColumnLabel(columns, row) {
  const primaryUrl = firstTemplateImageUrl(cell(row, columns.primaryImageColumn));
  if (primaryUrl) {
    return columns.primaryImageHeader || "轮播图";
  }
  return columns.fallbackImageHeader || "产品素材图";
}

function firstMatchingHeader(originalHeaders, normalizedHeaders, predicate) {
  const index = normalizedHeaders.findIndex(predicate);
  return index === -1 ? "" : normalizeText(originalHeaders[index]);
}

function firstNonEmptyCell(row, indexes) {
  for (const index of indexes) {
    const value = cell(row, index);
    if (normalizeText(value)) {
      return value;
    }
  }
  return "";
}

function findFirstHeaderIndex(headers, candidates) {
  for (const candidate of candidates) {
    const index = headers.findIndex((header) => header.includes(candidate));
    if (index !== -1) {
      return index;
    }
  }
  return -1;
}

function columnLabel(index, header) {
  if (index === -1) return "";
  return `${header || "未命名列"} (第 ${index + 1} 列)`;
}

function cell(row, zeroBasedIndex) {
  if (!Array.isArray(row) || zeroBasedIndex < 0) return "";
  return row[zeroBasedIndex];
}

function normalizeHeader(value) {
  return normalizeText(value)
    .replace(/\*/g, "")
    .replace(/\s+/g, "");
}

function normalizeText(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

function trimTrailingPunctuation(value) {
  return String(value ?? "").replace(/[),;，；]+$/g, "");
}

function extensionFromUrl(url) {
  const text = normalizeText(url);
  if (!text) return "";

  try {
    const parsed = new URL(text);
    const pathname = parsed.pathname || "";
    const match = pathname.match(/\.([a-z0-9]{2,5})$/i);
    return match ? match[1].toLowerCase() : "";
  } catch {
    const match = text.match(/\.([a-z0-9]{2,5})(?:[?#].*)?$/i);
    return match ? match[1].toLowerCase() : "";
  }
}
