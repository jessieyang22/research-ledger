"""Tests for as_of.state_manifest. All fixtures are synthetic and use the SYN_ prefix."""

import json

import pytest

from as_of.core import AsOfError
from as_of.state_manifest import MANIFEST_FORMAT, MANIFEST_VERSION, StateManifest


def _build(names):
    manifest = StateManifest()
    for name in names:
        manifest.record_step(
            name,
            {"SYN_in.csv": "a" * 64},
            {"SYN_out.csv": "b" * 64},
            "SYN_v1",
        )
    return manifest


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True, indent=2)


# --- acceptance tests -------------------------------------------------------


def test_save_then_load_gives_same_digest(tmp_path):
    manifest = _build(["SYN_ingest", "SYN_build", "SYN_report"])
    path = str(tmp_path / "SYN_manifest.json")
    saved = manifest.save(path)
    loaded = StateManifest.load(path)
    assert saved == manifest.digest()
    assert loaded.digest() == saved
    assert loaded.steps() == manifest.steps()


def test_steps_keep_insertion_order():
    names = ["SYN_ingest", "SYN_build", "SYN_report"]
    manifest = _build(names)
    assert [s["step_name"] for s in manifest.steps()] == names
    reordered = _build(list(reversed(names)))
    assert manifest.digest() != reordered.digest()


def test_verify_returns_false_after_file_is_edited(tmp_path):
    manifest = _build(["SYN_ingest", "SYN_build"])
    path = str(tmp_path / "SYN_manifest.json")
    manifest.save(path)
    assert StateManifest.verify(path) is True

    data = _read_json(path)
    data["manifest"]["steps"][0]["code_version"] = "SYN_v2"
    _write_json(path, data)
    assert StateManifest.verify(path) is False


def test_two_manifests_with_same_steps_have_same_digest():
    first = _build(["SYN_ingest", "SYN_build"])
    second = _build(["SYN_ingest", "SYN_build"])
    assert first.digest() == second.digest()


# --- edge cases -------------------------------------------------------------


def test_empty_manifest_round_trips(tmp_path):
    manifest = StateManifest()
    path = str(tmp_path / "SYN_empty.json")
    digest = manifest.save(path)
    loaded = StateManifest.load(path)
    assert loaded.steps() == []
    assert loaded.digest() == digest
    assert StateManifest.verify(path) is True


def test_digest_is_hex_sha256():
    digest = _build(["SYN_ingest"]).digest()
    assert len(digest) == 64
    int(digest, 16)


def test_digest_changes_when_output_hash_changes():
    base = _build(["SYN_ingest"])
    other = StateManifest()
    other.record_step("SYN_ingest", {"SYN_in.csv": "a" * 64}, {"SYN_out.csv": "c" * 64}, "SYN_v1")
    assert base.digest() != other.digest()


def test_steps_returns_copies():
    manifest = _build(["SYN_ingest"])
    snapshot = manifest.steps()
    snapshot[0]["inputs"]["SYN_in.csv"] = "f" * 64
    snapshot[0]["step_name"] = "SYN_changed"
    assert manifest.steps()[0]["step_name"] == "SYN_ingest"
    assert manifest.steps()[0]["inputs"]["SYN_in.csv"] == "a" * 64


def test_record_step_rejects_empty_name():
    with pytest.raises(AsOfError):
        StateManifest().record_step("", {}, {}, "SYN_v1")


def test_record_step_rejects_empty_code_version():
    with pytest.raises(AsOfError):
        StateManifest().record_step("SYN_ingest", {}, {}, "")


def test_record_step_rejects_non_str_hash():
    with pytest.raises(AsOfError):
        StateManifest().record_step("SYN_ingest", {"SYN_in.csv": 123}, {}, "SYN_v1")


def test_record_step_rejects_non_dict_inputs():
    with pytest.raises(AsOfError):
        StateManifest().record_step("SYN_ingest", ["SYN_in.csv"], {}, "SYN_v1")


def test_verify_returns_false_for_missing_file(tmp_path):
    assert StateManifest.verify(str(tmp_path / "SYN_missing.json")) is False


def test_verify_returns_false_for_invalid_json(tmp_path):
    path = tmp_path / "SYN_broken.json"
    path.write_text("{not json", encoding="utf-8")
    assert StateManifest.verify(str(path)) is False


def test_verify_returns_false_when_digest_field_is_edited(tmp_path):
    manifest = _build(["SYN_ingest"])
    path = str(tmp_path / "SYN_manifest.json")
    manifest.save(path)
    data = _read_json(path)
    data["digest"] = "0" * 64
    _write_json(path, data)
    assert StateManifest.verify(path) is False


def test_load_rejects_wrong_format(tmp_path):
    manifest = _build(["SYN_ingest"])
    path = str(tmp_path / "SYN_manifest.json")
    manifest.save(path)
    data = _read_json(path)
    data["manifest"]["format"] = "SYN_other_format"
    _write_json(path, data)
    with pytest.raises(AsOfError):
        StateManifest.load(path)


def test_load_rejects_wrong_version(tmp_path):
    manifest = _build(["SYN_ingest"])
    path = str(tmp_path / "SYN_manifest.json")
    manifest.save(path)
    data = _read_json(path)
    data["manifest"]["version"] = MANIFEST_VERSION + 1
    _write_json(path, data)
    with pytest.raises(AsOfError):
        StateManifest.load(path)


def test_saved_file_carries_format_and_version(tmp_path):
    path = str(tmp_path / "SYN_manifest.json")
    _build(["SYN_ingest"]).save(path)
    body = _read_json(path)["manifest"]
    assert body["format"] == MANIFEST_FORMAT
    assert body["version"] == MANIFEST_VERSION
