import { importT2Products } from "../../application/usecases/importT2Products.js";
import { readRowsFromXlsxFile } from "./xlsxSheetIO.js";

export function importT2ProductsFromXlsx({ infoPath, pricePath, mapping }) {
  const infoRows = readRowsFromXlsxFile(infoPath);
  const priceRows = readRowsFromXlsxFile(pricePath);
  return importT2Products({ infoRows, priceRows, mapping });
}
