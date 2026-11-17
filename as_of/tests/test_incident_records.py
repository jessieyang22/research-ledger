"""Tests for as_of.incident_records. All fixtures are synthetic and use the SYN_ prefix."""

import dataclasses
from datetime import date, datetime, timedelta, timezone

import pytest

from as_of.core import AsOfError, Severity, ValidationStatus
from as_of.incident_records import (
    CHECK_ROOT_CAUSE,
    CHECK_SORTED,
    CHECK_STATUS,
    CHECK_TIMELINE,
    STATUS_CLOSED,
    STATUS_OPEN,
    add_timeline_event,
    close_incident,
    open_incident,
    validate_incident,
)


OPENED = date(2026, 1, 5)


def _open(severity=Severity.WARN):
    return open_incident("SYN_INC_1", "synthetic feed delay", severity, OPENED)


def _at(hour, minute=0, day=5):
    return datetime(2026, 1, day, hour, minute, tzinfo=timezone.utc)


def _status_map(findings):
    return {f.check_id: f.status for f in findings}


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------

def test_closing_with_empty_root_cause_raises():
    rec = add_timeline_event(_open(), _at(9), "SYN feed stalled")
    with pytest.raises(AsOfError):
        close_incident(rec, date(2026, 1, 6), "")


def test_add_timeline_event_keeps_timeline_sorted():
    rec = _open()
    rec = add_timeline_event(rec, _at(12), "SYN later event")
    rec = add_timeline_event(rec, _at(8), "SYN earliest event")
    rec = add_timeline_event(rec, _at(10), "SYN middle event")
    times = [event[0] for event in rec.timeline]
    assert times == sorted(times)
    assert [event[1] for event in rec.timeline] == [
        "SYN earliest event",
        "SYN middle event",
        "SYN later event",
    ]


def test_block_incident_with_empty_timeline_is_fail_finding():
    findings = validate_incident(_open(Severity.BLOCK))
    timeline = [f for f in findings if f.check_id == CHECK_TIMELINE][0]
    assert timeline.status == ValidationStatus.FAIL
    assert timeline.subject == "SYN_INC_1"


def test_close_incident_sets_status_closed():
    rec = add_timeline_event(_open(), _at(9), "SYN feed stalled")
    closed = close_incident(rec, date(2026, 1, 6), "SYN vendor outage")
    assert closed.status == STATUS_CLOSED
    assert closed.root_cause == "SYN vendor outage"


# ---------------------------------------------------------------------------
# Edge cases: open_incident
# ---------------------------------------------------------------------------

def test_open_incident_starts_open_with_no_timeline_or_root_cause():
    rec = _open()
    assert rec.status == STATUS_OPEN
    assert rec.timeline == ()
    assert rec.root_cause is None


@pytest.mark.parametrize("bad_id", ["", "   "])
def test_open_incident_rejects_blank_id(bad_id):
    with pytest.raises(AsOfError):
        open_incident(bad_id, "SYN summary", Severity.INFO, OPENED)


def test_open_incident_rejects_blank_summary():
    with pytest.raises(AsOfError):
        open_incident("SYN_INC_1", "  ", Severity.INFO, OPENED)


def test_open_incident_rejects_non_severity():
    with pytest.raises(AsOfError):
        open_incident("SYN_INC_1", "SYN summary", "block", OPENED)


def test_open_incident_rejects_datetime_as_opened_on():
    with pytest.raises(AsOfError):
        open_incident("SYN_INC_1", "SYN summary", Severity.INFO, datetime(2026, 1, 5, 9))


# ---------------------------------------------------------------------------
# Edge cases: add_timeline_event
# ---------------------------------------------------------------------------

def test_add_timeline_event_converts_to_utc():
    eastern = datetime(2026, 1, 5, 4, 0, tzinfo=timezone(timedelta(hours=-5)))
    rec = add_timeline_event(_open(), eastern, "SYN event")
    stored_at = rec.timeline[0][0]
    assert stored_at.utcoffset().total_seconds() == 0
    assert stored_at == datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)


def test_add_timeline_event_rejects_naive_datetime():
    with pytest.raises(AsOfError):
        add_timeline_event(_open(), datetime(2026, 1, 5, 9, 0), "SYN event")


def test_add_timeline_event_rejects_blank_text():
    with pytest.raises(AsOfError):
        add_timeline_event(_open(), _at(9), "   ")


def test_add_timeline_event_equal_timestamps_keep_insertion_order():
    rec = _open()
    rec = add_timeline_event(rec, _at(9), "SYN first")
    rec = add_timeline_event(rec, _at(9), "SYN second")
    assert [event[1] for event in rec.timeline] == ["SYN first", "SYN second"]


def test_add_timeline_event_does_not_mutate_input():
    rec = _open()
    add_timeline_event(rec, _at(9), "SYN event")
    assert rec.timeline == ()


