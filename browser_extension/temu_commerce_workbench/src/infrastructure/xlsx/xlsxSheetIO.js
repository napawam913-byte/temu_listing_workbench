import xlsx from "xlsx";

const XLSX = xlsx;

export function readRowsFromXlsxFile(filePath, { sheetName } = {}) {
  const workbook = XLSX.readFile(filePath, { cellDates: false });
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

export function writeRowsToXlsxBuffer(rows, { sheetName = "Sheet1" } = {}) {
  return writeWorkbookSheetsToXlsxBuffer([{ sheetName, rows }]);
}

export function writeWorkbookSheetsToXlsxBuffer(sheets) {
  const workbook = XLSX.utils.book_new();
  appendSheets(workbook, sheets);
  return XLSX.write(workbook, {
    type: "buffer",
    bookType: "xlsx"
  });
}

function appendSheets(workbook, sheets) {
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
