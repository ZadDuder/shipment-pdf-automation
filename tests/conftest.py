from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = PROJECT_ROOT / "пайтон скрипт" / "parse_moil_bundle.py"


@pytest.fixture()
def moil_parser():
    spec = importlib.util.spec_from_file_location("parse_moil_bundle", PARSER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
