#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const [, , sourcePath, ...bundlePaths] = process.argv;
if (!sourcePath || !bundlePaths.length) {
  throw new Error(
    'Usage: node verify_moroccanoil_build.js BUILD_SOURCE BUNDLE.json [...]'
  );
}

const source = fs.readFileSync(sourcePath, 'utf8');
const expected = {
  ILSO000003204: {
    customs: 103,
    cz: 105,
    quantity: 7848,
    before: 19177.56,
    after: 19177.56,
    discount: 0,
    boxes: 220,
    weight: 919.902,
  },
  ILSO000000570: {
    customs: 2,
    cz: 3,
    quantity: 948,
    before: 1706.4,
    after: 0,
    discount: 1706.4,
    boxes: 20,
    weight: 274.8,
  },
  ILSO000000580: {
    customs: 50,
    cz: 50,
    quantity: 400,
    before: 1120,
    after: 0,
    discount: 1120,
    boxes: 0,
    weight: 28,
  },
  ILSO000004437: {
    customs: 1,
    cz: 1,
    quantity: 6,
    before: 96,
    after: 0,
    discount: 96,
    boxes: 0,
    weight: 4.8,
  },
  ILSO000008323: {
    customs: 1,
    cz: 1,
    quantity: 372,
    before: 1365.24,
    after: 1365.24,
    discount: 0,
    boxes: 31,
    weight: 2.8427,
  },
};

const sum = (rows, key) =>
  rows.reduce((total, row) => total + Number(row[key] ?? 0), 0);

const closeTo = (actual, wanted, tolerance, label) => {
  if (Math.abs(actual - wanted) > tolerance) {
    throw new Error(`${label}: expected ${wanted}, got ${actual}`);
  }
};

const execute = new Function('$', '$input', source);
const summaries = [];

for (const bundlePath of bundlePaths) {
  const bundle = JSON.parse(fs.readFileSync(bundlePath, 'utf8'));
  const batchBarcode = new Map();
  for (const row of bundle.batchRows || []) {
    if (row.itemNo && row.barcode && !batchBarcode.has(row.itemNo)) {
      batchBarcode.set(row.itemNo, String(row.barcode));
    }
  }
  const seen = new Set();
  const masterRows = [];
  for (const [index, row] of (bundle.invoiceRows || []).entries()) {
    if (!row.itemNo || seen.has(row.itemNo)) continue;
    seen.add(row.itemNo);
    masterRows.push({
      SKU: row.itemNo,
      'SKU RU': `TEST-${row.itemNo}`,
      Barcode:
        batchBarcode.get(row.itemNo) ||
        `729${String(index + 1).padStart(10, '0')}`,
      'Customs Code': '3305900009',
      'PRODUCT DESCRIPTION RU': `RU ${row.itemNo}`,
      'PACKAGE DESCRIPTION RU': 'Тестовая транспортная упаковка',
      'страна происхождения': row.countryOfOrigin || '',
    });
  }

  const $ = (nodeName) => {
    if (nodeName !== 'Parse Python Output - MOROCCANOIL') {
      throw new Error(`Unexpected node: ${nodeName}`);
    }
    return { first: () => ({ json: bundle }) };
  };
  const $input = {
    all: () => masterRows.map((json) => ({ json })),
  };
  const result = execute($, $input)[0].json;
  const wanted = expected[bundle.shipmentKey];
  if (!wanted) {
    throw new Error(`No expectations for ${bundle.shipmentKey}`);
  }

  if (result.customsRows.length !== wanted.customs) {
    throw new Error(
      `${bundle.shipmentKey} customs: expected ${wanted.customs}, ` +
      `got ${result.customsRows.length}`
    );
  }
  if (result.czRows.length !== wanted.cz) {
    throw new Error(
      `${bundle.shipmentKey} CZ: expected ${wanted.cz}, ` +
      `got ${result.czRows.length}`
    );
  }

  for (const [name, rows] of [
    ['customs', result.customsRows],
    ['cz', result.czRows],
  ]) {
    closeTo(
      sum(rows, 'Quantity Количество'),
      wanted.quantity,
      0.001,
      `${bundle.shipmentKey} ${name} quantity`
    );
    closeTo(
      sum(rows, 'Total Before Discount'),
      wanted.before,
      0.1,
      `${bundle.shipmentKey} ${name} before`
    );
    closeTo(
      sum(rows, 'Total,$'),
      wanted.after,
      0.1,
      `${bundle.shipmentKey} ${name} after`
    );
    closeTo(
      sum(rows, 'Commercial Discount, $'),
      wanted.discount,
      0.1,
      `${bundle.shipmentKey} ${name} discount`
    );
    closeTo(
      sum(rows, 'Количество коробок, шт.'),
      wanted.boxes,
      0.001,
      `${bundle.shipmentKey} ${name} boxes`
    );
    closeTo(
      sum(rows, 'Вес, кг'),
      wanted.weight,
      0.02,
      `${bundle.shipmentKey} ${name} weight`
    );
  }

  summaries.push({
    shipmentKey: bundle.shipmentKey,
    invoiceNo: bundle.invoiceNo,
    customsRows: result.customsRows.length,
    czRows: result.czRows.length,
    quantity: sum(result.czRows, 'Quantity Количество'),
    totalBefore: sum(result.czRows, 'Total Before Discount'),
    totalAfter: sum(result.czRows, 'Total,$'),
    commercialDiscount: sum(result.czRows, 'Commercial Discount, $'),
    boxes: sum(result.czRows, 'Количество коробок, шт.'),
    weight: sum(result.czRows, 'Вес, кг'),
    source: path.basename(sourcePath),
  });
}

