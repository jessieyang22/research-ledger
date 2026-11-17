"""Tests for as_of.reported_vs_expected_bridge. All fixtures are synthetic (SYN_ ids)."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from as_of.core import AsOfError, EstimateRecord
from as_of.reported_vs_expected_bridge import (
    CLASS_BEAT,
    CLASS_INLINE,
    CLASS_MISS,
    CLASS_NO_EXPECTED,
    build_bridge,
    classify_surprise,
)

TICKER = "SYN_AAA"
METRIC = "eps"
PERIOD = "SYN_2026Q2"
REPORTED_AT = datetime(2026, 7, 30, 20, 0, 0, tzinfo=timezone.utc)


def _rec(eid, value, knowledge_at, analyst="SYN_AN1", ticker=TICKER,
         metric=METRIC, period=PERIOD):
    return EstimateRecord(
        estimate_id=eid,
        ticker=ticker,
        metric=metric,
        period=period,
        analyst_id=analyst,
        value=value,
        knowledge_at=knowledge_at,
        source_id="SYN_SRC1",
    )


def _ts(day):
    return datetime(2026, 7, day, 12, 0, 0, tzinfo=timezone.utc)


class _Ledger(object):
    """Ledger-like object exposing its records through a `records` attribute."""

    def __init__(self, records):
        self.records = list(records)


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------

def test_estimates_with_knowledge_after_reported_at_are_excluded_from_expected():
    ledger = [
        _rec("SYN_E1", 1.00, _ts(10), analyst="SYN_AN1"),
        _rec("SYN_E2", 9.00, datetime(2026, 7, 31, 9, 0, 0, tzinfo=timezone.utc),
             analyst="SYN_AN2"),
    ]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 1.50, REPORTED_AT)
    assert out["expected"] == pytest.approx(1.00)
    assert out["basis_as_of"] == _ts(10)


def test_reported_value_above_expected_gives_positive_surprise_and_beat():
    ledger = [_rec("SYN_E1", 2.00, _ts(10))]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 2.50, REPORTED_AT)
    assert out["expected"] == pytest.approx(2.00)
    assert out["surprise_abs"] == pytest.approx(0.50)
    assert out["surprise_pct"] > 0
    assert out["surprise_pct"] == pytest.approx(0.25)
    assert classify_surprise(out["surprise_pct"]) == CLASS_BEAT


def test_exact_match_classifies_as_inline():
    ledger = [_rec("SYN_E1", 2.00, _ts(10))]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 2.00, REPORTED_AT)
    assert out["surprise_abs"] == 0.0
    assert out["surprise_pct"] == 0.0
    assert classify_surprise(out["surprise_pct"]) == CLASS_INLINE


def test_with_no_estimates_expected_and_surprise_fields_are_none():
    out = build_bridge([], TICKER, METRIC, PERIOD, 2.00, REPORTED_AT)
    assert out["expected"] is None
    assert out["surprise_abs"] is None
    assert out["surprise_pct"] is None
    assert out["basis_as_of"] is None
    assert out["reported"] == 2.00
    assert classify_surprise(out["surprise_pct"]) == CLASS_NO_EXPECTED


# ---------------------------------------------------------------------------
# Edge cases: visibility and selection
# ---------------------------------------------------------------------------

def test_knowledge_exactly_at_reported_at_is_not_visible():
    # The spec is "known before the report time", so an estimate stamped at
    # the report instant cannot feed the expected value.
    ledger = [_rec("SYN_E1", 3.00, REPORTED_AT)]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 3.00, REPORTED_AT)
    assert out["expected"] is None
    assert out["basis_as_of"] is None


def test_knowledge_one_microsecond_before_reported_at_is_visible():
    just_before = REPORTED_AT - timedelta(microseconds=1)
    ledger = [_rec("SYN_E1", 3.00, just_before)]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 3.00, REPORTED_AT)
    assert out["expected"] == pytest.approx(3.00)
    assert out["basis_as_of"] == just_before


def test_latest_visible_estimate_per_analyst_is_used():
    ledger = [
        _rec("SYN_E1", 1.00, _ts(5), analyst="SYN_AN1"),
        _rec("SYN_E2", 2.00, _ts(20), analyst="SYN_AN1"),
        _rec("SYN_E3", 4.00, _ts(12), analyst="SYN_AN2"),
    ]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 3.00, REPORTED_AT)
    # SYN_AN1 contributes 2.00 (latest), SYN_AN2 contributes 4.00.
    assert out["expected"] == pytest.approx(3.00)
    assert out["basis_as_of"] == _ts(20)


def test_latest_per_analyst_ignores_later_record_hidden_by_reported_at():
    ledger = [
        _rec("SYN_E1", 1.00, _ts(5), analyst="SYN_AN1"),
        _rec("SYN_E2", 50.00, datetime(2026, 8, 1, tzinfo=timezone.utc),
             analyst="SYN_AN1"),
    ]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 1.00, REPORTED_AT)
    assert out["expected"] == pytest.approx(1.00)
    assert out["basis_as_of"] == _ts(5)


def test_tie_on_knowledge_at_keeps_earlier_record_in_ledger():
    ledger = [
        _rec("SYN_E1", 1.00, _ts(10), analyst="SYN_AN1"),
        _rec("SYN_E2", 7.00, _ts(10), analyst="SYN_AN1"),
    ]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 1.00, REPORTED_AT)
    assert out["expected"] == pytest.approx(1.00)


def test_expected_is_mean_across_analysts():
    ledger = [
        _rec("SYN_E1", 1.00, _ts(10), analyst="SYN_AN1"),
        _rec("SYN_E2", 2.00, _ts(11), analyst="SYN_AN2"),
        _rec("SYN_E3", 6.00, _ts(9), analyst="SYN_AN3"),
    ]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 3.00, REPORTED_AT)
    assert out["expected"] == pytest.approx(3.00)
    assert out["basis_as_of"] == _ts(11)


def test_non_matching_ticker_metric_and_period_are_ignored():
    ledger = [
        _rec("SYN_E1", 1.00, _ts(10)),
        _rec("SYN_E2", 99.00, _ts(10), ticker="SYN_BBB"),
        _rec("SYN_E3", 99.00, _ts(10), metric="revenue"),
        _rec("SYN_E4", 99.00, _ts(10), period="SYN_2026Q3"),
    ]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 1.00, REPORTED_AT)
    assert out["expected"] == pytest.approx(1.00)


def test_ledger_with_records_attribute_is_accepted():
    ledger = _Ledger([_rec("SYN_E1", 2.00, _ts(10))])
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 2.00, REPORTED_AT)
    assert out["expected"] == pytest.approx(2.00)


def test_none_ledger_behaves_like_no_estimates():
    out = build_bridge(None, TICKER, METRIC, PERIOD, 2.00, REPORTED_AT)
    assert out["expected"] is None
    assert out["surprise_pct"] is None


# ---------------------------------------------------------------------------
# Edge cases: surprise arithmetic
# ---------------------------------------------------------------------------

def test_zero_expected_gives_none_surprise_pct_but_keeps_surprise_abs():
    ledger = [_rec("SYN_E1", 0.00, _ts(10))]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 0.40, REPORTED_AT)
    assert out["expected"] == 0.0
    assert out["surprise_abs"] == pytest.approx(0.40)
    assert out["surprise_pct"] is None
    assert classify_surprise(out["surprise_pct"]) == CLASS_NO_EXPECTED


def test_negative_expected_uses_abs_in_percent_surprise():
    ledger = [_rec("SYN_E1", -2.00, _ts(10))]
    # Reported is less negative than expected: a positive surprise.
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, -1.00, REPORTED_AT)
    assert out["surprise_abs"] == pytest.approx(1.00)
    assert out["surprise_pct"] == pytest.approx(0.50)
    assert classify_surprise(out["surprise_pct"]) == CLASS_BEAT


def test_reported_below_expected_gives_negative_surprise_and_miss():
    ledger = [_rec("SYN_E1", 2.00, _ts(10))]
    out = build_bridge(ledger, TICKER, METRIC, PERIOD, 1.00, REPORTED_AT)
    assert out["surprise_abs"] == pytest.approx(-1.00)
    assert out["surprise_pct"] == pytest.approx(-0.50)
    assert classify_surprise(out["surprise_pct"]) == CLASS_MISS


def test_reported_value_is_returned_as_float():
    out = build_bridge([], TICKER, METRIC, PERIOD, 4, REPORTED_AT)
    assert isinstance(out["reported"], float)
    assert out["reported"] == 4.0


# ---------------------------------------------------------------------------
# Edge cases: input validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_reported_value_raises(bad):
    with pytest.raises(AsOfError):
        build_bridge([], TICKER, METRIC, PERIOD, bad, REPORTED_AT)


@pytest.mark.parametrize("bad", ["2.0", None, True])
def test_non_numeric_reported_value_raises(bad):
    with pytest.raises(AsOfError):
        build_bridge([], TICKER, METRIC, PERIOD, bad, REPORTED_AT)


def test_naive_reported_at_raises():
    with pytest.raises(AsOfError):
        build_bridge([], TICKER, METRIC, PERIOD, 1.0, datetime(2026, 7, 30, 20, 0, 0))


# ---------------------------------------------------------------------------
# classify_surprise
# ---------------------------------------------------------------------------

def test_classify_none_is_no_expected():
    assert classify_surprise(None) == CLASS_NO_EXPECTED


def test_classify_default_threshold_zero_splits_on_sign():
    assert classify_surprise(0.0001) == CLASS_BEAT
    assert classify_surprise(-0.0001) == CLASS_MISS
    assert classify_surprise(0.0) == CLASS_INLINE


def test_classify_band_boundaries_are_inline():
    assert classify_surprise(0.05, threshold=0.05) == CLASS_INLINE
    assert classify_surprise(-0.05, threshold=0.05) == CLASS_INLINE
    assert classify_surprise(0.0501, threshold=0.05) == CLASS_BEAT
    assert classify_surprise(-0.0501, threshold=0.05) == CLASS_MISS


@pytest.mark.parametrize("bad", [-0.1, float("nan"), float("inf"), "0.1", True])
def test_classify_rejects_invalid_threshold(bad):
    with pytest.raises(AsOfError):
        classify_surprise(0.1, threshold=bad)


def test_classify_result_is_string_label():
    assert isinstance(classify_surprise(0.2), str)
    assert math.isfinite(0.2)
