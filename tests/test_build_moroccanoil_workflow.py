from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_NODE = PROJECT_ROOT / "workflows" / "build_moroccanoil.js"
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
        "invoiceNo": "INV-TEST",
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


def test_kit_component_keeps_product_fields_but_not_money_or_logistics():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "KIT1",
                "description": "Color kit",
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
                "itemIndex": None,
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
    bundle["batchDocsCount"] = 1
    bundle["batchFiles"] = ["batch.xlsx"]
    bundle["batchRows"] = [
        {
            "itemNo": "COMP1",
            "quantity": 5,
            "batchNo": "STANDALONE-BATCH",
            "prodDate": "2026-01-01",
            "expDate": "2029-01-01",
        }
    ]

    result = run_build_node(
        bundle,
        [
            master_row("KIT1", "KIT", "7290000000001"),
            master_row("COMP1", "COMP", "7290000000002"),
        ],
    )

    for rows in (result["customsRows"], result["czRows"]):
        component = next(row for row in rows if row["Item No."] == "COMP1")
        assert component["#"] is None
        assert component["Артикул"] == "COMP"
        assert component["Description"] == "Kit component"
        assert component["Quantity Количество"] == 10
        assert component["Unit Price Before Discount"] is None
        assert component["Total Before Discount"] is None
        assert component["Discount Percentage, %"] is None
        assert component["Unit Price After Discount"] is None
        assert component["Total,$"] is None
        assert component["Commercial Discount, $"] is None
        assert component["Количество коробок, шт."] is None
        assert component["Вес, кг"] is None
        assert component["№ паллета"] is None

    component_cz = next(
        row for row in result["czRows"] if row["Item No."] == "COMP1"
    )
    assert component_cz["Batch No"] is None
    assert component_cz["Prod. date"] is None
    assert component_cz["Exp. Date"] is None


def test_kit_breakdown_is_repeated_directly_under_each_parent_pallet_row():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "KIT1",
                "description": "Color kit",
                "quantity": 10,
                "totalBeforeDiscount": 100,
                "totalPriceAfterDiscount": 100,
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": None,
                "itemNo": "COMP1",
                "description": "Two units in every kit",
                "quantity": 20,
                "totalBeforeDiscount": 40,
                "totalPriceAfterDiscount": 40,
                "__rowOrder": 2,
                "__isComponent": True,
            },
        ]
    )
    bundle["packingRows"] = [
        {
            "itemNo": "KIT1",
            "quantity": 4,
            "boxes": 1,
            "weight": 4,
            "pallet": "P1",
        },
        {
            "itemNo": "KIT1",
            "quantity": 6,
            "boxes": 1,
            "weight": 6,
            "pallet": "P2",
        },
    ]

    result = run_build_node(
        bundle,
        [
            master_row("KIT1", "KIT", "7290000000001"),
            master_row("COMP1", "COMP", "7290000000002"),
        ],
    )

    assert [
        (
            row["Item No."],
            row["Quantity Количество"],
            row["№ паллета"],
            row["#"],
        )
        for row in result["czRows"]
    ] == [
        ("KIT1", 4, "P1", 1),
        ("COMP1", 8, None, None),
        ("KIT1", 6, "P2", 2),
        ("COMP1", 12, None, None),
    ]
    assert sum(
        row["Quantity Количество"]
        for row in result["czRows"]
        if row["Item No."] == "COMP1"
    ) == 20


def test_kit_breakdown_is_repeated_under_each_parent_batch_row():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "KIT1",
                "description": "Color kit",
                "quantity": 10,
                "totalBeforeDiscount": 100,
                "totalPriceAfterDiscount": 100,
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": None,
                "itemNo": "COMP1",
                "description": "Two units in every kit",
                "quantity": 20,
                "__rowOrder": 2,
                "__isComponent": True,
            },
        ]
    )
    bundle["batchDocsCount"] = 1
    bundle["batchFiles"] = ["batch.xlsx"]
    bundle["batchRows"] = [
        {
            "itemNo": "KIT1",
            "quantity": 4,
            "batchNo": "BATCH-A",
        },
        {
            "itemNo": "KIT1",
            "quantity": 6,
            "batchNo": "BATCH-B",
        },
    ]
    bundle["packingRows"] = [
        {
            "itemNo": "KIT1",
            "quantity": 10,
            "boxes": 5,
            "weight": 20,
            "pallet": "P1",
        }
    ]

    result = run_build_node(
        bundle,
        [
            master_row("KIT1", "KIT", "7290000000001"),
            master_row("COMP1", "COMP", "7290000000002"),
        ],
    )

    assert [
        (
            row["Item No."],
            row["Quantity Количество"],
            row["Batch No"],
            row["#"],
        )
        for row in result["czRows"]
    ] == [
        ("KIT1", 4, "BATCH-A", 1),
        ("COMP1", 8, None, None),
        ("KIT1", 6, "BATCH-B", 2),
        ("COMP1", 12, None, None),
    ]
    parents = [row for row in result["czRows"] if row["#"] is not None]
    assert [row["Количество коробок, шт."] for row in parents] == [2, 3]
    assert [row["Вес, кг"] for row in parents] == [8, 12]
    assert sum(row["Количество коробок, шт."] for row in parents) == 5
    assert sum(row["Вес, кг"] for row in parents) == 20


