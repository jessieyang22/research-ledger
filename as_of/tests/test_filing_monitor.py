"""Tests for as_of.filing_monitor. All fixtures are synthetic (SYN_ prefix)."""

import inspect
from datetime import datetime, timedelta, timezone

import pytest

import as_of.filing_monitor as fm
from as_of.core import AsOfError, FilingRecord, SourceRecord, SourceType
from as_of.filing_monitor import FilingMonitor
from as_of.source_register import SourceRegister


def _utc(day, hour=12, minute=0):
    return datetime(2026, 1, day, hour, minute, tzinfo=timezone.utc)


def _register(*source_ids):
    reg = SourceRegister()
    for sid in source_ids:
        reg.add_source(
            SourceRecord(
                source_id=sid,
                source_type=SourceType.FILING,
                publisher="SYN_PUBLISHER",
                locator="SYN_LOCATOR/%s" % sid,
                retrieved_at=_utc(5),
                sha256="0" * 64,
                synthetic=True,
            )
        )
    return reg


def _filing(filing_id, ticker="SYN_T1", form_type="SYN_10K", accepted_at=None,
            source_id="SYN_S1"):
    accepted = accepted_at if accepted_at is not None else _utc(10)
    return FilingRecord(
        filing_id=filing_id,
        ticker=ticker,
        form_type=form_type,
        filed_at=accepted - timedelta(hours=1),
        accepted_at=accepted,
        source_id=source_id,
    )


@pytest.fixture
def monitor():
    return FilingMonitor(_register("SYN_S1", "SYN_S2"))


# Acceptance tests from the task list.

def test_same_filing_id_twice_returns_false_second_time(monitor):
    rec = _filing("SYN_F1")
    assert monitor.ingest_filing(rec) is True
    assert monitor.ingest_filing(rec) is False


def test_same_filing_id_second_time_does_not_replace_stored_copy(monitor):
    first = _filing("SYN_F1", ticker="SYN_T1", accepted_at=_utc(10))
    second = _filing("SYN_F1", ticker="SYN_T2", accepted_at=_utc(20))
    assert monitor.ingest_filing(first) is True
    assert monitor.ingest_filing(second) is False
    assert monitor.occurrences("SYN_T1", _utc(1), _utc(31)) == [first]
    assert monitor.occurrences("SYN_T2", _utc(1), _utc(31)) == []


def test_unregistered_source_id_raises_asof_error(monitor):
    with pytest.raises(AsOfError):
        monitor.ingest_filing(_filing("SYN_F9", source_id="SYN_UNKNOWN"))


def test_unregistered_source_is_not_stored(monitor):
    with pytest.raises(AsOfError):
        monitor.ingest_filing(_filing("SYN_F9", source_id="SYN_UNKNOWN"))
    assert monitor.occurrences("SYN_T1", _utc(1), _utc(31)) == []


def test_occurrences_filters_by_accepted_at_window(monitor):
    before = _filing("SYN_A", accepted_at=_utc(5))
    inside = _filing("SYN_B", accepted_at=_utc(12))
    after = _filing("SYN_C", accepted_at=_utc(20))
    for rec in (before, inside, after):
        monitor.ingest_filing(rec)
    got = monitor.occurrences("SYN_T1", _utc(10), _utc(15))
    assert got == [inside]


def test_occurrences_window_bounds_are_inclusive(monitor):
    lo_rec = _filing("SYN_LO", accepted_at=_utc(10))
    hi_rec = _filing("SYN_HI", accepted_at=_utc(15))
    monitor.ingest_filing(lo_rec)
    monitor.ingest_filing(hi_rec)
    got = monitor.occurrences("SYN_T1", _utc(10), _utc(15))
    assert got == [lo_rec, hi_rec]


def test_occurrences_excludes_just_outside_bounds(monitor):
    monitor.ingest_filing(_filing("SYN_EARLY", accepted_at=_utc(10) - timedelta(seconds=1)))
    monitor.ingest_filing(_filing("SYN_LATE", accepted_at=_utc(15) + timedelta(seconds=1)))
    assert monitor.occurrences("SYN_T1", _utc(10), _utc(15)) == []


def test_occurrences_filters_by_ticker(monitor):
    a = _filing("SYN_A", ticker="SYN_T1", accepted_at=_utc(12))
    b = _filing("SYN_B", ticker="SYN_T2", accepted_at=_utc(12))
    monitor.ingest_filing(a)
    monitor.ingest_filing(b)
    assert monitor.occurrences("SYN_T1", _utc(1), _utc(31)) == [a]
    assert monitor.occurrences("SYN_T3", _utc(1), _utc(31)) == []


