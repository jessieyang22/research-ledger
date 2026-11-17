"""Tests for as_of.estimate_ledger. All fixtures are synthetic and use the SYN_ prefix.

Topic: "estimate ledger and revisions".
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from as_of.core import AsOfError, EstimateRecord, ValidationStatus
from as_of.estimate_ledger import (
    CHECK_CLEAN,
    CHECK_NAIVE_TIME,
    CHECK_NO_ROWS,
    CHECK_NON_FINITE,
    EstimateLedger,
)

UTC = timezone.utc
T0 = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)


def _rec(
    analyst="SYN_A1",
    value=10.0,
    knowledge_at=T0,
    ticker="SYN_TKR",
    metric="eps",
    period="SYN_2026Q1",
    estimate_id=None,
    source_id="SYN_SRC_1",
):
    return EstimateRecord(
        estimate_id=estimate_id or "SYN_EST_%s_%s" % (analyst, knowledge_at.isoformat()),
        ticker=ticker,
        metric=metric,
        period=period,
        analyst_id=analyst,
        value=value,
        knowledge_at=knowledge_at,
        source_id=source_id,
    )


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_appending_duplicate_row_raises_asof_error():
    ledger = EstimateLedger()
    ledger.append(_rec(value=10.0))
    with pytest.raises(AsOfError):
        ledger.append(_rec(value=12.0))  # same analyst, series and knowledge_at
    assert len(ledger.rows("SYN_TKR", "eps", "SYN_2026Q1")) == 1


def test_consensus_as_of_excludes_estimates_known_after_as_of():
    ledger = EstimateLedger()
    ledger.append(_rec(analyst="SYN_A1", value=10.0, knowledge_at=T0))
    ledger.append(_rec(analyst="SYN_A2", value=20.0, knowledge_at=T0 + timedelta(days=5)))
    ledger.append(_rec(analyst="SYN_A3", value=100.0, knowledge_at=T0 + timedelta(days=10)))

    # Only A1 is known on day 1. A2 and A3 must be excluded.
    assert ledger.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", T0 + timedelta(days=1)) == 10.0
    # A1 and A2 are known on day 6, so the mean is 15.
    assert ledger.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", T0 + timedelta(days=6)) == 15.0


def test_consensus_as_of_equals_mean_of_each_analysts_latest_estimate():
    ledger = EstimateLedger()
    # A1 revises twice. A2 once. Only each analyst's latest should count.
    ledger.append(_rec(analyst="SYN_A1", value=10.0, knowledge_at=T0))
    ledger.append(_rec(analyst="SYN_A1", value=12.0, knowledge_at=T0 + timedelta(days=2)))
    ledger.append(_rec(analyst="SYN_A1", value=14.0, knowledge_at=T0 + timedelta(days=4)))
    ledger.append(_rec(analyst="SYN_A2", value=20.0, knowledge_at=T0 + timedelta(days=1)))
    ledger.append(_rec(analyst="SYN_A2", value=18.0, knowledge_at=T0 + timedelta(days=3)))

    as_of = T0 + timedelta(days=10)
    latest = ledger.latest_per_analyst("SYN_TKR", "eps", "SYN_2026Q1", as_of)
    assert [r.value for r in latest] == [14.0, 18.0]

    expected = (14.0 + 18.0) / 2.0
    assert ledger.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", as_of) == pytest.approx(expected)

    # Between A1's second and third revision, A1 should contribute 12.
    mid = T0 + timedelta(days=3, hours=12)
    assert ledger.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", mid) == pytest.approx((12.0 + 18.0) / 2.0)


def test_revision_adds_a_row_and_keeps_the_earlier_row():
    ledger = EstimateLedger()
    original = _rec(analyst="SYN_A1", value=10.0, knowledge_at=T0, estimate_id="SYN_EST_ORIG")
    revision = _rec(analyst="SYN_A1", value=11.5, knowledge_at=T0 + timedelta(days=7), estimate_id="SYN_EST_REV")
    ledger.append(original)
    ledger.append(revision)

    rows = ledger.rows("SYN_TKR", "eps", "SYN_2026Q1")
    assert len(rows) == 2
    assert [r.estimate_id for r in rows] == ["SYN_EST_ORIG", "SYN_EST_REV"]
    assert [r.value for r in rows] == [10.0, 11.5]

    # Point-in-time views see the right version of the same analyst's estimate.
    before = ledger.latest_per_analyst("SYN_TKR", "eps", "SYN_2026Q1", T0 + timedelta(days=1))
    after = ledger.latest_per_analyst("SYN_TKR", "eps", "SYN_2026Q1", T0 + timedelta(days=8))
    assert [r.value for r in before] == [10.0]
    assert [r.value for r in after] == [11.5]


# ---------------------------------------------------------------------------
# Edge cases: writes
# ---------------------------------------------------------------------------


def test_append_rejects_non_estimate_record():
    ledger = EstimateLedger()
    with pytest.raises(AsOfError):
        ledger.append({"ticker": "SYN_TKR"})


def test_append_rejects_naive_knowledge_at():
    ledger = EstimateLedger()
    naive = datetime(2026, 1, 10, 9, 0)
    with pytest.raises(AsOfError):
        ledger.append(_rec(knowledge_at=naive))
    assert ledger.rows("SYN_TKR", "eps", "SYN_2026Q1") == []


def test_same_instant_in_different_timezone_is_a_duplicate():
    ledger = EstimateLedger()
    ledger.append(_rec(value=10.0, knowledge_at=T0))
    # Same instant expressed in UTC+5. Normalisation should make this a duplicate.
    plus_five = timezone(timedelta(hours=5))
    same_instant = T0.astimezone(plus_five)
    with pytest.raises(AsOfError):
        ledger.append(_rec(value=10.0, knowledge_at=same_instant))


def test_same_analyst_different_series_is_not_a_duplicate():
    ledger = EstimateLedger()
    ledger.append(_rec(analyst="SYN_A1", metric="eps"))
    ledger.append(_rec(analyst="SYN_A1", metric="revenue"))
    ledger.append(_rec(analyst="SYN_A1", period="SYN_2026Q2"))
    assert len(ledger.rows("SYN_TKR", "eps", "SYN_2026Q1")) == 1
    assert len(ledger.rows("SYN_TKR", "revenue", "SYN_2026Q1")) == 1
    assert len(ledger.rows("SYN_TKR", "eps", "SYN_2026Q2")) == 1


def test_append_stores_knowledge_at_as_utc():
    ledger = EstimateLedger()
    plus_five = timezone(timedelta(hours=5))
    ledger.append(_rec(value=10.0, knowledge_at=T0.astimezone(plus_five)))
    stored = ledger.rows("SYN_TKR", "eps", "SYN_2026Q1")[0]
    assert stored.knowledge_at.utcoffset() == timedelta(0)
    assert stored.knowledge_at == T0


# ---------------------------------------------------------------------------
# Edge cases: reads
# ---------------------------------------------------------------------------


def test_rows_sorted_by_knowledge_then_analyst():
    ledger = EstimateLedger()
    ledger.append(_rec(analyst="SYN_B", knowledge_at=T0 + timedelta(days=2)))
    ledger.append(_rec(analyst="SYN_A", knowledge_at=T0 + timedelta(days=2)))
    ledger.append(_rec(analyst="SYN_C", knowledge_at=T0))
    rows = ledger.rows("SYN_TKR", "eps", "SYN_2026Q1")
    assert [r.analyst_id for r in rows] == ["SYN_C", "SYN_A", "SYN_B"]


def test_rows_returns_empty_for_unknown_series():
    ledger = EstimateLedger()
    ledger.append(_rec())
    assert ledger.rows("SYN_OTHER", "eps", "SYN_2026Q1") == []


def test_consensus_none_when_no_analyst_known_by_as_of():
    ledger = EstimateLedger()
    ledger.append(_rec(knowledge_at=T0 + timedelta(days=5)))
    assert ledger.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", T0) is None


def test_consensus_none_for_empty_ledger():
    ledger = EstimateLedger()
    assert ledger.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", T0) is None


def test_knowledge_exactly_at_as_of_is_included():
    ledger = EstimateLedger()
    ledger.append(_rec(value=7.0, knowledge_at=T0))
    assert ledger.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", T0) == 7.0


def test_knowledge_one_second_after_as_of_is_excluded():
    ledger = EstimateLedger()
    ledger.append(_rec(value=7.0, knowledge_at=T0 + timedelta(seconds=1)))
    assert ledger.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", T0) is None


def test_as_of_with_non_utc_offset_is_compared_correctly():
    ledger = EstimateLedger()
    ledger.append(_rec(value=7.0, knowledge_at=T0))  # 09:00 UTC
    # 04:00 at UTC-5 is 09:00 UTC, so the row is known exactly at as_of.
    minus_five = timezone(timedelta(hours=-5))
    as_of = datetime(2026, 1, 10, 4, 0, tzinfo=minus_five)
    assert ledger.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", as_of) == 7.0


def test_as_of_naive_raises():
    ledger = EstimateLedger()
    ledger.append(_rec())
    with pytest.raises(AsOfError):
        ledger.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", datetime(2026, 1, 11))


def test_latest_per_analyst_sorted_by_analyst_id():
    ledger = EstimateLedger()
    ledger.append(_rec(analyst="SYN_Z", value=1.0))
    ledger.append(_rec(analyst="SYN_M", value=2.0))
    ledger.append(_rec(analyst="SYN_B", value=3.0))
    latest = ledger.latest_per_analyst("SYN_TKR", "eps", "SYN_2026Q1", T0 + timedelta(days=1))
    assert [r.analyst_id for r in latest] == ["SYN_B", "SYN_M", "SYN_Z"]


def test_consensus_returns_float_type():
    ledger = EstimateLedger()
    ledger.append(_rec(value=3))
    result = ledger.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", T0)
    assert isinstance(result, float)
    assert result == 3.0


# ---------------------------------------------------------------------------
# Edge cases: validation
# ---------------------------------------------------------------------------


def test_validate_empty_ledger_warns():
    findings = EstimateLedger().validate()
    assert len(findings) == 1
    assert findings[0].check_id == CHECK_NO_ROWS
    assert findings[0].status == ValidationStatus.WARN


def test_validate_clean_ledger_passes():
    ledger = EstimateLedger()
    ledger.append(_rec(analyst="SYN_A1", value=10.0))
    ledger.append(_rec(analyst="SYN_A2", value=11.0))
    findings = ledger.validate()
    assert len(findings) == 1
    assert findings[0].check_id == CHECK_CLEAN
    assert findings[0].status == ValidationStatus.PASS


def test_validate_flags_non_finite_value():
    ledger = EstimateLedger()
    ledger.append(_rec(analyst="SYN_A1", value=float("nan")))
    ledger.append(_rec(analyst="SYN_A2", value=float("inf"), knowledge_at=T0 + timedelta(days=1)))
    findings = ledger.validate()
    bad = [f for f in findings if f.check_id == CHECK_NON_FINITE]
    assert len(bad) == 2
    assert all(f.status == ValidationStatus.FAIL for f in bad)


def test_validate_does_not_pass_when_findings_exist():
    ledger = EstimateLedger()
    ledger.append(_rec(value=math.nan))
    ids = [f.check_id for f in ledger.validate()]
    assert CHECK_CLEAN not in ids
    assert CHECK_NON_FINITE in ids


def test_validate_does_not_report_naive_time_for_appended_rows():
    # append() rejects naive times, so validate() should never see one from
    # a ledger built through the public API.
    ledger = EstimateLedger()
    with pytest.raises(AsOfError):
        ledger.append(_rec(knowledge_at=datetime(2026, 1, 10, 9, 0)))
    ids = [f.check_id for f in ledger.validate()]
    assert CHECK_NAIVE_TIME not in ids
