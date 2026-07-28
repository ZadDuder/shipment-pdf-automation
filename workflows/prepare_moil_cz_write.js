const data = $('Build Customs and CZ Rows').first().json;
const quoteSheet = (title) => `'${String(title).replace(/'/g, "''")}'`;
const valueOrBlank = (value) => (
  value === null || value === undefined ? '' : value
);
const sheetData = [];
for (const sheet of data.czSheets || []) {
  const rows = Array.isArray(sheet.rows) ? sheet.rows : [];
  if (!rows.length) continue;
  const headers = Object.keys(rows[0]);
  sheetData.push({
    range: `${quoteSheet(sheet.sheetName)}!A2`,
    majorDimension: 'ROWS',
    values: rows.map((row) => headers.map((header) => valueOrBlank(row[header]))),
  });
}

return [{
  json: {
    spreadsheetId: '1Av1S2wFoiLrIeeaBO-gFGgsBtzuwMgL1ziVd2lS6c3k',
    valueInputOption: 'USER_ENTERED',
    data: sheetData,
  }
}];
