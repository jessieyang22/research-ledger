"""Failure mode fm13: required clock time is blank.

Planted failure: a timestamp that the process requires (a knowledge, event,
release, ingest or report clock) is empty. Because the schema is not enforced
for that field, the blank flows downstream. The detection method is to
validate required time fields against the schema, and to mark the value
unavailable rather than filling it in when the source lacks it. All fixtures
are synthetic (SYN_ prefix); no network, no real data.

Detection points checked:
  - field_dictionary.validate_fields turns a blank non-nullable clock field
    into a FAIL finding (field.null).
  - readiness_record.build_readiness blocks go when such a FAIL finding exists.
  - estimate_ledger.EstimateLedger.append refuses a row whose knowledge_at is
    blank, so the blank never enters the ledger.
  - clock_ordering marks a blank clock as WARN and does not fill it in.
  - clock_as_of treats a blank knowledge clock as not visible, so it cannot
    be used as if it were known.

Gaps, marked xfail:
  - No module enforces the required-clock schema across a whole pipeline run
    before a proof starts. validate_fields only runs when a caller invokes it.
  - clock_ordering reports a blank clock as WARN, which does not block
    readiness. Only FAIL blocks. This is a design choice, noted here.
"""

from datetime import datetime, timezone

import pytest

from as_of.clock_as_of import known_as_of
from as_of.clock_ordering import check_clock_order
from as_of.clocks_record import make_clockset
from as_of.core import (
    AsOfError,
    EstimateRecord,
    Finding,
    ReadinessItem,
    ValidationStatus,
)
from as_of.estimate_ledger import EstimateLedger
from as_of.field_dictionary import validate_fields
from as_of.readiness_record import build_readiness


def _utc(day, hour=0):
    return datetime(2026, 10, day, hour, tzinfo=timezone.utc)


def _estimate_record(**overrides):
    # Synthetic estimate record shaped like the field dictionary expects.
    rec = {
        "ticker": "SYN_TKR",
        "source_id": "SYN_SRC_01",
        "ingest_at": _utc(5),
        "estimate_value": 1.25,
        "estimate_knowledge_at": _utc(4),
    }
    rec.update(overrides)
    return rec


def _fail_ids(findings):
    return [(f.check_id, f.subject) for f in findings if f.status is ValidationStatus.FAIL]


# Detection: schema validation flags a blank required clock field.


def test_fm13_blank_required_knowledge_clock_is_flagged_fail():
    record = _estimate_record(estimate_knowledge_at=None)
    findings = validate_fields(record, ["estimate_knowledge_at", "estimate_value", "ingest_at"])
    assert ("field.null", "estimate_knowledge_at") in _fail_ids(findings)


@pytest.mark.parametrize(
    "field",
    ["estimate_knowledge_at", "filed_at", "accepted_at", "macro_release_at", "ingest_at", "report_generated_at"],
)
def test_fm13_each_required_clock_field_blank_is_flagged(field):
    # Every non-nullable clock-governed timestamp must fail when blank.
    record = {field: None}
    findings = validate_fields(record, [field])
    assert (("field.null", field)) in _fail_ids(findings)


def test_fm13_nullable_clock_field_blank_is_not_overblocked():
    # exception_resolved_at is nullable (an open exception has no resolution
    # time). A blank there is legitimate and must not produce a FAIL.
    findings = validate_fields({"exception_resolved_at": None}, ["exception_resolved_at"])
    assert _fail_ids(findings) == []
    assert any(f.check_id == "field.null" and f.status is ValidationStatus.PASS for f in findings)


def test_fm13_complete_required_clocks_pass():
    findings = validate_fields(_estimate_record(), ["estimate_knowledge_at", "ingest_at"])
    assert _fail_ids(findings) == []


# Blocking: a FAIL from the schema check stops readiness.


def test_fm13_readiness_is_no_go_when_blank_clock_fail_present():
    record = _estimate_record(estimate_knowledge_at=None)
    findings = validate_fields(record, ["estimate_knowledge_at"])
    items = [ReadinessItem(item_id="schema_clocks", passed=True, evidence_ref="SYN_EV_01")]
    rec = build_readiness(items, findings, open_incident_count=0)
    assert rec["go"] is False
    assert any("estimate_knowledge_at" in reason for reason in rec["blocking"])


def test_fm13_readiness_is_go_when_all_required_clocks_present():
    findings = validate_fields(_estimate_record(), ["estimate_knowledge_at", "ingest_at"])
    items = [ReadinessItem(item_id="schema_clocks", passed=True, evidence_ref="SYN_EV_01")]
    rec = build_readiness(items, findings, open_incident_count=0)
    assert rec["go"] is True


# Blocking at the write path: the ledger refuses a blank knowledge time.


def test_fm13_ledger_refuses_blank_knowledge_time_instead_of_filling_it():
    ledger = EstimateLedger()
    blank = EstimateRecord(
        estimate_id="SYN_EST_01",
        ticker="SYN_TKR",
        metric="eps",
        period="2026Q3",
        analyst_id="SYN_AN_01",
        value=1.25,
        knowledge_at=None,
        source_id="SYN_SRC_01",
    )
    with pytest.raises(AsOfError):
        ledger.append(blank)


# Mark unavailable, never fill in: clock ordering and point-in-time visibility.


def test_fm13_blank_clock_is_marked_warn_and_not_filled_in():
    cs = make_clockset(event_at=_utc(1), release_at=_utc(2), ingest_at=_utc(3))
    findings = check_clock_order(cs)
    knowledge_rules = [f for f in findings if "knowledge" in f.subject]
    assert knowledge_rules, "rules touching the blank knowledge clock must still be reported"
    assert all(f.status is ValidationStatus.WARN for f in knowledge_rules)
    # The value itself is left blank rather than filled from another clock.
    assert cs.knowledge_at is None


def test_fm13_blank_knowledge_clock_is_never_visible():
    cs = make_clockset(event_at=_utc(1), release_at=_utc(2), ingest_at=_utc(3))
    assert known_as_of(cs, _utc(9)) is False


# Gap: no pipeline-level schema enforcement for required clocks.


@pytest.mark.xfail(
    strict=True,
    reason="GAP fm13: no module enforces a required-clock schema across a whole run before a proof starts",
)
def test_fm13_pipeline_rejects_run_with_blank_required_clock():
    from as_of import schema_enforcer  # noqa: F401  (does not exist; this is the gap)

    rows = [_estimate_record(estimate_knowledge_at=None)]
    findings = schema_enforcer.enforce(rows, required_clocks=["estimate_knowledge_at"])
    assert any(f.status is ValidationStatus.FAIL for f in findings)
