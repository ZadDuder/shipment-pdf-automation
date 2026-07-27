const data = $('Build Customs and CZ Rows').first().json;
const quoteSheet = (title) => `'${String(title).replace(/'/g, "''")}'`;
const valueOrBlank = (value) => (
  value === null || value === undefined ? '' : value
);
const rows = Array.isArray(data.czRows) ? data.czRows : [];
const headers = rows.length ? Object.keys(rows[0]) : [];

return [{
  json: {
    spreadsheetId: '1Av1S2wFoiLrIeeaBO-gFGgsBtzuwMgL1ziVd2lS6c3k',
    valueInputOption: 'USER_ENTERED',
    data: rows.length ? [{
      range: `${quoteSheet(data.czSheetName || `ЧЗ ${data.shipmentKey}`)}!A2`,
      majorDimension: 'ROWS',
      values: rows.map((row) => headers.map((header) => valueOrBlank(row[header]))),
    }] : [],
  }
}];
