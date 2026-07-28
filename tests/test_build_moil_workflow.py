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


def test_kit_component_batches_attach_by_component_description():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "MP26TRAVELC",
                "description": "Travel Kit 2026 - Hydration",
                "quantity": 96,
                "__invoiceNo": "INV-KIT",
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": 1,
                "itemNo": "M107COHY70",
                "description": "Hydrating Conditioner 70ml",
                "quantity": 96,
                "__invoiceNo": "INV-KIT",
                "__rowOrder": 2,
                "__isComponent": True,
            },
        ]
    )
    bundle["batchDocsCount"] = 1
    bundle["batchFiles"] = ["LOAD0006732.xlsx"]
    bundle["packingRows"] = [
        {
            "itemNo": "MP26TRAVELC",
            "quantity": 96,
            "boxes": 12,
            "weight": 60,
            "pallet": "14",
            "sscc": "100005654",
        }
    ]
    bundle["batchRows"] = [
        {
            "itemNo": "MP26TRAVELC",
            "kitComponentDescription": "Hydrating Conditioner 70ml",
            "quantity": 96,
            "quantityUnit": "pieces",
            "boxes": None,
            "pallet": "100005654",
            "batchNo": "0201FA",
        }
    ]

    result = run_build_node(
        bundle,
        [
            master_row("MP26TRAVELC", "KIT", "7290121931526"),
            master_row("M107COHY70", "COMP", "7290011000001"),
        ],
    )

    parent_rows = [
        row for row in result["czRows"]
        if row["Item No."] == "MP26TRAVELC"
    ]
    component_rows = [
        row for row in result["czRows"]
        if row["Item No."] == "M107COHY70"
    ]
    assert len(parent_rows) == 1
    assert parent_rows[0]["Quantity Количество"] == 96
    assert parent_rows[0]["Количество коробок, шт."] == 12
    assert parent_rows[0]["Batch No"] is None
    assert "нет строки в batch" not in (
        parent_rows[0]["__warning_reason"] or ""
    )
    assert len(component_rows) == 1
    assert component_rows[0]["Quantity Количество"] == 96
    assert component_rows[0]["Batch No"] == "0201FA"


def test_same_component_description_is_scoped_to_parent_kit():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "KIT-A",
                "description": "Kit A",
                "quantity": 10,
                "__invoiceNo": "INV-KIT",
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": 1,
                "itemNo": "COMP-A",
                "description": "Shared Component 10ml",
                "quantity": 10,
                "__invoiceNo": "INV-KIT",
                "__rowOrder": 2,
                "__isComponent": True,
            },
            {
                "itemIndex": 2,
                "itemNo": "KIT-B",
                "description": "Kit B",
                "quantity": 20,
                "__invoiceNo": "INV-KIT",
                "__rowOrder": 3,
                "__isComponent": False,
            },
            {
                "itemIndex": 2,
                "itemNo": "COMP-B",
                "description": "Shared Component 10ml",
                "quantity": 20,
                "__invoiceNo": "INV-KIT",
                "__rowOrder": 4,
                "__isComponent": True,
            },
        ]
    )
    bundle["batchDocsCount"] = 1
    bundle["batchFiles"] = ["kit.xlsx"]
    bundle["batchRows"] = [
        {
            "itemNo": "KIT-A",
            "kitComponentDescription": "Shared Component 10ml",
            "quantity": 10,
            "quantityUnit": "pieces",
            "batchNo": "BATCH-A",
        },
        {
            "itemNo": "KIT-B",
            "kitComponentDescription": "Shared Component 10ml",
            "quantity": 20,
            "quantityUnit": "pieces",
            "batchNo": "BATCH-B",
        },
    ]

    result = run_build_node(
        bundle,
        [
            master_row("KIT-A", "KIT-A", "7290000000001"),
            master_row("KIT-B", "KIT-B", "7290000000002"),
            master_row("COMP-A", "COMP-A", "7290000000003"),
            master_row("COMP-B", "COMP-B", "7290000000004"),
        ],
    )

    batches_by_component = {
        row["Item No."]: row["Batch No"]
        for row in result["czRows"]
        if row["Item No."] in {"COMP-A", "COMP-B"}
    }
    assert batches_by_component == {
        "COMP-A": "BATCH-A",
        "COMP-B": "BATCH-B",
    }


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


