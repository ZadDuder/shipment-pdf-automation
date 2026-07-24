from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "update_n8n_workflow.py"


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
