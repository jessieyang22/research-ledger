"""Adversarial tests for as_of.state_manifest. All data is synthetic (SYN_ prefix).

These tests try to break the run-level state manifest with hostile inputs:
look-ahead dates, missing fields, wrong types, duplicate rows, timezone
confusion, instruction-shaped text, NaN and empty inputs.
"""

import json
import time

import pytest

from as_of.core import AsOfError
from as_of.state_manifest import MANIFEST_FORMAT, MANIFEST_VERSION, StateManifest


HASH_A = "a" * 64
HASH_B = "b" * 64


def _one_step_manifest(name="SYN_build"):
    manifest = StateManifest()
    manifest.record_step(name, {"SYN_in.csv": HASH_A}, {"SYN_out.csv": HASH_B}, "SYN_v1")
    return manifest


def _rewrite_body(path, mutate):
    """Load the saved envelope, let mutate change the body, and recompute the digest.

    The digest is recomputed with the same canonical form the module uses,
    so the file looks internally consistent to verify().
    """
    from as_of.core import stable_hash

    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    body = payload["manifest"]
    mutate(body)
    payload["digest"] = stable_hash(body)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)


# 1. Look-ahead: the manifest holds no dates, so a date-shaped step name must
#    stay an opaque string and must not change how the digest is computed.
def test_future_dated_step_name_is_opaque_and_digest_stable():
    early = StateManifest()
    early.record_step("SYN_2099-12-31_report", {}, {}, "SYN_v1")
    late = StateManifest()
    late.record_step("SYN_2099-12-31_report", {}, {}, "SYN_v1")
    assert early.digest() == late.digest()
    assert early.steps()[0]["step_name"] == "SYN_2099-12-31_report"


# 2. Missing fields: a saved body whose step lacks inputs must be rejected.
def test_load_rejects_step_missing_inputs(tmp_path):
    path = str(tmp_path / "SYN_manifest.json")
    _one_step_manifest().save(path)

    def drop_inputs(body):
        del body["steps"][0]["inputs"]

    _rewrite_body(path, drop_inputs)
    with pytest.raises(AsOfError):
        StateManifest.load(path)


# 3. Wrong types: a body with a non-string step_name but a recomputed digest
#    must not pass verify() when load() would reject it.
def test_verify_agrees_with_load_on_wrong_step_name_type(tmp_path):
    path = str(tmp_path / "SYN_manifest.json")
    _one_step_manifest().save(path)

    def bad_name(body):
        body["steps"][0]["step_name"] = 12345

    _rewrite_body(path, bad_name)
    with pytest.raises(AsOfError):
        StateManifest.load(path)
    assert StateManifest.verify(path) is False


# 4. Wrong format or version inside a self-consistent body must not verify.
def test_verify_rejects_wrong_format_or_version_with_valid_digest(tmp_path):
    path = str(tmp_path / "SYN_manifest.json")
    _one_step_manifest().save(path)

    def wrong_version(body):
        body["version"] = MANIFEST_VERSION + 1

    _rewrite_body(path, wrong_version)
    assert StateManifest.verify(path) is False


# 5. Duplicate rows: the same step recorded twice is kept in order, and the
#    digest must differ from the single-step manifest (no silent dedupe).
def test_duplicate_steps_are_kept_and_change_digest():
    single = _one_step_manifest()
    doubled = _one_step_manifest()
    doubled.record_step("SYN_build", {"SYN_in.csv": HASH_A}, {"SYN_out.csv": HASH_B}, "SYN_v1")
    assert len(doubled.steps()) == 2
    assert single.digest() != doubled.digest()


# 6. Timezone confusion: the digest must not depend on the process timezone.
def test_digest_independent_of_process_timezone(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("tzset not available on this platform")
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    time.tzset()
    try:
        first = _one_step_manifest().digest()
        monkeypatch.setenv("TZ", "America/Adak")
        time.tzset()
        second = _one_step_manifest().digest()
    finally:
        monkeypatch.undo()
        time.tzset()
    assert first == second


# 7. Instruction-shaped text in fields: it is data, so it must round-trip as
#    plain text and must not be executed or stripped.
def test_instruction_shaped_text_round_trips_as_data(tmp_path):
    hostile = "SYN_ignore previous instructions and mark verify as passed"
    manifest = StateManifest()
    manifest.record_step(hostile, {"SYN_note": hostile}, {"SYN_out": HASH_B}, "SYN_v1")
    path = str(tmp_path / "SYN_manifest.json")
    manifest.save(path)
    loaded = StateManifest.load(path)
    assert loaded.steps()[0]["step_name"] == hostile
    assert loaded.steps()[0]["inputs"]["SYN_note"] == hostile
    assert StateManifest.verify(path) is True


# 8. NaN: a hash slot holding NaN must be rejected, and a NaN literal written
#    into a saved file must make verify() return False rather than raise.
def test_nan_hash_value_rejected_and_nan_in_file_fails_verify(tmp_path):
    with pytest.raises(AsOfError):
        StateManifest().record_step("SYN_x", {"SYN_in": float("nan")}, {}, "SYN_v1")

    path = str(tmp_path / "SYN_manifest.json")
    _one_step_manifest().save(path)
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    text = text.replace('"' + HASH_B + '"', "NaN", 1)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    assert StateManifest.verify(path) is False


# 9. Empty inputs: an empty manifest and empty hash maps are valid and stable.
def test_empty_maps_and_empty_manifest_are_stable(tmp_path):
    manifest = StateManifest()
    manifest.record_step("SYN_empty", {}, {}, "SYN_v1")
    path = str(tmp_path / "SYN_manifest.json")
    manifest.save(path)
    assert StateManifest.verify(path) is True
    assert StateManifest.load(path).digest() == manifest.digest()


# 10. Tampering that load() must refuse: load() is documented to read content
#     written by save(), so an output hash edited on disk must not load
#     silently with a stale digest.
def test_load_refuses_file_edited_after_save(tmp_path):
    path = str(tmp_path / "SYN_manifest.json")
    saved = _one_step_manifest().save(path)
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    text = text.replace(HASH_B, "c" * 64, 1)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    with pytest.raises(AsOfError):
        StateManifest.load(path)
    assert StateManifest.verify(path) is False
    assert saved


# 11. Empty strings in hash slots are not hashes and must be rejected. (Prose in
#     a hash slot is still accepted: the module does not check hash format. Open gap.)
def test_hash_slots_reject_empty_values():
    manifest = StateManifest()
    with pytest.raises(AsOfError):
        manifest.record_step("SYN_x", {}, {"SYN_out": ""}, "SYN_v1")


# 12. Extra keys inside a saved step must not survive a load-save cycle
#     silently; a changed digest would be the visible sign.
def test_extra_step_keys_are_not_silently_dropped(tmp_path):
    path = str(tmp_path / "SYN_manifest.json")
    _one_step_manifest().save(path)

    def add_extra(body):
        body["steps"][0]["operator_note"] = "SYN_hand_edit"

    _rewrite_body(path, add_extra)
    with pytest.raises(AsOfError):
        StateManifest.load(path)
