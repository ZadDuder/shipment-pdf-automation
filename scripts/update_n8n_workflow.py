#!/usr/bin/env python3
"""Replace selected n8n Code-node sources in SQLite.

Run only while the n8n service is stopped and after creating a database
backup. The current workflow row and its matching history version are updated
in one transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def parse_replacement(value: str) -> tuple[str, Path]:
    try:
        name, raw_path = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "replacement must use NODE_NAME=/path/to/source.js"
        ) from exc
    if not name or not raw_path:
        raise argparse.ArgumentTypeError(
            "replacement must include both node name and source path"
        )
    return name, Path(raw_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument(
        "--replace",
        required=True,
        action="append",
        type=parse_replacement,
        metavar="NODE_NAME=SOURCE.js",
    )
    args = parser.parse_args()

    replacements = {
        name: source.read_text(encoding="utf-8")
        for name, source in args.replace
    }

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
        counts = {name: 0 for name in replacements}
        for node in nodes:
            name = node.get("name")
            if name in replacements:
                node.setdefault("parameters", {})["jsCode"] = replacements[name]
                counts[name] += 1

        invalid = {name: count for name, count in counts.items() if count != 1}
        if invalid:
            raise SystemExit(f"expected exactly one matching node: {invalid}")

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
                f"unexpected workflow_history rows updated: {history_result.rowcount}"
            )
        database.commit()

    for name, source in replacements.items():
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        print(f"{name}: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
