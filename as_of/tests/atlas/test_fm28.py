"""Failure mode fm28: no on-time scheduled run.

Planted failure: a recurring as-of run is due every business day at 09:00 UTC.
The machine is asleep on Wednesday 2026-10-07, so no run finishes for that
slot. A catch-up run finishes later the same afternoon. The pipeline must not
record the missed slot as on time, must escalate it, and must block readiness.

All data here is synthetic. No network calls and no real scheduler are used.

Findings from the existing modules:
- schedule_contract.expected_runs builds the due slots from a cadence and a
  business-day rule. Each slot is a naive datetime, so the test attaches UTC.
- run_timeliness.classify_runs marks a slot with no finished run in its window
  as MISSED. late_or_missed_findings gives that a FAIL finding, and
  handling_action maps it to 'escalate_incident'. This is the detection path.
- A catch-up run that finishes after the grace window is LATE (WARN), not on
  time. A catch-up run that finishes after the next slot is not matched to the
  missed slot at all.
- readiness_record.build_readiness blocks go when a FAIL finding is supplied.
- Not present in any module: a heartbeat or uptime check on the machine, and a
  planner that proposes a manual rerun with a new cutoff for each MISSED slot.
  Those are written as a strict xfail with the gap stated, not faked.
"""

from datetime import date, datetime, timezone

import pytest

from as_of.core import ReadinessItem, RunStatus, ValidationStatus
from as_of import run_timeliness
from as_of.readiness_record import build_readiness
from as_of.run_timeliness import (
    ScheduleContract as TimelinessContract,
    classify_runs,
    handling_action,
    late_or_missed_findings,
)
from as_of.schedule_contract import ScheduleContract, expected_runs


def _as_utc(naive_runs):
    return [r.replace(tzinfo=timezone.utc) for r in naive_runs]


def _utc(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


def _business_day_slots():
    # Mon 2026-10-05 through Fri 2026-10-09, one slot per business day at 09:00.
    contract = ScheduleContract(
        name="SYN_FM28_DAILY_CLOSE",
        cadence="daily",
        due_time="09:00",
        grace_minutes=15,
        business_days_only=True,
    )
    return _as_utc(expected_runs(contract, date(2026, 10, 5), date(2026, 10, 9)))


def _timeliness_contract():
    return TimelinessContract(name="SYN_FM28_DAILY_CLOSE", grace_minutes=15)


def test_fixture_has_five_business_day_slots():
    slots = _business_day_slots()
    assert [s.day for s in slots] == [5, 6, 7, 8, 9]
    assert all(s.hour == 9 and s.minute == 0 for s in slots)


def test_sleep_through_a_slot_is_detected_as_missed():
    # Machine asleep on Wed 10-07, so no run finishes for that slot.
    slots = _business_day_slots()
    actual = [_utc(5, 9, 2), _utc(6, 9, 1), _utc(8, 9, 3), _utc(9, 9, 0)]

    rows = classify_runs(_timeliness_contract(), slots, actual)

    statuses = [r["status"] for r in rows]
    assert statuses == [
        RunStatus.ON_TIME,
        RunStatus.ON_TIME,
        RunStatus.MISSED,
        RunStatus.ON_TIME,
        RunStatus.ON_TIME,
    ]
    assert rows[2]["actual_at"] is None


def test_missed_slot_gets_fail_finding_and_escalation():
    slots = _business_day_slots()
    actual = [_utc(5, 9, 2), _utc(6, 9, 1), _utc(8, 9, 3), _utc(9, 9, 0)]
    rows = classify_runs(_timeliness_contract(), slots, actual)

    findings = late_or_missed_findings(rows)

    assert len(findings) == 1
    assert findings[0].check_id == "run_missed"
    assert findings[0].status is ValidationStatus.FAIL
    assert findings[0].subject.startswith("2026-10-07")
    assert handling_action(rows[2]["status"]) == "escalate_incident"


def test_missed_slot_blocks_readiness_go():
    slots = _business_day_slots()
    actual = [_utc(5, 9, 2), _utc(6, 9, 1), _utc(8, 9, 3), _utc(9, 9, 0)]
    rows = classify_runs(_timeliness_contract(), slots, actual)
    findings = late_or_missed_findings(rows)
    items = [ReadinessItem(item_id="SYN_FM28_TIMELINESS", passed=True, evidence_ref="SYN_EVIDENCE")]

    record = build_readiness(items, findings, open_incident_count=0)

    assert record["go"] is False
    assert any(reason.startswith("finding_failed: run_missed") for reason in record["blocking"])


def test_catch_up_run_after_next_slot_does_not_fill_the_missed_slot():
    # The machine wakes on Thu 10-08 at 14:00. That run is after Thursday's own
    # slot, so it cannot be claimed by Wednesday's slot. Wednesday stays MISSED.
    slots = _business_day_slots()
    actual = [_utc(5, 9, 2), _utc(6, 9, 1), _utc(8, 9, 3), _utc(8, 14, 0), _utc(9, 9, 0)]

    rows = classify_runs(_timeliness_contract(), slots, actual)

    assert rows[2]["status"] is RunStatus.MISSED
    assert rows[2]["actual_at"] is None
    assert rows[3]["status"] is RunStatus.ON_TIME
    assert rows[3]["actual_at"] == _utc(8, 9, 3)


def test_late_catch_up_on_the_missed_day_is_late_not_on_time():
    # Machine wakes on Wed 10-07 at 16:00. Still inside Wednesday's bracket,
    # so it is claimed as LATE. It must never be reported as on time.
    slots = _business_day_slots()
    actual = [_utc(5, 9, 2), _utc(6, 9, 1), _utc(7, 16, 0), _utc(8, 9, 3), _utc(9, 9, 0)]

    rows = classify_runs(_timeliness_contract(), slots, actual)

    assert rows[2]["status"] is RunStatus.LATE
    assert rows[2]["actual_at"] == _utc(7, 16, 0)
    findings = late_or_missed_findings(rows)
    assert [f.check_id for f in findings] == ["run_late"]
    assert findings[0].status is ValidationStatus.WARN
    assert handling_action(rows[2]["status"]) == "rerun_and_log"


def test_healthy_week_gives_no_findings_and_go_is_not_blocked_by_timeliness():
    slots = _business_day_slots()
    actual = [_utc(5, 9, 2), _utc(6, 9, 1), _utc(7, 9, 4), _utc(8, 9, 3), _utc(9, 9, 0)]

    rows = classify_runs(_timeliness_contract(), slots, actual)

    assert all(r["status"] is RunStatus.ON_TIME for r in rows)
    assert late_or_missed_findings(rows) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Gap: no module checks machine uptime or heartbeat, and no module plans a "
        "manual rerun with a new cutoff for a MISSED slot. run_timeliness only "
        "detects and escalates after the fact."
    ),
)
def test_planner_proposes_manual_rerun_with_new_cutoff_for_missed_slot():
    assert hasattr(run_timeliness, "plan_rerun_for_missed"), (
        "no rerun planner exists in run_timeliness"
    )
