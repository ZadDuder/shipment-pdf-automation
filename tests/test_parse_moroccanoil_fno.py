from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest
from openpyxl import Workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_DATA_DIR = PROJECT_ROOT / "файлы 30-07-2026"
LEGACY_DATA_DIR = PROJECT_ROOT / "Moroccanoil"


def _entry(path: Path) -> dict[str, str]:
    return {
        "path": str(path),
        "saved_name": path.name,
        "original_name": path.name,
    }


def test_discovers_supplier_fno_file_names(moroccanoil_parser, tmp_path):
    shipment = "ILSO000000570"
    invoice = tmp_path / "ILSO000000570-126018813 new.pdf"
    packing = tmp_path / "MO Packing Slip ILSO000000570.pdf"
    batch = tmp_path / "batch-ILSO000000570 (1).xlsx"
    for path in (invoice, packing, batch):
        path.touch()

    invoices, packings, batches, manifest = (
        moroccanoil_parser.discover_file_entries(str(tmp_path), shipment)
    )

    assert manifest is None
    assert [Path(row["path"]).name for row in invoices] == [invoice.name]
    assert [Path(row["path"]).name for row in packings] == [packing.name]
    assert [Path(row["path"]).name for row in batches] == [batch.name]


def test_manifest_cannot_reference_files_outside_shipment_directory(
    moroccanoil_parser, tmp_path
):
    shipment_dir = tmp_path / "shipment"
    shipment_dir.mkdir()
    inside = shipment_dir / "moroccanoil-inv-SAFE-1.pdf"
    outside = tmp_path / "outside.pdf"
    inside.touch()
    outside.touch()
    manifest = {
        "files": [
            {
                "saved_path": str(inside),
                "saved_name": inside.name,
                "doc_type": "inv",
            },
            {
                "saved_path": str(outside),
                "saved_name": outside.name,
                "doc_type": "pac",
            },
        ]
    }
    (shipment_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    entries = moroccanoil_parser.build_manifest_entries(
        str(shipment_dir), manifest
    )

    assert [Path(entry["path"]).name for entry in entries] == [inside.name]


def test_manifest_preserves_double_spaces_without_allowing_path_escape(
    moroccanoil_parser, tmp_path
):
    shipment_dir = tmp_path / "shipment"
    shipment_dir.mkdir()
    inside = shipment_dir / "MO  Packing Slip ILSO000004437.pdf"
    outside = tmp_path / "outside  invoice.pdf"
    inside.touch()
    outside.touch()
    manifest = {
        "files": [
            {
                "saved_path": inside.name,
                "saved_name": inside.name,
                "doc_type": "pac",
            },
            {
                "saved_path": str(outside),
                "saved_name": outside.name,
                "doc_type": "inv",
            },
        ]
    }

    entries = moroccanoil_parser.build_manifest_entries(
        str(shipment_dir), manifest
    )

    assert [entry["path"] for entry in entries] == [str(inside.resolve())]
    assert entries[0]["saved_name"] == inside.name


def test_discovery_does_not_reintroduce_rejected_symlink_from_fallback(
    moroccanoil_parser, tmp_path
):
    shipment = "SAFE"
    shipment_dir = tmp_path / "shipment"
    shipment_dir.mkdir()
    outside = tmp_path / f"moroccanoil-inv-{shipment}-1.pdf"
    outside.touch()
    symlink = shipment_dir / outside.name
    try:
        symlink.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")
    (shipment_dir / "manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "saved_name": symlink.name,
                        "doc_type": "inv",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    invoices, packings, batches, manifest_path = (
        moroccanoil_parser.discover_file_entries(
            str(shipment_dir), shipment
        )
    )

    assert invoices == []
    assert packings == []
    assert batches == []
    assert manifest_path == str(shipment_dir / "manifest.json")


def test_fno_invoice_table_parses_wrapped_skus_and_foc(
    moroccanoil_parser, monkeypatch, tmp_path
):
    invoice_path = tmp_path / "invoice.pdf"
    invoice_path.touch()
    table = [
        [
            "#",
            "Item No.",
            "Description",
            "Unit\nQuantity",
            "Unit Price\nBefore\nDiscount",
            "Total Before\nDiscount",
            "Discount\n%",
            "Unit Price\nAfter\nDiscount",
            "Total Price",
            "Produce\nCountry",
        ],
        [
            "1 FOC",
            "MBOX25HC\nTRYME",
            "Box for General Try Me Kit",
            "468",
            "1.80 $",
            "842.4 $",
            "100.00%",
            "0.00 $",
            "0.00 $",
            "Israel",
        ],
        [
            "2\nFOC",
            "M409OCRD\n20V250A",
            "SAMPLE - Oxidative Cream Developer",
            "480",
            "1.80 $",
            "864 $",
            "100.00%",
            "0.00 $",
            "0.00 $",
            "Italy",
        ],
    ]
    monkeypatch.setattr(
        moroccanoil_parser,
        "extract_pdf_lines",
        lambda _: ["Invoice No 126018813"],
    )
    monkeypatch.setattr(
        moroccanoil_parser,
        "extract_pdf_tables",
        lambda _: [table],
        raising=False,
    )

    warnings: list[str] = []
    invoice_no, rows = moroccanoil_parser.parse_invoice_pdf(
        _entry(invoice_path), "ILSO000000570", warnings
    )

    assert warnings == []
    assert invoice_no == "126018813"
    assert [row["itemNo"] for row in rows] == [
        "MBOX25HCTRYME",
        "M409OCRD20V250A",
    ]
    assert [row["quantity"] for row in rows] == [468.0, 480.0]
    assert all(row["__isFoc"] is True for row in rows)
    assert rows[0]["commercialDiscount"] == 842.4
    assert rows[1]["countryOfOrigin"] == "Italy"


def test_fno_invoice_text_fallback_parses_wrapped_sku_when_tables_are_empty(
    moroccanoil_parser, monkeypatch, tmp_path
):
    invoice_path = tmp_path / "ILSO000004437-126018816 new.pdf"
    invoice_path.touch()
    lines = [
        "Invoice No 126018816",
        (
            "1 FOC M408BVPW Blonde Voyage Powder Lightener "
            "6 16.00 $ 96 $ 100.00% 0.00 $ 0.00 $ Italy"
        ),
        "7L750 7 levels",
    ]
    monkeypatch.setattr(
        moroccanoil_parser,
        "extract_pdf_lines",
        lambda _: lines,
    )
    monkeypatch.setattr(
        moroccanoil_parser,
        "extract_pdf_tables",
        lambda _: [],
    )

    warnings: list[str] = []
    invoice_no, rows = moroccanoil_parser.parse_invoice_pdf(
        _entry(invoice_path), "ILSO000004437", warnings
    )

    assert warnings == []
    assert invoice_no == "126018816"
    assert len(rows) == 1
    assert rows[0]["itemNo"] == "M408BVPW7L750"
    assert rows[0]["quantity"] == 6
    assert rows[0]["totalBeforeDiscount"] == 96
    assert rows[0]["totalPriceAfterDiscount"] == 0
    assert rows[0]["commercialDiscount"] == 96
    assert rows[0]["countryOfOrigin"] == "Italy"
    assert rows[0]["__isFoc"] is True


def test_fno_invoice_text_fallback_keeps_repeated_one_character_sku_suffix(
    moroccanoil_parser, monkeypatch, tmp_path
):
    invoice_path = tmp_path / "invoice.pdf"
    invoice_path.touch()
    monkeypatch.setattr(
        moroccanoil_parser,
        "extract_pdf_lines",
        lambda _: [
            "Invoice No 126018817",
            (
                "1 M105THL10 Thickening Lotion "
                "360 5.44 $ 1958.4 $ 5.00% 5.17 $ 1,860.48 $ Israel"
            ),
            "0 100ml",
        ],
    )
    monkeypatch.setattr(
        moroccanoil_parser,
        "extract_pdf_tables",
        lambda _: [],
    )

    warnings: list[str] = []
    _, rows = moroccanoil_parser.parse_invoice_pdf(
        _entry(invoice_path), "ILSO000004438", warnings
    )

    assert warnings == []
    assert len(rows) == 1
    assert rows[0]["itemNo"] == "M105THL100"
    assert rows[0]["description"] == "Thickening Lotion 100ml"


def test_fno_packing_table_uses_columns_not_numbers_in_description(
    moroccanoil_parser, monkeypatch, tmp_path
):
    packing_path = tmp_path / "packing.pdf"
    packing_path.touch()
    tables = [
        [
            [
                "Package\nNumber",
                "SSCC",
                "Package Type",
                "Volume",
                "Height",
                "Width",
                "Length",
                "Gross weight",
                "Net weight",
            ],
            [
                "1 PL000004231 PL 1.872 1.56 1.00 1.20 567.184 550.184",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ],
            [
                "Item Code",
                "Item description",
                None,
                "Barcode",
                None,
                "Qty",
                "Piece",
                "Weight",
                "Total box",
            ],
            [
                "M408BVCL4\n00",
                "Blonde Voyage Clay Lightener 14.1\nOZ. / 400g",
                None,
                "barcode glyphs",
                None,
                "60",
                "",
                "27",
                "5",
            ],
        ],
        [
            [
                "2 CB000001149 0.04 0.25 0.40 0.40 8.5 8.40",
                None,
                None,
                None,
                None,
                None,
                None,
            ],
            [
                "M412ECCR1\n00",
                "Color Eclipse Permanent Cream 60ml",
                "barcode glyphs",
                "8",
                "8",
                "0.56",
                "0",
            ],
        ],
    ]
    monkeypatch.setattr(moroccanoil_parser, "extract_pdf_lines", lambda _: [])
    monkeypatch.setattr(
        moroccanoil_parser,
        "extract_pdf_tables",
        lambda _: tables,
        raising=False,
    )

    rows = moroccanoil_parser.parse_packing_pdf(
        _entry(packing_path), "ILSO000003204", []
    )

    assert len(rows) == 2
    assert rows[0]["itemNo"] == "M408BVCL400"
    assert rows[0]["quantity"] == 60.0
    assert rows[0]["weight"] == 27.0
    assert rows[0]["boxes"] == 5.0
    assert rows[0]["pallet"] == "PL000004231"
    assert rows[0]["sscc"] == "PL000004231"
    assert rows[0]["packageGrossWeight"] == 567.184
    assert rows[1]["pallet"] == "CB000001149"


def test_batch_technical_columns_are_parsed_and_reconciled(
    moroccanoil_parser, tmp_path
):
    batch_path = tmp_path / "batch-ILSO000000570 (1).xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Textbox22"])
    worksheet.append(["Shipment Code SHIP0009315", "Load LOAD0009148"])
    worksheet.append([])
    worksheet.append(
        [
            *[f"Textbox{idx}" for idx in range(12)],
            "ContainerId1",
            "ItemId1",
            "ItemName2",
            "ItemBarCode3",
            "KitInventBatchId",
            "KitItemName",
            "InventBatchId",
            "ProdDate",
            "ExpDate",
            "Qty",
        ]
    )
    worksheet.append(
        [
            *["label"] * 12,
            "PL000003269",
            "M409OCRD20V250A",
            "SAMPLE - Oxidative Cream Developer",
            7290116978727,
            "N/A",
            "N/A",
            "16B601IA55",
            "2026-02-16",
            "2029-02-15",
            20,
        ]
    )
    worksheet.append(
        [
            *["label"] * 12,
            "PL000003654",
            "MBOX25HCTRYME",
            "Box for General Try Me Kit",
            None,
            "N/A",
            "N/A",
            None,
            None,
            None,
            360,
        ]
    )
    workbook.save(batch_path)

    rows = moroccanoil_parser.parse_batch_xlsx(
        _entry(batch_path), "ILSO000000570", []
    )

    assert len(rows) == 2
    assert rows[0]["itemNo"] == "M409OCRD20V250A"
    assert rows[0]["pallet"] == "PL000003269"
    assert rows[0]["barcode"] == "7290116978727"
    assert rows[0]["batchNo"] == "16B601IA55"
    assert rows[0]["prodDate"] == "2026-02-16"
    assert rows[0]["quantity"] == 20.0
    assert rows[0]["quantityUnit"] == "boxes"
    assert rows[1]["batchNo"] is None

    packing_rows = [
        {
            "itemNo": "M409OCRD20V250A",
            "pallet": "PL000003269",
            "sscc": "PL000003269",
            "nestedInCb": None,
            "quantity": 480,
            "boxes": 20,
        },
        {
            "itemNo": "MBOX25HCTRYME",
            "pallet": "PL000003654",
            "sscc": "PL000003654",
            "nestedInCb": None,
            "quantity": 360,
            "boxes": 0,
        },
    ]
    moroccanoil_parser.convert_batch_box_quantities_to_pieces(
        rows, packing_rows, []
    )
    assert rows[0]["quantity"] == 480.0
    assert rows[0]["boxes"] == 20.0
    assert rows[0]["quantityUnit"] == "pieces"
    assert rows[1]["quantity"] == 360.0
    assert rows[1]["boxes"] == 0.0


