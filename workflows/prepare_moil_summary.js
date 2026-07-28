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
const czSheets = data.czSheets || [];
const customsRowsCount = customsSheets.reduce(
  (sum, sheet) => sum + (sheet.rows || []).length,
  0
);
const czRowsCount = czSheets.reduce(
  (sum, sheet) => sum + (sheet.rows || []).length,
  0
);
const sheetPairs = customsSheets.map((sheet, index) => (
  `• ${sheet.sheetName} / ${czSheets[index]?.sheetName || 'ЧЗ не сформирован'}`
));
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
  `• Честный Знак: ${czRowsCount} строк в ${czSheets.length} вкладках\n\n` +
  `Результат сформирован в ${customsSheets.length} парах вкладок:\n` +
  sheetPairs.join('\n');

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
