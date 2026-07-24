const body = $json.body ?? $json;
const company = String(body.company || '').trim().toLowerCase();
const shipmentKey = String(
  body.shipment_number || body.shipmentKey || ''
).trim();

const allowedCompanies = new Set(['moil', 'moroccanoil', 'bandi']);
if (!allowedCompanies.has(company)) {
  throw new Error('Неизвестная компания');
}
if (!/^[A-Za-z0-9_-]{1,64}$/.test(shipmentKey)) {
  throw new Error('Некорректный номер поставки');
}

const shipmentDir = `/opt/tg_uploads/${company}/${shipmentKey}`;

return [{
  json: {
    company,
    shipmentKey,
    shipmentDir,
    manifestPath: `${shipmentDir}/manifest.json`,
    chatId: body.user_id ?? body.chatId ?? null,
    username: body.username || null,
    files: Array.isArray(body.files) ? body.files : [],
    totalFiles: Number(
      body.total_files ||
      body.totalFiles ||
      (Array.isArray(body.files) ? body.files.length : 0)
    ),
  }
}];
