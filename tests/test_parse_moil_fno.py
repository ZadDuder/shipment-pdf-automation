from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook


def _entry(path: Path) -> dict[str, str]:
    return {
        "path": str(path),
        "original_name": path.name,
    }


def test_fno_invoice_layout_reconstructs_sku_and_skips_charge(
    moil_parser, monkeypatch, tmp_path
):
    invoice_path = tmp_path / "invoice.pdf"
    invoice_path.touch()
    lines = [
        "Invoice No 126023953",
        "# Item No. Description Unit Unit Price Total Before Discount Unit Price Total Price Produce",
        "Quantity Before Discount % After Country",
        "Discount Discount",
        "1 M105VL250 Volumizing Mousse 250ml 396 4.08 $ 1615.68 $ 5.00% 3.88 $ 1,534.90 $ United",
        "States",
        "2 M112HSM7 Luminous Hairspray Medium 240 2.47 $ 592.8 $ 5.00% 2.35 $ 563.16 $ United",
        "5 75ML States",
        "3 FOC M101OR100 Moroccanoil Treatment Original 5 8.86 $ 44.3 $ 100.00% 0.00 $ 0.00 $ Israel",
        "100ml",
        "4 M105THL10 Thickening Lotion 100ml 360 5.44 $ 1958.4 $ 5.00% 5.17 $ 1,860.48 $ United",
        "0 States",
        "5 DGR Charge code for dangerous items 1 300.00 $ 300 $ 0.00% 300.00 $ 300.00 $ Not",
        "Applicable",
    ]
    monkeypatch.setattr(moil_parser, "extract_pdf_lines", lambda _: lines)

    warnings: list[str] = []
    invoice_no, rows = moil_parser.parse_invoice_pdf(
        _entry(invoice_path), "LOAD0012605", warnings
    )

    assert invoice_no == "126023953"
    assert [row["itemNo"] for row in rows] == [
        "M105VL250",
        "M112HSM75",
        "M101OR100",
        "M105THL100",
    ]
    assert rows[0]["countryOfOrigin"] == "United States"
    assert rows[0]["commercialDiscount"] == 80.78
    assert rows[1]["description"] == "Luminous Hairspray Medium 75ML"
    assert rows[2]["__isFoc"] is True
    assert rows[2]["commercialDiscount"] == 44.3
    assert any("DGR" in warning for warning in warnings)


def test_fno_packing_layout_tracks_packages_and_continuations(
    moil_parser, monkeypatch, tmp_path
):
    packing_path = tmp_path / "packing.pdf"
    packing_path.touch()
    lines = [
        "Packages content",
        "Package SSCC Package Type Volume Height Width Length Gross weight Net weight",
        "Number",
        "1 100006202 PL 1.716 1.43 1.00 1.20 384.00 373.00",
        "Item Code Item description Barcode Qty Piece Weight Total box",
        'M108DTS205 Dry Texture Spray 205ml 1248 291.20 104',
        "7290016033601",
        "M102SHFC25 Frizz Control Shampoo 250ml 144 46.00 4",
        "0 7290116972466",
        "M103SHPU1L Blonde Perfecting Purple Shampoo 12 14.00 1",
        "1L 7290113140028",
        "M105SHEV250 Extra Volume Shampoo 250ml 6 1.74 0",
        "In 100005636",
        "Carton boxes: 1",
        "Subtotals: 1392 337.20 108.00",
        "Package SSCC Package Type Volume Height Width Length Gross weight Net weight",
        "Number",
        "2 100006333 PL 1.788 1.49 1.00 1.20 581.00 570.00",
        "Item Code Item description Barcode Qty Piece Weight Total box",
        "M105RB250 Root Boost 250ml 1620 523.80 135",
        "7290014344167",
    ]
    monkeypatch.setattr(moil_parser, "extract_pdf_lines", lambda _: lines)

    warnings: list[str] = []
    rows = moil_parser.parse_packing_pdf(
        _entry(packing_path), "LOAD0012605", warnings
    )

    assert warnings == []
    assert [row["itemNo"] for row in rows] == [
        "M108DTS205",
        "M102SHFC250",
        "M103SHPU1L",
        "M105SHEV250",
        "M105RB250",
    ]
    assert rows[0] == {
        "itemNo": "M108DTS205",
        "descriptionFromPacking": "Dry Texture Spray 205ml",
        "quantity": 1248.0,
        "weight": 291.2,
        "boxes": 104.0,
        "barcode": "7290016033601",
        "pallet": "1",
        "sscc": "100006202",
        "packageGrossWeight": 384.0,
        "packageNetWeight": 373.0,
        "nestedInCb": None,
        "__sourceFileName": "packing.pdf",
        "__sourceOriginalName": "packing.pdf",
        "__shipmentKey": "LOAD0012605",
    }
    assert rows[1]["barcode"] == "7290116972466"
    assert rows[2]["barcode"] == "7290113140028"
    assert rows[3]["descriptionFromPacking"] == "Extra Volume Shampoo 250ml"
    assert rows[3]["nestedInCb"] == "100005636"
    assert rows[4]["pallet"] == "2"
    assert rows[4]["sscc"] == "100006333"


def test_fno_packing_layout_accepts_inline_barcode(
    moil_parser, monkeypatch, tmp_path
):
    packing_path = tmp_path / "packing-inline-barcode.pdf"
    packing_path.touch()
    lines = [
        "Packages content",
        "Package SSCC Package Type Volume Height Width Length Gross weight Net weight",
        "Number",
        "1 100006202 PL 1.716 1.43 1.00 1.20 384.00 373.00",
        "Item Code Item description Barcode Qty Piece Weight Total box",
        "M108DTS205 Dry Texture Spray 205ml 7290016033601 1248 291.20 104",
    ]
    monkeypatch.setattr(moil_parser, "extract_pdf_lines", lambda _: lines)

    rows = moil_parser.parse_packing_pdf(
        _entry(packing_path), "LOAD0012605", []
    )

    assert len(rows) == 1
    assert rows[0]["itemNo"] == "M108DTS205"
    assert rows[0]["barcode"] == "7290016033601"
    assert rows[0]["quantity"] == 1248
    assert rows[0]["weight"] == 291.2
    assert rows[0]["boxes"] == 104


