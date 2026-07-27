const data = $('Build Customs and CZ Rows').first().json;

if (!data || !data.shipmentKey) {
  throw new Error('Нет shipmentKey после Build Customs and CZ Rows');
}

const customsSheetNames = (data.customsSheets || [])
  .map((sheet) => String(sheet.sheetName || '').trim())
  .filter(Boolean);

if (!customsSheetNames.length) {
  throw new Error('Не сформирован ни один таможенный лист по invoice');
}

return [{
  json: {
    spreadsheetId: '1Av1S2wFoiLrIeeaBO-gFGgsBtzuwMgL1ziVd2lS6c3k',
    shipmentKey: String(data.shipmentKey),
    customsSheetNames,
    czSheetName: String(data.czSheetName || `ЧЗ ${data.shipmentKey}`),
    templateCustomsName: 'TEMPLATE_CUSTOMS',
    templateCzName: 'TEMPLATE_CZ',
  }
}];
