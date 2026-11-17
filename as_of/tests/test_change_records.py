"""Tests for as_of.change_records. All fixtures are synthetic and use the SYN_ prefix.
"""

import dataclasses
from datetime import date

import pytest

from as_of.core import AsOfError, ChangeRecord, ValidationStatus
from as_of.change_records import (
    ALL_STATUSES,
    EVIDENCE_REQUIRED,
    LEGAL_MOVES,
    STATUS_APPLIED,
    STATUS_APPROVED,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    STATUS_VERIFIED,
    open_change,
    transition,
    validate_change,
)

OPENED = date(2026, 10, 1)
LATER = date(2026, 10, 5)


def _record(status, evidence_ref=None):
    return ChangeRecord(
        change_id="SYN_CHG_001",
        summary="SYN_summary",
        reason="SYN_reason",
        status=status,
        opened_on=OPENED,
        evidence_ref=evidence_ref,
    )


def _statuses(findings):
    return {f.check_id: f.status for f in findings}


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_proposed_to_verified_directly_raises_asof_error():
    rec = open_change("SYN_CHG_001", "SYN_summary", "SYN_reason", OPENED)
    with pytest.raises(AsOfError):
        transition(rec, STATUS_VERIFIED, LATER, evidence_ref="SYN_EV_1")


def test_applied_without_evidence_ref_is_fail_finding():
    rec = open_change("SYN_CHG_001", "SYN_summary", "SYN_reason", OPENED)
    rec = transition(rec, STATUS_APPROVED, LATER)
    applied = transition(rec, STATUS_APPLIED, LATER)  # no evidence_ref given
    assert applied.evidence_ref is None
    findings = validate_change(applied)
    evidence = [f for f in findings if f.check_id == "change.evidence"]
    assert len(evidence) == 1
    assert evidence[0].status == ValidationStatus.FAIL
    assert evidence[0].subject == "SYN_CHG_001"


def test_transition_returns_new_object_and_leaves_input_unchanged():
    rec = open_change("SYN_CHG_001", "SYN_summary", "SYN_reason", OPENED)
    snapshot = dataclasses.asdict(rec)
    nxt = transition(rec, STATUS_APPROVED, LATER)
    assert nxt is not rec
    assert nxt.status == STATUS_APPROVED
    assert rec.status == STATUS_PROPOSED
    assert dataclasses.asdict(rec) == snapshot


def test_rejected_is_reachable_only_from_proposed():
    rec = open_change("SYN_CHG_001", "SYN_summary", "SYN_reason", OPENED)
    rejected = transition(rec, STATUS_REJECTED, LATER)
    assert rejected.status == STATUS_REJECTED

    approved = transition(rec, STATUS_APPROVED, LATER)
    with pytest.raises(AsOfError):
        transition(approved, STATUS_REJECTED, LATER)

    applied = transition(approved, STATUS_APPLIED, LATER, evidence_ref="SYN_EV_1")
    with pytest.raises(AsOfError):
        transition(applied, STATUS_REJECTED, LATER)


# ---------------------------------------------------------------------------
# Status flow edge cases
# ---------------------------------------------------------------------------


def test_legal_moves_table_matches_documented_flow():
    assert LEGAL_MOVES[STATUS_PROPOSED] == frozenset({STATUS_APPROVED, STATUS_REJECTED})
    assert LEGAL_MOVES[STATUS_APPROVED] == frozenset({STATUS_APPLIED})
    assert LEGAL_MOVES[STATUS_APPLIED] == frozenset({STATUS_VERIFIED})
    assert LEGAL_MOVES[STATUS_VERIFIED] == frozenset()
    assert LEGAL_MOVES[STATUS_REJECTED] == frozenset()


def test_verified_and_rejected_are_terminal():
    verified = _record(STATUS_VERIFIED, evidence_ref="SYN_EV_1")
    for target in ALL_STATUSES:
        with pytest.raises(AsOfError):
            transition(verified, target, LATER)

    rejected = _record(STATUS_REJECTED)
    for target in ALL_STATUSES:
        with pytest.raises(AsOfError):
            transition(rejected, target, LATER)


