import json
import sys

import pytest

import scripts.apply_google_sheet_values as sheet_apply
from scripts.apply_google_sheet_values import (
    a1_column,
    build_cell_updates,
    main,
    normalize_values,
)


def test_a1_column_supports_columns_after_z():
    assert a1_column(1) == "A"
    assert a1_column(22) == "V"
    assert a1_column(26) == "Z"
    assert a1_column(27) == "AA"


def test_normalize_values_pads_missing_cells_and_rows():
    assert normalize_values([["a"], ["b", "c"]], rows=3, columns=3) == [
        ["a", "", ""],
        ["b", "c", ""],
        ["", "", ""],
    ]


def test_build_cell_updates_only_returns_changed_candidate_cells():
    before = [["A", "B"], ["old", "same"]]
    candidate = [["A", "B", "Alias"], ["new", "same", "legacy"]]

    updates = build_cell_updates(before, candidate)

    assert updates == [
        (1, 3, "Alias"),
        (2, 1, "new"),
        (2, 3, "legacy"),
    ]


def _write_values(path, values):
    path.write_text(json.dumps({"values": values}), encoding="utf-8")


def _run_main(monkeypatch, tmp_path, before, candidate, *, live_reads):
    before_path = tmp_path / "before.json"
    candidate_path = tmp_path / "candidate.json"
    credentials_path = tmp_path / "credentials.json"
    _write_values(before_path, before)
    _write_values(candidate_path, candidate)
    credentials_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "apply_google_sheet_values.py",
            "spreadsheet-id",
            "_master_catalog",
            str(before_path),
            str(candidate_path),
            "--credentials",
            str(credentials_path),
            "--backup-title",
            "_BACKUP_test",
            "--apply",
        ],
    )
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.service_account_token",
        lambda _credentials: "token",
    )
    reads = list(live_reads)

    def fake_get_values(*_args, **kwargs):
        if kwargs.get("value_render_option") == "FORMULA":
            return before
        return reads.pop(0)

    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.get_values",
        fake_get_values,
    )
    return main()


def test_main_refuses_stale_live_sheet_before_backup(monkeypatch, tmp_path):
    backup_called = False

    def fail_if_called(*_args):
        nonlocal backup_called
        backup_called = True
        raise AssertionError("backup must not be created for stale input")

    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.get_sheet_properties",
        lambda *_args: [{"title": "_master_catalog", "sheetId": 10}],
    )
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.duplicate_sheet",
        fail_if_called,
    )

    with pytest.raises(RuntimeError, match="live worksheet changed"):
        _run_main(
            monkeypatch,
            tmp_path,
            before=[["A"], ["old"]],
            candidate=[["A"], ["new"]],
            live_reads=[[["A"], ["changed-by-user"]]],
        )

    assert backup_called is False


def test_main_applies_backup_updates_append_and_verify(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.get_sheet_properties",
        lambda *_args: [{"title": "_master_catalog", "sheetId": 10}],
    )
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.duplicate_sheet",
        lambda *_args: calls.append(("backup",)) or 123,
    )
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.write_cell_updates",
        lambda *_args: calls.append(("updates", list(_args[-1]))),
    )
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.write_appended_rows",
        lambda *_args: calls.append(("append", _args[-3], _args[-2])),
    )
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.clear_range",
        lambda *_args: calls.append(("clear", _args[-1])),
    )

    result = _run_main(
        monkeypatch,
        tmp_path,
        before=[["A", "B"], ["old", "same"]],
        candidate=[
            ["A", "B", "Alias"],
            ["new", "same", "legacy"],
            ["appended", "row", "value"],
        ],
        live_reads=[
            [["A", "B"], ["old", "same"]],
            [
                ["A", "B", "Alias"],
                ["new", "same", "legacy"],
                ["appended", "row", "value"],
            ],
        ],
    )

    assert result == 0
    assert calls == [
        ("backup",),
        (
            "updates",
            [(1, 3, "Alias"), (2, 1, "new"), (2, 3, "legacy")],
        ),
        ("append", 3, [["appended", "row", "value"]]),
    ]


