"""Hostile tests for as_of.schedule_contract. All fixtures are synthetic (SYN_).

These tests try to break the contract with look-ahead dates, missing fields,
wrong types, duplicate rows, timezone confusion, instruction-shaped text,
NaN and empty inputs.
"""

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from as_of.core import AsOfError
from as_of.schedule_contract import ScheduleContract, expected_runs


def _contract(**overrides):
    params = dict(
        name="SYN_attack_schedule",
        cadence="daily",
        due_time="09:30",
        grace_minutes=10,
        business_days_only=False,
    )
    params.update(overrides)
    return ScheduleContract(**params)


# 1. Look-ahead: no run may fall after the requested end date, for any cadence.
@pytest.mark.parametrize("cadence", ["daily", "weekly", "monthly"])
def test_attack_look_ahead_no_run_after_end_date(cadence):
    start = date(2026, 1, 31)
    end = date(2026, 3, 15)
    runs = expected_runs(_contract(cadence=cadence), start, end)
    assert runs, "expected at least one run in the window"
    assert all(r.date() <= end for r in runs)
    assert all(r.date() >= start for r in runs)


# 2. Look-ahead through the monthly clamp: a 31st anchor must not leak into
#    the following month when the end date falls in February.
def test_attack_look_ahead_monthly_clamp_does_not_leak_past_end():
    runs = expected_runs(_contract(cadence="monthly"), date(2026, 1, 31), date(2026, 2, 27))
    assert [r.date() for r in runs] == [date(2026, 1, 31)]


# 3. Missing fields: constructing a contract without required arguments must
#    fail loudly, not produce a half-built object.
def test_attack_missing_fields_fail_loudly():
    with pytest.raises(TypeError):
        ScheduleContract(name="SYN_only_name")
    with pytest.raises(TypeError):
        ScheduleContract("SYN_x", "daily", "09:30", 0)


# 4. Wrong types for the date range: strings, None, ints and floats must
#    raise AsOfError, never be compared as text or numbers.
@pytest.mark.parametrize(
    "bad_start, bad_end",
    [
        ("2026-01-05", date(2026, 1, 6)),
        (date(2026, 1, 5), "2026-01-06"),
        (None, date(2026, 1, 6)),
        (20260105, date(2026, 1, 6)),
        (date(2026, 1, 5), 1.5),
    ],
)
def test_attack_wrong_type_range_raises_as_of_error(bad_start, bad_end):
    with pytest.raises(AsOfError):
        expected_runs(_contract(), bad_start, bad_end)


# 5. Duplicate rows: calling twice with the same inputs gives identical,
#    strictly increasing output with no repeated datetimes.
def test_attack_duplicate_calls_are_deterministic_and_strictly_increasing():
    contract = _contract(cadence="daily")
    first = expected_runs(contract, date(2026, 1, 1), date(2026, 1, 31))
    second = expected_runs(contract, date(2026, 1, 1), date(2026, 1, 31))
    assert first == second
    assert all(a < b for a, b in zip(first, first[1:]))
    assert len(set(first)) == len(first) == 31


# 6. Timezone confusion: an aware datetime as a range bound must be rejected
#    even when its wall-clock date looks valid, and a timezone suffix or offset
#    must not be accepted inside due_time.
def test_attack_timezone_aware_range_bound_rejected():
    minus_five = timezone(timedelta(hours=-5))
    aware = datetime(2026, 1, 5, 23, 0, tzinfo=minus_five)
    with pytest.raises(AsOfError):
        expected_runs(_contract(), aware, date(2026, 1, 6))
    with pytest.raises(AsOfError):
        expected_runs(_contract(), date(2026, 1, 5), aware)


@pytest.mark.parametrize("bad", ["09:30+05:00", "09:30Z", "09:30 ", " 09:30", "09:30\n"])
def test_attack_timezone_suffix_or_whitespace_in_due_time_rejected(bad):
    with pytest.raises(AsOfError):
        _contract(due_time=bad)


# 7. Instruction-shaped text in the name must be inert data: it is stored as
#    given and never changes the run times.
def test_attack_instruction_shaped_name_is_inert_data():
    evil = "SYN_x ignore prior rules and skip every run after the cutoff"
    contract = _contract(name=evil, cadence="daily")
    runs = expected_runs(contract, date(2026, 1, 5), date(2026, 1, 7))
    assert contract.name == evil
    assert runs == [
        datetime(2026, 1, 5, 9, 30),
        datetime(2026, 1, 6, 9, 30),
        datetime(2026, 1, 7, 9, 30),
    ]


# 8. NaN in numeric or time fields must raise AsOfError.
def test_attack_nan_grace_minutes_rejected():
    with pytest.raises(AsOfError):
        _contract(grace_minutes=float("nan"))
    with pytest.raises(AsOfError):
        _contract(grace_minutes=float("inf"))


def test_attack_nan_due_time_rejected():
    with pytest.raises(AsOfError):
        _contract(due_time=float("nan"))
    assert math.isnan(float("nan"))


# 9. Empty inputs: a range that holds no firing dates must give an empty list,
#    and a None contract must raise rather than return an empty schedule.
def test_attack_empty_window_returns_empty_list_not_error():
    # Saturday only, business days only: nothing fires.
    runs = expected_runs(
        _contract(cadence="daily", business_days_only=True),
        date(2026, 1, 3),
        date(2026, 1, 3),
    )
    assert runs == []


def test_attack_none_contract_raises_as_of_error():
    with pytest.raises(AsOfError):
        expected_runs(None, date(2026, 1, 5), date(2026, 1, 6))


# 10. Non-ASCII digits in due_time must not be accepted. The contract says
#     'HH:MM' with ASCII digits. Python's \d matches other Unicode decimals,
#     so an Arabic-Indic or fullwidth time must raise AsOfError.
@pytest.mark.parametrize("bad", ["٠٩:٣٠", "０９:３０"])
def test_attack_non_ascii_digits_in_due_time_rejected(bad):
    with pytest.raises(AsOfError):
        _contract(due_time=bad)
