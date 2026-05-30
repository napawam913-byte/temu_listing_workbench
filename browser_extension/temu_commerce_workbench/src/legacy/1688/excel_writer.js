const HEADERS = ["NAME", "SKC", "image", "核价", "单件", "重量", "倍数", "url"];
const ROW_HEIGHT_PT = 78;

const CRC_TABLE = new Uint32Array(256).map((_, index) => {
  let value = index;
  for (let bit = 0; bit < 8; bit += 1) {
    value = (value & 1) !== 0 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  }
  return value >>> 0;
});

function xmlEscape(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function toUint8Array(value) {
  if (value instanceof Uint8Array) {
    return value;
  }
  return new Uint8Array(value);
}

function encodeText(text) {
  return new TextEncoder().encode(text);
}

function createCrc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function dosDateTime(date = new Date()) {
  const year = Math.max(1980, date.getFullYear());
  const dosTime = ((date.getHours() & 0x1f) << 11) | ((date.getMinutes() & 0x3f) << 5) | ((Math.floor(date.getSeconds() / 2)) & 0x1f);
  const dosDate = (((year - 1980) & 0x7f) << 9) | (((date.getMonth() + 1) & 0x0f) << 5) | (date.getDate() & 0x1f);
  return { dosTime, dosDate };
}

function writeUInt16(view, offset, value) {
  view.setUint16(offset, value, true);
}

function writeUInt32(view, offset, value) {
  view.setUint32(offset, value >>> 0, true);
}

function numberCell(reference, value, styleId = 0) {
  return `<c r="${reference}" s="${styleId}"><v>${value}</v></c>`;
}

function stringCell(reference, value, styleId = 0) {
  return `<c r="${reference}" s="${styleId}" t="inlineStr"><is><t>${xmlEscape(value)}</t></is></c>`;
}

function columnName(index) {
  let value = "";
  let current = index;
  while (current > 0) {
    const remainder = (current - 1) % 26;
    value = String.fromCharCode(65 + remainder) + value;
    current = Math.floor((current - 1) / 26);
  }
  return value;
}

function buildSheetXml(records) {
  const rows = [];
  const headerCells = HEADERS.map((header, index) => stringCell(`${columnName(index + 1)}1`, header, 1)).join("");
  rows.push(`<row r="1" ht="24" customHeight="1">${headerCells}</row>`);

  records.forEach((record, index) => {
    const rowNumber = index + 2;
    const cells = [
      stringCell(`A${rowNumber}`, record.name ?? ""),
      stringCell(`B${rowNumber}`, record.skc ?? ""),
      stringCell(`C${rowNumber}`, record.imageFile ?? ""),
      numberCell(`D${rowNumber}`, Number(record.quotedPrice ?? 0), 2),
      numberCell(`E${rowNumber}`, Number(record.unitPrice ?? 0), 2),
      numberCell(`F${rowNumber}`, Number(record.weight ?? 0), 2),
      numberCell(`G${rowNumber}`, Number(record.quantity ?? 1), 2),
      stringCell(`H${rowNumber}`, record.url ?? "")
    ].join("");

    rows.push(`<row r="${rowNumber}" ht="${ROW_HEIGHT_PT}" customHeight="1">${cells}</row>`);
  });

  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <cols>
    <col min="1" max="1" width="22" customWidth="1"/>
    <col min="2" max="2" width="18" customWidth="1"/>
    <col min="3" max="3" width="16" customWidth="1"/>
    <col min="4" max="4" width="12" customWidth="1"/>
    <col min="5" max="5" width="12" customWidth="1"/>
    <col min="6" max="6" width="12" customWidth="1"/>
    <col min="7" max="7" width="10" customWidth="1"/>
    <col min="8" max="8" width="56" customWidth="1"/>
  </cols>
  <sheetData>
    ${rows.join("")}
  </sheetData>
  <drawing r:id="rId1"/>
</worksheet>`;
}

function buildWorkbookXml() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Records" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>`;
}

function buildWorkbookRelsXml() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`;
}

function buildRootRelsXml() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`;
}

function buildStylesXml() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><name val="Calibri"/></font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1">
    <border><left/><right/><top/><bottom/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="3">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
</styleSheet>`;
}

function buildSheetRelsXml() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>
</Relationships>`;
}

function buildDrawingXml(imageCount) {
  const oneCellAnchors = [];
  for (let index = 0; index < imageCount; index += 1) {
    const rowIndex = index + 1;
    oneCellAnchors.push(`
  <xdr:oneCellAnchor>
    <xdr:from>
      <xdr:col>2</xdr:col>
      <xdr:colOff>9525</xdr:colOff>
      <xdr:row>${rowIndex}</xdr:row>
      <xdr:rowOff>9525</xdr:rowOff>
    </xdr:from>
    <xdr:ext cx="914400" cy="914400"/>
    <xdr:pic>
      <xdr:nvPicPr>
        <xdr:cNvPr id="${index + 1}" name="Image ${index + 1}"/>
        <xdr:cNvPicPr/>
      </xdr:nvPicPr>
      <xdr:blipFill>
        <a:blip r:embed="rId${index + 1}"/>
        <a:stretch><a:fillRect/></a:stretch>
      </xdr:blipFill>
      <xdr:spPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="914400" cy="914400"/>
        </a:xfrm>
        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
      </xdr:spPr>
    </xdr:pic>
    <xdr:clientData/>
  </xdr:oneCellAnchor>`);
  }

  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
${oneCellAnchors.join("")}
</xdr:wsDr>`;
}

function buildDrawingRelsXml(images) {
  const relations = images
    .map((image, index) => {
      return `  <Relationship Id="rId${index + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/${image.mediaName}"/>`;
    })
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
${relations}
</Relationships>`;
}

