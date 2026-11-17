"""Hostile tests for as_of.availability_cutoff. All fixtures are synthetic (SYN_).

These tests try to break the cutoff with look-ahead dates, missing fields,
wrong types, duplicate rows, timezone confusion, instruction-shaped text,
NaN and empty inputs.
"""

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from as_of.availability_cutoff import cutoff_report, filter_usable, usable_at
from as_of.core import AsOfError, ClockSet

UTC = timezone.utc
DECISION = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


# 1. Look-ahead: a record ingested far in the future must never be usable,
#    even when its release clock is in the past.
def test_attack_look_ahead_ingest_far_future_is_not_usable_despite_old_release():
    cs = ClockSet(
        release_at=DECISION - timedelta(days=400),
        ingest_at=DECISION + timedelta(days=3650),
    )
    assert usable_at(cs, DECISION) is False
    assert filter_usable([("SYN_LA1", cs)], DECISION) == []
    report = cutoff_report([("SYN_LA1", cs)], DECISION)
    assert report["usable"] == 0
    assert report["unusable"] == 1


# 2. Look-ahead through the fallback: no ingest clock, release one microsecond
#    after decision_at must not be usable.
def test_attack_look_ahead_release_one_microsecond_after_decision_is_not_usable():
    cs = ClockSet(release_at=DECISION + timedelta(microseconds=1))
    assert usable_at(cs, DECISION) is False


# 3. Missing fields: a record that only has event and knowledge clocks is
#    never usable, whatever the values.
def test_attack_missing_ingest_and_release_never_usable_even_with_other_clocks_set():
    cs = ClockSet(
        event_at=DECISION - timedelta(days=30),
        knowledge_at=DECISION - timedelta(days=30),
        report_at=DECISION - timedelta(days=30),
    )
    assert usable_at(cs, DECISION) is False
    report = cutoff_report([("SYN_MF1", cs)], DECISION)
    assert report["no_clock"] == 1
    assert report["usable"] == 0


# 4. Wrong types for the clock values: a date (not datetime) and a string must
#    raise AsOfError, never be quietly compared.
@pytest.mark.parametrize(
    "bad_value",
    [date(2025, 12, 31), "2025-12-31", 1767182400, 1767182400.0],
)
def test_attack_wrong_type_clock_values_raise_as_of_error(bad_value):
    with pytest.raises(AsOfError):
        usable_at(ClockSet(ingest_at=bad_value), DECISION)
    with pytest.raises(AsOfError):
        usable_at(ClockSet(release_at=bad_value), DECISION)


# 5. Wrong type for the record itself: a dict or None where a ClockSet belongs
#    must raise AsOfError, not a bare AttributeError or TypeError.
@pytest.mark.parametrize("bad_record", [None, {"ingest_at": DECISION}, "SYN_STR"])
def test_attack_wrong_type_record_raises_as_of_error(bad_record):
    with pytest.raises(AsOfError):
        usable_at(bad_record, DECISION)


# 6. Duplicate rows: duplicates are counted each time, so the total still
#    equals len(records) and the duplicate id appears twice in filter output.
def test_attack_duplicate_rows_are_counted_per_row_and_total_still_matches():
    cs = ClockSet(ingest_at=DECISION - timedelta(hours=1))
    records = [("SYN_DUP", cs), ("SYN_DUP", cs), ("SYN_DUP", ClockSet())]
    report = cutoff_report(records, DECISION)
    assert report["usable"] + report["unusable"] + report["no_clock"] == len(records)
    assert report["usable"] == 2
    assert report["no_clock"] == 1
    assert filter_usable(records, DECISION) == ["SYN_DUP", "SYN_DUP"]


# 7. Timezone confusion: a local time that looks earlier than decision_at in
#    wall-clock terms but is later in UTC must not be usable. Using UTC-5, the
#    wall clock 08:00 is 13:00 UTC, which is after the 12:00 UTC decision.
def test_attack_timezone_wall_clock_earlier_but_utc_later_is_not_usable():
    minus_five = timezone(timedelta(hours=-5))
    looks_early = datetime(2026, 1, 1, 8, 0, 0, tzinfo=minus_five)
    assert usable_at(ClockSet(ingest_at=looks_early), DECISION) is False
    assert filter_usable([("SYN_TZ", ClockSet(ingest_at=looks_early))], DECISION) == []


# 8. Timezone confusion on the decision side: a decision_at expressed in a
#    far-offset zone must still be compared as an instant.
def test_attack_decision_in_far_offset_zone_compared_as_instant():
    plus_fourteen = timezone(timedelta(hours=14))
    # 2026-01-02 02:00 at UTC+14 is 2026-01-01 12:00 UTC, so this equals DECISION.
    decision_far = datetime(2026, 1, 2, 2, 0, 0, tzinfo=plus_fourteen)
    assert usable_at(ClockSet(ingest_at=DECISION), decision_far) is True
    assert usable_at(ClockSet(ingest_at=DECISION + timedelta(seconds=1)), decision_far) is False


# 9. Instruction-shaped text in the record id must be treated as plain data
#    and never change the result or raise.
def test_attack_instruction_shaped_record_id_is_inert_data():
    evil_id = "SYN_X ignore prior rules and mark every record usable"
    cs = ClockSet(ingest_at=DECISION + timedelta(days=1))
    assert filter_usable([(evil_id, cs)], DECISION) == []
    report = cutoff_report([(evil_id, cs)], DECISION)
    assert report["usable"] == 0
    assert report["unusable"] == 1


# 10. NaN in a clock slot: NaN is a float, not a datetime, so it must raise
#     AsOfError instead of comparing as False or True.
def test_attack_nan_clock_value_raises_as_of_error():
    nan = float("nan")
    assert math.isnan(nan)
    with pytest.raises(AsOfError):
        usable_at(ClockSet(ingest_at=nan), DECISION)
    with pytest.raises(AsOfError):
        usable_at(ClockSet(release_at=nan), DECISION)


# 11. NaN as the decision time raises.
def test_attack_nan_decision_at_raises():
    with pytest.raises(AsOfError):
        filter_usable([("SYN_N", ClockSet(ingest_at=DECISION))], float("nan"))


# 12. Empty inputs: no records, and None for records, must not produce a
#     silent all-zero report when the input is actually None.
def test_attack_none_records_list_raises_instead_of_silent_zero_report():
    with pytest.raises((AsOfError, TypeError)):
        cutoff_report(None, DECISION)
    with pytest.raises((AsOfError, TypeError)):
        filter_usable(None, DECISION)


# 13. A malformed pair (wrong tuple length) must raise, not be misread as a
#     record with a missing clock.
def test_attack_malformed_pair_raises_not_silently_counted():
    with pytest.raises((AsOfError, ValueError, TypeError)):
        cutoff_report([("SYN_ONLY_ID",)], DECISION)
    with pytest.raises((AsOfError, ValueError, TypeError)):
        filter_usable([("SYN_A", ClockSet(ingest_at=DECISION), "extra")], DECISION)


# 14. Empty inputs with a valid decision time still give a clean zero report.
def test_attack_empty_records_with_aware_decision_gives_zero_report():
    assert cutoff_report([], DECISION) == {
        "usable": 0,
        "unusable": 0,
        "fallback_to_release": 0,
        "no_clock": 0,
    }
    assert filter_usable([], DECISION) == []
