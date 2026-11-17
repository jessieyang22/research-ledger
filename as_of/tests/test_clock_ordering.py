"""Tests for as_of.clock_ordering. All fixtures are synthetic (SYN_ prefix in spirit; no real data)."""

from datetime import datetime, timedelta, timezone

import pytest

from as_of.clock_ordering import ORDER_RULES, check_clock_order
from as_of.core import ClockSet, Finding, ValidationStatus


BASE = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)


def _consistent():
    """A ClockSet where every rule holds with strictly increasing clocks."""
    return ClockSet(
        event_at=BASE,
        release_at=BASE + timedelta(hours=1),
        ingest_at=BASE + timedelta(hours=2),
        knowledge_at=BASE + timedelta(hours=3),
        report_at=BASE + timedelta(hours=4),
    )


def _by_check(findings, check_id):
    return [f for f in findings if f.check_id == check_id]


def test_fully_consistent_clockset_returns_no_findings():
    assert check_clock_order(_consistent()) == []


def test_knowledge_before_release_yields_fail_finding():
    cs = ClockSet(
        event_at=BASE,
        release_at=BASE + timedelta(hours=3),
        ingest_at=BASE + timedelta(hours=4),
        knowledge_at=BASE + timedelta(hours=1),  # knowledge < release
        report_at=BASE + timedelta(hours=5),
    )
    findings = check_clock_order(cs)
    hits = _by_check(findings, "clock.knowledge_before_release")
    assert len(hits) == 1
    assert hits[0].status == ValidationStatus.FAIL
    assert hits[0].subject == "clock:release<=knowledge"
    assert all(f.status != ValidationStatus.WARN for f in findings)


def test_none_clock_yields_warn_and_no_fail():
    cs = ClockSet(
        event_at=BASE,
        release_at=None,
        ingest_at=BASE + timedelta(hours=2),
        knowledge_at=BASE + timedelta(hours=3),
        report_at=BASE + timedelta(hours=4),
    )
    findings = check_clock_order(cs)
    assert findings, "a None clock should produce findings"
    assert all(f.status != ValidationStatus.FAIL for f in findings)
    warns = [f for f in findings if f.status == ValidationStatus.WARN]
    # release participates in event<=release, release<=ingest, release<=knowledge
    affected = {f.check_id for f in warns}
    assert {
        "clock.event_after_release",
        "clock.ingest_before_release",
        "clock.knowledge_before_release",
    } <= affected
    for f in warns:
        assert "release" in f.message


def test_ingest_before_release_yields_fail_finding():
    cs = ClockSet(
        event_at=BASE,
        release_at=BASE + timedelta(hours=2),
        ingest_at=BASE + timedelta(hours=1),  # ingest < release
        knowledge_at=BASE + timedelta(hours=3),
        report_at=BASE + timedelta(hours=4),
    )
    findings = check_clock_order(cs)
    hits = _by_check(findings, "clock.ingest_before_release")
    assert len(hits) == 1
    assert hits[0].status == ValidationStatus.FAIL
    assert hits[0].subject == "clock:release<=ingest"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_equal_clocks_are_not_a_violation():
    same = ClockSet(
        event_at=BASE,
        release_at=BASE,
        ingest_at=BASE,
        knowledge_at=BASE,
        report_at=BASE,
    )
    assert check_clock_order(same) == []


def test_event_after_release_yields_fail():
    cs = ClockSet(
        event_at=BASE + timedelta(hours=2),
        release_at=BASE + timedelta(hours=1),
        ingest_at=BASE + timedelta(hours=3),
        knowledge_at=BASE + timedelta(hours=4),
        report_at=BASE + timedelta(hours=5),
    )
    hits = _by_check(check_clock_order(cs), "clock.event_after_release")
    assert len(hits) == 1
    assert hits[0].status == ValidationStatus.FAIL


def test_report_before_knowledge_yields_fail():
    cs = ClockSet(
        event_at=BASE,
        release_at=BASE + timedelta(hours=1),
        ingest_at=BASE + timedelta(hours=2),
        knowledge_at=BASE + timedelta(hours=4),
        report_at=BASE + timedelta(hours=3),
    )
    hits = _by_check(check_clock_order(cs), "clock.report_before_knowledge")
    assert len(hits) == 1
    assert hits[0].status == ValidationStatus.FAIL


def test_all_clocks_none_gives_one_warn_per_rule_and_no_fail():
    findings = check_clock_order(ClockSet())
    assert len(findings) == len(ORDER_RULES)
    assert all(f.status == ValidationStatus.WARN for f in findings)
    assert [f.check_id for f in findings] == [r[0] for r in ORDER_RULES]


def test_findings_are_returned_in_rule_order():
    cs = ClockSet(
        event_at=BASE + timedelta(hours=9),  # violates event<=release
        release_at=BASE,
        ingest_at=BASE - timedelta(hours=1),  # violates release<=ingest
        knowledge_at=BASE - timedelta(hours=2),  # violates release<=knowledge
        report_at=BASE - timedelta(hours=3),  # violates knowledge<=report
    )
    findings = check_clock_order(cs)
    assert [f.check_id for f in findings] == [r[0] for r in ORDER_RULES]
    assert all(f.status == ValidationStatus.FAIL for f in findings)


def test_timezone_offsets_are_compared_in_utc():
    # Same instant expressed with different offsets must count as equal, not out of order.
    plus_two = timezone(timedelta(hours=2))
    cs = ClockSet(
        event_at=BASE,
        release_at=BASE.astimezone(plus_two),
        ingest_at=BASE + timedelta(hours=1),
        knowledge_at=BASE + timedelta(hours=2),
        report_at=BASE + timedelta(hours=3),
    )
    assert check_clock_order(cs) == []


def test_naive_datetime_raises():
    from as_of.core import AsOfError

    cs = ClockSet(event_at=datetime(2026, 1, 10, 12, 0, 0))
    with pytest.raises(AsOfError):
        check_clock_order(cs)


def test_returns_finding_instances():
    findings = check_clock_order(ClockSet())
    assert all(isinstance(f, Finding) for f in findings)
