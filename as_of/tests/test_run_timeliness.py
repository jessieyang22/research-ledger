"""Tests for as_of.run_timeliness.

Synthetic timestamps only.
"""

from datetime import datetime, timedelta, timezone

import pytest

from as_of.core import AsOfError, RunStatus, ValidationStatus
from as_of.run_timeliness import (
    ScheduleContract,
    classify_runs,
    handling_action,
    late_or_missed_findings,
)


def _utc(hour, minute=0, day=1):
    return datetime(2026, 1, day, hour, minute, tzinfo=timezone.utc)


def _contract(grace_minutes=15, name="synthetic_close"):
    return ScheduleContract(name=name, grace_minutes=grace_minutes)


# Acceptance tests


def test_a_run_inside_the_grace_window_is_on_time():
    slot = _utc(9, 0)
    rows = classify_runs(_contract(grace_minutes=15), [slot], [_utc(9, 10)])
    assert len(rows) == 1
    assert rows[0]["status"] is RunStatus.ON_TIME
    assert rows[0]["actual_at"] == _utc(9, 10)


def test_a_run_after_the_grace_window_is_late():
    slot = _utc(9, 0)
    rows = classify_runs(_contract(grace_minutes=15), [slot], [_utc(9, 16)])
    assert len(rows) == 1
    assert rows[0]["status"] is RunStatus.LATE
    assert rows[0]["actual_at"] == _utc(9, 16)


def test_an_expected_slot_with_no_run_is_missed_and_gives_a_fail_finding():
    slot = _utc(9, 0)
    rows = classify_runs(_contract(), [slot], [])
    assert len(rows) == 1
    assert rows[0]["status"] is RunStatus.MISSED
    assert rows[0]["actual_at"] is None

    findings = late_or_missed_findings(rows)
    assert len(findings) == 1
    assert findings[0].check_id == "run_missed"
    assert findings[0].status is ValidationStatus.FAIL
    assert findings[0].subject == "2026-01-01T09:00:00Z"


def test_one_actual_run_is_never_matched_to_two_slots():
    # Two slots sit 30 minutes apart. One run at 09:10 is closest to the
    # first slot, but it must not also count for the second one.
    slots = [_utc(9, 0), _utc(9, 30)]
    rows = classify_runs(_contract(grace_minutes=15), slots, [_utc(9, 10)])
    assert [r["status"] for r in rows] == [RunStatus.ON_TIME, RunStatus.MISSED]
    matched = [r["actual_at"] for r in rows if r["actual_at"] is not None]
    assert matched == [_utc(9, 10)]


def test_two_runs_are_given_to_two_slots_without_reuse():
    # Both runs are earlier than the second slot, so each slot can use one.
    # The slots must end up with two different runs, not the same run twice.
    slots = [_utc(9, 0), _utc(9, 30)]
    runs = [_utc(9, 5), _utc(9, 8)]
    rows = classify_runs(_contract(grace_minutes=15), slots, runs)
    matched = [r["actual_at"] for r in rows if r["actual_at"] is not None]
    assert len(matched) == 2
    assert len(set(matched)) == 2
    assert set(matched) == {_utc(9, 5), _utc(9, 8)}


# Edge cases


def test_run_exactly_at_grace_boundary_is_on_time():
    rows = classify_runs(_contract(grace_minutes=15), [_utc(9, 0)], [_utc(9, 15)])
    assert rows[0]["status"] is RunStatus.ON_TIME


def test_run_one_second_past_grace_boundary_is_late():
    late_at = _utc(9, 15) + timedelta(seconds=1)
    rows = classify_runs(_contract(grace_minutes=15), [_utc(9, 0)], [late_at])
    assert rows[0]["status"] is RunStatus.LATE


def test_zero_grace_treats_only_the_slot_instant_or_earlier_as_on_time():
    on_time = classify_runs(_contract(grace_minutes=0), [_utc(9, 0)], [_utc(9, 0)])
    late = classify_runs(_contract(grace_minutes=0), [_utc(9, 0)], [_utc(9, 1)])
    assert on_time[0]["status"] is RunStatus.ON_TIME
    assert late[0]["status"] is RunStatus.LATE


def test_run_finishing_before_its_slot_is_on_time():
    rows = classify_runs(_contract(), [_utc(9, 0)], [_utc(8, 55)])
    assert rows[0]["status"] is RunStatus.ON_TIME
    assert rows[0]["actual_at"] == _utc(8, 55)