def test_repeated_invoice_line_number_marks_kit_components(
    moil_parser, monkeypatch, tmp_path
):
    invoice_path = tmp_path / "kit-invoice.pdf"
    invoice_path.touch()
    lines = [
        "Invoice No 126022812",
        "# Item No. Description Unit Unit Price Total Before Discount Unit Price Total Price Produce",
        "1 MP26TRAVE Travel Kit 2026 - Hydration 976 10.35 $ 10096.72 $ 0.00% 10.35 $ 10,096.72 $ Israel",
        "LC",
        "1 BAGM26TRA BAG For Travel Kit 2026 976 2.50 $ 2440 $ 50.00% 1.25 $ 1,220.00 $ China",
        "VEL",
        "1 M101UM25 Moroccanoil Treatment Mist 25ml 976 3.27 $ 3191.52 $ 0.00% 3.27 $ 3,191.52 $ Israel",
    ]
    monkeypatch.setattr(moil_parser, "extract_pdf_lines", lambda _: lines)

    _, rows = moil_parser.parse_invoice_pdf(
        _entry(invoice_path), "LOAD0006732", []
    )

    assert [row["itemNo"] for row in rows] == [
        "MP26TRAVELC",
        "BAGM26TRAVEL",
        "M101UM25",
    ]
    assert [row["__isComponent"] for row in rows] == [False, True, True]
    assert [row["__rowOrder"] for row in rows] == [1, 2, 3]


def test_shipping_data_batch_layout_is_detected_and_forward_filled(
    moil_parser, tmp_path
):
    batch_path = tmp_path / "shipping-data.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append([])
    worksheet.append([])
    worksheet.append([])
    worksheet.append([None, "Shipment Code SHIP0019975"])
    worksheet.append([])
    worksheet.append([None, "Load LOAD0012605"])
    worksheet.append([None, "Packing List ILSO000004378"])
    worksheet.append([])
    worksheet.append([])
    worksheet.append([])
    worksheet.append(
        [
            "Pallet",
            None,
            "SKU",
            "Prod Name",
            "EAN",
            None,
            "Kit Batch No",
            "Kit component",
            None,
            "Batch No",
            "Prod. date",
            "Exp. date",
            "Shelf Life (days)",
            "Shelf Life Remaining (days)",
            None,
            "Qty",
        ]
    )
    worksheet.append(
        [
            "100006202",
            None,
            "M108DTS205",
            "Dry Texture Spray 205ml",
            "7290016033601",
            None,
            "N/A",
            "N/A",
            None,
            "29785",
            "2025-06-30",
            "2028-06-29",
            1095,
            709,
            None,
            67,
        ]
    )
    worksheet.append(
        [
            None,
            None,
            None,
            None,
            None,
            None,
            "N/A",
            "N/A",
            None,
            "30783",
            "2025-06-30",
            "2028-06-30",
            1095,
            710,
            None,
            37,
        ]
    )
    workbook.save(batch_path)

    warnings: list[str] = []
    rows = moil_parser.parse_batch_xlsx(
        _entry(batch_path), "LOAD0012605", warnings
    )

    assert warnings == []
    assert [row["itemNo"] for row in rows] == ["M108DTS205", "M108DTS205"]
    assert [row["pallet"] for row in rows] == ["100006202", "100006202"]
    assert [row["quantity"] for row in rows] == [67.0, 37.0]
    assert all(row["quantityUnit"] == "boxes" for row in rows)
    assert all(row["barcode"] == "7290016033601" for row in rows)


def test_batch_box_quantities_are_converted_to_pieces(moil_parser):
    packing_rows = [
        {
            "itemNo": "M108DTS205",
            "pallet": "100006202",
            "quantity": 1248.0,
            "boxes": 104.0,
        }
    ]
    batch_rows = [
        {
            "itemNo": "M108DTS205",
            "pallet": "100006202",
            "quantity": 67.0,
            "quantityUnit": "boxes",
        },
        {
            "itemNo": "M108DTS205",
            "pallet": "100006202",
            "quantity": 37.0,
            "quantityUnit": "boxes",
        },
    ]

    warnings: list[str] = []
    moil_parser.convert_batch_box_quantities_to_pieces(
        batch_rows, packing_rows, warnings
    )

    assert warnings == []
    assert [row["boxes"] for row in batch_rows] == [67.0, 37.0]
    assert [row["quantity"] for row in batch_rows] == [804.0, 444.0]
    assert all(row["quantityUnit"] == "pieces" for row in batch_rows)
    assert sum(row["quantity"] for row in batch_rows) == 1248.0


def test_invoice_validation_does_not_double_count_kit_components(moil_parser):
    rows = [
        {"quantity": 976.0, "__isComponent": False},
        {"quantity": 976.0, "__isComponent": True},
        {"quantity": 976.0, "__isComponent": True},
    ]

    assert moil_parser.sum_invoice_product_quantity(rows) == 976


def test_one_common_packing_is_valid_for_multiple_invoices(moil_parser):
    assert moil_parser.has_document_count_mismatch(7, 1) is False
    assert moil_parser.has_document_count_mismatch(1, 1) is False
    assert moil_parser.has_document_count_mismatch(3, 2) is True
