const meta = $json;
const setup = $('Prepare Sheet Setup Data').first().json;

const sheets = Array.isArray(meta.sheets) ? meta.sheets : [];
const titleToSheetId = new Map();

for (const sheet of sheets) {
  const props = sheet.properties || {};
  if (props.title) {
    titleToSheetId.set(props.title, props.sheetId);
  }
}

const templateCustomsSheetId = titleToSheetId.get(setup.templateCustomsName);
const templateCzSheetId = titleToSheetId.get(setup.templateCzName);

if (templateCustomsSheetId === undefined) {
  throw new Error(`Не найден шаблонный лист ${setup.templateCustomsName}`);
}

if (templateCzSheetId === undefined) {
  throw new Error(`Не найден шаблонный лист ${setup.templateCzName}`);
}

const requests = [];
const missingCustomsSheetNames = [];
for (const sheetName of setup.customsSheetNames) {
  if (titleToSheetId.has(sheetName)) continue;
  missingCustomsSheetNames.push(sheetName);
  requests.push({
    duplicateSheet: {
      sourceSheetId: templateCustomsSheetId,
      newSheetName: sheetName,
    }
  });
}

const czExists = titleToSheetId.has(setup.czSheetName);
if (!czExists) {
  requests.push({
    duplicateSheet: {
      sourceSheetId: templateCzSheetId,
      newSheetName: setup.czSheetName,
    }
  });
}

return [{
  json: {
    ...setup,
    missingCustomsSheetNames,
    czExists,
    templateCustomsSheetId,
    templateCzSheetId,
    requests,
    requestsCount: requests.length,
  }
}];