def test_legacy_text_and_first_row_batch_fallbacks(
    moroccanoil_parser, monkeypatch, tmp_path
):
    invoice_path = tmp_path / "legacy-invoice.pdf"
    packing_path = tmp_path / "legacy-packing.pdf"
    invoice_path.touch()
    packing_path.touch()
    pdf_lines = {
        str(invoice_path): [
            "Invoice No 7250996",
            (
                "M101OR100 1 10 0.00% Treatment Original "
                "8.86 $ 88.60 $ 8.86 $ 88.60 $ 0.00 $ Israel"
            ),
        ],
        str(packing_path): [
            "M101OR100 Treatment Original 8.600 10.000 1",
        ],
    }
    monkeypatch.setattr(
        moroccanoil_parser,
        "extract_pdf_lines",
        lambda path: pdf_lines[str(path)],
    )
    monkeypatch.setattr(
        moroccanoil_parser, "extract_pdf_tables", lambda _: []
    )

    invoice_no, invoice_rows = moroccanoil_parser.parse_invoice_pdf(
        _entry(invoice_path), "8251014", []
    )
    packing_rows = moroccanoil_parser.parse_packing_pdf(
        _entry(packing_path), "8251014", []
    )

    batch_path = tmp_path / "legacy-batch.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(
        [
            "SAP ItemCode",
            "WMS ItemCode",
            "ItemFrgnName",
            "Quantity",
            "BatchNum",
            "BatchProdDate",
            "BatchExpDate",
            "Barcode",
        ]
    )
    worksheet.append(
        [
            "M101OR100",
            "WMS-1",
            "Treatment Original",
            10,
            "LEGACY-LOT",
            "2026-01-01",
            "2029-01-01",
            7290012345678,
        ]
    )
    workbook.save(batch_path)
    batch_rows = moroccanoil_parser.parse_batch_xlsx(
        _entry(batch_path), "8251014", []
    )

    assert invoice_no == "7250996"
    assert invoice_rows[0]["itemNo"] == "M101OR100"
    assert invoice_rows[0]["totalPriceAfterDiscount"] == 88.6
    assert packing_rows[0]["quantity"] == 10
    assert packing_rows[0]["weight"] == 8.6
    assert packing_rows[0]["boxes"] == 1
    assert batch_rows[0]["itemNo"] == "M101OR100"
    assert batch_rows[0]["batchNo"] == "LEGACY-LOT"


