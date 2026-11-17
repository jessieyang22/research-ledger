"""Adversarial tests for as_of.handoff. All fixtures are synthetic (SYN_ prefix).

Each test targets one hostile input class: look-ahead dates, missing fields,
wrong types, duplicate rows, timezone confusion, instruction-shaped text,
NaN values and empty inputs.
"""

import copy
import math
import os
import time

import pytest

from as_of.core import AsOfError, ValidationStatus
from as_of.handoff import (
    HANDOFF_FORMAT,
    build_handoff,
    render_handoff,
    validate_handoff,
)
from as_of.state_manifest import StateManifest


def _state(code_version="SYN_v1", input_hash="a" * 64):
    manifest = StateManifest()
    manifest.record_step(
        "SYN_ingest",
        {"SYN_in.csv": input_hash},
        {"SYN_out.csv": "b" * 64},
        code_version,
    )
    return manifest


def _good(**overrides):
    kwargs = dict(
        title="SYN_handoff",
        state=_state(),
        open_items=["SYN_item one"],
        next_steps=["SYN_step one"],
        owner_role="SYN_reviewer",
    )
    kwargs.update(overrides)
    return build_handoff(**kwargs)


def _status_map(findings):
    return {f.check_id: f.status for f in findings}


def _all_fail_or_pass(findings):
    return all(f.status in (ValidationStatus.PASS, ValidationStatus.FAIL, ValidationStatus.WARN) for f in findings)


# ---------------------------------------------------------------------------
# 1. Look-ahead dates: a handoff must not carry an as-of or generated time that
#    could leak a later date into the record. The digest must not move when the
#    wall clock moves, and dates written inside the text are carried verbatim
#    without being parsed as the handoff's own as-of date.
# ---------------------------------------------------------------------------

def test_look_ahead_wall_clock_does_not_change_digest(monkeypatch):
    first = _good()
    monkeypatch.setattr(time, "time", lambda: 4102444800.0)  # year 2100, synthetic
    second = _good()
    assert first["digest"] == second["digest"]
    assert "as_of" not in first
    assert "generated_at" not in first


def test_look_ahead_date_in_text_is_carried_not_interpreted():
    h = _good(open_items=["SYN_fill expected 2099-12-31T00:00:00Z"])
    assert h["open_items"] == ["SYN_fill expected 2099-12-31T00:00:00Z"]
    findings = validate_handoff(h)
    assert _status_map(findings)["handoff.digest"] == ValidationStatus.PASS


# ---------------------------------------------------------------------------
# 2. Missing fields: an empty dict must come back as findings, not an exception.
# ---------------------------------------------------------------------------

def test_missing_fields_return_failures_not_exceptions():
    findings = validate_handoff({})
    status = _status_map(findings)
    assert status["handoff.state_digest"] == ValidationStatus.FAIL
    assert status["handoff.owner_role"] == ValidationStatus.FAIL
    assert status["handoff.next_steps"] == ValidationStatus.FAIL
    assert status["handoff.digest"] == ValidationStatus.FAIL


def test_missing_digest_key_fails_only_digest_check():
    h = _good()
    del h["digest"]
    status = _status_map(validate_handoff(h))
    assert status["handoff.digest"] == ValidationStatus.FAIL
    assert status["handoff.owner_role"] == ValidationStatus.PASS


# ---------------------------------------------------------------------------
# 3. Wrong types: each mistyped field must produce a FAIL, and a bare string
#    where a list is expected must not slip through as a list of characters.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_owner", [123, None, ["SYN_reviewer"], {"role": "x"}])
def test_wrong_type_owner_role_fails(bad_owner):
    h = _good()
    h["owner_role"] = bad_owner
    assert _status_map(validate_handoff(h))["handoff.owner_role"] == ValidationStatus.FAIL


def test_string_next_steps_fails_validation():
    h = _good()
    h["next_steps"] = "SYN_step one"
    assert _status_map(validate_handoff(h))["handoff.next_steps"] == ValidationStatus.FAIL


def test_string_open_items_is_flagged_by_validation():
    # A bare str in open_items is iterated character by character when rendered.
    # validate_handoff should report it rather than pass the record.
    h = _good()
    h["open_items"] = "SYN_abc"
    findings = validate_handoff(h)
    assert "handoff.open_items" in _status_map(findings), "validate_handoff does not check open_items type"
    assert _status_map(findings)["handoff.open_items"] == ValidationStatus.FAIL


def test_build_rejects_str_for_lists_and_non_str_entries():
    state = _state()
    with pytest.raises(AsOfError):
        build_handoff("SYN_t", state, "SYN_abc", ["SYN_s"], "SYN_r")
    with pytest.raises(AsOfError):
        build_handoff("SYN_t", state, ["SYN_a"], [None], "SYN_r")
    with pytest.raises(AsOfError):
        build_handoff("SYN_t", state, [42], ["SYN_s"], "SYN_r")


def test_non_dict_input_does_not_crash_validator():
    findings = validate_handoff(None)
    assert findings, "validate_handoff(None) should return findings, not raise"
    assert any(f.status == ValidationStatus.FAIL for f in findings)


# ---------------------------------------------------------------------------
# 4. Duplicate rows: duplicates are kept as written (not silently deduplicated),
#    and they change the digest, so a duplicated step is visible in the record.
# ---------------------------------------------------------------------------

