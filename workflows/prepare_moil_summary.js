const data = $('Build Customs and CZ Rows').first().json;

if (!data || !data.shipmentKey) {
  return [{
    json: {
      chatId: $('Parse Python Output').first().json.chatId ?? null,
      text: 'Ошибка: не удалось получить данные обработки'
    }
  }];
}

const customsSheets = data.customsSheets || [];
const customsSheetNames = customsSheets.map((sheet) => sheet.sheetName);
const customsRowsCount = customsSheets.reduce(
  (sum, sheet) => sum + (sheet.rows || []).length,
  0
);
const warnings = data.warnings || [];

let message =
  `✅ Обработка завершена\n\n` +
  `🏢 Компания: moil\n` +
  `📦 Поставка: ${data.shipmentKey}\n` +
  `📄 Invoice документов: ${data.invoiceDocsCount || 0}\n` +
  `📦 Packing документов: ${data.packingDocsCount || 0}\n` +
  `🏷️ Batch документов: ${data.batchDocsCount || 0}\n\n` +
  `📊 Результаты:\n` +
  `• Таможня: ${customsRowsCount} строк в ${customsSheets.length} вкладках\n` +
  `• Честный Знак: ${(data.czRows || []).length} строк в общей вкладке\n\n` +
  `Вкладки:\n` +
  customsSheetNames.map((name) => `• ${name}`).join('\n') +
  `\n• ${data.czSheetName || `ЧЗ ${data.shipmentKey}`}`;

if (warnings.length > 0) {
  message += `\n\n⚠️ Предупреждения:\n`;
  for (const warning of warnings) {
    message += `• ${warning}\n`;
  }
}

return [{
  json: {
    chatId: data.chatId,
    text: message.trim(),
  }
}];