def test_multiple_invoice_documents_create_customs_and_cz_pair_per_invoice():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "SKU-A",
                "quantity": 10,
                "__invoiceNo": "INV-A",
                "__isComponent": False,
            },
            {
                "itemIndex": 1,
                "itemNo": "SKU-B",
                "quantity": 20,
                "__invoiceNo": "INV-B",
                "__isComponent": False,
            },
        ]
    )
    bundle["invoiceDocsCount"] = 2

    result = run_build_node(
        bundle,
        [
            master_row("SKU-A", "A", "7290000000001"),
            master_row("SKU-B", "B", "7290000000002"),
        ],
    )

    assert [sheet["sheetName"] for sheet in result["customsSheets"]] == [
        "INV-A",
        "INV-B",
    ]
    assert [row["Item No."] for row in result["customsSheets"][0]["rows"]] == [
        "SKU-A"
    ]
    assert [row["Item No."] for row in result["customsSheets"][1]["rows"]] == [
        "SKU-B"
    ]
    assert [sheet["sheetName"] for sheet in result["czSheets"]] == [
        "ЧЗ INV-A",
        "ЧЗ INV-B",
    ]
    assert [row["Item No."] for row in result["czSheets"][0]["rows"]] == [
        "SKU-A"
    ]
    assert [row["Item No."] for row in result["czSheets"][1]["rows"]] == [
        "SKU-B"
    ]


def test_equal_quantity_invoices_consume_distinct_packing_rows():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "SKU1",
                "quantity": 10,
                "__invoiceNo": "INV-A",
                "__isComponent": False,
            },
            {
                "itemIndex": 1,
                "itemNo": "SKU1",
                "quantity": 10,
                "__invoiceNo": "INV-B",
                "__isComponent": False,
            },
        ]
    )
    bundle["invoiceDocsCount"] = 2
    bundle["packingRows"] = [
        {
            "itemNo": "SKU1",
            "quantity": 10,
            "boxes": 1,
            "weight": 10,
            "pallet": "1",
            "sscc": "1001",
        },
        {
            "itemNo": "SKU1",
            "quantity": 10,
            "boxes": 2,
            "weight": 20,
            "pallet": "2",
            "sscc": "1002",
        },
    ]

    result = run_build_node(
        bundle,
        [master_row("SKU1", "1001", "7290000000001")],
    )

    assert [
        (
            sheet["invoiceNo"],
            sheet["rows"][0]["Количество коробок, шт."],
            sheet["rows"][0]["Вес, кг"],
            sheet["rows"][0]["№ паллета"],
        )
        for sheet in result["customsSheets"]
    ] == [
        ("INV-A", 1, 10, "1"),
        ("INV-B", 2, 20, "2"),
    ]
    assert [
        (
            sheet["invoiceNo"],
            sheet["rows"][0]["Количество коробок, шт."],
            sheet["rows"][0]["Вес, кг"],
            sheet["rows"][0]["№ паллета"],
        )
        for sheet in result["czSheets"]
    ] == [
        ("INV-A", 1, 10, "1"),
        ("INV-B", 2, 20, "2"),
    ]


@pytest.mark.parametrize(
    ("invoice_docs_count", "invoice_numbers"),
    [
        (1, ["INV-A", "INV-B"]),
        (2, ["INV-A", "INV-A"]),
        (2, ["", ""]),
    ],
)
def test_invoice_document_and_parsed_number_mismatch_is_rejected(
    invoice_docs_count, invoice_numbers
):
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "SKU-A",
                "quantity": 10,
                "__invoiceNo": invoice_numbers[0],
                "__isComponent": False,
            },
            {
                "itemIndex": 1,
                "itemNo": "SKU-B",
                "quantity": 20,
                "__invoiceNo": invoice_numbers[1],
                "__isComponent": False,
            },
        ]
    )
    bundle["invoiceDocsCount"] = invoice_docs_count

    with pytest.raises(subprocess.CalledProcessError) as error:
        run_build_node(bundle, [])

    assert "invoice" in error.value.stderr


@pytest.mark.parametrize("packing_docs_count", [0, 2])
def test_non_single_packing_document_is_rejected(packing_docs_count):
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "SKU1",
                "description": "Product",
                "quantity": 1,
                "__invoiceNo": "INV-A",
                "__isComponent": False,
            }
        ]
    )
    bundle["packingDocsCount"] = packing_docs_count

    with pytest.raises(subprocess.CalledProcessError) as error:
        run_build_node(bundle, [])

    assert "один общий packing" in error.value.stderr


