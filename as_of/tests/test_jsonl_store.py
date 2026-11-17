"""Tests for as_of.jsonl_store. All fixtures are synthetic and use the SYN_ prefix."""

import inspect
import types

import pytest

from as_of import jsonl_store
from as_of.core import AsOfError


def _records():
    return [
        {"SYN_id": 1, "SYN_note": "first"},
        {"SYN_id": 2, "SYN_note": "second"},
        {"SYN_id": 3, "SYN_note": "third"},
    ]


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_append_three_records_then_read_returns_them_in_insertion_order(tmp_path):
    path = str(tmp_path / "SYN_ledger.jsonl")
    for record in _records():
        jsonl_store.append_record(path, record)

    assert jsonl_store.read_records(path) == _records()
    assert jsonl_store.count_records(path) == 3


def test_read_records_on_non_json_line_raises_naming_line_number(tmp_path):
    path = tmp_path / "SYN_bad_json.jsonl"
    path.write_text('{"SYN_id": 1}\n{"SYN_id": 2\n{"SYN_id": 3}\n', encoding="utf-8")

    with pytest.raises(AsOfError) as excinfo:
        jsonl_store.read_records(str(path))
    assert "line 2" in str(excinfo.value)


def test_read_records_on_non_object_json_value_raises(tmp_path):
    for bad_line in ["[1, 2, 3]", "42", '"SYN_text"', "null", "true"]:
        path = tmp_path / "SYN_non_object.jsonl"
        path.write_text('{"SYN_id": 1}\n' + bad_line + "\n", encoding="utf-8")

        with pytest.raises(AsOfError) as excinfo:
            jsonl_store.read_records(str(path))
        assert "line 2" in str(excinfo.value)
        assert "not a JSON object" in str(excinfo.value)


def test_module_exposes_no_truncate_delete_or_overwrite_function():
    forbidden = ("truncate", "delete", "overwrite")
    function_names = [
        name
        for name, value in vars(jsonl_store).items()
        if not name.startswith("_")
        and (inspect.isfunction(value) or isinstance(value, types.BuiltinFunctionType))
    ]
    assert function_names, "expected the module to define public functions"
    for name in function_names:
        lowered = name.lower()
        for word in forbidden:
            assert word not in lowered, "forbidden function name: %s" % name


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_missing_file_reads_as_empty_history(tmp_path):
    path = str(tmp_path / "SYN_does_not_exist.jsonl")
    assert jsonl_store.read_records(path) == []
    assert jsonl_store.count_records(path) == 0


def test_append_creates_one_canonical_line_per_record(tmp_path):
    path = tmp_path / "SYN_canonical.jsonl"
    jsonl_store.append_record(str(path), {"SYN_b": 2, "SYN_a": 1})

    raw = path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert raw.count("\n") == 1
    assert raw == '{"SYN_a":1,"SYN_b":2}\n'


def test_append_preserves_existing_lines(tmp_path):
    path = tmp_path / "SYN_append_only.jsonl"
    path.write_text('{"SYN_id": 0}\n', encoding="utf-8")
    jsonl_store.append_record(str(path), {"SYN_id": 1})

    assert jsonl_store.read_records(str(path)) == [{"SYN_id": 0}, {"SYN_id": 1}]


def test_append_rejects_non_dict_record_and_writes_nothing(tmp_path):
    path = tmp_path / "SYN_reject.jsonl"
    with pytest.raises(AsOfError):
        jsonl_store.append_record(str(path), ["SYN_not", "a_dict"])
    assert not path.exists()


def test_append_rejects_nan_and_writes_nothing(tmp_path):
    path = tmp_path / "SYN_nan.jsonl"
    with pytest.raises(Exception):
        jsonl_store.append_record(str(path), {"SYN_value": float("nan")})
    assert not path.exists() or path.read_text(encoding="utf-8") == ""


def test_empty_path_is_rejected():
    with pytest.raises(AsOfError):
        jsonl_store.read_records("")
    with pytest.raises(AsOfError):
        jsonl_store.append_record("", {"SYN_id": 1})