REAL_CASES = [
    (
        "ILSO000003204",
        "126018812",
        103,
        7848,
        19177.56,
        103,
        919.902,
        220,
        105,
        {"PL000004231": 3168, "PL000004232": 4680},
    ),
    (
        "ILSO000000570",
        "126018813",
        2,
        948,
        1706.40,
        3,
        274.8,
        20,
        3,
        {"PL000003269": 588, "PL000003654": 360},
    ),
    (
        "ILSO000000580",
        "126018814",
        50,
        400,
        1120,
        50,
        28,
        0,
        50,
        {
            "CB000001146": 48,
            "CB000001149": 120,
            "CB000001150": 120,
            "CB000001157": 112,
        },
    ),
]


@pytest.mark.skipif(not REAL_DATA_DIR.exists(), reason="real supplier package absent")
@pytest.mark.parametrize(
    (
        "shipment",
        "invoice_no",
        "invoice_count",
        "quantity",
        "total_before",
        "packing_count",
        "weight",
        "boxes",
        "batch_count",
        "pallet_quantities",
    ),
    REAL_CASES,
)
def test_real_fno_complete_sets(
    moroccanoil_parser,
    shipment,
    invoice_no,
    invoice_count,
    quantity,
    total_before,
    packing_count,
    weight,
    boxes,
    batch_count,
    pallet_quantities,
):
    invoice_path = next(REAL_DATA_DIR.glob(f"{shipment}-*.pdf"))
    packing_path = REAL_DATA_DIR / f"MO Packing Slip {shipment}.pdf"
    batch_path = next(REAL_DATA_DIR.glob(f"batch-{shipment}*.xlsx"))
    warnings: list[str] = []

    parsed_invoice_no, invoice_rows = moroccanoil_parser.parse_invoice_pdf(
        _entry(invoice_path), shipment, warnings
    )
    packing_rows = moroccanoil_parser.parse_packing_pdf(
        _entry(packing_path), shipment, warnings
    )
    batch_rows = moroccanoil_parser.parse_batch_xlsx(
        _entry(batch_path), shipment, warnings
    )
    moroccanoil_parser.convert_batch_box_quantities_to_pieces(
        batch_rows, packing_rows, warnings
    )

    assert warnings == []
    assert parsed_invoice_no == invoice_no
    assert len(invoice_rows) == invoice_count
    assert sum(row["quantity"] for row in invoice_rows) == pytest.approx(quantity)
    assert sum(row["totalBeforeDiscount"] for row in invoice_rows) == pytest.approx(
        total_before
    )
    assert len(packing_rows) == packing_count
    assert sum(row["quantity"] for row in packing_rows) == pytest.approx(quantity)
    assert sum(row["weight"] for row in packing_rows) == pytest.approx(weight)
    assert sum(row["boxes"] for row in packing_rows) == pytest.approx(boxes)
    assert len(batch_rows) == batch_count
    assert sum(row["quantity"] for row in batch_rows) == pytest.approx(quantity)
    assert sum(row["boxes"] for row in batch_rows) == pytest.approx(boxes)
    assert all(row["quantityUnit"] == "pieces" for row in batch_rows)

    actual_pallet_quantities = Counter()
    for row in batch_rows:
        actual_pallet_quantities[row["pallet"]] += row["quantity"]
    assert actual_pallet_quantities == pallet_quantities

    if shipment == "ILSO000003204":
        clay = next(row for row in packing_rows if row["itemNo"] == "M408BVCL400")
        assert clay["quantity"] == 60
    if shipment in {"ILSO000000570", "ILSO000000580"}:
        assert all(row["__isFoc"] is True for row in invoice_rows)


