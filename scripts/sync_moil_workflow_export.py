#!/usr/bin/env python3
"""Synchronize maintained MOIL/MOROCCANOIL node sources into final.json."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = PROJECT_ROOT / "final.json"
SPREADSHEET_ID = "1Av1S2wFoiLrIeeaBO-gFGgsBtzuwMgL1ziVd2lS6c3k"
HTTP_CREDENTIALS = {
    "googleApi": {
        "id": "3LOHOCZ59mCHy9dU",
        "name": "Google API SA",
    }
}

CODE_SOURCES = {
    "Build Customs and CZ Rows": "workflows/build_moil.js",
    "Build Moroccanoil Customs and CZ Rows": "workflows/build_moroccanoil.js",
    "Prepare Sheet Setup Data": "workflows/prepare_moil_sheet_setup.js",
    "Build Create Requests": "workflows/build_moil_create_requests.js",
    "Prepare Customs Rows": "workflows/prepare_moil_customs_write.js",
    "Prepare CZ Rows": "workflows/prepare_moil_cz_write.js",
    "Prepare Summary Message1": "workflows/prepare_moil_summary.js",
}


def http_parameters(url_suffix: str, json_body: str) -> dict:
    return {
        "method": "POST",
        "url": (
            f"=https://sheets.googleapis.com/v4/spreadsheets/"
            f"{SPREADSHEET_ID}{url_suffix}"
        ),
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "googleApi",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": json_body,
        "options": {},
    }


def main() -> int:
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}

    for node_name, relative_source in CODE_SOURCES.items():
        nodes[node_name]["parameters"]["jsCode"] = (
            PROJECT_ROOT / relative_source
        ).read_text(encoding="utf-8")

    clear_customs_body = (
        "={{ { ranges: ($json.customsSheets || []).map((sheet) => "
        "\"'\" + String(sheet.sheetName).replace(/'/g, \"''\") + "
        "\"'!A2:ZZ\") } }}"
    )
    clear_cz_body = (
        "={{ { ranges: ($json.czSheets || []).map((sheet) => "
        "\"'\" + String(sheet.sheetName).replace(/'/g, \"''\") + "
        "\"'!A2:ZZ\") } }}"
    )
    write_body = (
        "={{ { valueInputOption: $json.valueInputOption, data: $json.data } }}"
    )

    http_nodes = {
        "Clear Customs Sheet": http_parameters(
            "/values:batchClear",
            clear_customs_body,
        ),
        "Write Customs Rows": http_parameters(
            "/values:batchUpdate",
            write_body,
        ),
        "Clear CZ Sheet": http_parameters(
            "/values:batchClear",
            clear_cz_body,
        ),
        "Write CZ Rows": http_parameters(
            "/values:batchUpdate",
            write_body,
        ),
    }
    for node_name, parameters in http_nodes.items():
        node = nodes[node_name]
        node["type"] = "n8n-nodes-base.httpRequest"
        node["typeVersion"] = 4.2
        node["parameters"] = parameters
        node["credentials"] = HTTP_CREDENTIALS

    WORKFLOW_PATH.write_text(
        json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
