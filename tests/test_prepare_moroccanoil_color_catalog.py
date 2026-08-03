from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.prepare_moroccanoil_color_catalog import build_catalog_update


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_SOURCE = (
    Path.home()
    / "Загрузки"
    / "Telegram Desktop"
    / "Color FNO PO form - Russia - June 2026.xlsx"
)
REAL_MASTER = PROJECT_ROOT / "tmp" / "moroc-master-before.json"


def master_values() -> list[list[str]]:
    return [
        [
            "GTIN",
            "SKU Code - 1",
            "SKU Code - 2",
            "АРТИКУЛ",
            "Код ТНВЭД",
            "DG/NDG",
            "Category",
            "Collection",
            "Description",
            "Перевод",
            "BARCODE",
            "ОПИСАНИЕ УПАКОВКИ",
        ],
        [
            "7291",
            "OLD1",
            "FMC-OLD1",
            "RU-OLD1",
            "3305",
            "NDG",
            "Color",
            "Collection",
            "Old description",
            "Перевод",
            "7291",
            "ТУБА",
        ],
        [
            "7292",
            "ACCESSORY-GL",
            "ACCESSORY-GL",
            "ACCESSORY",
            "9615",
            "NDG",
            "Accessory",
            "Accessories",
            "Accessory description",
            "Аксессуар",
            "7292",
            "КОРОБКА",
        ],
    ]


def test_updates_existing_rows_and_preserves_all_aliases():
    mappings = [
        {
            "source_row": 3,
            "old_sku": "OLD1",
            "new_sku": "NEW1",
            "sku_ru": "RU-NEW1",
            "barcode": "7291",
            "description": "New description",
        }
    ]

    candidate, report = build_catalog_update(master_values(), mappings)

    headers = candidate[0]
    row = dict(zip(headers, candidate[1]))
    assert row["SKU Code - 1"] == "OLD1"
    assert row["SKU Code - 2"] == "NEW1"
    assert row["АРТИКУЛ"] == "RU-NEW1"
    assert row["Old SKU FNO"] == "OLD1"
    assert row["Legacy SKU Code - 2"] == "FMC-OLD1"
    assert row["Перевод"] == "Перевод"
    assert report["matched_by_old_sku"] == 1
    assert report["added_rows"] == 0


def test_invalid_ru_does_not_erase_existing_article_and_blank_barcode_is_filled():
    values = master_values()
    values[1][0] = ""
    values[1][10] = ""
    mappings = [
        {
            "source_row": 3,
            "old_sku": "OLD1",
            "new_sku": "NEW1",
            "sku_ru": "/",
            "barcode": "7291",
            "description": "New description",
        }
    ]

    candidate, report = build_catalog_update(values, mappings)

    row = dict(zip(candidate[0], candidate[1]))
    assert row["АРТИКУЛ"] == "RU-OLD1"
    assert row["GTIN"] == "7291"
    assert row["BARCODE"] == "7291"
    assert report["invalid_ru_rows"] == [3]
    assert report["filled_blank_barcodes"] == 1


def test_unique_barcode_fallback_keeps_existing_legacy_code():
    mappings = [
        {
            "source_row": 210,
            "old_sku": "ACCESSORY",
            "new_sku": "NEW-ACCESSORY",
            "sku_ru": "ACCESSORY",
            "barcode": "7292",
            "description": "Accessory",
        }
    ]

    candidate, report = build_catalog_update(master_values(), mappings)

    row = dict(zip(candidate[0], candidate[2]))
    assert row["SKU Code - 1"] == "ACCESSORY-GL"
    assert row["SKU Code - 2"] == "NEW-ACCESSORY"
    assert row["Old SKU FNO"] == "ACCESSORY"
    assert row["Legacy SKU Code - 2"] == "ACCESSORY-GL"
    assert report["matched_by_barcode"] == 1


def test_unmatched_mapping_adds_only_authoritative_source_fields():
    mappings = [
        {
            "source_row": 63,
            "old_sku": "NEW-SHADE-GL",
            "new_sku": "NEW-SHADE",
            "sku_ru": "SHADE(123)",
            "barcode": "7293",
            "description": "New shade description",
        }
    ]

    candidate, report = build_catalog_update(master_values(), mappings)

    row = dict(zip(candidate[0], candidate[-1]))
    assert row["GTIN"] == "7293"
    assert row["SKU Code - 1"] == "NEW-SHADE-GL"
    assert row["SKU Code - 2"] == "NEW-SHADE"
    assert row["АРТИКУЛ"] == "SHADE(123)"
    assert row["Description"] == "New shade description"
    assert row["BARCODE"] == "7293"
    assert row["Код ТНВЭД"] == ""
    assert row["Перевод"] == ""
    assert row["ОПИСАНИЕ УПАКОВКИ"] == ""
    assert report["added_rows"] == 1


def test_rejects_alias_that_would_resolve_to_two_master_rows():
    values = master_values()
    values.append(
        [
            "7293",
            "OTHER",
            "NEW1",
            "RU-OTHER",
            "3305",
            "NDG",
            "Color",
            "Collection",
            "Other description",
            "Перевод",
            "7293",
            "ТУБА",
        ]
    )
    mappings = [
        {
            "source_row": 3,
            "old_sku": "OLD1",
            "new_sku": "NEW1",
            "sku_ru": "RU-NEW1",
            "barcode": "7291",
            "description": "New description",
        }
    ]

    with pytest.raises(ValueError, match="Alias NEW1 resolves to master rows"):
        build_catalog_update(values, mappings)


@pytest.mark.skipif(
    not REAL_SOURCE.exists() or not REAL_MASTER.exists(),
    reason="real client mapping or production snapshot absent",
)
def test_real_color_mapping_has_expected_safe_update_counts():
    from scripts.prepare_moroccanoil_color_catalog import load_source_mappings

    master = json.loads(REAL_MASTER.read_text(encoding="utf-8"))["values"]
    mappings = load_source_mappings(REAL_SOURCE)

    candidate, report = build_catalog_update(master, mappings)

    assert report["source_product_rows"] == 216
    assert report["matched_by_old_sku"] == 182
    assert report["matched_by_barcode"] == 9
    assert report["added_rows"] == 25
    assert report["invalid_ru_rows"] == [5]
    assert report["duplicate_source_barcodes"] == {
        "7290113147812": [47, 132]
    }
    assert len(candidate) == 237
