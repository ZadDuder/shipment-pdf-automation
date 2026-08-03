#!/usr/bin/env python3
"""Safely apply a reviewed values snapshot to one Google Sheets worksheet.

The command is dry-run by default.  In apply mode it verifies that the live
values still match the supplied before-snapshot, duplicates the worksheet as
a hidden backup, writes only changed cells plus appended rows, and verifies the
complete result.  A failed verification triggers a best-effort rollback.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Iterable
from urllib import error, parse, request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def clean(value: Any) -> str:
    return str(value if value is not None else "")


def a1_column(number: int) -> str:
    """Return the A1 column label for a one-based column number."""
    if number < 1:
        raise ValueError("column number must be positive")
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def normalize_values(
    values: list[list[Any]],
    *,
    rows: int,
    columns: int,
) -> list[list[str]]:
    """Normalize a sparse Sheets values response to a rectangular matrix."""
    normalized: list[list[str]] = []
    for row_number in range(rows):
        source = values[row_number] if row_number < len(values) else []
        row = [clean(value) for value in source[:columns]]
        row.extend([""] * (columns - len(row)))
        normalized.append(row)
    return normalized


def build_cell_updates(
    before: list[list[Any]],
    candidate: list[list[Any]],
) -> list[tuple[int, int, str]]:
    """Return changed candidate cells as one-based row/column coordinates."""
    rows = len(candidate)
    columns = max((len(row) for row in candidate), default=0)
    old = normalize_values(before, rows=rows, columns=columns)
    new = normalize_values(candidate, rows=rows, columns=columns)
    return [
        (row_index + 1, column_index + 1, new[row_index][column_index])
        for row_index in range(rows)
        for column_index in range(columns)
        if old[row_index][column_index] != new[row_index][column_index]
    ]


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def service_account_token(credentials_path: Path) -> str:
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    issued_at = int(time.time())
    token_uri = credentials.get("token_uri", "https://oauth2.googleapis.com/token")
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": credentials["client_email"],
        "scope": SHEETS_SCOPE,
        "aud": token_uri,
        "iat": issued_at,
        "exp": issued_at + 3600,
    }
    encoded_header = _base64url(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    encoded_claims = _base64url(
        json.dumps(claims, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    private_key = serialization.load_pem_private_key(
        credentials["private_key"].encode("utf-8"),
        password=None,
    )
    signature = private_key.sign(
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    assertion = f"{signing_input.decode('ascii')}.{_base64url(signature)}"
    body = parse.urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    ).encode("ascii")
    response = _http_json(
        token_uri,
        method="POST",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return str(response["access_token"])


def _http_json(
    url: str,
    *,
    token: str | None = None,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = dict(headers or {})
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    http_request = request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with request.urlopen(http_request, timeout=60) as response:
            content = response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Google API request failed ({exc.code}): {detail[:2000]}"
        ) from exc
    if not content:
        return {}
    decoded = json.loads(content.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError("Google API returned an unexpected response")
    return decoded


def _quoted_sheet(sheet_name: str) -> str:
    return "'" + sheet_name.replace("'", "''") + "'"


def _values_url(spreadsheet_id: str, range_name: str) -> str:
    encoded_range = parse.quote(range_name, safe="")
    return f"{SHEETS_API}/{spreadsheet_id}/values/{encoded_range}"


def get_values(
    token: str,
    spreadsheet_id: str,
    range_name: str,
    *,
    value_render_option: str | None = None,
) -> list[list[Any]]:
    url = _values_url(spreadsheet_id, range_name)
    if value_render_option:
        url += "?" + parse.urlencode(
            {"valueRenderOption": value_render_option}
        )
    response = _http_json(
        url,
        token=token,
    )
    values = response.get("values", [])
    if not isinstance(values, list):
        raise RuntimeError("Google Sheets values response is malformed")
    return values


def get_sheet_properties(
    token: str,
    spreadsheet_id: str,
) -> list[dict[str, Any]]:
    fields = parse.urlencode(
        {"includeGridData": "false", "fields": "sheets.properties"}
    )
    response = _http_json(
        f"{SHEETS_API}/{spreadsheet_id}?{fields}",
        token=token,
    )
    return [sheet["properties"] for sheet in response.get("sheets", [])]


def duplicate_sheet(
    token: str,
    spreadsheet_id: str,
    source_sheet_id: int,
    backup_title: str,
) -> int:
    response = _http_json(
        f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
        token=token,
        method="POST",
        payload={
            "requests": [
                {
                    "duplicateSheet": {
                        "sourceSheetId": source_sheet_id,
                        "newSheetName": backup_title,
                    }
                }
            ]
        },
    )
    backup_sheet_id = int(
        response["replies"][0]["duplicateSheet"]["properties"]["sheetId"]
    )
    _http_json(
        f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
        token=token,
        method="POST",
        payload={
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": backup_sheet_id,
                            "hidden": True,
                        },
                        "fields": "hidden",
                    }
                }
            ]
        },
    )
    return backup_sheet_id


def _cell_range(sheet_name: str, row: int, column: int) -> str:
    return f"{_quoted_sheet(sheet_name)}!{a1_column(column)}{row}"


def write_cell_updates(
    token: str,
    spreadsheet_id: str,
    sheet_name: str,
    updates: Iterable[tuple[int, int, str]],
) -> None:
    updates = list(updates)
    clear_ranges = [
        _cell_range(sheet_name, row, column)
        for row, column, value in updates
        if value == ""
    ]
    value_data = [
        {
            "range": _cell_range(sheet_name, row, column),
            "majorDimension": "ROWS",
            "values": [[value]],
        }
        for row, column, value in updates
        if value != ""
    ]
    if clear_ranges:
        _http_json(
            f"{SHEETS_API}/{spreadsheet_id}/values:batchClear",
            token=token,
            method="POST",
            payload={"ranges": clear_ranges},
        )
    if value_data:
        _http_json(
            f"{SHEETS_API}/{spreadsheet_id}/values:batchUpdate",
            token=token,
            method="POST",
            payload={"valueInputOption": "RAW", "data": value_data},
        )


def write_appended_rows(
    token: str,
    spreadsheet_id: str,
    sheet_name: str,
    first_row: int,
    values: list[list[str]],
    columns: int,
) -> None:
    if not values:
        return
    last_row = first_row + len(values) - 1
    target_range = (
        f"{_quoted_sheet(sheet_name)}!A{first_row}:"
        f"{a1_column(columns)}{last_row}"
    )
    _http_json(
        f"{SHEETS_API}/{spreadsheet_id}/values:batchUpdate",
        token=token,
        method="POST",
        payload={
            "valueInputOption": "RAW",
            "data": [
                {
                    "range": target_range,
                    "majorDimension": "ROWS",
                    "values": values,
                }
            ],
        },
    )


def clear_range(
    token: str,
    spreadsheet_id: str,
    range_name: str,
) -> None:
    _http_json(
        f"{SHEETS_API}/{spreadsheet_id}/values:batchClear",
        token=token,
        method="POST",
        payload={"ranges": [range_name]},
    )


def _load_values(path: Path) -> list[list[Any]]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    values = parsed.get("values") if isinstance(parsed, dict) else parsed
    if not isinstance(values, list) or not values:
        raise ValueError(f"values payload is empty or malformed: {path}")
    if not all(isinstance(row, list) for row in values):
        raise ValueError(f"values payload contains a non-row value: {path}")
    return values


def _first_difference(
    actual: list[list[str]],
    expected: list[list[str]],
) -> str:
    for row_index, (actual_row, expected_row) in enumerate(
        zip(actual, expected),
        1,
    ):
        for column_index, (actual_value, expected_value) in enumerate(
            zip(actual_row, expected_row),
            1,
        ):
            if actual_value != expected_value:
                return (
                    f"{a1_column(column_index)}{row_index}: "
                    f"live={actual_value!r}, expected={expected_value!r}"
                )
    return "matrix dimensions differ"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spreadsheet_id")
    parser.add_argument("sheet_name")
    parser.add_argument("before_snapshot", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--backup-title")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply after all preflight checks; otherwise only report",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    before_values = _load_values(args.before_snapshot)
    candidate_values = _load_values(args.candidate)
    columns = max(len(row) for row in candidate_values)
    if columns < 1:
        raise ValueError("candidate has no columns")

    before_rows = len(before_values)
    candidate_rows = len(candidate_values)
    if candidate_rows < before_rows:
        raise ValueError("candidate cannot remove existing worksheet rows")
    before = normalize_values(
        before_values,
        rows=before_rows,
        columns=columns,
    )
    candidate = normalize_values(
        candidate_values,
        rows=candidate_rows,
        columns=columns,
    )

    token = service_account_token(args.credentials)
    read_range = (
        f"{_quoted_sheet(args.sheet_name)}!A1:"
        f"{a1_column(columns)}1000"
    )
    live_values = get_values(token, args.spreadsheet_id, read_range)
    comparison_rows = max(before_rows, len(live_values))
    live = normalize_values(
        live_values,
        rows=comparison_rows,
        columns=columns,
    )
    expected_before = normalize_values(
        before_values,
        rows=comparison_rows,
        columns=columns,
    )
    if live != expected_before:
        raise RuntimeError(
            "live worksheet changed after the snapshot; refusing to write ("
            + _first_difference(live, expected_before)
            + ")"
        )

    existing_updates = build_cell_updates(before, candidate[:before_rows])
    appended_rows = candidate[before_rows:]
    if existing_updates:
        formula_values = normalize_values(
            get_values(
                token,
                args.spreadsheet_id,
                read_range,
                value_render_option="FORMULA",
            ),
            rows=comparison_rows,
            columns=columns,
        )
        formula_cells = [
            f"{a1_column(column)}{row}"
            for row, column, _value in existing_updates
            if formula_values[row - 1][column - 1].startswith("=")
        ]
        if formula_cells:
            raise RuntimeError(
                "refusing to replace formulas in changed cells: "
                + ", ".join(formula_cells[:20])
            )
    summary: dict[str, Any] = {
        "mode": "apply" if args.apply else "dry-run",
        "sheet": args.sheet_name,
        "before_rows": before_rows,
        "candidate_rows": candidate_rows,
        "columns": columns,
        "changed_existing_cells": len(existing_updates),
        "appended_rows": len(appended_rows),
    }
    if not args.apply:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    properties = get_sheet_properties(token, args.spreadsheet_id)
    source = next(
        (sheet for sheet in properties if sheet.get("title") == args.sheet_name),
        None,
    )
    if source is None:
        raise RuntimeError(f"worksheet not found: {args.sheet_name}")
    backup_title = args.backup_title or (
        f"_BACKUP_{args.sheet_name}_"
        + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    )
    if any(sheet.get("title") == backup_title for sheet in properties):
        raise RuntimeError(f"backup worksheet already exists: {backup_title}")

    backup_sheet_id = duplicate_sheet(
        token,
        args.spreadsheet_id,
        int(source["sheetId"]),
        backup_title,
    )
    summary["backup_title"] = backup_title
    summary["backup_sheet_id"] = backup_sheet_id

    try:
        write_cell_updates(
            token,
            args.spreadsheet_id,
            args.sheet_name,
            existing_updates,
        )
        write_appended_rows(
            token,
            args.spreadsheet_id,
            args.sheet_name,
            before_rows + 1,
            appended_rows,
            columns,
        )
        verify_range = (
            f"{_quoted_sheet(args.sheet_name)}!A1:"
            f"{a1_column(columns)}{candidate_rows}"
        )
        written = normalize_values(
            get_values(token, args.spreadsheet_id, verify_range),
            rows=candidate_rows,
            columns=columns,
        )
        if written != candidate:
            raise RuntimeError(
                "post-write verification failed ("
                + _first_difference(written, candidate)
                + ")"
            )
    except Exception:
        rollback_updates = [
            (row, column, before[row - 1][column - 1])
            for row, column, _value in existing_updates
        ]
        write_cell_updates(
            token,
            args.spreadsheet_id,
            args.sheet_name,
            rollback_updates,
        )
        if appended_rows:
            clear_range(
                token,
                args.spreadsheet_id,
                f"{_quoted_sheet(args.sheet_name)}!A{before_rows + 1}:"
                f"{a1_column(columns)}{candidate_rows}",
            )
        raise

    summary["verified"] = True
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