def test_component_stays_with_its_parent_across_multiple_invoice_documents():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "A-FIRST",
                "quantity": 1,
                "__invoiceNo": "INV-A",
                "__sourceFileName": "invoice-a.pdf",
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": 2,
                "itemNo": "B-SECOND",
                "quantity": 1,
                "__invoiceNo": "INV-A",
                "__sourceFileName": "invoice-a.pdf",
                "__rowOrder": 2,
                "__isComponent": False,
            },
            {
                "itemIndex": 1,
                "itemNo": "Z-KIT",
                "quantity": 1,
                "__invoiceNo": "INV-B",
                "__sourceFileName": "invoice-b.pdf",
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": None,
                "itemNo": "Z-COMP",
                "quantity": 1,
                "__invoiceNo": "INV-B",
                "__sourceFileName": "invoice-b.pdf",
                "__rowOrder": 2,
                "__isComponent": True,
            },
        ]
    )
    bundle["invoiceDocsCount"] = 2

    result = run_build_node(
        bundle,
        [
            master_row("A-FIRST", "A", "7290000000001"),
            master_row("B-SECOND", "B", "7290000000002"),
            master_row("Z-KIT", "KIT", "7290000000003"),
            master_row("Z-COMP", "COMP", "7290000000004"),
        ],
    )

    expected = ["A-FIRST", "B-SECOND", "Z-KIT", "Z-COMP"]
    assert [row["Item No."] for row in result["customsRows"]] == expected
    assert [row["Item No."] for row in result["czRows"]] == expected


def test_duplicate_kit_sku_is_isolated_by_invoice_document():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "SAME-KIT",
                "description": "Kit in invoice A",
                "quantity": 10,
                "totalBeforeDiscount": 100,
                "totalPriceAfterDiscount": 100,
                "__invoiceNo": "INV-A",
                "__sourceFileName": "moroccanoil-inv-TEST-01.pdf",
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": None,
                "itemNo": "COMP-A",
                "quantity": 10,
                "__invoiceNo": "INV-A",
                "__sourceFileName": "moroccanoil-inv-TEST-01.pdf",
                "__rowOrder": 2,
                "__isComponent": True,
            },
            {
                "itemIndex": 1,
                "itemNo": "SAME-KIT",
                "description": "Kit in invoice B",
                "quantity": 20,
                "totalBeforeDiscount": 300,
                "totalPriceAfterDiscount": 300,
                "__invoiceNo": "INV-B",
                "__sourceFileName": "moroccanoil-inv-TEST-02.pdf",
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": None,
                "itemNo": "COMP-B",
                "quantity": 40,
                "__invoiceNo": "INV-B",
                "__sourceFileName": "moroccanoil-inv-TEST-02.pdf",
                "__rowOrder": 2,
                "__isComponent": True,
            },
        ]
    )
    bundle["invoiceDocsCount"] = 2
    bundle["packingRows"] = [
        {
            "itemNo": "SAME-KIT",
            "quantity": 10,
            "boxes": 1,
            "weight": 10,
            "pallet": "P1",
            "__sourceFileName": "moroccanoil-pac-TEST-01.pdf",
        },
        {
            "itemNo": "SAME-KIT",
            "quantity": 20,
            "boxes": 2,
            "weight": 20,
            "pallet": "P2",
            "__sourceFileName": "moroccanoil-pac-TEST-02.pdf",
        },
    ]
    bundle["batchDocsCount"] = 2
    bundle["batchFiles"] = ["batch-01.xlsx", "batch-02.xlsx"]
    bundle["batchRows"] = [
        {
            "itemNo": "SAME-KIT",
            "quantity": 10,
            "batchNo": "BATCH-A",
            "__sourceFileName": "moroccanoil-batch-TEST-01.xlsx",
        },
        {
            "itemNo": "SAME-KIT",
            "quantity": 20,
            "batchNo": "BATCH-B",
            "__sourceFileName": "moroccanoil-batch-TEST-02.xlsx",
        },
    ]

    result = run_build_node(
        bundle,
        [
            master_row("SAME-KIT", "KIT", "7290000000001"),
            master_row("COMP-A", "COMP-A", "7290000000002"),
            master_row("COMP-B", "COMP-B", "7290000000003"),
        ],
    )

    assert [
        (
            row["Item No."],
            row["Quantity Количество"],
            row["#"],
        )
        for row in result["customsRows"]
    ] == [
        ("SAME-KIT", 10, 1),
        ("COMP-A", 10, None),
        ("SAME-KIT", 20, 2),
        ("COMP-B", 40, None),
    ]
    assert [
        (
            row["Item No."],
            row["Quantity Количество"],
            row["Batch No"],
            row["Количество коробок, шт."],
            row["Вес, кг"],
            row["№ паллета"],
        )
        for row in result["czRows"]
    ] == [
        ("SAME-KIT", 10, "BATCH-A", 1, 10, "P1"),
        ("COMP-A", 10, None, None, None, None),
        ("SAME-KIT", 20, "BATCH-B", 2, 20, "P2"),
        ("COMP-B", 40, None, None, None, None),
    ]