def test_m101lt100_is_allocated_between_regular_and_foc_invoices():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "M101LT100",
                "description": "Moroccanoil Treatment Light 100ml",
                "quantity": 5,
                "unitPriceBeforeDiscount": 8.86,
                "totalBeforeDiscount": 44.3,
                "discountPercentage": 100,
                "unitPriceAfterDiscount": 0,
                "totalPriceAfterDiscount": 0,
                "commercialDiscount": 44.3,
                "__invoiceNo": "126022814",
                "__rowOrder": 1,
                "__isComponent": False,
                "__isFoc": True,
            },
            {
                "itemIndex": 5,
                "itemNo": "M101LT100",
                "description": "Moroccanoil Treatment Light 100ml",
                "quantity": 240,
                "unitPriceBeforeDiscount": 8.86,
                "totalBeforeDiscount": 2126.4,
                "discountPercentage": 0,
                "unitPriceAfterDiscount": 8.86,
                "totalPriceAfterDiscount": 2126.4,
                "commercialDiscount": 0,
                "__invoiceNo": "126022816",
                "__rowOrder": 5,
                "__isComponent": False,
            },
        ]
    )
    bundle["invoiceDocsCount"] = 2
    bundle["batchDocsCount"] = 1
    bundle["batchFiles"] = ["LOAD0006732.xlsx"]
    bundle["packingRows"] = [
        {
            "itemNo": "M101LT100",
            "quantity": 240,
            "boxes": 5,
            "weight": 69.1,
            "pallet": "9",
            "sscc": "100004392",
        },
        {
            "itemNo": "M101LT100",
            "quantity": 5,
            "boxes": 0,
            "weight": 1.35,
            "pallet": "13",
            "sscc": "100005635",
            "nestedInCb": "100005636",
        },
    ]
    bundle["batchRows"] = [
        {
            "itemNo": "M101LT100",
            "quantity": 240,
            "quantityUnit": "pieces",
            "boxes": 5,
            "pallet": "100004392",
            "batchNo": "14734LDZ",
        },
        {
            "itemNo": "M101LT100",
            "quantity": 5,
            "quantityUnit": "pieces",
            "boxes": 0,
            "pallet": "100005636",
            "batchNo": "14477BZ",
        },
    ]

    result = run_build_node(
        bundle,
        [master_row("M101LT100", "100005636", "7290011587757")],
    )

    by_invoice = {
        sheet["invoiceNo"]: sheet["rows"][0]
        for sheet in result["customsSheets"]
    }
    assert by_invoice["126022814"]["Quantity Количество"] == 5
    assert by_invoice["126022814"]["Количество коробок, шт."] == 0
    assert by_invoice["126022814"]["Вес, кг"] == 1.35
    assert by_invoice["126022814"]["№ паллета"] == "13"
    assert by_invoice["126022814"]["Total,$"] == 0
    assert by_invoice["126022816"]["Quantity Количество"] == 240
    assert by_invoice["126022816"]["Количество коробок, шт."] == 5
    assert by_invoice["126022816"]["Вес, кг"] == 69.1
    assert by_invoice["126022816"]["№ паллета"] == "9"

    cz_by_invoice = {
        sheet["invoiceNo"]: sheet["rows"]
        for sheet in result["czSheets"]
    }
    assert [
        (
            row["Quantity Количество"],
            row["Количество коробок, шт."],
            row["Вес, кг"],
            row["№ паллета"],
            row["Batch No"],
        )
        for row in cz_by_invoice["126022814"]
        if row["Item No."] == "M101LT100"
    ] == [(5, 0, 1.35, "13", "14477BZ")]
    assert [
        (
            row["Quantity Количество"],
            row["Количество коробок, шт."],
            row["Вес, кг"],
            row["№ паллета"],
            row["Batch No"],
        )
        for row in cz_by_invoice["126022816"]
        if row["Item No."] == "M101LT100"
    ] == [(240, 5, 69.1, "9", "14734LDZ")]


