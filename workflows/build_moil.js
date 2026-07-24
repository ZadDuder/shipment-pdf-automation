const pythonData = $('Parse Python Output').first().json;
const masterRows = $input.all().map((item) => item.json);

if (!pythonData || !pythonData.invoiceRows) {
  return [{
    json: {
      error: pythonData?.error || 'No Python data found',
      chatId: pythonData?.chatId || null
    }
  }];
}

const clean = (value) => String(value ?? '').trim();

const normalizeCode = (value) =>
  clean(value).replace(/[^A-Z0-9-]/gi, '').toUpperCase();

const hasValue = (value) =>
  value !== null && value !== undefined && value !== '';

const parseNumber = (value) => {
  if (!hasValue(value)) return null;
  const normalized = String(value).replace(/[^\d,.-]/g, '').replace(/,/g, '');
  const num = Number(normalized);
  return Number.isFinite(num) ? num : null;
};

const uniqSorted = (values) =>
  [...new Set(values.filter((v) => hasValue(v)).map((v) => String(v)))]
    .sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }));

const round2 = (value) =>
  value === null || value === undefined ? null : Number(Number(value).toFixed(2));

const scalePackingBoxes = (boxes, scale = 1) => {
  if (boxes === null || boxes === undefined) return null;
  if (Number(boxes) === 0) return 0;
  return Math.max(1, Math.round(Number(boxes) * Number(scale)));
};

const countryMap = {
  'израиль': 'Israel',
  'israel': 'Israel',
  'china': 'China',
  'китай': 'China',
  'usa': 'USA',
  'u.s.a.': 'USA',
  'сша': 'USA',
};

const normalizeCountry = (value) => {
  const raw = clean(value);
  if (!raw) return '';
  const key = raw.toLowerCase();
  return countryMap[key] || raw;
};

const gtinToText = (value) => {
  if (value === null || value === undefined || value === '') return null;

  if (typeof value === 'number' && Number.isFinite(value)) {
    return String(Math.trunc(value));
  }

  const text = String(value).trim();

  if (/^\d+\.0+$/.test(text)) {
    return text.replace(/\.0+$/, '');
  }

  const digits = text.replace(/\D/g, '');
  return digits || null;
};

const detectMaster = (row) => {
  const get = (...keys) => {
    for (const key of keys) {
      if (hasValue(row[key])) return row[key];
    }
    return null;
  };

  const textValues = Object.values(row)
    .filter((value) => typeof value === 'string' && value.trim());

  const translationHeuristic =
    textValues.find((value) => /[А-ЯЁа-яё]{5,}/.test(value)) || null;

  const packageHeuristic =
    textValues.find((value) => /упаков|флакон|транспортн|группов|короб/i.test(String(value))) || null;

  const itemNo = normalizeCode(
    get(
      'SKU',
      'Item No.',
      'itemNo',
      'SKU Code - 2',
      'SKU Code - 1',
      'Артикул поставщика',
      'Арт производителя',
      'Артикул производителя',
      'Vendor Code',
      'ItemCode',
      'SAP ItemCode'
    )
  );

  const gtin = gtinToText(
    get(
      'Код товара',
      'Barcode',
      'BARCODE',
      'GTIN',
      'gtin',
      'Штрихкод',
      'Баркод',
      'EAN'
    )
  );

  if (!itemNo && !gtin) return null;

  return {
    itemNo: itemNo || null,
    article: get(
      'SKU RU',
      'Артикул',
      'АРТИКУЛ',
      'article',
      'Арт. Ру-Бьюти',
      'Артикул РУ'
    ),
    gtin,
    customsCode: get(
      'Customs Code',
      'Код ТНВЭД',
      'Код ТНВЭД ',
      'customsCode',
      'Код ТНВЭД (13933)',
      'ТНВЭД'
    ),
    translation: get(
      'PRODUCT DESCRIPTION RU',
      'Перевод',
      'translation',
      'Полное наименование товара (2478)',
      'Наименование RU',
      'Наименование'
    ) || translationHeuristic || '',
    packageDescription: get(
      'PACKAGE DESCRIPTION RU',
      'Пояснения к материалу и упаковке',
      'ОПИСАНИЕ УПАКОВКИ',
      'packageDescription',
      'Пояснения к материалу и упаковке (для таможни)'
    ) || packageHeuristic || '',
    countryOfOrigin: normalizeCountry(
      get(
        'Country Of Origin',
        'страна происхождения',
        'countryOfOrigin',
        'Страна происхождения'
      )
    ),
    ds: get(
      'Декларация о соответствии (23557)',
      'ДС',
      'СГР/деклация'
    ),
    dt: get(
      'ДТ'
    ),
    tovar: get(
      'ТОВАР',
      'Товар'
    ),
    alcohol: get(
      '% содержания спирта',
      'Концентрация спирта',
      'Alcohol',
      'СПИРТ'
    ),
    dataMatrix: get(
      'Data Matrix'
    ),
    label: get(
      'этикетка',
      'Этикетка'
    ),
  };
};

