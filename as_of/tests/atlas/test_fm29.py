"""Failure mode fm29: catch-up packet arrives late.

A missed scheduled run is executed later as a catch-up run, and its late output
is consumed as if it were on time. Detection is to compare scheduled and actual
run times, and to label catch-up output as a late-run failure so it is not
treated as on time.

Fixtures use the SYN_ prefix and fixed UTC datetimes. Nothing here reads a
clock, a file or a network resource.

What the repo has today:
  - run_timeliness.classify_runs marks a run that lands after slot + grace as
    LATE, and late_or_missed_findings turns it into a WARN 'run_late' finding.
    A slot with no assignable run is MISSED and gives a FAIL 'run_missed'.
  - readiness_record.build_readiness blocks on FAIL findings and open incidents.
    It does not block on WARN findings.

Gaps, marked xfail (strict):
  - run_timeliness matches by timestamp only. A catch-up run carries no slot
    identity, so a catch-up for a missed slot that lands inside the next slot's
    grace window is claimed by the next slot and reported ON_TIME. Nothing
    labels it as catch-up output.
  - A LATE row is only a WARN. build_readiness returns go=True when the only
    problem is a late run, so late output can still flow into a go decision.
"""

from datetime import datetime, timezone

import pytest

from as_of.core import Finding, ReadinessItem, RunStatus, ValidationStatus
from as_of.readiness_record import build_readiness
from as_of.run_timeliness import (
    ScheduleContract,
    classify_runs,
    handling_action,
    late_or_missed_findings,
)

SYN_GRACE_MINUTES = 15


def _utc(day, hour, minute=0):
    return datetime(2026, 1, day, hour, minute, tzinfo=timezone.utc)


def _contract():
    return ScheduleContract(name="SYN_daily_packet", grace_minutes=SYN_GRACE_MINUTES)


def _slots():
    # Daily synthetic slots at 09:00 UTC for three days.
    return [_utc(1, 9), _utc(2, 9), _utc(3, 9)]


def _by_slot(rows):
    return {row["slot"]: row for row in rows}


def _fails(findings):
    return [f for f in findings if f.status == ValidationStatus.FAIL]


def _warns(findings):
    return [f for f in findings if f.status == ValidationStatus.WARN]


def test_planted_catch_up_after_grace_is_labelled_late_not_on_time():
    """Planted: Jan 2 run is missed on time and redone at 14:00 the same day.

    The catch-up output must be reported as LATE, with a WARN 'run_late'
    finding and the rerun_and_log handling action.
    """
    actual = [_utc(1, 9, 2), _utc(2, 14, 0), _utc(3, 9, 1)]
    rows = classify_runs(_contract(), _slots(), actual)
    jan2 = _by_slot(rows)[_utc(2, 9)]

    assert jan2["status"] is RunStatus.LATE
    assert jan2["actual_at"] == _utc(2, 14, 0)
    assert handling_action(jan2["status"]) == "rerun_and_log"

    findings = late_or_missed_findings(rows)
    late = [f for f in findings if f.check_id == "run_late"]
    assert len(late) == 1
    assert late[0].status == ValidationStatus.WARN
    assert late[0].subject == "2026-01-02T09:00:00Z"
    assert _fails(findings) == []


def test_planted_catch_up_that_misses_the_slot_is_detected_as_missed():
    """Planted: Jan 2 has no on-time run and its catch-up lands after the Jan 3 slot.

    The Jan 2 slot must be MISSED and give a FAIL 'run_missed' finding, so the
    gap is not hidden. The late output must not be silently attached to Jan 2.
    """
    actual = [_utc(1, 9, 2), _utc(3, 10, 30)]
    rows = classify_runs(_contract(), _slots(), actual)
    jan2 = _by_slot(rows)[_utc(2, 9)]

    assert jan2["status"] is RunStatus.MISSED
    assert jan2["actual_at"] is None
    assert handling_action(jan2["status"]) == "escalate_incident"

    fails = _fails(late_or_missed_findings(rows))
    assert [f.check_id for f in fails] == ["run_missed"]
    assert fails[0].subject == "2026-01-02T09:00:00Z"


def test_planted_missed_catch_up_blocks_readiness():
    """Planted: the same Jan 2 miss must block a go decision through readiness_record."""
    actual = [_utc(1, 9, 2), _utc(3, 10, 30)]
    rows = classify_runs(_contract(), _slots(), actual)
    findings = late_or_missed_findings(rows)
    items = [ReadinessItem(item_id="SYN_run_schedule", passed=True, evidence_ref="SYN_ev_1")]

    record = build_readiness(items, findings, open_incident_count=0)

    assert record["go"] is False
    assert any("run_missed" in reason for reason in record["blocking"])


def test_control_on_time_runs_produce_no_late_or_missed_finding():
    """Control: when every slot is met inside grace, nothing is flagged and go is True."""
    actual = [_utc(1, 9, 5), _utc(2, 9, 10), _utc(3, 9, 1)]
    rows = classify_runs(_contract(), _slots(), actual)
    assert all(row["status"] is RunStatus.ON_TIME for row in rows)

    findings = late_or_missed_findings(rows)
    assert findings == []

    items = [ReadinessItem(item_id="SYN_run_schedule", passed=True, evidence_ref="SYN_ev_1")]
    assert build_readiness(items, findings, open_incident_count=0)["go"] is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm29 gap: classify_runs matches runs by timestamp only and carries no slot "
        "identity. A catch-up for the Jan 2 slot that lands at Jan 3 09:05 falls inside "
        "the Jan 3 grace window, so the Jan 3 slot claims it and reports ON_TIME. Nothing "
        "labels the run as catch-up output."
    ),
)
def test_catch_up_output_is_not_reported_on_time_for_the_next_slot():
    """Expected control: late catch-up output must not be counted as the next slot's on-time run.

    Jan 3 has no run of its own, and the only run near Jan 3 09:00 is the Jan 2
    catch-up at 09:05. That run must not produce an ON_TIME status for Jan 3.
    """
    actual = [_utc(1, 9, 2), _utc(3, 9, 5)]
    rows = _by_slot(classify_runs(_contract(), _slots(), actual))
    jan3 = rows[_utc(3, 9)]
    assert jan3["status"] is not RunStatus.ON_TIME


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm29 gap: a LATE row is only a WARN finding (run_late), and build_readiness "
        "blocks only on FAIL findings and open incidents. A late catch-up therefore "
        "does not block a go decision, so its output can still be used as if on time."
    ),
)
def test_late_catch_up_output_blocks_readiness():
    """Expected control: a late catch-up run must block a go decision until it is reviewed."""
    actual = [_utc(1, 9, 2), _utc(2, 14, 0), _utc(3, 9, 1)]
    rows = classify_runs(_contract(), _slots(), actual)
    findings = late_or_missed_findings(rows)
    items = [ReadinessItem(item_id="SYN_run_schedule", passed=True, evidence_ref="SYN_ev_1")]

    record = build_readiness(items, findings, open_incident_count=0)
    assert record["go"] is False