def test_single_invoice_keeps_customer_examples_separate_and_complete():
    bundle = base_bundle(
        [
            {
                "itemIndex": 14,
                "itemNo": "M105THL100",
                "description": "Thickening Lotion 100ml",
                "quantity": 360,
                "unitPriceBeforeDiscount": 5.44,
                "totalBeforeDiscount": 1958.4,
                "discountPercentage": 5,
                "unitPriceAfterDiscount": 5.17,
                "totalPriceAfterDiscount": 1860.48,
                "commercialDiscount": 97.92,
                "__invoiceNo": "126022816",
                "__rowOrder": 14,
                "__isComponent": False,
            },
            {
                "itemIndex": 72,
                "itemNo": "M201HCM40",
                "description": "Hand Cream 40ml Fragrance Originale",
                "quantity": 432,
                "unitPriceBeforeDiscount": 2.81,
                "totalBeforeDiscount": 1213.92,
                "discountPercentage": 0,
                "unitPriceAfterDiscount": 2.81,
                "totalPriceAfterDiscount": 1213.92,
                "commercialDiscount": 0,
                "__invoiceNo": "126022816",
                "__rowOrder": 72,
                "__isComponent": False,
            },
        ]
    )
    bundle["packingRows"] = [
        {
            "itemNo": "UNRELATED",
            "quantity": 999,
            "boxes": 99,
            "weight": 999,
            "pallet": "1",
        },
        {
            "itemNo": "M105THL100",
            "quantity": 360,
            "boxes": 6,
            "weight": 54,
            "pallet": "6",
        },
        {
            "itemNo": "M201HCM40",
            "quantity": 432,
            "boxes": 3,
            "weight": 25.92,
            "pallet": "12",
        },
    ]

    result = run_build_node(
        bundle,
        [
            master_row("M105THL100", "877657", "7290015877657"),
            master_row("M201HCM40", "146549", "7290113146549"),
        ],
    )
    by_sku = {row["Item No."]: row for row in result["customsRows"]}

    thickening = by_sku["M105THL100"]
    assert thickening["Артикул"] == "877657"
    assert thickening["Commercial Discount, $"] == 97.92
    assert thickening["Количество коробок, шт."] == 6
    assert thickening["Вес, кг"] == 54

    hand_cream = by_sku["M201HCM40"]
    assert hand_cream["Артикул"] == "146549"
    assert hand_cream["Quantity Количество"] == 432
    assert hand_cream["Количество коробок, шт."] == 3
    assert hand_cream["Вес, кг"] == 25.92


def test_same_sku_component_does_not_absorb_standalone_product_data():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "KIT1",
                "description": "Travel kit",
                "quantity": 976,
                "unitPriceBeforeDiscount": 10,
                "totalBeforeDiscount": 9760,
                "discountPercentage": 0,
                "unitPriceAfterDiscount": 10,
                "totalPriceAfterDiscount": 9760,
                "commercialDiscount": 0,
                "__invoiceNo": "INV-A",
                "__rowOrder": 1,
                "__isComponent": False,
            },
            {
                "itemIndex": None,
                "itemNo": "M201HCM40",
                "description": "Hand Cream kit component",
                "quantity": 976,
                "__invoiceNo": "INV-A",
                "__rowOrder": 2,
                "__isComponent": True,
            },
            {
                "itemIndex": 72,
                "itemNo": "M201HCM40",
                "description": "Hand Cream 40ml Fragrance Originale",
                "quantity": 432,
                "unitPriceBeforeDiscount": 2.81,
                "totalBeforeDiscount": 1213.92,
                "discountPercentage": 0,
                "unitPriceAfterDiscount": 2.81,
                "totalPriceAfterDiscount": 1213.92,
                "commercialDiscount": 0,
                "__invoiceNo": "INV-A",
                "__rowOrder": 72,
                "__isComponent": False,
            },
        ]
    )
    bundle["packingRows"] = [
        {
            "itemNo": "M201HCM40",
            "quantity": 432,
            "boxes": 3,
            "weight": 25.92,
            "pallet": "12",
        }
    ]

    result = run_build_node(
        bundle,
        [
            master_row("KIT1", "1001", "7290000000001"),
            master_row("M201HCM40", "146549", "7290113146549"),
        ],
    )
    hand_cream_rows = [
        row for row in result["customsRows"]
        if row["Item No."] == "M201HCM40"
    ]

    assert len(hand_cream_rows) == 2
    component, standalone = hand_cream_rows
    assert component["#"] is None
    assert component["Quantity Количество"] == 976
    assert component["Total Before Discount"] is None
    assert component["Total,$"] is None
    assert component["Количество коробок, шт."] is None
    assert component["Вес, кг"] is None

    assert standalone["#"] == 2
    assert standalone["Quantity Количество"] == 432
    assert standalone["Total Before Discount"] == 1213.92
    assert standalone["Total,$"] == 1213.92
    assert standalone["Количество коробок, шт."] == 3
    assert standalone["Вес, кг"] == 25.92