def test_main_rolls_back_existing_updates_and_appended_rows(
    monkeypatch,
    tmp_path,
):
    calls = []
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.get_sheet_properties",
        lambda *_args: [{"title": "_master_catalog", "sheetId": 10}],
    )
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.duplicate_sheet",
        lambda *_args: calls.append(("backup",)) or 123,
    )
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.write_cell_updates",
        lambda *_args: calls.append(("updates", list(_args[-1]))),
    )
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.write_appended_rows",
        lambda *_args: calls.append(("append", _args[-3], _args[-2])),
    )
    monkeypatch.setattr(
        "scripts.apply_google_sheet_values.clear_range",
        lambda *_args: calls.append(("clear", _args[-1])),
    )

    with pytest.raises(RuntimeError, match="post-write verification failed"):
        _run_main(
            monkeypatch,
            tmp_path,
            before=[["A", "B"], ["old", "same"]],
            candidate=[
                ["A", "B", "Alias"],
                ["new", "same", "legacy"],
                ["appended", "row", "value"],
            ],
            live_reads=[
                [["A", "B"], ["old", "same"]],
                [["wrong"]],
            ],
        )

    assert calls == [
        ("backup",),
        (
            "updates",
            [(1, 3, "Alias"), (2, 1, "new"), (2, 3, "legacy")],
        ),
        ("append", 3, [["appended", "row", "value"]]),
        (
            "updates",
            [(1, 3, ""), (2, 1, "old"), (2, 3, "")],
        ),
        ("clear", "'_master_catalog'!A3:C3"),
    ]


def write_payload(path, values):
    path.write_text(json.dumps({"values": values}), encoding="utf-8")


def test_apply_rolls_back_changed_and_appended_values_on_write_failure(
    tmp_path,
    monkeypatch,
):
    before = tmp_path / "before.json"
    candidate = tmp_path / "candidate.json"
    credentials = tmp_path / "credentials.json"
    before_values = [["Header"], ["old"]]
    candidate_values = [["Header"], ["new"], ["added"]]
    write_payload(before, before_values)
    write_payload(candidate, candidate_values)
    credentials.write_text("{}", encoding="utf-8")

    cell_writes = []
    cleared = []
    monkeypatch.setattr(sheet_apply, "service_account_token", lambda _path: "token")
    monkeypatch.setattr(
        sheet_apply,
        "get_values",
        lambda *_args, **_kwargs: before_values,
    )
    monkeypatch.setattr(
        sheet_apply,
        "get_sheet_properties",
        lambda *_args: [{"title": "Master", "sheetId": 123}],
    )
    monkeypatch.setattr(sheet_apply, "duplicate_sheet", lambda *_args: 456)
    monkeypatch.setattr(
        sheet_apply,
        "write_cell_updates",
        lambda _token, _spreadsheet, _sheet, updates: cell_writes.append(
            list(updates)
        ),
    )

    def fail_append(*_args):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(sheet_apply, "write_appended_rows", fail_append)
    monkeypatch.setattr(
        sheet_apply,
        "clear_range",
        lambda _token, _spreadsheet, range_name: cleared.append(range_name),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "apply_google_sheet_values.py",
            "spreadsheet",
            "Master",
            str(before),
            str(candidate),
            "--credentials",
            str(credentials),
            "--backup-title",
            "backup",
            "--apply",
        ],
    )

    with pytest.raises(RuntimeError, match="simulated write failure"):
        sheet_apply.main()

    assert cell_writes == [[(2, 1, "new")], [(2, 1, "old")]]
    assert cleared == ["'Master'!A3:A3"]


def test_apply_refuses_to_overwrite_formula_in_changed_cell(
    tmp_path,
    monkeypatch,
):
    before = tmp_path / "before.json"
    candidate = tmp_path / "candidate.json"
    credentials = tmp_path / "credentials.json"
    before_values = [["Header"], ["calculated"]]
    write_payload(before, before_values)
    write_payload(candidate, [["Header"], ["replacement"]])
    credentials.write_text("{}", encoding="utf-8")

    reads = iter([before_values, [["Header"], ["=A1"]]])
    monkeypatch.setattr(sheet_apply, "service_account_token", lambda _path: "token")
    monkeypatch.setattr(
        sheet_apply,
        "get_values",
        lambda *_args, **_kwargs: next(reads),
    )
    monkeypatch.setattr(
        sheet_apply,
        "duplicate_sheet",
        lambda *_args: pytest.fail("backup must not be created after formula check"),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "apply_google_sheet_values.py",
            "spreadsheet",
            "Master",
            str(before),
            str(candidate),
            "--credentials",
            str(credentials),
            "--apply",
        ],
    )

    with pytest.raises(RuntimeError, match="replace formulas.*A2"):
        sheet_apply.main()
