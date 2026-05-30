export async function readRowsFromBrowserFile(file, { sheetName } = {}) {
  const XLSX = getXlsx();
  const arrayBuffer = await file.arrayBuffer();
  const workbook = XLSX.read(arrayBuffer, { type: "array", cellDates: false });
  const targetSheetName = sheetName || workbook.SheetNames[0];
  const sheet = workbook.Sheets[targetSheetName];
  if (!sheet) {
    throw new Error(`Worksheet not found: ${targetSheetName}`);
  }

  return XLSX.utils.sheet_to_json(sheet, {
    header: 1,
    blankrows: false,
    defval: ""
  });
}

export function writeRowsToXlsxBlob(rows, { sheetName = "Sheet1" } = {}) {
  return writeWorkbookSheetsToXlsxBlob([{ sheetName, rows }]);
}

export function writeWorkbookSheetsToXlsxBlob(sheets) {
  const XLSX = getXlsx();
  const workbook = XLSX.utils.book_new();
  appendSheets(XLSX, workbook, sheets);
  const array = XLSX.write(workbook, {
    type: "array",
    bookType: "xlsx"
  });

  return new Blob([array], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  });
}

function appendSheets(XLSX, workbook, sheets) {
  if (!Array.isArray(sheets) || !sheets.length) {
    throw new Error("At least one worksheet is required");
  }

  for (const sheetConfig of sheets) {
    const sheetName = sheetConfig.sheetName || "Sheet1";
    const rows = Array.isArray(sheetConfig.rows) ? sheetConfig.rows : [];
    const sheet = XLSX.utils.aoa_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, sheet, sheetName);
  }
}

function getXlsx() {
  if (!globalThis.XLSX) {
    throw new Error("SheetJS is not loaded");
  }
  return globalThis.XLSX;
}
