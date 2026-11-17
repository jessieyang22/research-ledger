"""Tests for as_of.availability_cutoff. All fixtures are synthetic.
"""

from datetime import datetime, timedelta, timezone

import pytest

from as_of.availability_cutoff import cutoff_report, filter_usable, usable_at
from as_of.core import AsOfError, ClockSet

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
DECISION = T0


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_a_record_released_before_decision_at_but_ingested_after_it_is_not_usable():
    cs = ClockSet(
        release_at=DECISION - timedelta(hours=2),
        ingest_at=DECISION + timedelta(minutes=5),
    )
    assert usable_at(cs, DECISION) is False
    assert filter_usable([("SYN_R1", cs)], DECISION) == []


def test_with_no_ingest_at_the_release_at_fallback_is_used_and_counted():
    cs = ClockSet(release_at=DECISION - timedelta(hours=1), ingest_at=None)
    assert usable_at(cs, DECISION) is True
    report = cutoff_report([("SYN_R2", cs)], DECISION)
    assert report["usable"] == 1
    assert report["fallback_to_release"] == 1
    assert report["no_clock"] == 0


def test_cutoff_report_counts_sum_to_the_number_of_records():
    records = [
        ("SYN_A", ClockSet(ingest_at=DECISION - timedelta(hours=1))),
        ("SYN_B", ClockSet(ingest_at=DECISION + timedelta(hours=1))),
        ("SYN_C", ClockSet(release_at=DECISION - timedelta(hours=1))),
        ("SYN_D", ClockSet(release_at=DECISION + timedelta(hours=1))),
        ("SYN_E", ClockSet()),
        ("SYN_F", ClockSet(event_at=DECISION, knowledge_at=DECISION)),
    ]
    report = cutoff_report(records, DECISION)
    assert report["usable"] + report["unusable"] + report["no_clock"] == len(records)
    assert report["usable"] == 2
    assert report["unusable"] == 2
    assert report["no_clock"] == 2
    assert report["fallback_to_release"] == 2


def test_a_record_with_no_ingest_or_release_clock_is_no_clock_and_not_usable():
    cs = ClockSet(event_at=DECISION - timedelta(days=3), knowledge_at=DECISION)
    assert usable_at(cs, DECISION) is False
    report = cutoff_report([("SYN_N", cs)], DECISION)
    assert report["no_clock"] == 1
    assert report["usable"] == 0
    assert report["unusable"] == 0
    assert report["fallback_to_release"] == 0
    assert filter_usable([("SYN_N", cs)], DECISION) == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_ingest_exactly_at_decision_at_is_usable():
    cs = ClockSet(ingest_at=DECISION)
    assert usable_at(cs, DECISION) is True


def test_ingest_one_second_after_decision_at_is_not_usable():
    cs = ClockSet(ingest_at=DECISION + timedelta(seconds=1))
    assert usable_at(cs, DECISION) is False


def test_release_exactly_at_decision_at_is_usable_when_no_ingest():
    cs = ClockSet(release_at=DECISION, ingest_at=None)
    assert usable_at(cs, DECISION) is True
    report = cutoff_report([("SYN_X", cs)], DECISION)
    assert report["usable"] == 1
    assert report["fallback_to_release"] == 1


def test_ingest_before_decision_wins_over_later_release():
    # Ingest is the preferred clock, so a late release does not block a
    # record that was already in our store before decision_at.
    cs = ClockSet(
        ingest_at=DECISION - timedelta(hours=1),
        release_at=DECISION + timedelta(hours=1),
    )
    assert usable_at(cs, DECISION) is True
    report = cutoff_report([("SYN_I", cs)], DECISION)
    assert report["usable"] == 1
    assert report["fallback_to_release"] == 0


def test_release_only_after_decision_at_is_unusable_and_counted_as_fallback():
    cs = ClockSet(release_at=DECISION + timedelta(minutes=1))
    report = cutoff_report([("SYN_L", cs)], DECISION)
    assert report["unusable"] == 1
    assert report["fallback_to_release"] == 1
    assert report["usable"] == 0
    assert report["no_clock"] == 0


def test_fallback_key_overlaps_usable_and_unusable_without_double_counting_total():
    records = [
        ("SYN_F1", ClockSet(release_at=DECISION - timedelta(minutes=1))),
        ("SYN_F2", ClockSet(release_at=DECISION + timedelta(minutes=1))),
    ]
    report = cutoff_report(records, DECISION)
    assert report["fallback_to_release"] == 2
    assert report["usable"] + report["unusable"] + report["no_clock"] == 2


def test_filter_usable_keeps_original_order():
    records = [
        ("SYN_Z", ClockSet(ingest_at=DECISION - timedelta(hours=3))),
        ("SYN_Y", ClockSet(ingest_at=DECISION + timedelta(hours=3))),
        ("SYN_X", ClockSet(release_at=DECISION - timedelta(hours=2))),
        ("SYN_W", ClockSet()),
        ("SYN_V", ClockSet(ingest_at=DECISION)),
    ]
    assert filter_usable(records, DECISION) == ["SYN_Z", "SYN_X", "SYN_V"]


def test_empty_records_give_all_zero_report():
    report = cutoff_report([], DECISION)
    assert report == {
        "usable": 0,
        "unusable": 0,
        "fallback_to_release": 0,
        "no_clock": 0,
    }
    assert filter_usable([], DECISION) == []


def test_non_utc_offsets_are_compared_as_instants():
    # 13:00 at UTC+02:00 is 11:00 UTC, which is before DECISION (12:00 UTC).
    plus_two = timezone(timedelta(hours=2))
    ingest = datetime(2026, 1, 1, 13, 0, 0, tzinfo=plus_two)
    cs = ClockSet(ingest_at=ingest)
    assert usable_at(cs, DECISION) is True
    # 13:30 at UTC-01:00 is 14:30 UTC, after DECISION.
    minus_one = timezone(timedelta(hours=-1))
    late = datetime(2026, 1, 1, 13, 30, 0, tzinfo=minus_one)
    assert usable_at(ClockSet(ingest_at=late), DECISION) is False


def test_naive_decision_at_raises():
    with pytest.raises(AsOfError):
        usable_at(ClockSet(ingest_at=T0), datetime(2026, 1, 1, 12, 0, 0))
    with pytest.raises(AsOfError):
        filter_usable([("SYN_N", ClockSet(ingest_at=T0))], datetime(2026, 1, 1))
    with pytest.raises(AsOfError):
        cutoff_report([("SYN_N", ClockSet(ingest_at=T0))], datetime(2026, 1, 1))


def test_naive_ingest_clock_raises():
    cs = ClockSet(ingest_at=datetime(2026, 1, 1, 11, 0, 0))
    with pytest.raises(AsOfError):
        usable_at(cs, DECISION)


def test_naive_release_clock_raises_when_used_as_fallback():
    cs = ClockSet(release_at=datetime(2026, 1, 1, 11, 0, 0))
    with pytest.raises(AsOfError):
        usable_at(cs, DECISION)