const masterByItemNo = {};
const masterByGtin = {};

for (const row of masterRows) {
  const normalized = detectMaster(row);
  if (!normalized) continue;

  if (normalized.itemNo) {
    masterByItemNo[normalized.itemNo] = normalized;
  }

  if (normalized.gtin) {
    masterByGtin[normalized.gtin] = normalized;
  }
}

const resolveMaster = ({ itemNo = null, gtin = null, batchBarcode = null } = {}) => {
  const normalizedItemNo = itemNo ? normalizeCode(itemNo) : null;
  const normalizedGtin = gtinToText(gtin);
  const normalizedBatchBarcode = gtinToText(batchBarcode);

  if (normalizedItemNo && masterByItemNo[normalizedItemNo]) {
    return masterByItemNo[normalizedItemNo];
  }

  if (normalizedGtin && masterByGtin[normalizedGtin]) {
    return masterByGtin[normalizedGtin];
  }

  if (normalizedBatchBarcode && masterByGtin[normalizedBatchBarcode]) {
    return masterByGtin[normalizedBatchBarcode];
  }

  return null;
};

const bundle = pythonData;
const hasAnyBatchFiles = Array.isArray(bundle.batchFiles) && bundle.batchFiles.length > 0;

const packingMap = {};
for (const row of bundle.packingRows || []) {
  const normalizedCode = normalizeCode(row.itemNo);
  if (!normalizedCode) continue;

  if (!packingMap[normalizedCode]) {
    packingMap[normalizedCode] = [];
  }

  packingMap[normalizedCode].push({
    itemNo: normalizedCode,
    boxes: parseNumber(row.boxes),
    weight: parseNumber(row.weight),
    quantity: parseNumber(row.quantity),
    pallet: hasValue(row.pallet) ? String(row.pallet) : null,
    sscc: hasValue(row.sscc) ? String(row.sscc) : null,
    descriptionFromPacking: clean(row.descriptionFromPacking),
    sourceFileName: row.__sourceFileName || null,
    nestedInCb: row.nestedInCb ?? null,
  });
}

const batchMap = {};
for (const row of bundle.batchRows || []) {
  const normalizedCode = normalizeCode(row.itemNo || row.sapItemCode || row['SAP ItemCode']);
  if (!normalizedCode) continue;

  if (!batchMap[normalizedCode]) {
    batchMap[normalizedCode] = [];
  }

  batchMap[normalizedCode].push({
    itemNo: normalizedCode,
    wmsItemCode: clean(row.wmsItemCode),
    itemFrgnName: clean(row.itemFrgnName),
    quantity: parseNumber(row.quantity),
    quantityUnit: clean(row.quantityUnit),
    boxes: parseNumber(row.boxes),
    pallet: hasValue(row.pallet) ? String(row.pallet) : null,
    batchNo: clean(row.batchNo),
    prodDate: clean(row.prodDate),
    expDate: clean(row.expDate),
    barcode: gtinToText(row.barcode),
    sourceFileName: row.__sourceFileName || null,
  });
}

const rawInvoiceRows = [...(bundle.invoiceRows || [])]
  .map((row, idx) => ({
    ...row,
    __rowOrder: hasValue(row.__rowOrder) ? Number(row.__rowOrder) : idx + 1,
    __isComponent: Boolean(row.__isComponent) || row.itemIndex === null || row.itemIndex === undefined || row.itemIndex === '',
  }))
  .sort((a, b) => {
    const aOrder = hasValue(a.__rowOrder) ? Number(a.__rowOrder) : 999999;
    const bOrder = hasValue(b.__rowOrder) ? Number(b.__rowOrder) : 999999;
    if (aOrder !== bOrder) return aOrder - bOrder;
    return String(a.itemNo || '').localeCompare(String(b.itemNo || ''));
  });