def test_no_expected_slots_gives_no_rows_even_with_extra_runs():
    assert classify_runs(_contract(), [], [_utc(9, 0)]) == []


def test_extra_run_with_no_slot_produces_no_row_and_no_finding():
    rows = classify_runs(_contract(), [_utc(9, 0)], [_utc(9, 2), _utc(14, 0)])
    assert len(rows) == 1
    assert rows[0]["status"] is RunStatus.ON_TIME
    assert late_or_missed_findings(rows) == []


def test_slots_are_returned_in_ascending_order_even_if_given_unsorted():
    slots = [_utc(11, 0), _utc(9, 0), _utc(10, 0)]
    runs = [_utc(9, 1), _utc(10, 1), _utc(11, 1)]
    rows = classify_runs(_contract(), slots, runs)
    assert [r["slot"] for r in rows] == [_utc(9, 0), _utc(10, 0), _utc(11, 0)]
    assert all(r["status"] is RunStatus.ON_TIME for r in rows)


def test_late_run_for_slot_n_is_not_stolen_by_slot_n_minus_one():
    # Slot 1 has its own run at 09:01. Slot 2 finishes late at 10:40. The
    # late run must be assigned to slot 2, not counted against slot 1.
    slots = [_utc(9, 0), _utc(10, 0)]
    runs = [_utc(9, 1), _utc(10, 40)]
    rows = classify_runs(_contract(grace_minutes=15), slots, runs)
    assert rows[0]["status"] is RunStatus.ON_TIME
    assert rows[0]["actual_at"] == _utc(9, 1)
    assert rows[1]["status"] is RunStatus.LATE
    assert rows[1]["actual_at"] == _utc(10, 40)


def test_run_at_next_slot_time_is_not_claimed_by_earlier_slot():
    slots = [_utc(9, 0), _utc(10, 0)]
    rows = classify_runs(_contract(grace_minutes=60), slots, [_utc(10, 0)])
    assert rows[0]["status"] is RunStatus.MISSED
    assert rows[1]["status"] is RunStatus.ON_TIME


def test_multiple_missed_slots_each_get_a_fail_finding():
    slots = [_utc(9, 0), _utc(10, 0), _utc(11, 0)]
    rows = classify_runs(_contract(), slots, [_utc(10, 3)])
    statuses = [r["status"] for r in rows]
    assert statuses == [RunStatus.MISSED, RunStatus.ON_TIME, RunStatus.MISSED]
    findings = late_or_missed_findings(rows)
    assert [f.check_id for f in findings] == ["run_missed", "run_missed"]
    assert all(f.status is ValidationStatus.FAIL for f in findings)


def test_late_row_gives_a_warn_finding_and_on_time_gives_none():
    rows = classify_runs(_contract(grace_minutes=5), [_utc(9, 0)], [_utc(9, 30)])
    findings = late_or_missed_findings(rows)
    assert len(findings) == 1
    assert findings[0].check_id == "run_late"
    assert findings[0].status is ValidationStatus.WARN


def test_naive_datetime_in_slots_is_rejected():
    naive = datetime(2026, 1, 1, 9, 0)
    with pytest.raises(AsOfError):
        classify_runs(_contract(), [naive], [_utc(9, 0)])


def test_naive_datetime_in_runs_is_rejected():
    naive = datetime(2026, 1, 1, 9, 0)
    with pytest.raises(AsOfError):
        classify_runs(_contract(), [_utc(9, 0)], [naive])


def test_negative_grace_is_rejected():
    with pytest.raises(AsOfError):
        classify_runs(_contract(grace_minutes=-1), [_utc(9, 0)], [])


def test_non_integer_grace_is_rejected():
    with pytest.raises(AsOfError):
        classify_runs(_contract(grace_minutes=1.5), [_utc(9, 0)], [])


def test_handling_actions_map_each_status():
    assert handling_action(RunStatus.ON_TIME) == "none"
    assert handling_action(RunStatus.LATE) == "rerun_and_log"
    assert handling_action(RunStatus.MISSED) == "escalate_incident"


def test_handling_action_rejects_unknown_status():
    with pytest.raises(AsOfError):
        handling_action("on_time")


def test_late_or_missed_findings_rejects_non_enum_status():
    with pytest.raises(AsOfError):
        late_or_missed_findings([{"slot": _utc(9, 0), "status": "late", "actual_at": None}])