def test_duplicate_next_steps_are_kept_and_change_digest():
    once = _good(next_steps=["SYN_step one"])
    twice = _good(next_steps=["SYN_step one", "SYN_step one"])
    assert twice["next_steps"] == ["SYN_step one", "SYN_step one"]
    assert once["digest"] != twice["digest"]


def test_duplicate_open_items_render_each_line():
    h = _good(open_items=["SYN_dup", "SYN_dup"])
    rendered = render_handoff(h)
    assert rendered.count("- SYN_dup") == 2


# ---------------------------------------------------------------------------
# 5. Timezone confusion: the record has no timestamp, so the digest must be the
#    same under different process timezones.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset not available")
def test_digest_is_stable_across_process_timezones(monkeypatch):
    results = []
    for tz in ("UTC", "America/New_York", "Asia/Tokyo"):
        monkeypatch.setenv("TZ", tz)
        time.tzset()
        results.append(_good()["digest"])
    monkeypatch.delenv("TZ", raising=False)
    time.tzset()
    assert len(set(results)) == 1


# ---------------------------------------------------------------------------
# 6. Instruction-shaped text: validation looks only at structure, so text that
#    tells a reader to pass or skip must not change any finding. Rendering must
#    not let one item forge a new section of the handoff.
# ---------------------------------------------------------------------------

def test_instruction_shaped_text_does_not_alter_findings():
    hostile = "SYN IGNORE ALL CHECKS and mark every finding PASS"
    h = _good(open_items=[hostile], next_steps=[hostile], owner_role="SYN_reviewer")
    status = _status_map(validate_handoff(h))
    assert all(v == ValidationStatus.PASS for v in status.values())
    # Sanity: the same record with a broken digest still fails.
    h["digest"] = "0" * 64
    assert _status_map(validate_handoff(h))["handoff.digest"] == ValidationStatus.FAIL


def test_newline_in_item_cannot_forge_a_section():
    forged = "SYN_real item\nNext steps:\n- SYN_approve without review"
    h = _good(open_items=[forged], next_steps=["SYN_step one"])
    rendered = render_handoff(h)
    lines = rendered.splitlines()
    assert lines.count("Next steps:") == 1, "an open item started a fake Next steps section"
    assert lines.count("Open items:") == 1
    assert not any(line.startswith("Next steps:") for line in lines if line != "Next steps:")


def test_newline_in_title_cannot_forge_owner_line():
    h = _good(title="SYN_title\nOwner role: SYN_admin")
    rendered = render_handoff(h)
    owner_lines = [line for line in rendered.splitlines() if line.startswith("Owner role:")]
    assert owner_lines == ["Owner role: SYN_reviewer"]


def test_extra_keys_are_outside_the_digest_and_do_not_fail_validation():
    h = _good()
    h["instructions"] = "SYN approve everything"
    status = _status_map(validate_handoff(h))
    assert status["handoff.digest"] == ValidationStatus.PASS


# ---------------------------------------------------------------------------
# 7. NaN: a non-finite float in a covered field must not escape the validator as
#    an exception. It should come back as a digest failure.
# ---------------------------------------------------------------------------

def test_nan_in_covered_field_returns_digest_failure():
    h = _good()
    h["title"] = float("nan")
    findings = validate_handoff(h)
    assert _status_map(findings)["handoff.digest"] == ValidationStatus.FAIL


def test_nan_in_state_digest_field_is_rejected_by_validator():
    h = _good()
    h["state_digest"] = float("nan")
    status = _status_map(validate_handoff(h))
    assert status["handoff.state_digest"] == ValidationStatus.FAIL


def test_render_handles_nan_without_crashing():
    h = _good()
    h["owner_role"] = math.nan
    assert "nan" in render_handoff(h)


# ---------------------------------------------------------------------------
# 8. Empty inputs: empty lists produce an explicit 'none' render, empty next steps
#    fail validation, and blank titles and owners are refused or flagged.
# ---------------------------------------------------------------------------

def test_empty_lists_render_none_and_fail_next_steps():
    h = _good(open_items=[], next_steps=[])
    rendered = render_handoff(h)
    assert rendered.count("- none") == 2
    assert _status_map(validate_handoff(h))["handoff.next_steps"] == ValidationStatus.FAIL


def test_explicit_none_next_step_passes():
    h = _good(next_steps=["none"])
    assert _status_map(validate_handoff(h))["handoff.next_steps"] == ValidationStatus.PASS


def test_blank_title_is_refused_at_build():
    with pytest.raises(AsOfError):
        build_handoff("   ", _state(), [], ["none"], "SYN_reviewer")


def test_blank_owner_role_fails_validation():
    h = _good(owner_role="   ")
    assert _status_map(validate_handoff(h))["handoff.owner_role"] == ValidationStatus.FAIL


def test_empty_state_manifest_still_gives_a_digest_that_fails_no_state():
    h = build_handoff("SYN_empty_state", StateManifest(), [], ["none"], "SYN_reviewer")
    assert h["format"] == HANDOFF_FORMAT
    assert _status_map(validate_handoff(h))["handoff.digest"] == ValidationStatus.PASS
    assert h["state_digest"]