const invoiceAgg = {};
for (const row of rawInvoiceRows) {
  if (row.__isComponent) continue;

  const itemNo = normalizeCode(row.itemNo);
  if (!itemNo) continue;

  if (!invoiceAgg[itemNo]) {
    invoiceAgg[itemNo] = {
      itemNo,
      itemIndexes: [],
      description: clean(row.description),
      countryOfOrigin: clean(row.countryOfOrigin),
      quantity: 0,
      discountPercentage: parseNumber(row.discountPercentage),
      unitPriceBeforeDiscount: parseNumber(row.unitPriceBeforeDiscount),
      unitPriceAfterDiscount: parseNumber(row.unitPriceAfterDiscount),
      totalBeforeDiscount: 0,
      totalPriceAfterDiscount: 0,
      commercialDiscount: 0,
      warnings: [],
      __firstRowOrder: hasValue(row.__rowOrder) ? Number(row.__rowOrder) : 999999,
    };
  }

  const target = invoiceAgg[itemNo];

  if (hasValue(row.itemIndex)) {
    target.itemIndexes.push(Number(row.itemIndex));
  }

  if (!target.description && row.description) {
    target.description = clean(row.description);
  }

  if (!target.countryOfOrigin && row.countryOfOrigin) {
    target.countryOfOrigin = clean(row.countryOfOrigin);
  }

  target.quantity += parseNumber(row.quantity) || 0;
  target.totalBeforeDiscount += parseNumber(row.totalBeforeDiscount) || 0;
  target.totalPriceAfterDiscount += parseNumber(row.totalPriceAfterDiscount) || 0;
  target.commercialDiscount += parseNumber(row.commercialDiscount) || 0;

  const priceBefore = parseNumber(row.unitPriceBeforeDiscount);
  if (target.unitPriceBeforeDiscount === null || target.unitPriceBeforeDiscount === undefined) {
    target.unitPriceBeforeDiscount = priceBefore;
  } else if (priceBefore !== null && target.unitPriceBeforeDiscount !== priceBefore) {
    target.warnings.push('разные unit price before в invoice');
  }

  const priceAfter = parseNumber(row.unitPriceAfterDiscount);
  if (target.unitPriceAfterDiscount === null || target.unitPriceAfterDiscount === undefined) {
    target.unitPriceAfterDiscount = priceAfter;
  } else if (priceAfter !== null && target.unitPriceAfterDiscount !== priceAfter) {
    target.warnings.push('разные unit price after в invoice');
  }

  const discount = parseNumber(row.discountPercentage);
  if (target.discountPercentage === null || target.discountPercentage === undefined) {
    target.discountPercentage = discount;
  } else if (discount !== null && target.discountPercentage !== discount) {
    target.warnings.push('разный discount % в invoice');
  }
}

const aggregatedMainRows = Object.values(invoiceAgg).sort((a, b) => {
  if (a.__firstRowOrder !== b.__firstRowOrder) return a.__firstRowOrder - b.__firstRowOrder;
  return String(a.itemNo).localeCompare(String(b.itemNo));
});

const mainMap = {};
for (const row of aggregatedMainRows) {
  mainMap[row.itemNo] = row;
}

const displaySequence = [];
const emittedMain = new Set();

for (const row of rawInvoiceRows) {
  const itemNo = normalizeCode(row.itemNo);
  if (!itemNo) continue;

  if (row.__isComponent) {
    displaySequence.push({
      type: 'component',
      row,
      itemNo,
      rowOrder: hasValue(row.__rowOrder) ? Number(row.__rowOrder) : 999999,
    });
    continue;
  }

  if (!emittedMain.has(itemNo) && mainMap[itemNo]) {
    emittedMain.add(itemNo);
    displaySequence.push({
      type: 'main',
      row: mainMap[itemNo],
      itemNo,
      rowOrder: mainMap[itemNo].__firstRowOrder,
    });
  }
}

const aggregatePackingTotals = (rows) => {
  if (!rows.length) {
    return {
      quantity: null,
      boxes: null,
      weight: null,
      pallets: [],
    };
  }

  let quantity = 0;
  let boxes = 0;
  let weight = 0;

  let hasQuantity = false;
  let hasBoxes = false;
  let hasWeight = false;

  for (const row of rows) {
    if (row.quantity !== null && row.quantity !== undefined) {
      quantity += row.quantity;
      hasQuantity = true;
    }
    if (row.boxes !== null && row.boxes !== undefined) {
      boxes += row.boxes;
      hasBoxes = true;
    }
    if (row.weight !== null && row.weight !== undefined) {
      weight += row.weight;
      hasWeight = true;
    }
  }

  return {
    quantity: hasQuantity ? quantity : null,
    boxes: hasBoxes ? boxes : null,
    weight: hasWeight ? weight : null,
    pallets: uniqSorted(rows.map((row) => row.pallet)),
  };
};

const splitPackingByPallet = (rows) => {
  const byPallet = {};

  for (const row of rows) {
    const palletKey = row.pallet || 'без паллеты';
    if (!byPallet[palletKey]) {
      byPallet[palletKey] = {
        quantity: 0,
        boxes: 0,
        weight: 0,
        hasQuantity: false,
        hasBoxes: false,
        hasWeight: false,
      };
    }

    if (row.quantity !== null && row.quantity !== undefined) {
      byPallet[palletKey].quantity += row.quantity;
      byPallet[palletKey].hasQuantity = true;
    }
    if (row.boxes !== null && row.boxes !== undefined) {
      byPallet[palletKey].boxes += row.boxes;
      byPallet[palletKey].hasBoxes = true;
    }
    if (row.weight !== null && row.weight !== undefined) {
      byPallet[palletKey].weight += row.weight;
      byPallet[palletKey].hasWeight = true;
    }
  }

  return Object.entries(byPallet)
    .sort(([a], [b]) => String(a).localeCompare(String(b), undefined, { numeric: true }))
    .map(([palletKey, totals]) => ({
      palletKey,
      quantity: totals.hasQuantity ? totals.quantity : null,
      boxes: totals.hasBoxes ? totals.boxes : null,
      weight: totals.hasWeight ? totals.weight : null,
    }));
};

