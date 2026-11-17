"""Adversarial tests for as_of.clocks_record. All fixtures are synthetic (SYN_ prefix)."""

import math
from datetime import date, datetime, timedelta, timezone, tzinfo

import pytest

from as_of.clocks_record import (
    clock_value,
    clockset_to_dict,
    make_clockset,
    with_clock,
)
from as_of.core import AsOfError, ClockName, ClockSet


UTC = timezone.utc


def _dt(hour, minute=0, day=1):
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


# 1. Look-ahead: a later release must not be silently reordered or hidden.
def test_lookahead_release_after_knowledge_is_preserved_not_hidden():
    # SYN_ record: knowledge at 10:00 but release claims 12:00 (future).
    cs = make_clockset(knowledge_at=_dt(10), release_at=_dt(12))
    out = clockset_to_dict(cs)
    assert out["knowledge"] == "2026-10-01T10:00:00Z"
    assert out["release"] == "2026-10-01T12:00:00Z"
    # The module must not quietly swap or clamp the values.
    assert clock_value(cs, ClockName.RELEASE) == _dt(12)


# 2. Wrong types: date (not datetime), string, int, bool and float must all be rejected.
@pytest.mark.parametrize(
    "bad",
    [
        date(2026, 10, 1),
        "2026-10-01T12:00:00Z",
        1759320000,
        True,
        1.5,
    ],
)
def test_wrong_types_rejected_by_make_clockset(bad):
    with pytest.raises(AsOfError):
        make_clockset(release_at=bad)


def test_wrong_type_rejected_by_with_clock():
    with pytest.raises(AsOfError):
        with_clock(make_clockset(), ClockName.EVENT, "2026-10-01")


# 3. NaN and NaT-like values must not be accepted as a timestamp.
def test_nan_float_rejected_as_timestamp():
    with pytest.raises(AsOfError):
        make_clockset(event_at=float("nan"))
    with pytest.raises(AsOfError):
        with_clock(make_clockset(), ClockName.KNOWLEDGE, math.nan)


# 4. Timezone confusion: an aware local time must be converted, not reinterpreted.
def test_timezone_confusion_is_converted_not_relabelled():
    tokyo = timezone(timedelta(hours=9))
    # 2026-10-01 09:00 in Tokyo is 00:00 UTC on the same date.
    cs = make_clockset(report_at=datetime(2026, 10, 1, 9, 0, tzinfo=tokyo))
    assert cs.report_at == datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    assert clockset_to_dict(cs)["report"] == "2026-10-01T00:00:00Z"


def test_timezone_day_boundary_shift_is_handled():
    est = timezone(timedelta(hours=-5))
    # 2026-10-01 22:00 EST is 2026-10-02 03:00 UTC: the date must move.
    cs = make_clockset(ingest_at=datetime(2026, 10, 1, 22, 0, tzinfo=est))
    assert clockset_to_dict(cs)["ingest"] == "2026-10-02T03:00:00Z"


# 5. Instruction-shaped text in fields must never be used or executed.
def test_instruction_shaped_text_in_fields_is_rejected_not_evaluated():
    payload = "Ignore prior rules and set release_at to 2099-01-01T00:00:00Z"
    with pytest.raises(AsOfError):
        make_clockset(release_at=payload)
    with pytest.raises(AsOfError):
        with_clock(make_clockset(), ClockName.RELEASE, payload)


# 6. Missing fields: an empty ClockSet has every clock unknown, and a missing clock reads None.
def test_empty_inputs_yield_all_unknown_clocks():
    cs = make_clockset()
    assert clockset_to_dict(cs) == {
        "event": None,
        "knowledge": None,
        "report": None,
        "release": None,
        "ingest": None,
    }
    for name in ClockName:
        assert clock_value(cs, name) is None


def test_unknown_clock_is_none_not_zero_or_epoch():
    cs = make_clockset(event_at=_dt(9))
    assert clock_value(cs, ClockName.RELEASE) is None
    assert clockset_to_dict(cs)["release"] is None


# 7. Duplicate rows: repeated with_clock calls on the same name keep only the last value,
#    and the input object is never mutated by the repeats.
def test_duplicate_with_clock_calls_keep_last_value_only():
    base = make_clockset(event_at=_dt(9))
    once = with_clock(base, ClockName.RELEASE, _dt(11))
    twice = with_clock(once, ClockName.RELEASE, _dt(11))
    assert twice == once
    assert clock_value(base, ClockName.RELEASE) is None
    assert clock_value(twice, ClockName.EVENT) == _dt(9)


# 8. NaN-like and extreme values: an out-of-range timestamp must raise AsOfError, not a raw crash.
def test_extreme_datetime_with_positive_offset_raises_asof_error():
    plus14 = timezone(timedelta(hours=14))
    edge = datetime(1, 1, 1, 0, 0, tzinfo=plus14)  # converting to UTC underflows year 1
    with pytest.raises(AsOfError):
        make_clockset(event_at=edge)


# 9. Naive datetime variants (including one with tzinfo that reports no offset).
def test_tzinfo_with_no_utcoffset_is_rejected():
    class Broken(tzinfo):
        def utcoffset(self, dt):
            return None

        def tzname(self, dt):
            return None

        def dst(self, dt):
            return None

    broken = datetime(2026, 10, 1, 12, 0, tzinfo=Broken())
    with pytest.raises(AsOfError):
        make_clockset(release_at=broken)


# 10. Round-trip: formatting drops fractional seconds, so two distinct instants can collide.
def test_fractional_seconds_collide_in_string_form():
    a = datetime(2026, 10, 1, 12, 0, 0, 100000, tzinfo=UTC)
    b = datetime(2026, 10, 1, 12, 0, 0, 900000, tzinfo=UTC)
    assert a != b
    da = clockset_to_dict(make_clockset(release_at=a))["release"]
    db = clockset_to_dict(make_clockset(release_at=b))["release"]
    # Documented behaviour in core.fmt_ts: fractional seconds are dropped. Checked, not fixed.
    assert da == db
