from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "update_n8n_workflow.py"
EXPORT_SCRIPT = PROJECT_ROOT / "scripts" / "update_n8n_nodes_from_export.py"


def test_updates_entity_and_matching_history_in_one_run(tmp_path):
    database_path = tmp_path / "n8n.sqlite"
    source_path = tmp_path / "node.js"
    source_path.write_text("return [{ json: { ok: true } }];\n", encoding="utf-8")
    original_nodes = [
        {
            "name": "Target Node",
            "parameters": {"jsCode": "old"},
        }
    ]

    with sqlite3.connect(database_path) as database:
        database.execute(
            """
            CREATE TABLE workflow_entity (
                id TEXT PRIMARY KEY,
                versionId TEXT NOT NULL,
                nodes TEXT NOT NULL,
                updatedAt TEXT
            )
            """
        )
        database.execute(
            """
            CREATE TABLE workflow_history (
                workflowId TEXT NOT NULL,
                versionId TEXT NOT NULL,
                nodes TEXT NOT NULL,
                updatedAt TEXT
            )
            """
        )
        serialized = json.dumps(original_nodes)
        database.execute(
            "INSERT INTO workflow_entity VALUES (?, ?, ?, NULL)",
            ("workflow-1", "version-1", serialized),
        )
        database.execute(
            "INSERT INTO workflow_history VALUES (?, ?, ?, NULL)",
            ("workflow-1", "version-1", serialized),
        )

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--database",
            str(database_path),
            "--workflow-id",
            "workflow-1",
            "--replace",
            f"Target Node={source_path}",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    with sqlite3.connect(database_path) as database:
        entity_nodes = json.loads(
            database.execute(
                "SELECT nodes FROM workflow_entity"
            ).fetchone()[0]
        )
        history_nodes = json.loads(
            database.execute(
                "SELECT nodes FROM workflow_history"
            ).fetchone()[0]
        )

    assert entity_nodes == history_nodes
    assert entity_nodes[0]["parameters"]["jsCode"] == source_path.read_text(
        encoding="utf-8"
    )


def test_updates_selected_node_configuration_from_export(tmp_path):
    database_path = tmp_path / "n8n.sqlite"
    export_path = tmp_path / "workflow.json"
    production_nodes = [
        {
            "id": "prod-id",
            "name": "Target Node",
            "position": [1, 2],
            "parameters": {"operation": "old"},
            "type": "old-type",
            "typeVersion": 1,
        },
        {
            "id": "untouched",
            "name": "Other Node",
            "parameters": {"value": "same"},
        },
    ]
    export_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "export-id",
                        "name": "Target Node",
                        "position": [99, 99],
                        "parameters": {"operation": "new"},
                        "type": "new-type",
                        "typeVersion": 4.2,
                        "credentials": {"googleApi": {"id": "credential"}},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with sqlite3.connect(database_path) as database:
        database.execute(
            """
            CREATE TABLE workflow_entity (
                id TEXT PRIMARY KEY,
                versionId TEXT NOT NULL,
                nodes TEXT NOT NULL,
                updatedAt TEXT
            )
            """
        )
        database.execute(
            """
            CREATE TABLE workflow_history (
                workflowId TEXT NOT NULL,
                versionId TEXT NOT NULL,
                nodes TEXT NOT NULL,
                updatedAt TEXT
            )
            """
        )
        serialized = json.dumps(production_nodes)
        database.execute(
            "INSERT INTO workflow_entity VALUES (?, ?, ?, NULL)",
            ("workflow-1", "version-1", serialized),
        )
        database.execute(
            "INSERT INTO workflow_history VALUES (?, ?, ?, NULL)",
            ("workflow-1", "version-1", serialized),
        )

    subprocess.run(
        [
            sys.executable,
            str(EXPORT_SCRIPT),
            "--database",
            str(database_path),
            "--workflow-id",
            "workflow-1",
            "--export",
            str(export_path),
            "--node",
            "Target Node",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    with sqlite3.connect(database_path) as database:
        entity_nodes = json.loads(
            database.execute(
                "SELECT nodes FROM workflow_entity"
            ).fetchone()[0]
        )
        history_nodes = json.loads(
            database.execute(
                "SELECT nodes FROM workflow_history"
            ).fetchone()[0]
        )

    assert entity_nodes == history_nodes
    target = entity_nodes[0]
    assert target["id"] == "prod-id"
    assert target["position"] == [1, 2]
    assert target["parameters"] == {"operation": "new"}
    assert target["type"] == "new-type"
    assert target["typeVersion"] == 4.2
    assert target["credentials"] == {"googleApi": {"id": "credential"}}
    assert entity_nodes[1] == production_nodes[1]