const buildComponentCustomsRow = (row) => {
  const itemNo = normalizeCode(row.itemNo);
  const master = resolveMaster({ itemNo });
  const masterMissing = !master;
  const articleMissing = !hasValue(master?.article);
  const translationMissing = !hasValue(master?.translation);
  const packageMissing = !hasValue(master?.packageDescription);

  const warnings = [];
  if (masterMissing) warnings.push(`нет строки в справочнике для ${itemNo}`);
  if (!masterMissing && articleMissing) warnings.push('пустой артикул в справочнике');
  if (!masterMissing && translationMissing) warnings.push('пустой перевод в справочнике');
  if (!masterMissing && packageMissing) warnings.push('пустые пояснения к материалу и упаковке');

  return {
    '#': null,
    'Item No.': itemNo,
    'Артикул': hasValue(master?.article) ? String(master.article).trim() : null,
    'Description': clean(row.description) || null,
    'Перевод': master?.translation ?? '',
    'Пояснения к материалу и упаковке': master?.packageDescription ?? '',
    'Country Of Origin': master?.countryOfOrigin || normalizeCountry(row.countryOfOrigin),
    'Quantity Количество': parseNumber(row.quantity),
    'Unit Price Before Discount': null,
    'Total Before Discount': null,
    'Discount Percentage, %': null,
    'Unit Price After Discount': null,
    'Total,$': null,
    'Commercial Discount, $': null,
    'Количество коробок, шт.': null,
    'Вес, кг': null,
    '№ паллета': null,

    '__row_warning': warnings.length > 0,
    '__error_article': masterMissing || articleMissing,
    '__error_qty': false,
    '__warning_nested_cb': false,
    '__warning_boxes_zero': false,
    '__warning_boxes_missing': false,
    '__warning_weight_zero': false,
    '__warning_weight_missing': false,
    '__warning_reason': warnings.join(' | ') || null,
  };
};

const buildComponentCzRows = (row) => {
  const itemNo = normalizeCode(row.itemNo);
  const master = resolveMaster({ itemNo });
  const masterMissing = !master;
  const articleMissing = !hasValue(master?.article);
  const translationMissing = !hasValue(master?.translation);
  const packageMissing = !hasValue(master?.packageDescription);
  const customsCodeText = hasValue(master?.customsCode) ? String(master.customsCode).trim() : null;
  const gtinText = gtinToText(master?.gtin);
  const batchRowsForItem = batchMap[itemNo] || [];

  const buildWarnings = (finalGtin) => {
    const warnings = [];
    if (masterMissing) warnings.push(`нет строки в справочнике для ${itemNo}`);
    if (!masterMissing && articleMissing) warnings.push('пустой артикул в справочнике');
    if (!masterMissing && translationMissing) warnings.push('пустой перевод в справочнике');
    if (!masterMissing && packageMissing) warnings.push('пустые пояснения к материалу и упаковке');
    if (!customsCodeText) warnings.push('не заполнен Код ТНВЭД');
    if (hasAnyBatchFiles && !batchRowsForItem.length) warnings.push(`нет строки в batch для ${itemNo}`);
    if (!finalGtin) warnings.push('не заполнен GTIN');
    return warnings;
  };

  const makeRow = (batchRow) => {
    const finalGtin = gtinText || (batchRow?.barcode) || null;
    const rowWarnings = buildWarnings(finalGtin);
    const baseQty = parseNumber(row.quantity) ?? 0;
    const batchQty = batchRow ? batchRow.quantity : null;
    const qty = batchQty ?? (baseQty || null);
    const share = (baseQty && batchQty != null) ? batchQty / baseQty : null;

    return {
      '#': null,
      'Item No.': itemNo,
      'Артикул': hasValue(master?.article) ? String(master.article).trim() : null,
      'Код ТНВЭД': customsCodeText,
      'GTIN': finalGtin ? `'${finalGtin}` : null,
      'Description': clean(row.description) || null,
      'Перевод': master?.translation ?? '',
      'Пояснения к материалу и упаковке': master?.packageDescription ?? '',
      'Country Of Origin': master?.countryOfOrigin || normalizeCountry(row.countryOfOrigin),
      'Quantity Количество': qty,
      'Unit Price Before Discount': null,
      'Total Before Discount': null,
      'Discount Percentage, %': null,
      'Unit Price After Discount': null,
      'Total,$': null,
      'Commercial Discount, $': null,
      'Количество коробок, шт.': null,
      'Вес, кг': null,
      '№ паллета': null,
      'Batch No': batchRow?.batchNo || null,
      'Prod. date': batchRow?.prodDate || null,
      'Exp. Date': batchRow?.expDate || null,
      'Data Matrix': master?.dataMatrix ?? null,
      'этикетка': master?.label ?? null,
      '% содержания спирта': master?.alcohol ?? null,
      'ДС': master?.ds ?? null,
      'ДТ': master?.dt ?? null,
      'ТОВАР': master?.tovar || clean(row.description) || null,

      '__row_warning': rowWarnings.length > 0,
      '__error_article': masterMissing || articleMissing,
      '__error_tnved': !customsCodeText,
      '__error_gtin': !finalGtin,
      '__warning_nested_cb': false,
      '__warning_boxes_zero': false,
      '__warning_boxes_missing': false,
      '__warning_weight_zero': false,
      '__warning_weight_missing': false,
      '__warning_reason': rowWarnings.join(' | ') || null,
    };
  };

  if (batchRowsForItem.length) {
    return batchRowsForItem.map((b) => makeRow(b));
  }
  return [makeRow(null)];
};