@pytest.mark.parametrize(
    ("invoice_quantity", "expected_boxes", "expected_weight", "expected_pallet"),
    [
        (6, 0, 1.68, "14"),
        (1188, 33, 332.64, "16"),
    ],
)
def test_shared_packing_selects_exact_rows_for_each_invoice(
    invoice_quantity, expected_boxes, expected_weight, expected_pallet
):
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "M201BDM100",
                "description": "Brumes du Maroc 100ml",
                "quantity": invoice_quantity,
                "unitPriceBeforeDiscount": 7,
                "totalBeforeDiscount": 7 * invoice_quantity,
                "discountPercentage": 0,
                "unitPriceAfterDiscount": 7,
                "totalPriceAfterDiscount": 7 * invoice_quantity,
                "commercialDiscount": 0,
                "__invoiceNo": "INV-A",
                "__rowOrder": 1,
                "__isComponent": False,
            }
        ]
    )
    bundle["packingRows"] = [
        {
            "itemNo": "M201BDM100",
            "quantity": 6,
            "boxes": 0,
            "weight": 1.68,
            "pallet": "14",
            "nestedInCb": "100005655",
        },
        {
            "itemNo": "M201BDM100",
            "quantity": 1188,
            "boxes": 33,
            "weight": 332.64,
            "pallet": "16",
        },
    ]

    result = run_build_node(
        bundle,
        [master_row("M201BDM100", "141230", "7290113141230")],
    )
    customs = result["customsRows"][0]

    assert customs["Количество коробок, шт."] == expected_boxes
    assert customs["Вес, кг"] == expected_weight
    assert customs["№ паллета"] == expected_pallet
    assert customs["__error_qty"] is False
    assert "qty invoice=" not in (customs["__warning_reason"] or "")

    assert len(result["czRows"]) == 1
    assert result["czRows"][0]["Количество коробок, шт."] == expected_boxes
    assert result["czRows"][0]["Вес, кг"] == expected_weight
    assert result["czRows"][0]["№ паллета"] == expected_pallet


def test_ambiguous_exact_packing_subsets_keep_warning_and_fallback():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "SKU1",
                "description": "Product",
                "quantity": 10,
                "__invoiceNo": "INV-A",
                "__isComponent": False,
            }
        ]
    )
    bundle["packingRows"] = [
        {"itemNo": "SKU1", "quantity": 10, "boxes": 1, "weight": 10, "pallet": "1"},
        {"itemNo": "SKU1", "quantity": 4, "boxes": 1, "weight": 4, "pallet": "2"},
        {"itemNo": "SKU1", "quantity": 6, "boxes": 1, "weight": 6, "pallet": "3"},
    ]

    result = run_build_node(
        bundle,
        [master_row("SKU1", "1001", "7290000000001")],
    )
    customs = result["customsRows"][0]

    assert customs["__error_qty"] is True
    assert "qty invoice=10, packing=20" in customs["__warning_reason"]
    assert customs["№ паллета"] == "1; 2; 3"


def test_many_same_sku_packing_rows_use_bounded_fallback():
    bundle = base_bundle(
        [
            {
                "itemIndex": 1,
                "itemNo": "SKU1",
                "description": "Product",
                "quantity": 100,
                "__invoiceNo": "INV-A",
                "__isComponent": False,
            }
        ]
    )
    bundle["packingRows"] = [
        {
            "itemNo": "SKU1",
            "quantity": quantity,
            "boxes": 1,
            "weight": quantity,
            "pallet": str(quantity),
        }
        for quantity in range(1, 26)
    ]

    result = run_build_node(
        bundle,
        [master_row("SKU1", "1001", "7290000000001")],
    )
    customs = result["customsRows"][0]

    assert customs["__error_qty"] is True
    assert "qty invoice=100, packing=325" in customs["__warning_reason"]
