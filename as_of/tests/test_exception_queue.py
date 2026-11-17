"""Tests for as_of.exception_queue. All fixtures are synthetic (SYN_ prefix)."""

from datetime import datetime, timedelta, timezone

import pytest

from as_of.core import AsOfError, Severity
from as_of.exception_queue import ExceptionQueue

T0 = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)
T2 = T0 + timedelta(hours=2)


def test_open_same_kind_subject_and_time_twice_leaves_one_item():
    q = ExceptionQueue()
    first = q.open("CATALYST_NO_DATE", "SYN_CAT_001", T0, note="first", severity=Severity.WARN)
    second = q.open("CATALYST_NO_DATE", "SYN_CAT_001", T0, note="ignored", severity=Severity.BLOCK)

    assert first.exception_id == second.exception_id
    assert second == first  # existing record is returned unchanged
    assert len(q.open_items()) == 1
    assert q.counts() == {"open": 1, "resolved": 0, "total": 1}


def test_open_same_time_in_other_timezone_is_still_one_item():
    q = ExceptionQueue()
    utc_rec = q.open("SOURCE_CHANGED", "SYN_SRC_9", T0)
    offset = timezone(timedelta(hours=-5))
    same_instant = T0.astimezone(offset)
    again = q.open("SOURCE_CHANGED", "SYN_SRC_9", same_instant)

    assert again.exception_id == utc_rec.exception_id
    assert q.counts()["total"] == 1


def test_open_distinct_triples_make_distinct_items():
    q = ExceptionQueue()
    a = q.open("KIND_A", "SYN_1", T0)
    b = q.open("KIND_B", "SYN_1", T0)  # different kind
    c = q.open("KIND_A", "SYN_2", T0)  # different subject
    d = q.open("KIND_A", "SYN_1", T1)  # different time

    assert len({a.exception_id, b.exception_id, c.exception_id, d.exception_id}) == 4
    assert q.counts() == {"open": 4, "resolved": 0, "total": 4}


def test_open_defaults_severity_to_info():
    q = ExceptionQueue()
    rec = q.open("KIND_A", "SYN_1", T0)
    assert rec.severity is Severity.INFO
    assert rec.resolved_at is None
    assert rec.note == ""


def test_open_rejects_bad_arguments():
    q = ExceptionQueue()
    with pytest.raises(AsOfError):
        q.open("", "SYN_1", T0)
    with pytest.raises(AsOfError):
        q.open("KIND_A", "", T0)
    with pytest.raises(AsOfError):
        q.open("KIND_A", "SYN_1", T0, severity="warn")  # not a Severity
    with pytest.raises(AsOfError):
        q.open("KIND_A", "SYN_1", datetime(2026, 1, 5, 9, 0, 0))  # naive datetime
    assert q.counts() == {"open": 0, "resolved": 0, "total": 0}


def test_prioritized_lists_block_before_warn_before_info():
    q = ExceptionQueue()
    q.open("K", "SYN_INFO", T0, severity=Severity.INFO)
    q.open("K", "SYN_BLOCK", T2, severity=Severity.BLOCK)
    q.open("K", "SYN_WARN", T1, severity=Severity.WARN)

    ordered = [r.severity for r in q.prioritized()]
    assert ordered == [Severity.BLOCK, Severity.WARN, Severity.INFO]


def test_prioritized_is_oldest_first_within_a_severity():
    q = ExceptionQueue()
    q.open("K", "SYN_NEW", T2, severity=Severity.WARN)
    q.open("K", "SYN_OLD", T0, severity=Severity.WARN)
    q.open("K", "SYN_MID", T1, severity=Severity.WARN)

    assert [r.subject_id for r in q.prioritized()] == ["SYN_OLD", "SYN_MID", "SYN_NEW"]


def test_prioritized_excludes_resolved_items():
    q = ExceptionQueue()
    blk = q.open("K", "SYN_BLOCK", T0, severity=Severity.BLOCK)
    q.open("K", "SYN_INFO", T0, severity=Severity.INFO)
    q.resolve(blk.exception_id, T1, "fixed")

    assert [r.subject_id for r in q.prioritized()] == ["SYN_INFO"]


def test_empty_queue_prioritized_and_counts():
    q = ExceptionQueue()
    assert q.prioritized() == []
    assert q.open_items() == []
    assert q.counts() == {"open": 0, "resolved": 0, "total": 0}


def test_resolve_sets_resolved_at_and_note():
    q = ExceptionQueue()
    rec = q.open("K", "SYN_1", T0)
    done = q.resolve(rec.exception_id, T1, "confirmed date")

    assert done.resolved_at == T1
    assert done.note == "confirmed date"
    assert q.open_items() == []


def test_resolving_twice_raises_asof_error():
    q = ExceptionQueue()
    rec = q.open("K", "SYN_1", T0)
    q.resolve(rec.exception_id, T1, "first close")

    with pytest.raises(AsOfError):
        q.resolve(rec.exception_id, T2, "second close")


def test_resolve_unknown_id_raises_asof_error():
    q = ExceptionQueue()
    with pytest.raises(AsOfError):
        q.resolve("no-such-id", T1, "nothing")


def test_resolve_before_opened_at_raises_and_leaves_item_open():
    q = ExceptionQueue()
    rec = q.open("K", "SYN_1", T1)
    with pytest.raises(AsOfError):
        q.resolve(rec.exception_id, T0, "too early")
    assert q.counts() == {"open": 1, "resolved": 0, "total": 1}


def test_counts_separates_open_and_resolved():
    q = ExceptionQueue()
    a = q.open("K", "SYN_A", T0)
    q.open("K", "SYN_B", T0)
    q.open("K", "SYN_C", T0)
    q.resolve(a.exception_id, T1, "closed")

    assert q.counts() == {"open": 2, "resolved": 1, "total": 3}
    assert len(q.open_items()) == 2


def test_reopening_a_resolved_triple_returns_resolved_record():
    q = ExceptionQueue()
    rec = q.open("K", "SYN_1", T0)
    q.resolve(rec.exception_id, T1, "closed")
    again = q.open("K", "SYN_1", T0)

    assert again.resolved_at == T1
    assert q.counts() == {"open": 0, "resolved": 1, "total": 1}
