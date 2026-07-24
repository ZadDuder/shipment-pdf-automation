from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_NODE = PROJECT_ROOT / "workflows" / "build_moil.js"
pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js is required to execute the n8n Code node locally",
)


def run_build_node(bundle: dict, master_rows: list[dict]) -> dict:
    harness = r"""
const fs = require('fs');
const code = fs.readFileSync(process.argv[1], 'utf8');
const bundle = JSON.parse(process.argv[2]);
const masterRows = JSON.parse(process.argv[3]);
const $ = (name) => {
  if (name !== 'Parse Python Output') throw new Error(`Unexpected node: ${name}`);
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


def master_row(sku: str, article: str, barcode: str) -> dict:
    return {
        "SKU": sku,
        "SKU RU": article,
        "Barcode": barcode,
        "Customs Code": "3305900009",
        "PRODUCT DESCRIPTION RU": f"RU {sku}",
        "PACKAGE DESCRIPTION RU": "Флакон в транспортной упаковке",
        "страна происхождения": "Израиль",
    }


def base_bundle(invoice_rows: list[dict]) -> dict:
    return {
        "shipmentKey": "TEST",
        "invoiceNo": "1",
        "invoiceDocsCount": 1,
        "packingDocsCount": 1,
        "batchDocsCount": 0,
        "batchFiles": [],
        "invoiceRows": invoice_rows,
        "packingRows": [],
        "batchRows": [],
        "warnings": [],
        "chatId": 1,
    }


def test_kit_components_are_visible_without_double_counting_money():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "KIT1",
                "description": "Travel kit",
                "quantity": 10,
                "unitPriceBeforeDiscount": 10,
                "totalBeforeDiscount": 100,
                "discountPercentage": 0,
                "unitPriceAfterDiscount": 10,
                "totalPriceAfterDiscount": 100,
                "commercialDiscount": 0,
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": 1,
                "itemNo": "COMP1",
                "description": "Kit component",
                "quantity": 10,
                "unitPriceBeforeDiscount": 4,
                "totalBeforeDiscount": 40,
                "discountPercentage": 0,
                "unitPriceAfterDiscount": 4,
                "totalPriceAfterDiscount": 40,
                "commercialDiscount": 0,
                "__rowOrder": 2,
                "__isComponent": True,
            },
        ]
    )

    result = run_build_node(
        bundle,
        [
            master_row("KIT1", "1001", "7290000000001"),
            master_row("COMP1", "1002", "7290000000002"),
        ],
    )

    assert [row["Item No."] for row in result["customsRows"]] == ["KIT1", "COMP1"]
    assert [row["#"] for row in result["customsRows"]] == [1, None]
    component = result["customsRows"][1]
    assert component["Quantity Количество"] == 10
    assert component["Unit Price Before Discount"] is None
    assert component["Total Before Discount"] is None
    assert component["Unit Price After Discount"] is None
    assert component["Total,$"] is None
    assert component["Commercial Discount, $"] is None


def test_foc_total_after_discount_stays_zero():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "FOC1",
                "description": "Free sample",
                "quantity": 5,
                "unitPriceBeforeDiscount": 8.86,
                "totalBeforeDiscount": 44.3,
                "discountPercentage": 100,
                "unitPriceAfterDiscount": 0,
                "totalPriceAfterDiscount": 0,
                "commercialDiscount": 44.3,
                "__rowOrder": 1,
                "__isComponent": False,
                "__isFoc": True,
            }
        ]
    )

    result = run_build_node(
        bundle,
        [master_row("FOC1", "1003", "7290000000003")],
    )

    customs = result["customsRows"][0]
    cz = result["czRows"][0]
    assert customs["Total Before Discount"] == 44.3
    assert customs["Total,$"] == 0
    assert customs["Commercial Discount, $"] == 44.3
    assert cz["Total,$"] == 0


def test_batch_rows_split_boxes_and_weight_without_duplication():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "SKU1",
                "description": "Product",
                "quantity": 120,
                "unitPriceBeforeDiscount": 2,
                "totalBeforeDiscount": 240,
                "discountPercentage": 0,
                "unitPriceAfterDiscount": 2,
                "totalPriceAfterDiscount": 240,
                "commercialDiscount": 0,
                "__rowOrder": 1,
                "__isComponent": False,
            }
        ]
    )
    bundle["batchDocsCount"] = 1
    bundle["batchFiles"] = ["shipping-data.xlsx"]
    bundle["packingRows"] = [
        {
            "itemNo": "SKU1",
            "quantity": 120,
            "boxes": 10,
            "weight": 30,
            "pallet": "1",
            "sscc": "100006202",
        }
    ]
    bundle["batchRows"] = [
        {
            "itemNo": "SKU1",
            "quantity": 72,
            "quantityUnit": "pieces",
            "boxes": 6,
            "pallet": "100006202",
            "batchNo": "A",
        },
        {
            "itemNo": "SKU1",
            "quantity": 48,
            "quantityUnit": "pieces",
            "boxes": 4,
            "pallet": "100006202",
            "batchNo": "B",
        },
    ]

    result = run_build_node(
        bundle,
        [master_row("SKU1", "1004", "7290000000004")],
    )

    assert [row["Количество коробок, шт."] for row in result["czRows"]] == [6, 4]
    assert [row["Вес, кг"] for row in result["czRows"]] == [18, 12]
    assert [row["№ паллета"] for row in result["czRows"]] == ["1", "1"]
    assert sum(row["Количество коробок, шт."] for row in result["czRows"]) == 10
    assert sum(row["Вес, кг"] for row in result["czRows"]) == 30


def test_explicit_zero_boxes_are_not_turned_into_one():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "SKU2",
                "description": "Nested product",
                "quantity": 6,
                "unitPriceBeforeDiscount": 1,
                "totalBeforeDiscount": 6,
                "discountPercentage": 0,
                "unitPriceAfterDiscount": 1,
                "totalPriceAfterDiscount": 6,
                "commercialDiscount": 0,
                "__rowOrder": 1,
                "__isComponent": False,
            }
        ]
    )
    bundle["packingRows"] = [
        {
            "itemNo": "SKU2",
            "quantity": 6,
            "boxes": 0,
            "weight": 1.74,
            "pallet": "1",
            "nestedInCb": "100005636",
        }
    ]

    result = run_build_node(
        bundle,
        [master_row("SKU2", "1005", "7290000000005")],
    )

    assert result["customsRows"][0]["Количество коробок, шт."] == 0
    assert result["czRows"][0]["Количество коробок, шт."] == 0
    assert result["czRows"][0]["__warning_boxes_zero"] is True