const customsRows = [];
let customsIndex = 1;

for (const entry of displaySequence) {
  if (entry.type === 'component') {
    customsRows.push(buildComponentCustomsRow(entry.row));
    continue;
  }

  const invoiceRow = entry.row;
  const itemNo = invoiceRow.itemNo;
  const batchRows = batchMap[itemNo] || [];
  const packingRows = packingMap[itemNo] || [];
  const fallbackBatchBarcode = batchRows.find((r) => r.barcode)?.barcode || null;
  const master = resolveMaster({ itemNo, batchBarcode: fallbackBatchBarcode });
  const packingTotals = aggregatePackingTotals(packingRows);

  const qtyScale = (packingTotals.quantity && invoiceRow.quantity !== null && invoiceRow.quantity !== undefined && Number(packingTotals.quantity) !== Number(invoiceRow.quantity))
    ? Number(invoiceRow.quantity) / Number(packingTotals.quantity)
    : 1;

  const rowWarnings = [];

  const masterMissing = !master;
  const articleMissing = !hasValue(master?.article);
  const translationMissing = !hasValue(master?.translation);
  const packageMissing = !hasValue(master?.packageDescription);

  const packingMissing = !packingRows.length;
  const qtyMismatch =
    packingTotals.quantity !== null &&
    invoiceRow.quantity !== null &&
    invoiceRow.quantity !== undefined &&
    Number(packingTotals.quantity) !== Number(invoiceRow.quantity);

  const hasNestedInCb = packingRows.some((r) => hasValue(r.nestedInCb));
  const hasZeroBoxes = packingRows.some((r) => r.boxes === 0);
  const hasMissingBoxes = packingRows.some((r) => r.boxes === null || r.boxes === undefined);
  const hasZeroWeight = packingRows.some((r) => r.weight === 0);
  const hasMissingWeight = packingRows.some((r) => r.weight === null || r.weight === undefined);

  if (masterMissing) rowWarnings.push(`нет строки в справочнике для ${itemNo}`);
  if (!masterMissing && articleMissing) rowWarnings.push('пустой артикул в справочнике');
  if (!masterMissing && translationMissing) rowWarnings.push('пустой перевод в справочнике');
  if (!masterMissing && packageMissing) rowWarnings.push('пустые пояснения к материалу и упаковке');
  if (packingMissing) rowWarnings.push(`нет строки в packing для ${itemNo}`);
  if (qtyMismatch) rowWarnings.push(`qty invoice=${invoiceRow.quantity}, packing=${packingTotals.quantity}`);
  if (hasNestedInCb) rowWarnings.push('есть вложение IN CB');
  if (hasZeroBoxes) rowWarnings.push('есть строка с boxes=0');
  if (hasMissingBoxes) rowWarnings.push('есть строка без значения boxes');
  if (hasZeroWeight) rowWarnings.push('есть строка с weight=0');
  if (hasMissingWeight) rowWarnings.push('есть строка без значения weight');

  const articleValue = hasValue(master?.article) ? String(master.article).trim() : null;

  customsRows.push({
    '#': customsIndex++,
    'Item No.': itemNo,
    'Артикул': articleValue,
    'Description': invoiceRow.description || (packingRows[0]?.descriptionFromPacking ?? ''),
    'Перевод': master?.translation ?? '',
    'Пояснения к материалу и упаковке': master?.packageDescription ?? '',
    'Country Of Origin': master?.countryOfOrigin || normalizeCountry(invoiceRow.countryOfOrigin),
    'Quantity Количество': invoiceRow.quantity ?? null,
    'Unit Price Before Discount': invoiceRow.unitPriceBeforeDiscount ?? null,
    'Total Before Discount': round2(invoiceRow.totalBeforeDiscount),
    'Discount Percentage, %':
      invoiceRow.discountPercentage !== null && invoiceRow.discountPercentage !== undefined
        ? `${Number(invoiceRow.discountPercentage).toFixed(2)} %`
        : null,
    'Unit Price After Discount': invoiceRow.unitPriceAfterDiscount ?? null,
    'Total,$': round2(invoiceRow.totalPriceAfterDiscount ?? invoiceRow.totalBeforeDiscount),
    'Commercial Discount, $': round2(invoiceRow.commercialDiscount),
    'Количество коробок, шт.': scalePackingBoxes(packingTotals.boxes, qtyScale),
    'Вес, кг': packingTotals.weight !== null ? Number((packingTotals.weight * qtyScale).toFixed(3)) : null,
    '№ паллета': packingTotals.pallets.join('; ') || null,

    '__row_warning': rowWarnings.length > 0,
    '__error_article': masterMissing || articleMissing,
    '__error_qty': qtyMismatch,
    '__warning_nested_cb': hasNestedInCb,
    '__warning_boxes_zero': hasZeroBoxes,
    '__warning_boxes_missing': hasMissingBoxes,
    '__warning_weight_zero': hasZeroWeight,
    '__warning_weight_missing': hasMissingWeight,
    '__warning_reason': rowWarnings.join(' | ') || null,
  });
}