function buildContentTypesXml(images) {
  const imageOverrides = [];
  const extensionTypes = new Map();

  for (const image of images) {
    extensionTypes.set(image.extension, image.mimeType);
  }

  for (const [extension, mimeType] of extensionTypes) {
    imageOverrides.push(`  <Default Extension="${extension}" ContentType="${mimeType}"/>`);
  }

  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
${imageOverrides.join("\n")}
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>
</Types>`;
}

function buildZip(entries) {
  const localChunks = [];
  const centralChunks = [];
  let offset = 0;
  const now = dosDateTime();

  for (const entry of entries) {
    const fileNameBytes = encodeText(entry.name);
    const dataBytes = toUint8Array(entry.data);
    const crc32 = createCrc32(dataBytes);

    const localHeader = new ArrayBuffer(30 + fileNameBytes.length);
    const localView = new DataView(localHeader);
    writeUInt32(localView, 0, 0x04034b50);
    writeUInt16(localView, 4, 20);
    writeUInt16(localView, 6, 0);
    writeUInt16(localView, 8, 0);
    writeUInt16(localView, 10, now.dosTime);
    writeUInt16(localView, 12, now.dosDate);
    writeUInt32(localView, 14, crc32);
    writeUInt32(localView, 18, dataBytes.length);
    writeUInt32(localView, 22, dataBytes.length);
    writeUInt16(localView, 26, fileNameBytes.length);
    writeUInt16(localView, 28, 0);
    new Uint8Array(localHeader, 30).set(fileNameBytes);

    const centralHeader = new ArrayBuffer(46 + fileNameBytes.length);
    const centralView = new DataView(centralHeader);
    writeUInt32(centralView, 0, 0x02014b50);
    writeUInt16(centralView, 4, 20);
    writeUInt16(centralView, 6, 20);
    writeUInt16(centralView, 8, 0);
    writeUInt16(centralView, 10, 0);
    writeUInt16(centralView, 12, now.dosTime);
    writeUInt16(centralView, 14, now.dosDate);
    writeUInt32(centralView, 16, crc32);
    writeUInt32(centralView, 20, dataBytes.length);
    writeUInt32(centralView, 24, dataBytes.length);
    writeUInt16(centralView, 28, fileNameBytes.length);
    writeUInt16(centralView, 30, 0);
    writeUInt16(centralView, 32, 0);
    writeUInt16(centralView, 34, 0);
    writeUInt16(centralView, 36, 0);
    writeUInt32(centralView, 38, 0);
    writeUInt32(centralView, 42, offset);
    new Uint8Array(centralHeader, 46).set(fileNameBytes);

    localChunks.push(new Uint8Array(localHeader), dataBytes);
    centralChunks.push(new Uint8Array(centralHeader));
    offset += localHeader.byteLength + dataBytes.length;
  }

  const centralSize = centralChunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const endOfCentralDirectory = new ArrayBuffer(22);
  const eocdView = new DataView(endOfCentralDirectory);
  writeUInt32(eocdView, 0, 0x06054b50);
  writeUInt16(eocdView, 4, 0);
  writeUInt16(eocdView, 6, 0);
  writeUInt16(eocdView, 8, entries.length);
  writeUInt16(eocdView, 10, entries.length);
  writeUInt32(eocdView, 12, centralSize);
  writeUInt32(eocdView, 16, offset);
  writeUInt16(eocdView, 20, 0);

  const size =
    localChunks.reduce((sum, chunk) => sum + chunk.length, 0) +
    centralSize +
    endOfCentralDirectory.byteLength;

  const zip = new Uint8Array(size);
  let pointer = 0;

  for (const chunk of localChunks) {
    zip.set(chunk, pointer);
    pointer += chunk.length;
  }

  for (const chunk of centralChunks) {
    zip.set(chunk, pointer);
    pointer += chunk.length;
  }

  zip.set(new Uint8Array(endOfCentralDirectory), pointer);
  return zip.buffer;
}

export async function buildWorkbookBuffer(records, resolveImage) {
  const imageEntries = [];

  for (let index = 0; index < records.length; index += 1) {
    const record = records[index];
    const image = await resolveImage(record);
    const extension = image.extension.toLowerCase();
    imageEntries.push({
      ...image,
      extension,
      mediaName: `image${index + 1}.${extension}`
    });
  }

  const files = [
    { name: "[Content_Types].xml", data: encodeText(buildContentTypesXml(imageEntries)) },
    { name: "_rels/.rels", data: encodeText(buildRootRelsXml()) },
    { name: "xl/workbook.xml", data: encodeText(buildWorkbookXml()) },
    { name: "xl/_rels/workbook.xml.rels", data: encodeText(buildWorkbookRelsXml()) },
    { name: "xl/styles.xml", data: encodeText(buildStylesXml()) },
    { name: "xl/worksheets/sheet1.xml", data: encodeText(buildSheetXml(records)) },
    { name: "xl/worksheets/_rels/sheet1.xml.rels", data: encodeText(buildSheetRelsXml()) },
    { name: "xl/drawings/drawing1.xml", data: encodeText(buildDrawingXml(imageEntries.length)) },
    { name: "xl/drawings/_rels/drawing1.xml.rels", data: encodeText(buildDrawingRelsXml(imageEntries)) }
  ];

  for (const image of imageEntries) {
    files.push({ name: `xl/media/${image.mediaName}`, data: image.bytes });
  }

  return buildZip(files);
}
