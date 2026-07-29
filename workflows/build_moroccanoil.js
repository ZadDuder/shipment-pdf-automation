const pythonData = $('Parse Python Output - MOROCCANOIL').first().json;
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

const documentKeyFor = (row) =>
  clean(row.__sourceFileName)
  || clean(row.__invoiceNo)
  || '__bundle';

const sourceOrdinal = (value) => {
  const match = clean(value).match(/-(\d+)\.[^.]+$/);
  return match ? Number(match[1]) : null;
};

const rowsQuantity = (rows) => {
  let total = 0;
  let hasQuantity = false;
  for (const row of rows) {
    const quantity = parseNumber(row.quantity);
    if (quantity === null) continue;
    total += quantity;
    hasQuantity = true;
  }
  return hasQuantity ? total : null;
};

const quantitiesMatch = (left, right) => (
  left !== null
  && right !== null
  && Math.abs(Number(left) - Number(right)) < 0.000001
);

const selectExactRowsForQuantity = (rows, targetQuantity) => {
  const target = parseNumber(targetQuantity);
  if (!rows.length || target === null) return null;
  if (quantitiesMatch(rowsQuantity(rows), target)) return rows;

  const exactSingle = rows.find(
    (row) => quantitiesMatch(parseNumber(row.quantity), target)
  );
  if (exactSingle) return [exactSingle];

  if (rows.length > 18) return null;
  const quantityKey = (value) => Math.round(Number(value) * 1_000_000);
  const targetKey = quantityKey(target);
  const subsets = new Map([[0, []]]);

  for (let index = 0; index < rows.length; index += 1) {
    const quantity = parseNumber(rows[index].quantity);
    if (quantity === null || quantity <= 0) continue;
    const rowKey = quantityKey(quantity);
    for (const [sumKey, indexes] of [...subsets.entries()].reverse()) {
      const nextKey = sumKey + rowKey;
      if (nextKey > targetKey || subsets.has(nextKey)) continue;
      subsets.set(nextKey, [...indexes, index]);
    }
  }

  const selectedIndexes = subsets.get(targetKey);
  return selectedIndexes?.length
    ? selectedIndexes.map((index) => rows[index])
    : null;
};

const selectRowsForInvoiceEntry = (
  rows,
  entry,
  usedRows,
  siblingCount
) => {
  const available = rows.filter((row) => !usedRows.has(row));
  if (!available.length) return [];
  if (siblingCount <= 1) {
    for (const row of available) usedRows.add(row);
    return available;
  }

  const invoiceOrdinal = sourceOrdinal(entry.row.__sourceFileName);
  const sameDocument = invoiceOrdinal === null
    ? []
    : available.filter(
        (row) => sourceOrdinal(row.sourceFileName) === invoiceOrdinal
      );
  const targetQuantity = parseNumber(entry.row.quantity);
  const selected = (
    selectExactRowsForQuantity(sameDocument, targetQuantity)
    || selectExactRowsForQuantity(available, targetQuantity)
    || (sameDocument.length ? sameDocument : available)
  );

  for (const row of selected) usedRows.add(row);
  return selected;
};

const round2 = (value) =>
  value === null || value === undefined ? null : Number(Number(value).toFixed(2));

const allocateIntegerTotal = (total, weights) => {
  if (total === null || total === undefined) {
    return weights.map(() => null);
  }
  if (!weights.length) return [];

  const normalizedTotal = Math.max(0, Math.round(Number(total)));
  const normalizedWeights = weights.map((weight) => Math.max(0, Number(weight) || 0));
  const weightTotal = normalizedWeights.reduce((sum, weight) => sum + weight, 0);
  if (!weightTotal) {
    const result = weights.map(() => 0);
    result[0] = normalizedTotal;
    return result;
  }

  const exact = normalizedWeights.map(
    (weight) => normalizedTotal * weight / weightTotal
  );
  const result = exact.map((value) => Math.floor(value));
  let remainder = normalizedTotal - result.reduce((sum, value) => sum + value, 0);
  const order = exact
    .map((value, index) => ({ index, fraction: value - Math.floor(value) }))
    .sort((a, b) => b.fraction - a.fraction || a.index - b.index);

  for (let index = 0; index < remainder; index += 1) {
    result[order[index % order.length].index] += 1;
  }
  return result;
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
    __inputOrder: idx + 1,
    __documentKey: documentKeyFor(row),
    __rowOrder: hasValue(row.__rowOrder) ? Number(row.__rowOrder) : idx + 1,
    __isComponent: Boolean(row.__isComponent) || row.itemIndex === null || row.itemIndex === undefined || row.itemIndex === '',
  }));