def test_full_happy_path_reaches_verified():
    rec = open_change("SYN_CHG_001", "SYN_summary", "SYN_reason", OPENED)
    rec = transition(rec, STATUS_APPROVED, LATER)
    rec = transition(rec, STATUS_APPLIED, LATER, evidence_ref="SYN_EV_APPLY")
    rec = transition(rec, STATUS_VERIFIED, date(2026, 10, 9), evidence_ref="SYN_EV_VERIFY")
    assert rec.status == STATUS_VERIFIED
    assert rec.evidence_ref == "SYN_EV_VERIFY"


def test_unknown_target_status_raises():
    rec = open_change("SYN_CHG_001", "SYN_summary", "SYN_reason", OPENED)
    with pytest.raises(AsOfError):
        transition(rec, "merged", LATER)


def test_transition_date_before_opened_on_raises():
    rec = open_change("SYN_CHG_001", "SYN_summary", "SYN_reason", OPENED)
    with pytest.raises(AsOfError):
        transition(rec, STATUS_APPROVED, date(2026, 9, 30))


def test_transition_same_day_as_opened_is_allowed():
    rec = open_change("SYN_CHG_001", "SYN_summary", "SYN_reason", OPENED)
    assert transition(rec, STATUS_APPROVED, OPENED).status == STATUS_APPROVED


def test_transition_requires_change_record_and_date():
    rec = open_change("SYN_CHG_001", "SYN_summary", "SYN_reason", OPENED)
    with pytest.raises(AsOfError):
        transition("not a record", STATUS_APPROVED, LATER)
    with pytest.raises(AsOfError):
        transition(rec, STATUS_APPROVED, "2026-10-05")


# ---------------------------------------------------------------------------
# Evidence handling
# ---------------------------------------------------------------------------


def test_transition_without_evidence_keeps_stored_evidence():
    rec = _record(STATUS_APPROVED, evidence_ref="SYN_EV_OLD")
    applied = transition(rec, STATUS_APPLIED, LATER)
    assert applied.evidence_ref == "SYN_EV_OLD"


def test_transition_with_evidence_replaces_stored_evidence():
    rec = _record(STATUS_APPROVED, evidence_ref="SYN_EV_OLD")
    applied = transition(rec, STATUS_APPLIED, LATER, evidence_ref="SYN_EV_NEW")
    assert applied.evidence_ref == "SYN_EV_NEW"


def test_applied_with_evidence_passes():
    findings = validate_change(_record(STATUS_APPLIED, evidence_ref="SYN_EV_1"))
    statuses = _statuses(findings)
    assert statuses["change.status"] == ValidationStatus.PASS
    assert statuses["change.evidence"] == ValidationStatus.PASS


def test_verified_without_evidence_is_fail():
    findings = validate_change(_record(STATUS_VERIFIED))
    assert _statuses(findings)["change.evidence"] == ValidationStatus.FAIL


def test_whitespace_only_evidence_is_fail():
    findings = validate_change(_record(STATUS_APPLIED, evidence_ref="   "))
    assert _statuses(findings)["change.evidence"] == ValidationStatus.FAIL


def test_proposed_without_evidence_passes_evidence_check():
    findings = validate_change(_record(STATUS_PROPOSED))
    assert _statuses(findings)["change.evidence"] == ValidationStatus.PASS


def test_evidence_required_set_is_applied_and_verified():
    assert EVIDENCE_REQUIRED == frozenset({STATUS_APPLIED, STATUS_VERIFIED})


def test_unknown_status_on_record_is_fail_status_finding():
    findings = validate_change(_record("merged"))
    assert _statuses(findings)["change.status"] == ValidationStatus.FAIL


def test_validate_change_returns_two_findings_with_subject():
    findings = validate_change(_record(STATUS_PROPOSED))
    assert len(findings) == 2
    assert {f.check_id for f in findings} == {"change.status", "change.evidence"}
    assert all(f.subject == "SYN_CHG_001" for f in findings)


# ---------------------------------------------------------------------------
# open_change input checks
# ---------------------------------------------------------------------------


def test_open_change_starts_proposed_without_evidence():
    rec = open_change("SYN_CHG_002", "SYN_summary", "SYN_reason", OPENED)
    assert rec.status == STATUS_PROPOSED
    assert rec.evidence_ref is None
    assert rec.opened_on == OPENED


def test_open_change_rejects_blank_id():
    with pytest.raises(AsOfError):
        open_change("   ", "SYN_summary", "SYN_reason", OPENED)


def test_open_change_rejects_non_date_opened_on():
    with pytest.raises(AsOfError):
        open_change("SYN_CHG_002", "SYN_summary", "SYN_reason", "2026-10-01")
