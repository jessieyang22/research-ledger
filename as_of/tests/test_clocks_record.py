"""Tests for as_of.clocks_record. All fixtures are synthetic (SYN_ prefix)."""

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from as_of.clocks_record import (
    clock_value,
    clockset_to_dict,
    make_clockset,
    with_clock,
)
from as_of.core import CLOCK_NAMES, AsOfError, ClockName, ClockSet


UTC = timezone.utc


def _dt(hour, minute=0):
    return datetime(2026, 10, 1, hour, minute, tzinfo=UTC)


def _full_set():
    return make_clockset(
        event_at=_dt(9),
        knowledge_at=_dt(10),
        report_at=_dt(11),
        release_at=_dt(12),
        ingest_at=_dt(13),
    )


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_assigning_to_clockset_attribute_raises_frozen():
    cs = _full_set()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cs.release_at = _dt(20)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cs.event_at = None
    # The value is unchanged after the failed assignment.
    assert cs.release_at == _dt(12)


def test_with_clock_returns_new_object_and_leaves_original_unchanged():
    cs = _full_set()
    new = with_clock(cs, ClockName.RELEASE, _dt(20))

    assert new is not cs
    assert isinstance(new, ClockSet)
    assert new.release_at == _dt(20)
    # Original is untouched on every clock.
    assert cs.release_at == _dt(12)
    assert cs == _full_set()
    # Other clocks carry over in the new object.
    assert new.event_at == cs.event_at
    assert new.knowledge_at == cs.knowledge_at
    assert new.report_at == cs.report_at
    assert new.ingest_at == cs.ingest_at


def test_clockset_to_dict_keys_equal_core_clock_names():
    out = clockset_to_dict(_full_set())
    assert set(out.keys()) == set(CLOCK_NAMES)
    assert list(out.keys()) == list(CLOCK_NAMES)


def test_clock_value_release_returns_release_at():
    cs = _full_set()
    assert clock_value(cs, ClockName.RELEASE) == cs.release_at
    assert clock_value(cs, ClockName.RELEASE) == _dt(12)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(ClockName))
def test_clock_value_reads_each_clock(name):
    cs = _full_set()
    expected = {
        ClockName.EVENT: _dt(9),
        ClockName.KNOWLEDGE: _dt(10),
        ClockName.REPORT: _dt(11),
        ClockName.RELEASE: _dt(12),
        ClockName.INGEST: _dt(13),
    }[name]
    assert clock_value(cs, name) == expected


def test_unset_clock_reads_as_none():
    cs = make_clockset(event_at=_dt(9))
    assert clock_value(cs, ClockName.RELEASE) is None
    assert clock_value(cs, ClockName.EVENT) == _dt(9)


def test_default_clockset_is_all_none():
    cs = make_clockset()
    assert all(clock_value(cs, n) is None for n in ClockName)
    assert all(v is None for v in clockset_to_dict(cs).values())


def test_naive_datetime_in_make_clockset_raises():
    with pytest.raises(AsOfError):
        make_clockset(release_at=datetime(2026, 10, 1, 12, 0))


def test_naive_datetime_in_with_clock_raises():
    cs = _full_set()
    with pytest.raises(AsOfError):
        with_clock(cs, ClockName.RELEASE, datetime(2026, 10, 1, 12, 0))
    # Failed call does not alter the original.
    assert cs.release_at == _dt(12)


def test_non_utc_aware_input_is_normalised_to_utc():
    est = timezone(timedelta(hours=-4))
    local = datetime(2026, 10, 1, 8, 0, tzinfo=est)  # 12:00 UTC
    cs = make_clockset(release_at=local)
    assert cs.release_at.utcoffset() == timedelta(0)
    assert cs.release_at == datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_with_clock_normalises_non_utc_value():
    est = timezone(timedelta(hours=-4))
    cs = with_clock(_full_set(), ClockName.INGEST, datetime(2026, 10, 1, 9, 0, tzinfo=est))
    assert cs.ingest_at.utcoffset() == timedelta(0)
    assert cs.ingest_at == _dt(13)


def test_with_clock_none_clears_that_clock_only():
    cs = _full_set()
    cleared = with_clock(cs, ClockName.REPORT, None)
    assert cleared.report_at is None
    assert cleared.release_at == cs.release_at
    assert cs.report_at == _dt(11)


def test_with_clock_chained_changes_do_not_mutate_intermediates():
    base = make_clockset()
    step1 = with_clock(base, ClockName.EVENT, _dt(9))
    step2 = with_clock(step1, ClockName.RELEASE, _dt(12))
    assert clock_value(base, ClockName.EVENT) is None
    assert clock_value(step1, ClockName.RELEASE) is None
    assert clock_value(step2, ClockName.EVENT) == _dt(9)
    assert clock_value(step2, ClockName.RELEASE) == _dt(12)


def test_with_clock_rejects_non_clockname():
    with pytest.raises(TypeError):
        with_clock(_full_set(), "release", _dt(12))


def test_clock_value_rejects_non_clockname():
    with pytest.raises(TypeError):
        clock_value(_full_set(), "release")


def test_clockset_to_dict_formats_utc_strings():
    out = clockset_to_dict(_full_set())
    assert out["release"] == "2026-10-01T12:00:00Z"
    assert out["event"] == "2026-10-01T09:00:00Z"


def test_clockset_to_dict_mixes_none_and_strings():
    out = clockset_to_dict(make_clockset(knowledge_at=_dt(10)))
    assert out["knowledge"] == "2026-10-01T10:00:00Z"
    assert out["release"] is None


def test_clockset_to_dict_does_not_mutate_clockset():
    cs = _full_set()
    clockset_to_dict(cs)
    assert cs == _full_set()