const documentOrder = new Map();
for (const row of rawInvoiceRows) {
  if (!documentOrder.has(row.__documentKey)) {
    documentOrder.set(row.__documentKey, documentOrder.size);
  }
}
rawInvoiceRows.sort((a, b) => {
  const documentDiff = (
    documentOrder.get(a.__documentKey)
    - documentOrder.get(b.__documentKey)
  );
  if (documentDiff !== 0) return documentDiff;
  if (a.__rowOrder !== b.__rowOrder) return a.__rowOrder - b.__rowOrder;
  return a.__inputOrder - b.__inputOrder;
});

const invoiceAgg = {};
for (const row of rawInvoiceRows) {
  if (row.__isComponent) continue;

  const itemNo = normalizeCode(row.itemNo);
  if (!itemNo) continue;
  const mainKey = `${row.__documentKey}\u0000${row.__inputOrder}`;

  if (!invoiceAgg[mainKey]) {
    invoiceAgg[mainKey] = {
      mainKey,
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
      __firstInputOrder: row.__inputOrder,
      __documentKey: row.__documentKey,
      __sourceFileName: row.__sourceFileName || null,
      __invoiceNo: row.__invoiceNo || null,
    };
  }

  const target = invoiceAgg[mainKey];

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
  if (a.__firstInputOrder !== b.__firstInputOrder) {
    return a.__firstInputOrder - b.__firstInputOrder;
  }
  return String(a.itemNo).localeCompare(String(b.itemNo));
});

const mainMap = new Map();
for (const row of aggregatedMainRows) {
  mainMap.set(row.mainKey, row);
}

const displaySequence = [];
const emittedMain = new Set();
const currentParentByDocument = new Map();

for (const row of rawInvoiceRows) {
  const itemNo = normalizeCode(row.itemNo);
  if (!itemNo) continue;
  const documentKey = row.__documentKey;

  if (row.__isComponent) {
    const parentKey = currentParentByDocument.get(documentKey) || null;
    displaySequence.push({
      type: 'component',
      row,
      itemNo,
      parentKey,
      rowOrder: hasValue(row.__rowOrder) ? Number(row.__rowOrder) : 999999,
    });
    continue;
  }

  const mainKey = `${documentKey}\u0000${row.__inputOrder}`;
  currentParentByDocument.set(documentKey, mainKey);
  if (!emittedMain.has(mainKey) && mainMap.has(mainKey)) {
    emittedMain.add(mainKey);
    displaySequence.push({
      type: 'main',
      row: mainMap.get(mainKey),
      itemNo,
      mainKey,
      rowOrder: mainMap.get(mainKey).__firstRowOrder,
    });
  }
}

const mainCountByItemNo = new Map();
for (const entry of displaySequence) {
  if (entry.type !== 'main') continue;
  mainCountByItemNo.set(
    entry.itemNo,
    (mainCountByItemNo.get(entry.itemNo) || 0) + 1
  );
}