# ---------------------------------------------------------------------------
# Edge cases: close_incident
# ---------------------------------------------------------------------------

def test_close_incident_rejects_whitespace_root_cause():
    rec = add_timeline_event(_open(), _at(9), "SYN event")
    with pytest.raises(AsOfError):
        close_incident(rec, date(2026, 1, 6), "   ")


def test_close_incident_rejects_empty_timeline():
    with pytest.raises(AsOfError):
        close_incident(_open(), date(2026, 1, 6), "SYN root cause")


def test_close_incident_rejects_closed_on_before_opened_on():
    rec = add_timeline_event(_open(), _at(9), "SYN event")
    with pytest.raises(AsOfError):
        close_incident(rec, date(2026, 1, 4), "SYN root cause")


def test_close_incident_accepts_closed_on_same_day_as_opened():
    rec = add_timeline_event(_open(), _at(9), "SYN event")
    closed = close_incident(rec, OPENED, "SYN root cause")
    assert closed.status == STATUS_CLOSED


def test_close_incident_rejects_datetime_as_closed_on():
    rec = add_timeline_event(_open(), _at(9), "SYN event")
    with pytest.raises(AsOfError):
        close_incident(rec, datetime(2026, 1, 6, 9), "SYN root cause")


def test_close_incident_does_not_mutate_input():
    rec = add_timeline_event(_open(), _at(9), "SYN event")
    close_incident(rec, date(2026, 1, 6), "SYN root cause")
    assert rec.status == STATUS_OPEN
    assert rec.root_cause is None


# ---------------------------------------------------------------------------
# Edge cases: validate_incident
# ---------------------------------------------------------------------------

def test_non_block_incident_with_empty_timeline_is_warn():
    findings = validate_incident(_open(Severity.WARN))
    assert _status_map(findings)[CHECK_TIMELINE] == ValidationStatus.WARN


def test_block_incident_with_timeline_passes_presence_check():
    rec = add_timeline_event(_open(Severity.BLOCK), _at(9), "SYN event")
    assert _status_map(validate_incident(rec))[CHECK_TIMELINE] == ValidationStatus.PASS


def test_unsorted_timeline_is_fail_finding():
    rec = _open()
    rec = add_timeline_event(rec, _at(9), "SYN first")
    rec = add_timeline_event(rec, _at(10), "SYN second")
    # The public API keeps order, so build an out-of-order record directly.
    unsorted = dataclasses.replace(rec, timeline=tuple(reversed(rec.timeline)))
    assert _status_map(validate_incident(unsorted))[CHECK_SORTED] == ValidationStatus.FAIL


def test_sorted_timeline_passes_sorted_check():
    rec = add_timeline_event(_open(), _at(9), "SYN first")
    rec = add_timeline_event(rec, _at(10), "SYN second")
    assert _status_map(validate_incident(rec))[CHECK_SORTED] == ValidationStatus.PASS


def test_closed_incident_without_root_cause_is_fail():
    rec = add_timeline_event(_open(), _at(9), "SYN event")
    closed_no_cause = dataclasses.replace(rec, status=STATUS_CLOSED, root_cause=None)
    assert _status_map(validate_incident(closed_no_cause))[CHECK_ROOT_CAUSE] == ValidationStatus.FAIL


def test_closed_incident_with_blank_root_cause_is_fail():
    rec = add_timeline_event(_open(), _at(9), "SYN event")
    closed_blank = dataclasses.replace(rec, status=STATUS_CLOSED, root_cause="   ")
    assert _status_map(validate_incident(closed_blank))[CHECK_ROOT_CAUSE] == ValidationStatus.FAIL


def test_closed_incident_with_empty_timeline_is_status_fail():
    rec = _open()
    closed_no_timeline = dataclasses.replace(rec, status=STATUS_CLOSED, root_cause="SYN cause")
    assert _status_map(validate_incident(closed_no_timeline))[CHECK_STATUS] == ValidationStatus.FAIL


def test_unknown_status_is_fail():
    rec = add_timeline_event(_open(), _at(9), "SYN event")
    bad = dataclasses.replace(rec, status="archived")
    assert _status_map(validate_incident(bad))[CHECK_STATUS] == ValidationStatus.FAIL


def test_valid_closed_incident_passes_all_checks():
    rec = add_timeline_event(_open(), _at(9), "SYN event")
    closed = close_incident(rec, date(2026, 1, 6), "SYN root cause")
    statuses = _status_map(validate_incident(closed))
    assert set(statuses.values()) == {ValidationStatus.PASS}


def test_validate_returns_one_finding_per_check():
    findings = validate_incident(_open())
    assert len(findings) == 4
    assert {f.check_id for f in findings} == {
        CHECK_TIMELINE, CHECK_SORTED, CHECK_ROOT_CAUSE, CHECK_STATUS,
    }
