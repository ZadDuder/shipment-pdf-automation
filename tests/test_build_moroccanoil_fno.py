from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_NODE = PROJECT_ROOT / "workflows" / "build_moroccanoil.js"
WORKFLOW_EXPORT = PROJECT_ROOT / "final.json"


def run_build_node(bundle: dict, master_rows: list[dict]) -> dict:
    harness = r"""
const fs = require('fs');
const code = fs.readFileSync(process.argv[1], 'utf8');
const bundle = JSON.parse(process.argv[2]);
const masterRows = JSON.parse(process.argv[3]);
const $ = (name) => {
  if (name !== 'Parse Python Output - MOROCCANOIL') {
    throw new Error(`Unexpected node: ${name}`);
  }
  return { first: () => ({ json: bundle }) };
};
const $input = { all: () => masterRows.map((json) => ({ json })) };
const execute = new Function('$', '$input', code);
const result = execute($, $input);
process.stdout.write(JSON.stringify(result[0].json));
"""
    completed = subprocess.run(
        [
            "node",
            "-e",
            harness,
            str(BUILD_NODE),
            json.dumps(bundle, ensure_ascii=False),
            json.dumps(master_rows, ensure_ascii=False),
        ],
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def test_source_does_not_replace_valid_zero_values():
    source = BUILD_NODE.read_text(encoding="utf-8")

    assert "totalPriceAfterDiscount ||" not in source
    assert "const scalePackingBoxes" in source
    assert "if (Number(boxes) === 0) return 0;" in source
    assert (
        "packingTotals.boxes !== null ? Math.max(1, Math.round" not in source
    )
    assert "split.boxes !== null ? Math.max(1, Math.round" not in source
    assert "не найдена в packing" in source


def test_maintained_source_is_synced_to_workflow_export():
    workflow = json.loads(WORKFLOW_EXPORT.read_text(encoding="utf-8"))
    exported_source = next(
        node["parameters"]["jsCode"]
        for node in workflow["nodes"]
        if node["name"] == "Build Moroccanoil Customs and CZ Rows"
    )

    assert exported_source == BUILD_NODE.read_text(encoding="utf-8")


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js is required to execute the n8n Code node locally",
)
def test_foc_batch_rows_keep_zero_total_boxes_and_matching_pallet():
    bundle = {
        "shipmentKey": "ILSO000000580",
        "invoiceNo": "126018814",
        "batchFiles": ["batch.xlsx"],
        "invoiceRows": [
            {
                "itemIndex": 1,
                "itemNo": "M412ECCR100",
                "description": "Color Eclipse",
                "quantity": 8,
                "unitPriceBeforeDiscount": 2.8,
                "totalBeforeDiscount": 22.4,
                "discountPercentage": 100,
                "unitPriceAfterDiscount": 0,
                "totalPriceAfterDiscount": 0,
                "commercialDiscount": 22.4,
                "countryOfOrigin": "Italy",
            }
        ],
        "packingRows": [
            {
                "itemNo": "M412ECCR100",
                "quantity": 8,
                "weight": 0.56,
                "boxes": 0,
                "pallet": "CB000001146",
                "sscc": "CB000001146",
            }
        ],
        "batchRows": [
            {
                "itemNo": "M412ECCR100",
                "quantity": 8,
                "quantityUnit": "pieces",
                "boxes": 0,
                "batchNo": "10B623IA00",
                "prodDate": "2026-02-10",
                "expDate": "2029-02-09",
                "barcode": "7290121930871",
                "pallet": "CB000001146",
            }
        ],
        "warnings": [],
    }
    master = [
        {
            "SKU": "M412ECCR100",
            "SKU RU": "977973",
            "Barcode": "7290121930871",
            "Customs Code": "3305900009",
            "PRODUCT DESCRIPTION RU": "Краска",
            "PACKAGE DESCRIPTION RU": "Туба",
            "страна происхождения": "Italy",
        }
    ]

    result = run_build_node(bundle, master)

    assert len(result["customsRows"]) == 1
    assert result["customsRows"][0]["Total,$"] == 0
    assert result["customsRows"][0]["Количество коробок, шт."] == 0
    assert len(result["czRows"]) == 1
    assert result["czRows"][0]["Total,$"] == 0
    assert result["czRows"][0]["Количество коробок, шт."] == 0
    assert result["czRows"][0]["Вес, кг"] == 0.56
    assert result["czRows"][0]["№ паллета"] == "CB000001146"


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js is required to execute the n8n Code node locally",
)
def test_blank_batch_rows_are_allocated_to_their_own_pallets():
    bundle = {
        "shipmentKey": "ILSO000000570",
        "invoiceNo": "126018813",
        "batchFiles": ["batch.xlsx"],
        "invoiceRows": [
            {
                "itemIndex": 1,
                "itemNo": "MBOX25HCTRYME",
                "description": "Box for General Try Me Kit",
                "quantity": 468,
                "unitPriceBeforeDiscount": 1.8,
                "totalBeforeDiscount": 842.4,
                "discountPercentage": 100,
                "unitPriceAfterDiscount": 0,
                "totalPriceAfterDiscount": 0,
                "commercialDiscount": 842.4,
                "countryOfOrigin": "Israel",
            }
        ],
        "packingRows": [
            {
                "itemNo": "MBOX25HCTRYME",
                "quantity": 108,
                "weight": 32.4,
                "boxes": 0,
                "pallet": "PL000003269",
                "sscc": "PL000003269",
            },
            {
                "itemNo": "MBOX25HCTRYME",
                "quantity": 360,
                "weight": 108,
                "boxes": 0,
                "pallet": "PL000003654",
                "sscc": "PL000003654",
            },
        ],
        "batchRows": [
            {
                "itemNo": "MBOX25HCTRYME",
                "quantity": 108,
                "quantityUnit": "pieces",
                "boxes": 0,
                "batchNo": None,
                "pallet": "PL000003269",
            },
            {
                "itemNo": "MBOX25HCTRYME",
                "quantity": 360,
                "quantityUnit": "pieces",
                "boxes": 0,
                "batchNo": None,
                "pallet": "PL000003654",
            },
        ],
        "warnings": [],
    }
    master = [
        {
            "SKU": "MBOX25HCTRYME",
            "SKU RU": "146549",
            "Barcode": "7290113146549",
            "Customs Code": "3304990000",
            "PRODUCT DESCRIPTION RU": "Набор",
            "PACKAGE DESCRIPTION RU": "Коробка",
            "страна происхождения": "Israel",
        }
    ]

    rows = run_build_node(bundle, master)["czRows"]

    assert [row["Quantity Количество"] for row in rows] == [108, 360]
    assert [row["Количество коробок, шт."] for row in rows] == [0, 0]
    assert [row["Вес, кг"] for row in rows] == [32.4, 108]
    assert [row["№ паллета"] for row in rows] == [
        "PL000003269",
        "PL000003654",
    ]
    assert all(row["Batch No"] is None for row in rows)
    assert sum(row["Total,$"] for row in rows) == 0


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js is required to execute the n8n Code node locally",
)
def test_unmatched_batch_pallet_does_not_fall_back_to_all_packing():
    bundle = {
        "shipmentKey": "MISMATCH",
        "invoiceNo": "1",
        "batchFiles": ["batch.xlsx"],
        "invoiceRows": [
            {
                "itemIndex": 1,
                "itemNo": "SKU1",
                "description": "Item",
                "quantity": 20,
                "totalBeforeDiscount": 20,
                "totalPriceAfterDiscount": 20,
                "commercialDiscount": 0,
            }
        ],
        "packingRows": [
            {
                "itemNo": "SKU1",
                "quantity": 20,
                "weight": 10,
                "boxes": 2,
                "pallet": "PL-CORRECT",
                "sscc": "PL-CORRECT",
            }
        ],
        "batchRows": [
            {
                "itemNo": "SKU1",
                "quantity": 10,
                "boxes": 1,
                "pallet": "PL-WRONG-1",
            },
            {
                "itemNo": "SKU1",
                "quantity": 10,
                "boxes": 1,
                "pallet": "PL-WRONG-2",
            },
        ],
        "warnings": [],
    }
    master = [
        {
            "SKU": "SKU1",
            "SKU RU": "1",
            "Barcode": "7290000000001",
            "Customs Code": "3305900009",
            "PRODUCT DESCRIPTION RU": "Товар",
            "PACKAGE DESCRIPTION RU": "Коробка",
        }
    ]

    rows = run_build_node(bundle, master)["czRows"]

    assert [row["Количество коробок, шт."] for row in rows] == [None, None]
    assert [row["Вес, кг"] for row in rows] == [None, None]
    assert [row["№ паллета"] for row in rows] == [None, None]
    assert all("не найдена в packing" in row["__warning_reason"] for row in rows)
