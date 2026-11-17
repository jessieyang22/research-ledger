"""Tests for as_of.checkpoints. All fixtures are synthetic and use the SYN_ prefix."""

import json
import os

import pytest

from as_of.checkpoints import (
    CHECKPOINT_SUFFIX,
    latest_step,
    read_checkpoint,
    should_skip,
    write_checkpoint,
)
from as_of.core import AsOfError
from as_of.state_manifest import StateManifest


def _manifest(step_names=("SYN_ingest",)):
    manifest = StateManifest()
    for name in step_names:
        manifest.record_step(
            name,
            {"SYN_in.csv": "a" * 64},
            {"SYN_out.csv": "b" * 64},
            "SYN_v1",
        )
    return manifest


def _payload():
    return {"SYN_rows": 3, "SYN_label": "synthetic", "SYN_flag": True, "SYN_none": None}


def _checkpoint_file(tmp_path, step):
    return os.path.join(str(tmp_path), step + CHECKPOINT_SUFFIX)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True, indent=2)


# --- acceptance tests -------------------------------------------------------


def test_write_then_read_returns_equal_payload(tmp_path):
    payload = _payload()
    path = write_checkpoint(str(tmp_path), "SYN_ingest", payload, _manifest(), "SYN_hash_1")
    assert os.path.isfile(path)
    assert read_checkpoint(str(tmp_path), "SYN_ingest") == payload


def test_checkpoint_whose_file_is_altered_raises_on_read(tmp_path):
    write_checkpoint(str(tmp_path), "SYN_ingest", _payload(), _manifest(), "SYN_hash_1")
    path = _checkpoint_file(tmp_path, "SYN_ingest")
    envelope = _read_json(path)
    envelope["body"]["payload"]["SYN_rows"] = 999
    _write_json(path, envelope)
    with pytest.raises(AsOfError):
        read_checkpoint(str(tmp_path), "SYN_ingest")


def test_should_skip_is_false_when_input_hash_differs(tmp_path):
    write_checkpoint(str(tmp_path), "SYN_ingest", _payload(), _manifest(), "SYN_hash_1")
    assert should_skip(str(tmp_path), "SYN_ingest", "SYN_hash_1") is True
    assert should_skip(str(tmp_path), "SYN_ingest", "SYN_hash_2") is False


def test_latest_step_returns_last_step_in_order_that_has_a_checkpoint(tmp_path):
    steps = ["SYN_ingest", "SYN_build", "SYN_report"]
    manifest = _manifest(steps)
    write_checkpoint(str(tmp_path), "SYN_ingest", _payload(), manifest, "SYN_h")
    write_checkpoint(str(tmp_path), "SYN_build", _payload(), manifest, "SYN_h")
    assert latest_step(str(tmp_path), steps) == "SYN_build"
    write_checkpoint(str(tmp_path), "SYN_report", _payload(), manifest, "SYN_h")
    assert latest_step(str(tmp_path), steps) == "SYN_report"


# --- edge cases -------------------------------------------------------------


def test_should_skip_true_only_for_verified_matching_checkpoint(tmp_path):
    assert should_skip(str(tmp_path), "SYN_ingest", "SYN_hash_1") is False
    write_checkpoint(str(tmp_path), "SYN_ingest", _payload(), _manifest(), "SYN_hash_1")
    assert should_skip(str(tmp_path), "SYN_ingest", "SYN_hash_1") is True


def test_should_skip_is_false_when_checkpoint_is_altered(tmp_path):
    write_checkpoint(str(tmp_path), "SYN_ingest", _payload(), _manifest(), "SYN_hash_1")
    path = _checkpoint_file(tmp_path, "SYN_ingest")
    envelope = _read_json(path)
    envelope["body"]["input_hash"] = "SYN_hash_2"
    _write_json(path, envelope)
    assert should_skip(str(tmp_path), "SYN_ingest", "SYN_hash_2") is False


def test_altered_manifest_digest_raises_on_read(tmp_path):
    write_checkpoint(str(tmp_path), "SYN_ingest", _payload(), _manifest(), "SYN_hash_1")
    path = _checkpoint_file(tmp_path, "SYN_ingest")
    envelope = _read_json(path)
    envelope["body"]["manifest_digest"] = "0" * 64
    _write_json(path, envelope)
    with pytest.raises(AsOfError):
        read_checkpoint(str(tmp_path), "SYN_ingest")


def test_read_missing_checkpoint_raises_asof_error(tmp_path):
    with pytest.raises(AsOfError):
        read_checkpoint(str(tmp_path), "SYN_missing")


def test_read_invalid_json_raises_asof_error(tmp_path):
    path = _checkpoint_file(tmp_path, "SYN_ingest")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    with pytest.raises(AsOfError):
        read_checkpoint(str(tmp_path), "SYN_ingest")


def test_tuple_payload_comes_back_as_list(tmp_path):
    payload = {"SYN_pair": (1, 2)}
    write_checkpoint(str(tmp_path), "SYN_ingest", payload, _manifest(), "SYN_hash_1")
    assert read_checkpoint(str(tmp_path), "SYN_ingest") == {"SYN_pair": [1, 2]}


def test_write_replaces_existing_checkpoint(tmp_path):
    write_checkpoint(str(tmp_path), "SYN_ingest", {"SYN_v": 1}, _manifest(), "SYN_hash_1")
    write_checkpoint(str(tmp_path), "SYN_ingest", {"SYN_v": 2}, _manifest(), "SYN_hash_2")
    assert read_checkpoint(str(tmp_path), "SYN_ingest") == {"SYN_v": 2}
    assert should_skip(str(tmp_path), "SYN_ingest", "SYN_hash_1") is False
    assert should_skip(str(tmp_path), "SYN_ingest", "SYN_hash_2") is True


def test_write_leaves_no_temporary_file(tmp_path):
    write_checkpoint(str(tmp_path), "SYN_ingest", _payload(), _manifest(), "SYN_hash_1")
    assert not os.path.exists(_checkpoint_file(tmp_path, "SYN_ingest") + ".tmp")


def test_write_rejects_non_dict_payload_and_empty_input_hash(tmp_path):
    with pytest.raises(AsOfError):
        write_checkpoint(str(tmp_path), "SYN_ingest", ["SYN_not_a_dict"], _manifest(), "SYN_hash_1")
    with pytest.raises(AsOfError):
        write_checkpoint(str(tmp_path), "SYN_ingest", _payload(), _manifest(), "")


def test_unsafe_step_name_is_rejected(tmp_path):
    for bad in ["../SYN_escape", "SYN step", "", "SYN.step", "x" * 65]:
        with pytest.raises(AsOfError):
            write_checkpoint(str(tmp_path), bad, _payload(), _manifest(), "SYN_hash_1")


def test_latest_step_is_none_when_no_checkpoints_exist(tmp_path):
    assert latest_step(str(tmp_path), ["SYN_ingest", "SYN_build"]) is None


def test_latest_step_follows_given_order_not_alphabetical_order(tmp_path):
    manifest = _manifest()
    write_checkpoint(str(tmp_path), "SYN_a", _payload(), manifest, "SYN_h")
    write_checkpoint(str(tmp_path), "SYN_b", _payload(), manifest, "SYN_h")
    assert latest_step(str(tmp_path), ["SYN_b", "SYN_a"]) == "SYN_a"
