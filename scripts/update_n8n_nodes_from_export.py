#!/usr/bin/env python3
"""Update selected n8n nodes from an exported workflow.

Run only while n8n is stopped and after backing up its SQLite database.
Only the executable node configuration is copied; ids, positions and
connections remain those of the production workflow.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


COPIED_FIELDS = ("parameters", "type", "typeVersion", "credentials")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--export", required=True, type=Path)
    parser.add_argument(
        "--node",
        required=True,
        action="append",
        dest="node_names",
    )
    args = parser.parse_args()

    exported = json.loads(args.export.read_text(encoding="utf-8"))
    exported_by_name = {
        node.get("name"): node
        for node in exported.get("nodes", [])
        if node.get("name") in args.node_names
    }
    missing_export = sorted(set(args.node_names) - set(exported_by_name))
    if missing_export:
        raise SystemExit(f"nodes missing from export: {missing_export}")

    with sqlite3.connect(args.database) as database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute(
            "SELECT nodes, versionId FROM workflow_entity WHERE id = ?",
            (args.workflow_id,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"workflow not found: {args.workflow_id}")

        nodes_text, version_id = row
        nodes = json.loads(nodes_text)
        counts = {name: 0 for name in args.node_names}
        for node in nodes:
            name = node.get("name")
            if name not in exported_by_name:
                continue
            source = exported_by_name[name]
            for field in COPIED_FIELDS:
                if field in source:
                    node[field] = source[field]
                else:
                    node.pop(field, None)
            counts[name] += 1

        invalid = {name: count for name, count in counts.items() if count != 1}
        if invalid:
            raise SystemExit(f"expected exactly one production node: {invalid}")

        serialized = json.dumps(nodes, ensure_ascii=False, separators=(",", ":"))
        database.execute(
            """
            UPDATE workflow_entity
            SET nodes = ?, updatedAt = STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW')
            WHERE id = ?
            """,
            (serialized, args.workflow_id),
        )
        history_result = database.execute(
            """
            UPDATE workflow_history
            SET nodes = ?, updatedAt = STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW')
            WHERE workflowId = ? AND versionId = ?
            """,
            (serialized, args.workflow_id, version_id),
        )
        if history_result.rowcount not in (0, 1):
            raise SystemExit(
                f"unexpected workflow_history rows updated: "
                f"{history_result.rowcount}"
            )
        database.commit()

    for name in args.node_names:
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
