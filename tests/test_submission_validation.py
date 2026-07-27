from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "bot" / "submission_validation.py"


@pytest.fixture(scope="module")
def validation_module():
    spec = importlib.util.spec_from_file_location(
        "submission_validation", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_moil_requires_at_least_one_invoice(validation_module):
    error = validation_module.validate_submission(
        "moil",
        {"inv": 0, "pac": 1, "batch": 0},
    )

    assert error is not None
    assert "invoice" in error
    assert "общий packing" in error


@pytest.mark.parametrize("invoice_count", [1, 2, 7])
def test_moil_accepts_full_invoice_package(validation_module, invoice_count):
    assert (
        validation_module.validate_submission(
            "moil",
            {"inv": invoice_count, "pac": 1, "batch": 0},
        )
        is None
    )


@pytest.mark.parametrize("packing_count", [0, 2, 3])
def test_moil_requires_exactly_one_packing(validation_module, packing_count):
    error = validation_module.validate_submission(
        "moil",
        {"inv": 1, "pac": packing_count, "batch": 0},
    )

    assert error is not None
    assert "invoice" in error
    assert "один общий packing" in error


def test_moil_rejects_more_than_one_batch_file(validation_module):
    error = validation_module.validate_submission(
        "moil",
        {"inv": 7, "pac": 1, "batch": 2},
    )

    assert error is not None
    assert "batch" in error


@pytest.mark.parametrize("company", ["bandi", "moroccanoil"])
def test_other_companies_keep_existing_multi_invoice_behavior(
    validation_module, company
):
    assert (
        validation_module.validate_submission(
            company,
            {"inv": 3, "pac": 1, "batch": 0},
        )
        is None
    )
