"""Tests for as_of.handoff. All fixtures are synthetic and use the SYN_ prefix."""

import copy

import pytest

from as_of.core import AsOfError, ValidationStatus
from as_of.handoff import (
    HANDOFF_FORMAT,
    HANDOFF_VERSION,
    build_handoff,
    render_handoff,
    validate_handoff,
)
from as_of.state_manifest import StateManifest


def _state(code_version="SYN_v1"):
    manifest = StateManifest()
    manifest.record_step(
        "SYN_ingest",
        {"SYN_in.csv": "a" * 64},
        {"SYN_out.csv": "b" * 64},
        code_version,
    )
    return manifest


def _status_map(findings):
    return {f.check_id: f.status for f in findings}


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


# --- acceptance tests -------------------------------------------------------


def test_handoff_with_no_next_steps_and_no_none_entry_is_fail():
    h = _good(next_steps=[])
    findings = validate_handoff(h)
    assert _status_map(findings)["handoff.next_steps"] == ValidationStatus.FAIL


def test_render_handoff_includes_state_digest():
    state = _state()
    h = build_handoff(
        title="SYN_handoff",
        state=state,
        open_items=[],
        next_steps=["none"],
        owner_role="SYN_reviewer",
    )
    text = render_handoff(h)
    assert "State digest: %s" % state.digest() in text
    assert state.digest() in text


def test_empty_owner_role_is_fail():
    h = _good(owner_role="")
    findings = validate_handoff(h)
    assert _status_map(findings)["handoff.owner_role"] == ValidationStatus.FAIL


def test_same_inputs_give_same_handoff_digest():
    first = _good()
    second = _good()
    assert first["digest"] == second["digest"]
    assert first == second


# --- edge cases -------------------------------------------------------------


def test_whitespace_only_owner_role_is_fail():
    findings = validate_handoff(_good(owner_role="   "))
    assert _status_map(findings)["handoff.owner_role"] == ValidationStatus.FAIL


def test_explicit_none_next_step_passes():
    findings = validate_handoff(_good(next_steps=["none"]))
    assert _status_map(findings)["handoff.next_steps"] == ValidationStatus.PASS


def test_none_marker_is_case_and_space_insensitive():
    findings = validate_handoff(_good(next_steps=["  None  "]))
    assert _status_map(findings)["handoff.next_steps"] == ValidationStatus.PASS


def test_none_alongside_real_steps_warns():
    findings = validate_handoff(_good(next_steps=["SYN_step one", "none"]))
    status = _status_map(findings)
    assert status["handoff.next_steps"] == ValidationStatus.PASS
    assert status["handoff.next_steps_none"] == ValidationStatus.WARN


def test_blank_next_step_only_is_fail():
    findings = validate_handoff(_good(next_steps=["   "]))
    assert _status_map(findings)["handoff.next_steps"] == ValidationStatus.FAIL


def test_real_next_steps_pass():
    findings = validate_handoff(_good(next_steps=["SYN_step one", "SYN_step two"]))
    assert _status_map(findings)["handoff.next_steps"] == ValidationStatus.PASS


def test_good_handoff_has_no_fail_findings():
    findings = validate_handoff(_good())
    assert all(f.status != ValidationStatus.FAIL for f in findings)


def test_tampered_body_fails_digest_check():
    h = _good()
    h["next_steps"] = ["SYN_changed step"]
    findings = validate_handoff(h)
    assert _status_map(findings)["handoff.digest"] == ValidationStatus.FAIL


def test_missing_digest_fails_digest_check():
    h = _good()
    del h["digest"]
    findings = validate_handoff(h)
    assert _status_map(findings)["handoff.digest"] == ValidationStatus.FAIL


def test_missing_state_digest_fails():
    h = _good()
    h["state_digest"] = ""
    findings = validate_handoff(h)
    assert _status_map(findings)["handoff.state_digest"] == ValidationStatus.FAIL


def test_next_steps_not_a_list_fails():
    h = _good()
    h["next_steps"] = "SYN_step one"
    findings = validate_handoff(h)
    assert _status_map(findings)["handoff.next_steps"] == ValidationStatus.FAIL


def test_digest_changes_when_next_steps_change():
    assert _good(next_steps=["SYN_a"])["digest"] != _good(next_steps=["SYN_b"])["digest"]


def test_digest_changes_when_state_changes():
    a = _good(state=_state("SYN_v1"))
    b = _good(state=_state("SYN_v2"))
    assert a["state_digest"] != b["state_digest"]
    assert a["digest"] != b["digest"]


def test_digest_ignores_input_list_mutation_after_build():
    items = ["SYN_step one"]
    h = _good(next_steps=items)
    items.append("SYN_late step")
    assert validate_handoff(h)[-1].status == ValidationStatus.PASS
    assert h["next_steps"] == ["SYN_step one"]


def test_build_rejects_str_for_next_steps():
    with pytest.raises(AsOfError):
        _good(next_steps="SYN_step one")


def test_build_rejects_non_str_entries():
    with pytest.raises(AsOfError):
        _good(open_items=[42])


def test_build_rejects_non_manifest_state():
    with pytest.raises(AsOfError):
        _good(state={"digest": "x"})


def test_build_rejects_empty_title():
    with pytest.raises(AsOfError):
        _good(title="   ")


def test_build_records_format_and_version():
    h = _good()
    assert h["format"] == HANDOFF_FORMAT
    assert h["version"] == HANDOFF_VERSION


def test_render_shows_none_when_open_items_empty():
    h = _good(open_items=[], next_steps=["SYN_step one"])
    text = render_handoff(h)
    assert "Open items:\n- none" in text


def test_render_lists_open_items_and_steps():
    h = _good(open_items=["SYN_open a"], next_steps=["SYN_step b"])
    text = render_handoff(h)
    assert "- SYN_open a" in text
    assert "- SYN_step b" in text
    assert "Owner role: SYN_reviewer" in text
    assert "Handoff digest: %s" % h["digest"] in text


def test_validate_does_not_mutate_input():
    h = _good()
    snapshot = copy.deepcopy(h)
    validate_handoff(h)
    assert h == snapshot