const packingRowsByEntry = new Map();
const batchRowsByEntry = new Map();
const usedPackingRows = new Set();
const usedBatchRows = new Set();
for (const entry of displaySequence) {
  if (entry.type !== 'main') continue;
  const siblingCount = mainCountByItemNo.get(entry.itemNo) || 1;
  packingRowsByEntry.set(
    entry,
    selectRowsForInvoiceEntry(
      packingMap[entry.itemNo] || [],
      entry,
      usedPackingRows,
      siblingCount
    )
  );
  batchRowsByEntry.set(
    entry,
    selectRowsForInvoiceEntry(
      batchMap[entry.itemNo] || [],
      entry,
      usedBatchRows,
      siblingCount
    )
  );
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

  const buildWarnings = (finalGtin) => {
    const warnings = [];
    if (masterMissing) warnings.push(`нет строки в справочнике для ${itemNo}`);
    if (!masterMissing && articleMissing) warnings.push('пустой артикул в справочнике');
    if (!masterMissing && translationMissing) warnings.push('пустой перевод в справочнике');
    if (!masterMissing && packageMissing) warnings.push('пустые пояснения к материалу и упаковке');
    if (!customsCodeText) warnings.push('не заполнен Код ТНВЭД');
    if (!finalGtin) warnings.push('не заполнен GTIN');
    return warnings;
  };

  const makeRow = (batchRow) => {
    const finalGtin = gtinText || (batchRow?.barcode) || null;
    const rowWarnings = buildWarnings(finalGtin);
    const baseQty = parseNumber(row.quantity) ?? 0;

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
      'Quantity Количество': baseQty || null,
      'Unit Price Before Discount': null,
      'Total Before Discount': null,
      'Discount Percentage, %': null,
      'Unit Price After Discount': null,
      'Total,$': null,
      'Commercial Discount, $': null,
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
  const batchRows = batchRowsByEntry.get(entry) || [];
  const packingRows = packingRowsByEntry.get(entry) || [];
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
    'Количество коробок, шт.': packingTotals.boxes !== null ? Math.max(1, Math.round(packingTotals.boxes * qtyScale)) : null,
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
const czRowsByEntry = new Map();

for (const entry of displaySequence) {
  if (entry.type === 'component') {
    const componentRows = buildComponentCzRows(entry.row);
    for (const r of componentRows) {
      czRows.push(r);
    }
    czRowsByEntry.set(entry, {
      rows: componentRows,
      baseQuantity: parseNumber(entry.row.quantity),
    });
    continue;
  }

  const czStartIndex = czRows.length;
  const invoiceRow = entry.row;
  const itemNo = invoiceRow.itemNo;
  const packingRows = packingRowsByEntry.get(entry) || [];
  const batchRows = batchRowsByEntry.get(entry) || [];
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
    const packingTotals = aggregatePackingTotals(packingRows);
    const czQtyScale = (
      packingTotals.quantity
      && invoiceRow.quantity !== null
      && invoiceRow.quantity !== undefined
      && Number(packingTotals.quantity) !== Number(invoiceRow.quantity)
    )
      ? Number(invoiceRow.quantity) / Number(packingTotals.quantity)
      : 1;
    const batchWeights = batchRows.map(
      (batch) => parseNumber(batch.quantity) ?? 1
    );
    const scaledBoxes = packingTotals.boxes === null
      ? null
      : Math.max(0, Math.round(packingTotals.boxes * czQtyScale));
    const boxesByBatch = allocateIntegerTotal(scaledBoxes, batchWeights);
    const scaledWeight = packingTotals.weight === null
      ? null
      : Number((packingTotals.weight * czQtyScale).toFixed(3));
    const batchWeightTotal = batchWeights.reduce(
      (sum, weight) => sum + Number(weight || 0),
      0
    );
    const weightByBatch = batchWeights.map((weight, index) => {
      if (scaledWeight === null) return null;
      if (!batchWeightTotal) return index === 0 ? scaledWeight : 0;
      return Number((scaledWeight * Number(weight) / batchWeightTotal).toFixed(3));
    });
    if (scaledWeight !== null && weightByBatch.length) {
      const priorWeight = weightByBatch
        .slice(0, -1)
        .reduce((sum, weight) => sum + Number(weight || 0), 0);
      weightByBatch[weightByBatch.length - 1] = Number(
        (scaledWeight - priorWeight).toFixed(3)
      );
    }

    for (let batchIndex = 0; batchIndex < batchRows.length; batchIndex += 1) {
      const batch = batchRows[batchIndex];
      const baseQty = Number(invoiceRow.quantity || 0);
      const share =
        baseQty && batch.quantity !== null && batch.quantity !== undefined
          ? Number(batch.quantity) / baseQty
          : null;

      const finalGtin = gtinText || batch.barcode || null;
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
        'Количество коробок, шт.': boxesByBatch[batchIndex],
        'Вес, кг': weightByBatch[batchIndex],
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
        'Количество коробок, шт.': split.boxes !== null ? Math.max(1, Math.round(split.boxes * czQtyScale)) : null,
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

  czRowsByEntry.set(entry, {
    rows: czRows.slice(czStartIndex),
    baseQuantity: parseNumber(invoiceRow.quantity),
  });
}

const componentsByParent = new Map();
const mainEntryByKey = new Map();
for (const entry of displaySequence) {
  if (entry.type === 'main') {
    mainEntryByKey.set(entry.mainKey, entry);
    continue;
  }
  if (!entry.parentKey) continue;
  if (!componentsByParent.has(entry.parentKey)) {
    componentsByParent.set(entry.parentKey, []);
  }
  componentsByParent.get(entry.parentKey).push(entry);
}

const orderedCzRows = [];
for (const entry of displaySequence) {
  const entryResult = czRowsByEntry.get(entry);
  if (!entryResult) continue;

  if (entry.type === 'component') {
    if (
      !entry.parentKey
      || !mainEntryByKey.has(entry.parentKey)
    ) {
      orderedCzRows.push(...entryResult.rows);
    }
    continue;
  }

  const components = componentsByParent.get(entry.mainKey) || [];
  if (!components.length) {
    orderedCzRows.push(...entryResult.rows);
    continue;
  }

  const parentQuantity = Number(entryResult.baseQuantity || 0);
  for (const parentRow of entryResult.rows) {
    orderedCzRows.push(parentRow);
    const parentBlockQuantity = parseNumber(parentRow['Quantity Количество']);

    for (const componentEntry of components) {
      const componentResult = czRowsByEntry.get(componentEntry);
      const componentRow = componentResult?.rows?.[0];
      if (!componentRow) continue;

      const componentQuantity = Number(componentResult.baseQuantity || 0);
      const componentRatio = parentQuantity
        ? componentQuantity / parentQuantity
        : null;
      const blockQuantity = (
        componentRatio !== null
        && parentBlockQuantity !== null
      )
        ? round2(parentBlockQuantity * componentRatio)
        : componentRow['Quantity Количество'];

      orderedCzRows.push({
        ...componentRow,
        'Quantity Количество': blockQuantity,
      });
    }
  }
}
czRows.length = 0;
czRows.push(...orderedCzRows);

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
