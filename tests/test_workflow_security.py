from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_MOIL_SPREADSHEET = "1Av1S2wFoiLrIeeaBO-gFGgsBtzuwMgL1ziVd2lS6c3k"
OBSOLETE_MOIL_SPREADSHEET = "1yb8n-hmOra3tCOyB6nnJctnM3rc_px_IC5Zj84mhZBA"


def _workflow() -> dict:
    return json.loads((PROJECT_ROOT / "final.json").read_text(encoding="utf-8"))


def test_webhook_payload_is_validated_before_shell_interpolation():
    source = (
        PROJECT_ROOT / "workflows" / "normalize_bot_payload.js"
    ).read_text(encoding="utf-8")

    assert "allowedCompanies" in source
    assert "[A-Za-z0-9_-]{1,64}" in source
    assert "shipment_dir" not in source
    assert "`/opt/tg_uploads/${company}/${shipmentKey}`" in source


def test_workflow_uses_current_moil_spreadsheet_only():
    serialized = json.dumps(_workflow(), ensure_ascii=False)

    assert PRODUCTION_MOIL_SPREADSHEET in serialized
    assert OBSOLETE_MOIL_SPREADSHEET not in serialized


def test_moil_workflow_writes_customs_and_cz_pair_per_invoice():
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    setup_code = nodes["Prepare Sheet Setup Data"]["parameters"]["jsCode"]
    create_code = nodes["Build Create Requests"]["parameters"]["jsCode"]
    summary_code = nodes["Prepare Summary Message1"]["parameters"]["jsCode"]

    assert "customsSheetNames" in setup_code
    assert "czSheetNames" in setup_code
    assert "for (const sheetName of setup.customsSheetNames)" in create_code
    assert "for (const sheetName of setup.czSheetNames)" in create_code
    assert "парах вкладок" in summary_code

    for node_name in ("Clear Customs Sheet", "Clear CZ Sheet"):
        node = nodes[node_name]
        assert node["type"] == "n8n-nodes-base.httpRequest"
        assert node["parameters"]["url"].endswith("/values:batchClear")

    for node_name in ("Write Customs Rows", "Write CZ Rows"):
        node = nodes[node_name]
        assert node["type"] == "n8n-nodes-base.httpRequest"
        assert node["parameters"]["url"].endswith("/values:batchUpdate")