def test_occurrences_sorted_by_accepted_at_then_filing_id(monitor):
    late = _filing("SYN_A", accepted_at=_utc(20))
    tie_b = _filing("SYN_B", accepted_at=_utc(12))
    tie_a = _filing("SYN_C", accepted_at=_utc(12))
    for rec in (late, tie_b, tie_a):
        monitor.ingest_filing(rec)
    got = monitor.occurrences("SYN_T1", _utc(1), _utc(31))
    assert [r.filing_id for r in got] == ["SYN_B", "SYN_C", "SYN_A"]


def test_occurrences_normalises_non_utc_aware_bounds(monitor):
    rec = _filing("SYN_F1", accepted_at=_utc(12, hour=12))
    monitor.ingest_filing(rec)
    eastern = timezone(timedelta(hours=-5))
    lo = datetime(2026, 1, 12, 7, 0, tzinfo=eastern)   # 12:00 UTC
    hi = datetime(2026, 1, 12, 7, 30, tzinfo=eastern)  # 12:30 UTC
    assert monitor.occurrences("SYN_T1", lo, hi) == [rec]


def test_occurrences_rejects_naive_start(monitor):
    with pytest.raises(AsOfError):
        monitor.occurrences("SYN_T1", datetime(2026, 1, 1), _utc(31))


def test_occurrences_rejects_naive_end(monitor):
    with pytest.raises(AsOfError):
        monitor.occurrences("SYN_T1", _utc(1), datetime(2026, 1, 31))


def test_occurrence_summary_counts_by_form_type(monitor):
    monitor.ingest_filing(_filing("SYN_A", form_type="SYN_10K", accepted_at=_utc(12)))
    monitor.ingest_filing(_filing("SYN_B", form_type="SYN_10K", accepted_at=_utc(13)))
    monitor.ingest_filing(_filing("SYN_C", form_type="SYN_8K", accepted_at=_utc(14)))
    monitor.ingest_filing(_filing("SYN_D", form_type="SYN_8K", accepted_at=_utc(30)))
    summary = monitor.occurrence_summary(_utc(10), _utc(15))
    assert summary == {"SYN_10K": 2, "SYN_8K": 1}


def test_occurrence_summary_omits_empty_form_types(monitor):
    monitor.ingest_filing(_filing("SYN_A", form_type="SYN_10K", accepted_at=_utc(12)))
    summary = monitor.occurrence_summary(_utc(10), _utc(15))
    assert "SYN_8K" not in summary
    assert summary == {"SYN_10K": 1}


def test_occurrence_summary_bounds_inclusive(monitor):
    monitor.ingest_filing(_filing("SYN_A", form_type="SYN_10K", accepted_at=_utc(10)))
    monitor.ingest_filing(_filing("SYN_B", form_type="SYN_10K", accepted_at=_utc(15)))
    assert monitor.occurrence_summary(_utc(10), _utc(15)) == {"SYN_10K": 2}


def test_occurrence_summary_empty_window_returns_empty_dict(monitor):
    monitor.ingest_filing(_filing("SYN_A", accepted_at=_utc(12)))
    assert monitor.occurrence_summary(_utc(20), _utc(25)) == {}


def test_occurrence_summary_rejects_naive_bounds(monitor):
    with pytest.raises(AsOfError):
        monitor.occurrence_summary(datetime(2026, 1, 1), _utc(31))


def test_constructor_rejects_non_register():
    with pytest.raises(AsOfError):
        FilingMonitor({"SYN_S1": object()})


def test_ingest_rejects_non_filing_record(monitor):
    with pytest.raises(AsOfError):
        monitor.ingest_filing({"filing_id": "SYN_F1"})


def test_no_function_name_contains_score_material_or_rank():
    names = []
    for name, obj in vars(fm).items():
        if inspect.isfunction(obj) and obj.__module__ == fm.__name__:
            names.append(name)
        elif inspect.isclass(obj) and obj.__module__ == fm.__name__:
            names.extend(
                n for n, m in vars(obj).items()
                if inspect.isfunction(m) or isinstance(m, (staticmethod, classmethod))
            )
    assert names, "expected the module to define functions or methods"
    banned = ("score", "material", "rank")
    for name in names:
        lowered = name.lower()
        for word in banned:
            assert word not in lowered, "function %r contains %r" % (name, word)
