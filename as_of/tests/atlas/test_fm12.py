"""Failure mode fm12: fresh session cannot explain the state.

The current state depends on chat history that a new session does not have, so
the state cannot be rebuilt from saved artifacts alone. The detection procedure
is to run the handoff from saved artifacts only, with no prior conversation,
and to add any field, source or rule that the attempt shows is missing. All
fixtures are synthetic (SYN_ prefix), written to pytest's tmp_path, and no
network is used.

Detection points checked:
  - A saved state manifest can be reloaded and verified from disk. (detects, passing)
  - A handoff saved to disk can be reloaded and its digest recomputed. (detects, passing)
  - A handoff with no owner role is FAIL in handoff.validate_handoff. (detects)
  - A handoff with no next step and no explicit 'none' is FAIL. (detects)
  - A tampered handoff body fails the digest check. (detects)
  - A handoff whose state digest points at a manifest that was never saved
    (state that lived only in chat) is caught by StateManifest.verify, which
    returns False for a missing file. (detects)
  - validate_handoff does not take a manifest and does not compare the handoff's
    state_digest with a manifest on disk, so a handoff pointing at the wrong
    state passes validation. (gap, xfail)
  - No module checks that open items or next steps refer only to artifacts
    that exist on disk, so next steps such as "continue as discussed" pass.
    (gap, xfail)
"""

import json
import os

import pytest

from as_of.core import ValidationStatus
from as_of.handoff import build_handoff, validate_handoff
from as_of.state_manifest import StateManifest

SYN_OWNER = "SYN_owner_role"
SYN_STEP = "SYN_step_rerun_proof_1"


def _saved_state(tmp_path):
    """Build a small synthetic state, save it to disk, and return (manifest, path)."""
    state = StateManifest()
    state.record_step(
        "SYN_earnings_reconciliation",
        {"SYN_input": "a" * 64},
        {"SYN_output": "b" * 64},
        "SYN_v1",
    )
    path = os.path.join(str(tmp_path), "state", "manifest.json")
    state.save(path)
    return state, path


def _write_handoff(tmp_path, handoff):
    """Write a handoff dict to disk as JSON, the only thing a fresh session gets."""
    path = os.path.join(str(tmp_path), "handoff", "handoff.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(handoff, handle, sort_keys=True, indent=2)
    return path


def _load_handoff(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _fails(findings):
    return [f for f in findings if f.status is ValidationStatus.FAIL]


# Detected: the artifacts a fresh session needs can be reloaded from disk.


def test_fm12_saved_state_reloads_from_disk_with_no_chat(tmp_path):
    state, path = _saved_state(tmp_path)
    assert StateManifest.verify(path) is True
    reloaded = StateManifest.load(path)
    assert reloaded.digest() == state.digest()


def test_fm12_complete_handoff_rebuilds_from_saved_artifacts(tmp_path):
    state, manifest_path = _saved_state(tmp_path)
    handoff = build_handoff(
        title="SYN_handoff_fm12",
        state=state,
        open_items=["SYN_open_item_1"],
        next_steps=[SYN_STEP],
        owner_role=SYN_OWNER,
    )
    handoff_path = _write_handoff(tmp_path, handoff)

    # Fresh session: only files on disk. Nothing from the first session is in memory.
    fresh = _load_handoff(handoff_path)
    assert _fails(validate_handoff(fresh)) == []
    assert StateManifest.verify(manifest_path) is True
    assert fresh["state_digest"] == StateManifest.load(manifest_path).digest()


# Detected: missing fields a fresh session would need.


def test_fm12_handoff_without_owner_role_is_flagged(tmp_path):
    state, _ = _saved_state(tmp_path)
    handoff = build_handoff("SYN_handoff_fm12", state, [], [SYN_STEP], owner_role="")
    failed = {f.check_id for f in _fails(validate_handoff(handoff))}
    assert "handoff.owner_role" in failed


def test_fm12_handoff_without_next_step_is_flagged(tmp_path):
    state, _ = _saved_state(tmp_path)
    handoff = build_handoff("SYN_handoff_fm12", state, [], [], owner_role=SYN_OWNER)
    failed = {f.check_id for f in _fails(validate_handoff(handoff))}
    assert "handoff.next_steps" in failed


def test_fm12_explicit_none_next_step_is_accepted(tmp_path):
    state, _ = _saved_state(tmp_path)
    handoff = build_handoff("SYN_handoff_fm12", state, [], ["none"], owner_role=SYN_OWNER)
    assert _fails(validate_handoff(handoff)) == []


def test_fm12_tampered_handoff_body_fails_digest(tmp_path):
    state, _ = _saved_state(tmp_path)
    handoff = build_handoff("SYN_handoff_fm12", state, [], [SYN_STEP], owner_role=SYN_OWNER)
    handoff["next_steps"] = ["SYN_edited_after_save"]
    failed = {f.check_id for f in _fails(validate_handoff(handoff))}
    assert "handoff.digest" in failed


# Detected: a handoff that points at state which exists only in the first session.


def test_fm12_state_never_saved_is_not_reconstructible(tmp_path):
    """The first session built a state in memory and wrote the handoff, but never saved the manifest."""
    state = StateManifest()
    state.record_step("SYN_chat_only_step", {"SYN_in": "c" * 64}, {"SYN_out": "d" * 64}, "SYN_v1")
    handoff = build_handoff("SYN_handoff_fm12", state, [], [SYN_STEP], owner_role=SYN_OWNER)
    handoff_path = _write_handoff(tmp_path, handoff)

    # The handoff validates on its own, which is exactly why this case is dangerous.
    assert _fails(validate_handoff(_load_handoff(handoff_path))) == []

    # A fresh session looks for the manifest the handoff names and cannot find it.
    missing = os.path.join(str(tmp_path), "state", "manifest.json")
    assert StateManifest.verify(missing) is False


# Gaps: no module cross-checks a handoff against saved artifacts.


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GAP fm12: validate_handoff takes only the handoff dict. It does not load "
        "the manifest on disk and compare state_digest with it, so a handoff that "
        "points at the wrong or unsaved state passes validation."
    ),
)
def test_fm12_handoff_state_digest_must_match_saved_manifest(tmp_path):
    saved, manifest_path = _saved_state(tmp_path)
    other = StateManifest()
    other.record_step("SYN_other_step", {"SYN_in": "e" * 64}, {"SYN_out": "f" * 64}, "SYN_v1")
    handoff = build_handoff("SYN_handoff_fm12", other, [], [SYN_STEP], owner_role=SYN_OWNER)
    # Desired behaviour: a cross-check against the saved manifest produces a FAIL.
    failed = {f.check_id for f in _fails(validate_handoff(handoff))}
    assert "handoff.state_digest_matches_manifest" in failed


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GAP fm12: no module checks that next steps or open items refer only to "
        "artifacts saved on disk. A step such as 'continue as discussed' passes."
    ),
)
def test_fm12_next_step_must_reference_saved_artifact(tmp_path):
    state, _ = _saved_state(tmp_path)
    handoff = build_handoff(
        "SYN_handoff_fm12", state, [], ["continue as discussed"], owner_role=SYN_OWNER
    )
    failed = {f.check_id for f in _fails(validate_handoff(handoff))}
    assert "handoff.next_steps_reference" in failed