const mismatchBundle = {
  shipmentKey: 'PALLET-MISMATCH-CHECK',
  invoiceNo: 'TEST',
  batchFiles: ['batch.xlsx'],
  invoiceRows: [{
    itemIndex: 1,
    itemNo: 'SKU1',
    description: 'Item',
    quantity: 20,
    totalBeforeDiscount: 20,
    totalPriceAfterDiscount: 20,
    commercialDiscount: 0,
  }],
  packingRows: [{
    itemNo: 'SKU1',
    quantity: 20,
    weight: 10,
    boxes: 2,
    pallet: 'PL-CORRECT',
    sscc: 'PL-CORRECT',
  }],
  batchRows: [
    { itemNo: 'SKU1', quantity: 10, boxes: 1, pallet: 'PL-WRONG-1' },
    { itemNo: 'SKU1', quantity: 10, boxes: 1, pallet: 'PL-WRONG-2' },
  ],
  warnings: [],
};
const mismatchMaster = [{
  SKU: 'SKU1',
  'SKU RU': '1',
  Barcode: '7290000000001',
  'Customs Code': '3305900009',
  'PRODUCT DESCRIPTION RU': 'Товар',
  'PACKAGE DESCRIPTION RU': 'Коробка',
}];
const mismatch$ = (nodeName) => {
  if (nodeName !== 'Parse Python Output - MOROCCANOIL') {
    throw new Error(`Unexpected node: ${nodeName}`);
  }
  return { first: () => ({ json: mismatchBundle }) };
};
const mismatchInput = {
  all: () => mismatchMaster.map((json) => ({ json })),
};
const mismatchRows = execute(mismatch$, mismatchInput)[0].json.czRows;
for (const row of mismatchRows) {
  if (
    row['Количество коробок, шт.'] !== null ||
    row['Вес, кг'] !== null ||
    row['№ паллета'] !== null ||
    !String(row.__warning_reason || '').includes('не найдена в packing')
  ) {
    throw new Error('Unmatched batch pallet did not fail closed');
  }
}

process.stdout.write(`${JSON.stringify(summaries, null, 2)}\n`);
