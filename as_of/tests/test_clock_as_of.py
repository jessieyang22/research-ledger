"""Tests for as_of.clock_as_of. All fixtures are synthetic and use the SYN_ prefix.
"""

from datetime import datetime, timedelta, timezone

import pytest

from as_of.clock_as_of import known_as_of, latest_known, visible_at
from as_of.core import AsOfError, ClockSet

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_knowledge_time_after_as_of_is_excluded():
    as_of = T0
    later = ClockSet(knowledge_at=T0 + timedelta(seconds=1))
    assert known_as_of(later, as_of) is False
    assert visible_at([later], as_of) == []


def test_knowledge_time_exactly_equal_to_as_of_is_included():
    as_of = T0
    exact = ClockSet(knowledge_at=T0)
    assert known_as_of(exact, as_of) is True
    assert visible_at([exact], as_of) == [exact]


def test_records_with_knowledge_at_none_are_never_visible():
    as_of = T0
    unknown = ClockSet(event_at=T0, knowledge_at=None)
    # Even a far-future as_of cannot make a None knowledge clock visible.
    far_future = datetime(2100, 1, 1, tzinfo=UTC)
    assert known_as_of(unknown, as_of) is False
    assert known_as_of(unknown, far_future) is False
    assert visible_at([unknown], far_future) == []
    assert latest_known([unknown], far_future) is None


def test_latest_known_returns_largest_knowledge_at_at_or_before_as_of():
    as_of = T0 + timedelta(hours=2)
    early = ClockSet(knowledge_at=T0 - timedelta(hours=5))
    middle = ClockSet(knowledge_at=T0 + timedelta(hours=1))
    late_excluded = ClockSet(knowledge_at=T0 + timedelta(hours=3))
    # Input order is deliberately not sorted by knowledge_at.
    records = [middle, late_excluded, early]
    assert latest_known(records, as_of) is middle


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_known_as_of_none_knowledge_at_returns_false_without_raising():
    assert known_as_of(ClockSet(knowledge_at=None), T0) is False


def test_visible_at_preserves_original_order():
    a = ClockSet(knowledge_at=T0 - timedelta(days=3))
    b = ClockSet(knowledge_at=T0 - timedelta(days=1))
    c = ClockSet(knowledge_at=T0 - timedelta(days=2))
    result = visible_at([a, b, c], T0)
    assert result == [a, b, c]


def test_visible_at_empty_input_returns_empty_list():
    assert visible_at([], T0) == []


def test_latest_known_empty_input_returns_none():
    assert latest_known([], T0) is None


def test_latest_known_none_visible_returns_none():
    future_only = [
        ClockSet(knowledge_at=T0 + timedelta(minutes=1)),
        ClockSet(knowledge_at=T0 + timedelta(days=1)),
    ]
    assert latest_known(future_only, T0) is None


def test_latest_known_tie_returns_first_in_input_order():
    first = ClockSet(event_at=T0, knowledge_at=T0 - timedelta(hours=1))
    second = ClockSet(event_at=T0 + timedelta(minutes=5), knowledge_at=T0 - timedelta(hours=1))
    assert latest_known([first, second], T0) is first
    assert latest_known([second, first], T0) is second


def test_latest_known_skips_none_knowledge_records():
    unknown = ClockSet(knowledge_at=None)
    known = ClockSet(knowledge_at=T0 - timedelta(hours=2))
    assert latest_known([unknown, known], T0) is known


def test_comparison_across_timezones_uses_utc_instant():
    # Same instant expressed in a non-UTC zone (UTC-5) must compare equal to as_of.
    est = timezone(timedelta(hours=-5))
    same_instant_est = datetime(2026, 1, 1, 7, 0, 0, tzinfo=est)  # == 12:00 UTC
    cs = ClockSet(knowledge_at=same_instant_est)
    assert known_as_of(cs, T0) is True
    # One second later in EST is 12:00:01 UTC, which is after as_of.
    cs_later = ClockSet(knowledge_at=same_instant_est + timedelta(seconds=1))
    assert known_as_of(cs_later, T0) is False


def test_as_of_in_non_utc_zone_is_normalised():
    est = timezone(timedelta(hours=-5))
    as_of_est = datetime(2026, 1, 1, 7, 0, 0, tzinfo=est)  # == 12:00 UTC
    cs = ClockSet(knowledge_at=T0)
    assert known_as_of(cs, as_of_est) is True


def test_naive_as_of_raises_as_of_error():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(AsOfError):
        known_as_of(ClockSet(knowledge_at=T0), naive)


def test_naive_knowledge_at_raises_as_of_error():
    naive_knowledge = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(AsOfError):
        known_as_of(ClockSet(knowledge_at=naive_knowledge), T0)


def test_latest_known_does_not_mutate_input():
    a = ClockSet(knowledge_at=T0 - timedelta(hours=1))
    b = ClockSet(knowledge_at=T0 + timedelta(hours=1))
    records = [b, a]
    latest_known(records, T0)
    assert records == [b, a]