const czRows = [];
let czIndex = 1;

for (const entry of displaySequence) {
  if (entry.type === 'component') {
    for (const r of buildComponentCzRows(entry.row)) {
      czRows.push(r);
    }
    continue;
  }

  const invoiceRow = entry.row;
  const itemNo = invoiceRow.itemNo;
  const packingRows = packingMap[itemNo] || [];
  const batchRows = batchMap[itemNo] || [];
  const fallbackBatchBarcode = batchRows.find((r) => r.barcode)?.barcode || null;
  const master = resolveMaster({ itemNo, batchBarcode: fallbackBatchBarcode });

  const masterMissing = !master;
  const articleMissing = !hasValue(master?.article);
  const translationMissing = !hasValue(master?.translation);
  const packageMissing = !hasValue(master?.packageDescription);
  const customsCodeText = hasValue(master?.customsCode) ? String(master.customsCode).trim() : null;
  const gtinText = gtinToText(master?.gtin);

  const hasNestedInCb = packingRows.some((r) => hasValue(r.nestedInCb));
  const hasZeroBoxes = packingRows.some((r) => r.boxes === 0);
  const hasMissingBoxes = packingRows.some((r) => r.boxes === null || r.boxes === undefined);
  const hasZeroWeight = packingRows.some((r) => r.weight === 0);
  const hasMissingWeight = packingRows.some((r) => r.weight === null || r.weight === undefined);

  const buildBaseCzWarnings = () => {
    const warnings = [];

    if (masterMissing) warnings.push(`нет строки в справочнике для ${itemNo}`);
    if (!masterMissing && articleMissing) warnings.push('пустой артикул в справочнике');
    if (!masterMissing && translationMissing) warnings.push('пустой перевод в справочнике');
    if (!masterMissing && packageMissing) warnings.push('пустые пояснения к материалу и упаковке');
    if (!customsCodeText) warnings.push('не заполнен Код ТНВЭД');
    if (!packingRows.length) warnings.push(`нет строки в packing для ${itemNo}`);
    if (hasAnyBatchFiles && !batchRows.length) warnings.push(`нет строки в batch для ${itemNo}`);
    if (hasNestedInCb) warnings.push('есть вложение IN CB');
    if (hasZeroBoxes) warnings.push('есть строка с boxes=0');
    if (hasMissingBoxes) warnings.push('есть строка без значения boxes');
    if (hasZeroWeight) warnings.push('есть строка с weight=0');
    if (hasMissingWeight) warnings.push('есть строка без значения weight');

    return warnings;
  };

  if (batchRows.length) {
    for (const batch of batchRows) {
      const baseQty = Number(invoiceRow.quantity || 0);
      const share =
        baseQty && batch.quantity !== null && batch.quantity !== undefined
          ? Number(batch.quantity) / baseQty
          : null;

      const finalGtin = gtinText || batch.barcode || null;
      const rowWarnings = buildBaseCzWarnings();
      if (!finalGtin) rowWarnings.push('не заполнен GTIN');

      const batchPallet = clean(batch.pallet);
      const matchedPackingRows = batchPallet
        ? packingRows.filter((row) =>
            clean(row.sscc) === batchPallet || clean(row.pallet) === batchPallet
          )
        : packingRows;
      const allocatedPackingRows = matchedPackingRows.length
        ? matchedPackingRows
        : packingRows;
      const packingTotals = aggregatePackingTotals(allocatedPackingRows);
      const peerBatchRows = batchPallet
        ? batchRows.filter((row) => clean(row.pallet) === batchPallet)
        : batchRows;
      const peerBatchQuantity = peerBatchRows.reduce(
        (sum, row) => sum + Number(row.quantity || 0),
        0
      );
      const packingShare =
        peerBatchQuantity && batch.quantity !== null && batch.quantity !== undefined
          ? Number(batch.quantity) / peerBatchQuantity
          : (peerBatchRows.length === 1 ? 1 : null);
      const allocatedBoxes = batch.boxes !== null && batch.boxes !== undefined
        ? Number(batch.boxes)
        : (packingTotals.boxes !== null && packingShare !== null
            ? Math.round(Number(packingTotals.boxes) * packingShare)
            : null);
      const allocatedWeight = packingTotals.weight !== null && packingShare !== null
        ? Number((Number(packingTotals.weight) * packingShare).toFixed(3))
        : null;

      czRows.push({
        '#': czIndex++,
        'Item No.': itemNo,
        'Артикул': hasValue(master?.article) ? String(master.article).trim() : null,
        'Код ТНВЭД': customsCodeText,
        'GTIN': finalGtin ? `'${finalGtin}` : null,
        'Description': invoiceRow.description || null,
        'Перевод': master?.translation ?? '',
        'Пояснения к материалу и упаковке': master?.packageDescription ?? '',
        'Country Of Origin': master?.countryOfOrigin || normalizeCountry(invoiceRow.countryOfOrigin),
        'Quantity Количество': batch.quantity ?? invoiceRow.quantity ?? null,
        'Unit Price Before Discount': invoiceRow.unitPriceBeforeDiscount ?? null,
        'Total Before Discount': share
          ? round2(Number(invoiceRow.totalBeforeDiscount) * share)
          : round2(invoiceRow.totalBeforeDiscount),
        'Discount Percentage, %':
          invoiceRow.discountPercentage !== null && invoiceRow.discountPercentage !== undefined
            ? `${Number(invoiceRow.discountPercentage).toFixed(2)} %`
            : null,
        'Unit Price After Discount': invoiceRow.unitPriceAfterDiscount ?? null,
        'Total,$': share
          ? round2(Number(invoiceRow.totalPriceAfterDiscount ?? invoiceRow.totalBeforeDiscount) * share)
          : round2(invoiceRow.totalPriceAfterDiscount ?? invoiceRow.totalBeforeDiscount),
        'Commercial Discount, $': share
          ? round2(Number(invoiceRow.commercialDiscount || 0) * share)
          : round2(invoiceRow.commercialDiscount),
        'Количество коробок, шт.': allocatedBoxes,
        'Вес, кг': allocatedWeight,
        '№ паллета': packingTotals.pallets.join('; ') || null,
        'Batch No': batch.batchNo || null,
        'Prod. date': batch.prodDate || null,
        'Exp. Date': batch.expDate || null,
        'Data Matrix': master?.dataMatrix ?? null,
        'этикетка': master?.label ?? null,
        '% содержания спирта': master?.alcohol ?? null,
        'ДС': master?.ds ?? null,
        'ДТ': master?.dt ?? null,
        'ТОВАР': master?.tovar || batch.itemFrgnName || invoiceRow.description || null,

        '__row_warning': rowWarnings.length > 0,
        '__error_article': masterMissing || articleMissing,
        '__error_tnved': !customsCodeText,
        '__error_gtin': !finalGtin,
        '__warning_nested_cb': hasNestedInCb,
        '__warning_boxes_zero': hasZeroBoxes,
        '__warning_boxes_missing': hasMissingBoxes,
        '__warning_weight_zero': hasZeroWeight,
        '__warning_weight_missing': hasMissingWeight,
        '__warning_reason': rowWarnings.join(' | ') || null,
      });
    }
  } else if (!packingRows.length) {
    const finalGtin = gtinText || null;
    const rowWarnings = buildBaseCzWarnings();
    if (!finalGtin) rowWarnings.push('не заполнен GTIN');

    czRows.push({
      '#': czIndex++,
      'Item No.': itemNo,
      'Артикул': hasValue(master?.article) ? String(master.article).trim() : null,
      'Код ТНВЭД': customsCodeText,
      'GTIN': finalGtin ? `'${finalGtin}` : null,
      'Description': invoiceRow.description || null,
      'Перевод': master?.translation ?? '',
      'Пояснения к материалу и упаковке': master?.packageDescription ?? '',
      'Country Of Origin': master?.countryOfOrigin || normalizeCountry(invoiceRow.countryOfOrigin),
      'Quantity Количество': invoiceRow.quantity ?? null,
      'Unit Price Before Discount': invoiceRow.unitPriceBeforeDiscount ?? null,
      'Total Before Discount': round2(invoiceRow.totalBeforeDiscount),
      'Discount Percentage, %':
        invoiceRow.discountPercentage !== null && invoiceRow.discountPercentage !== undefined
          ? `${Number(invoiceRow.discountPercentage).toFixed(2)} %`
          : null,
      'Unit Price After Discount': invoiceRow.unitPriceAfterDiscount ?? null,
      'Total,$': round2(invoiceRow.totalPriceAfterDiscount ?? invoiceRow.totalBeforeDiscount),
      'Commercial Discount, $': round2(invoiceRow.commercialDiscount),
      'Количество коробок, шт.': null,
      'Вес, кг': null,
      '№ паллета': null,
      'Batch No': null,
      'Prod. date': null,
      'Exp. Date': null,
      'Data Matrix': master?.dataMatrix ?? null,
      'этикетка': master?.label ?? null,
      '% содержания спирта': master?.alcohol ?? null,
      'ДС': master?.ds ?? null,
      'ДТ': master?.dt ?? null,
      'ТОВАР': master?.tovar || invoiceRow.description || null,

      '__row_warning': rowWarnings.length > 0,
      '__error_article': masterMissing || articleMissing,
      '__error_tnved': !customsCodeText,
      '__error_gtin': !finalGtin,
      '__warning_nested_cb': hasNestedInCb,
      '__warning_boxes_zero': hasZeroBoxes,
      '__warning_boxes_missing': hasMissingBoxes,
      '__warning_weight_zero': hasZeroWeight,
      '__warning_weight_missing': hasMissingWeight,
      '__warning_reason': rowWarnings.join(' | ') || null,
    });
  } else {
    const palletSplits = splitPackingByPallet(packingRows);
    const czPackingTotals = aggregatePackingTotals(packingRows);
    const czPackingTotalQty = czPackingTotals.quantity;
    const czBaseQty = Number(invoiceRow.quantity || 0);
    const czQtyScale = (czPackingTotalQty && czBaseQty && Number(czPackingTotalQty) !== czBaseQty)
      ? czBaseQty / Number(czPackingTotalQty)
      : 1;

    for (const split of palletSplits) {
      const baseQty = czBaseQty;
      const palletProportion = (czPackingTotalQty && split.quantity !== null && split.quantity !== undefined)
        ? Number(split.quantity) / Number(czPackingTotalQty)
        : null;
      const invoicePalletQty = (palletProportion !== null && czBaseQty)
        ? round2(czBaseQty * palletProportion)
        : split.quantity ?? czBaseQty;
      const share = palletProportion !== null
        ? palletProportion
        : (baseQty && split.quantity !== null && split.quantity !== undefined
            ? Number(split.quantity) / baseQty
            : null);

      const finalGtin = gtinText || null;
      const rowWarnings = buildBaseCzWarnings();
      if (!finalGtin) rowWarnings.push('не заполнен GTIN');

      czRows.push({
        '#': czIndex++,
        'Item No.': itemNo,
        'Артикул': hasValue(master?.article) ? String(master.article).trim() : null,
        'Код ТНВЭД': customsCodeText,
        'GTIN': finalGtin ? `'${finalGtin}` : null,
        'Description': invoiceRow.description || null,
        'Перевод': master?.translation ?? '',
        'Пояснения к материалу и упаковке': master?.packageDescription ?? '',
        'Country Of Origin': master?.countryOfOrigin || normalizeCountry(invoiceRow.countryOfOrigin),
        'Quantity Количество': invoicePalletQty,
        'Unit Price Before Discount': invoiceRow.unitPriceBeforeDiscount ?? null,
        'Total Before Discount': share
          ? round2(Number(invoiceRow.totalBeforeDiscount) * share)
          : round2(invoiceRow.totalBeforeDiscount),
        'Discount Percentage, %':
          invoiceRow.discountPercentage !== null && invoiceRow.discountPercentage !== undefined
            ? `${Number(invoiceRow.discountPercentage).toFixed(2)} %`
            : null,
        'Unit Price After Discount': invoiceRow.unitPriceAfterDiscount ?? null,
        'Total,$': share
          ? round2(Number(invoiceRow.totalPriceAfterDiscount ?? invoiceRow.totalBeforeDiscount) * share)
          : round2(invoiceRow.totalPriceAfterDiscount ?? invoiceRow.totalBeforeDiscount),
        'Commercial Discount, $': share
          ? round2(Number(invoiceRow.commercialDiscount || 0) * share)
          : round2(invoiceRow.commercialDiscount),
        'Количество коробок, шт.': scalePackingBoxes(split.boxes, czQtyScale),
        'Вес, кг': split.weight !== null ? Number((split.weight * czQtyScale).toFixed(3)) : null,
        '№ паллета': split.palletKey === 'без паллеты' ? null : split.palletKey,
        'Batch No': null,
        'Prod. date': null,
        'Exp. Date': null,
        'Data Matrix': master?.dataMatrix ?? null,
        'этикетка': master?.label ?? null,
        '% содержания спирта': master?.alcohol ?? null,
        'ДС': master?.ds ?? null,
        'ДТ': master?.dt ?? null,
        'ТОВАР': master?.tovar || invoiceRow.description || null,

        '__row_warning': rowWarnings.length > 0,
        '__error_article': masterMissing || articleMissing,
        '__error_tnved': !customsCodeText,
        '__error_gtin': !finalGtin,
        '__warning_nested_cb': hasNestedInCb,
        '__warning_boxes_zero': hasZeroBoxes,
        '__warning_boxes_missing': hasMissingBoxes,
        '__warning_weight_zero': hasZeroWeight,
        '__warning_weight_missing': hasMissingWeight,
        '__warning_reason': rowWarnings.join(' | ') || null,
      });
    }
  }
}

return [{
  json: {
    shipmentKey: bundle.shipmentKey,
    invoiceNo: bundle.invoiceNo,
    invoiceDocsCount: bundle.invoiceDocsCount,
    packingDocsCount: bundle.packingDocsCount,
    batchDocsCount: bundle.batchDocsCount || 0,
    customsRows,
    czRows,
    warnings: bundle.warnings || [],
    chatId: bundle.chatId,
  }
}];