def test_repeated_kit_sku_in_one_invoice_keeps_separate_component_blocks():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "SAME-KIT",
                "description": "First kit block",
                "quantity": 10,
                "__invoiceNo": "INV-A",
                "__sourceFileName": "invoice-a.pdf",
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": None,
                "itemNo": "COMP-A",
                "quantity": 10,
                "__invoiceNo": "INV-A",
                "__sourceFileName": "invoice-a.pdf",
                "__rowOrder": 2,
                "__isComponent": True,
            },
            {
                "itemIndex": 2,
                "itemNo": "SAME-KIT",
                "description": "Second kit block",
                "quantity": 20,
                "__invoiceNo": "INV-A",
                "__sourceFileName": "invoice-a.pdf",
                "__rowOrder": 3,
                "__isComponent": False,
            },
            {
                "itemIndex": None,
                "itemNo": "COMP-B",
                "quantity": 40,
                "__invoiceNo": "INV-A",
                "__sourceFileName": "invoice-a.pdf",
                "__rowOrder": 4,
                "__isComponent": True,
            },
        ]
    )

    result = run_build_node(
        bundle,
        [
            master_row("SAME-KIT", "KIT", "7290000000001"),
            master_row("COMP-A", "COMP-A", "7290000000002"),
            master_row("COMP-B", "COMP-B", "7290000000003"),
        ],
    )

    expected = [
        ("SAME-KIT", 10, 1),
        ("COMP-A", 10, None),
        ("SAME-KIT", 20, 2),
        ("COMP-B", 40, None),
    ]
    for rows in (result["customsRows"], result["czRows"]):
        assert [
            (
                row["Item No."],
                row["Quantity Количество"],
                row["#"],
            )
            for row in rows
        ] == expected


def test_free_kit_keeps_zero_total_after_discount():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "FREE-KIT",
                "description": "Free stylist gift set",
                "quantity": 60,
                "unitPriceBeforeDiscount": 10.85,
                "totalBeforeDiscount": 651,
                "discountPercentage": 100,
                "unitPriceAfterDiscount": 0,
                "totalPriceAfterDiscount": 0,
                "commercialDiscount": 651,
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": None,
                "itemNo": "FREE-COMP",
                "description": "Gift set bag",
                "quantity": 60,
                "totalBeforeDiscount": 450,
                "totalPriceAfterDiscount": 0,
                "commercialDiscount": 450,
                "__rowOrder": 2,
                "__isComponent": True,
            },
        ]
    )

    result = run_build_node(
        bundle,
        [
            master_row("FREE-KIT", "KIT", "7290000000001"),
            master_row("FREE-COMP", "COMP", "7290000000002"),
        ],
    )

    assert result["customsRows"][0]["Total,$"] == 0
    assert result["czRows"][0]["Total,$"] == 0
