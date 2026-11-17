"""Failure mode fm37: a model assigns materiality, or a human field is auto-filled.

A materiality judgment or a reviewer field is filled automatically, so no
person made the decision. The expected detection is to inspect the exception
record and the sign-off, and to clear an auto-filled field and assign it to a
named reviewer.

Fixtures use the SYN_ prefix.

Findings from reading the package:

* No module scores materiality. filing_monitor and exception_vocabulary keep
  filing occurrences at INFO and say that significance belongs to a person.
  Those tests pass.
* ExceptionRecord has no reviewer, assignee or signed-by field, so an exception
  cannot show who reviewed it. That is a gap. The test is a strict xfail.
* readiness_record treats any item with passed=True as a pass, whatever its
  evidence_ref says. A sign-off item filled in automatically therefore clears
  the go/no-go gate. That is a gap. The test is a strict xfail.
* handoff.validate_handoff only checks that owner_role is a non-empty string,
  so a placeholder such as "auto" passes. That is a gap. The test is a strict
  xfail.
* exception_queue.open takes the vocabulary default severity when none is
  given. That default is a fixed rule, not a materiality judgment, but nothing
  records that it was set automatically. Covered by the ExceptionRecord gap.
"""

import dataclasses
from datetime import datetime, timezone

import pytest

from as_of import exception_vocabulary, filing_monitor, handoff, readiness_record
from as_of.core import ExceptionRecord, ReadinessItem, Severity, ValidationStatus
from as_of.exception_queue import ExceptionQueue
from as_of.exception_vocabulary import ExceptionKind
from as_of.state_manifest import StateManifest

PLANTED_SUBJECT = "SYN_FM37_POSITION"
PLANTED_AUTO_REVIEWER = "auto:model-filled"
PLANTED_AUTO_OWNER = "auto"
OPENED_AT = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def _planted_exception(queue: ExceptionQueue):
    """Open a synthetic exception with no severity given, so the default is applied."""
    return queue.open(ExceptionKind.MISSING_PRICE, PLANTED_SUBJECT, OPENED_AT)


def _signoff_item(evidence_ref: str) -> ReadinessItem:
    """A synthetic sign-off item for the reviewed-packet control."""
    return ReadinessItem(item_id="ctl_pm_packet_reviewed", passed=True, evidence_ref=evidence_ref)


def _state() -> StateManifest:
    return StateManifest()


# ---------------------------------------------------------------------------
# Detection that exists today (these pass)
# ---------------------------------------------------------------------------


def test_no_module_exposes_a_materiality_scorer():
    """Detected: none of the exception and sign-off modules has a materiality or significance function."""
    modules = (filing_monitor, exception_vocabulary, readiness_record, handoff)
    for mod in modules:
        names = [n.lower() for n in dir(mod) if not n.startswith("_")]
        assert not any("materi" in n or "significan" in n for n in names), mod.__name__


def test_filing_occurrence_is_info_and_not_scored_as_material():
    """Detected: a planted filing exception defaults to INFO, so no materiality is implied."""
    queue = ExceptionQueue()
    rec = queue.open(ExceptionKind.FILING_OCCURRED, PLANTED_SUBJECT, OPENED_AT)
    assert rec.severity == Severity.INFO


def test_unsigned_packet_item_blocks_readiness():
    """Detected: a sign-off item that did not pass blocks the go/no-go record."""
    item = ReadinessItem(item_id="ctl_pm_packet_reviewed", passed=False, evidence_ref="SYN_EVIDENCE_1")
    rec = readiness_record.build_readiness([item], [], 0)
    assert rec["go"] is False
    assert any("ctl_pm_packet_reviewed" in reason for reason in rec["blocking"])


def test_handoff_with_no_owner_is_flagged():
    """Detected: an empty owner_role produces a FAIL finding, so the handoff cannot pass unowned."""
    h = handoff.build_handoff("SYN_FM37_HANDOFF", _state(), [], ["SYN_NEXT"], "")
    findings = handoff.validate_handoff(h)
    owner = [f for f in findings if f.check_id == "handoff.owner_role"]
    assert owner and owner[0].status == ValidationStatus.FAIL


def test_default_severity_comes_from_the_fixed_vocabulary():
    """Documents the source of the default: the vocabulary, not a model judgment."""
    queue = ExceptionQueue()
    rec = _planted_exception(queue)
    assert rec.severity == exception_vocabulary.default_severity(ExceptionKind.MISSING_PRICE)


# ---------------------------------------------------------------------------
# Documented gaps: current behavior accepts the auto-filled field (these pass)
# ---------------------------------------------------------------------------


def test_exception_record_has_no_reviewer_field_today():
    """Documents the gap: ExceptionRecord cannot name who reviewed or signed off an exception."""
    names = [f.name for f in dataclasses.fields(ExceptionRecord)]
    assert not any(n in ("reviewer", "assignee", "signed_by", "approver") for n in names)


def test_planted_auto_signoff_passes_readiness_today():
    """Documents the live failure: an auto-filled sign-off counts as a pass."""
    rec = readiness_record.build_readiness([_signoff_item(PLANTED_AUTO_REVIEWER)], [], 0)
    assert rec["go"] is True
    assert rec["blocking"] == []


def test_planted_auto_owner_passes_handoff_today():
    """Documents the live failure: a placeholder owner string is accepted as an owner."""
    h = handoff.build_handoff("SYN_FM37_HANDOFF", _state(), [], ["SYN_NEXT"], PLANTED_AUTO_OWNER)
    findings = handoff.validate_handoff(h)
    owner = [f for f in findings if f.check_id == "handoff.owner_role"]
    assert owner and owner[0].status == ValidationStatus.PASS


# ---------------------------------------------------------------------------
# Expected controls that do not exist yet (strict xfail, reported as gaps)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm37 gap: ExceptionRecord has no reviewer field, so an exception cannot "
        "name a human reviewer, and an auto-filled reviewer cannot be cleared."
    ),
)
def test_exception_record_requires_a_named_reviewer():
    """Expected control: the exception record carries a reviewer field."""
    names = [f.name for f in dataclasses.fields(ExceptionRecord)]
    assert "reviewer" in names


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm37 gap: readiness_record trusts passed=True and does not inspect "
        "evidence_ref, so an auto-filled sign-off clears the go/no-go gate."
    ),
)
def test_auto_filled_signoff_blocks_readiness():
    """Expected control: a sign-off whose evidence is auto-filled blocks readiness."""
    rec = readiness_record.build_readiness([_signoff_item(PLANTED_AUTO_REVIEWER)], [], 0)
    assert rec["go"] is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm37 gap: validate_handoff checks only that owner_role is non-empty, "
        "so a placeholder owner passes and is not assigned to a named reviewer."
    ),
)
def test_auto_owner_role_is_flagged():
    """Expected control: a placeholder owner_role yields a FAIL finding."""
    h = handoff.build_handoff("SYN_FM37_HANDOFF", _state(), [], ["SYN_NEXT"], PLANTED_AUTO_OWNER)
    findings = handoff.validate_handoff(h)
    owner = [f for f in findings if f.check_id == "handoff.owner_role"]
    assert owner and owner[0].status == ValidationStatus.FAIL
