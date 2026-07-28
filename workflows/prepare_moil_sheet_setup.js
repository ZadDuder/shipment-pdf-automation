const data = $('Build Customs and CZ Rows').first().json;

if (!data || !data.shipmentKey) {
  throw new Error('Нет shipmentKey после Build Customs and CZ Rows');
}

const customsSheetNames = (data.customsSheets || [])
  .map((sheet) => String(sheet.sheetName || '').trim())
  .filter(Boolean);
const czSheetNames = (data.czSheets || [])
  .map((sheet) => String(sheet.sheetName || '').trim())
  .filter(Boolean);

if (
  !customsSheetNames.length ||
  czSheetNames.length !== customsSheetNames.length
) {
  throw new Error('Не сформированы пары таможня/ЧЗ для каждого invoice');
}

return [{
  json: {
    spreadsheetId: '1Av1S2wFoiLrIeeaBO-gFGgsBtzuwMgL1ziVd2lS6c3k',
    shipmentKey: String(data.shipmentKey),
    customsSheetNames,
    czSheetNames,
    templateCustomsName: 'TEMPLATE_CUSTOMS',
    templateCzName: 'TEMPLATE_CZ',
  }
}];
