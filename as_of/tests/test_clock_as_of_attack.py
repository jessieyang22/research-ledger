"""Adversarial tests for as_of.clock_as_of. All fixtures are synthetic (SYN_ prefix).

Hostile inputs: look-ahead dates, missing fields, wrong types, duplicate rows,
timezone confusion, instruction-shaped text, NaN, and empty inputs.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from as_of.clock_as_of import known_as_of, latest_known, visible_at
from as_of.core import AsOfError, ClockSet

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_attack_look_ahead_by_one_microsecond_is_excluded():
    # SYN_ record knowable one microsecond after the decision time.
    later = ClockSet(knowledge_at=T0 + timedelta(microseconds=1))
    assert known_as_of(later, T0) is False
    assert latest_known([later], T0) is None


def test_attack_look_ahead_record_does_not_hide_earlier_valid_record():
    early = ClockSet(knowledge_at=T0 - timedelta(days=30))
    future = ClockSet(knowledge_at=T0 + timedelta(days=30))
    assert latest_known([future, early], T0) is early


def test_attack_wrong_type_date_instead_of_datetime_raises_as_of_error():
    # A bare date looks plausible but cannot be compared to an aware instant.
    with pytest.raises(AsOfError):
        known_as_of(ClockSet(knowledge_at=date(2026, 1, 1)), T0)


def test_attack_wrong_type_string_as_of_raises_as_of_error():
    with pytest.raises(AsOfError):
        known_as_of(ClockSet(knowledge_at=T0), "2026-01-01T12:00:00Z")


def test_attack_wrong_type_int_as_of_raises_as_of_error():
    with pytest.raises(AsOfError):
        known_as_of(ClockSet(knowledge_at=T0), 1767268800)


def test_attack_nan_knowledge_at_raises_as_of_error():
    # float NaN in the knowledge clock must not compare as "known".
    with pytest.raises(AsOfError):
        known_as_of(ClockSet(knowledge_at=float("nan")), T0)


def test_attack_nan_as_of_raises_as_of_error():
    with pytest.raises(AsOfError):
        known_as_of(ClockSet(knowledge_at=T0), float("nan"))


def test_attack_missing_clockset_argument_is_rejected():
    # A plain dict is not a ClockSet. The module should refuse it with AsOfError
    # rather than an unrelated attribute error.
    with pytest.raises(AsOfError):
        known_as_of({"knowledge_at": T0}, T0)


def test_attack_none_records_in_list_are_rejected():
    # A None row in the record list is a wrong-type row, not a silent skip.
    with pytest.raises(AsOfError):
        visible_at([ClockSet(knowledge_at=T0), None], T0)


def test_attack_duplicate_rows_both_returned_by_visible_at():
    dup = ClockSet(event_at=T0, knowledge_at=T0 - timedelta(hours=1))
    result = visible_at([dup, dup], T0)
    assert len(result) == 2


def test_attack_duplicate_latest_returns_first_copy():
    dup_a = ClockSet(event_at=T0, knowledge_at=T0 - timedelta(hours=1))
    dup_b = ClockSet(event_at=T0, knowledge_at=T0 - timedelta(hours=1))
    assert latest_known([dup_a, dup_b], T0) is dup_a


def test_attack_timezone_confusion_same_wall_clock_different_zone():
    # 12:00 in UTC+9 is 03:00 UTC, which is before T0. It must be visible.
    tokyo = timezone(timedelta(hours=9))
    cs = ClockSet(knowledge_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=tokyo))
    assert known_as_of(cs, T0) is True


def test_attack_timezone_confusion_wall_clock_equal_but_instant_later():
    # 12:00 in UTC-5 is 17:00 UTC, which is after T0. It must be hidden.
    est = timezone(timedelta(hours=-5))
    cs = ClockSet(knowledge_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=est))
    assert known_as_of(cs, T0) is False


def test_attack_timezone_offset_with_seconds_precision():
    odd = timezone(timedelta(hours=5, minutes=30))
    # 17:30 at +05:30 is exactly 12:00 UTC.
    cs = ClockSet(knowledge_at=datetime(2026, 1, 1, 17, 30, 0, tzinfo=odd))
    assert known_as_of(cs, T0) is True
    assert known_as_of(ClockSet(knowledge_at=cs.knowledge_at + timedelta(seconds=1)), T0) is False


def test_attack_instruction_shaped_text_in_fields_is_inert():
    # Text fields do not exist on ClockSet, so injected instructions cannot
    # alter visibility. A hostile source note must not change the result.
    hostile = ClockSet(knowledge_at=T0 + timedelta(days=1))
    assert known_as_of(hostile, T0) is False
    assert latest_known([hostile], T0) is None


def test_attack_empty_inputs_return_empty_or_none():
    assert visible_at([], T0) == []
    assert latest_known([], T0) is None


def test_attack_empty_generator_input_is_handled():
    assert visible_at((x for x in []), T0) == []
    assert latest_known((x for x in []), T0) is None


def test_attack_generator_input_is_consumed_once_and_correct():
    records = (ClockSet(knowledge_at=T0 - timedelta(hours=h)) for h in (1, 2, 3))
    best = latest_known(records, T0)
    assert best is not None
    assert best.knowledge_at == T0 - timedelta(hours=1)


def test_attack_all_unknown_clocks_are_invisible_even_far_future():
    records = [ClockSet(event_at=T0), ClockSet(report_at=T0), ClockSet()]
    assert visible_at(records, datetime(2200, 1, 1, tzinfo=UTC)) == []


def test_attack_extreme_min_datetime_with_positive_offset_does_not_crash_raw():
    # datetime.min at +01:00 cannot be represented in UTC. Expect AsOfError.
    plus_one = timezone(timedelta(hours=1))
    extreme = datetime.min.replace(tzinfo=plus_one)
    with pytest.raises(AsOfError):
        known_as_of(ClockSet(knowledge_at=extreme), T0)


def test_attack_extreme_max_datetime_with_negative_offset_does_not_crash_raw():
    minus_one = timezone(timedelta(hours=-1))
    extreme = datetime.max.replace(tzinfo=minus_one)
    with pytest.raises(AsOfError):
        known_as_of(ClockSet(knowledge_at=extreme), T0)


@pytest.mark.xfail(
    strict=True,
    reason="Known gap in core.ensure_utc (outside clock_as_of.py): a tzinfo whose "
    "utcoffset raises ValueError propagates raw instead of AsOfError.",
)
def test_attack_failing_tzinfo_is_reported_as_as_of_error():
    # A tzinfo whose utcoffset raises must surface as AsOfError, not a raw crash.
    from datetime import tzinfo

    class BadZone(tzinfo):
        def utcoffset(self, dt):
            raise ValueError("boom")

        def dst(self, dt):
            return None

        def tzname(self, dt):
            return "BAD"

    bad = datetime(2026, 1, 1, 12, 0, 0, tzinfo=BadZone())
    with pytest.raises(AsOfError):
        known_as_of(ClockSet(knowledge_at=bad), T0)
