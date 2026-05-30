import { writeRowsToXlsxBuffer } from "./xlsxSheetIO.js";
import { productsToSheetRows } from "./productSheetRows.js";

export function createProductSheetExporter() {
  return {
    async export(products) {
      return exportProductsToXlsxBuffer(products);
    }
  };
}

export function exportProductsToXlsxBuffer(products) {
  return writeRowsToXlsxBuffer(productsToSheetRows(products), { sheetName: "Products" });
}