@pytest.mark.skipif(not REAL_DATA_DIR.exists(), reason="real supplier package absent")
def test_real_fno_invoice_text_fallback_when_tables_are_missing(moroccanoil_parser):
    invoice_path = REAL_DATA_DIR / "ILSO000004437-126018816 new.pdf"
    warnings: list[str] = []

    parsed_invoice_no, invoice_rows = moroccanoil_parser.parse_invoice_pdf(
        _entry(invoice_path), "ILSO000004437", warnings
    )

    assert warnings == []
    assert parsed_invoice_no == "126018816"
    assert len(invoice_rows) == 1
    row = invoice_rows[0]
    assert row["itemIndex"] == 1
    assert row["itemNo"] == "M408BVPW7L750"
    assert row["description"] == "Blonde Voyage Powder Lightener 7 levels"
    assert row["quantity"] == 6
    assert row["unitPriceBeforeDiscount"] == 16
    assert row["totalBeforeDiscount"] == 96
    assert row["discountPercentage"] == 100
    assert row["unitPriceAfterDiscount"] == 0
    assert row["totalPriceAfterDiscount"] == 0
    assert row["commercialDiscount"] == 96
    assert row["countryOfOrigin"] == "Italy"
    assert row["__isFoc"] is True
    assert row["__sourceLayout"] == "fno-text-2026"


@pytest.mark.skipif(not LEGACY_DATA_DIR.exists(), reason="legacy fixture absent")
def test_legacy_moroccanoil_bundle_still_parses(moroccanoil_parser):
    invoices, packings, batches, _ = moroccanoil_parser.discover_file_entries(
        str(LEGACY_DATA_DIR), "8251014"
    )
    warnings: list[str] = []
    invoice_rows = []
    for entry in invoices:
        _, rows = moroccanoil_parser.parse_invoice_pdf(
            entry, "8251014", warnings
        )
        invoice_rows.extend(rows)
    packing_rows = []
    for entry in packings:
        packing_rows.extend(
            moroccanoil_parser.parse_packing_pdf(entry, "8251014", warnings)
        )
    batch_rows = []
    for entry in batches:
        batch_rows.extend(
            moroccanoil_parser.parse_batch_xlsx(entry, "8251014", warnings)
        )

    assert warnings == []
    assert len(invoice_rows) == 88
    assert len(packing_rows) == 71
    assert len(batch_rows) == 83
