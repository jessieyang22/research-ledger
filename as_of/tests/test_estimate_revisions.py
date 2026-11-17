"""Tests for as_of.estimate_revisions. All fixtures are synthetic and use the SYN_ prefix."""

from datetime import datetime, timezone

import pytest

from as_of.core import AsOfError, EstimateRecord
from as_of.estimate_revisions import (
    consensus_series,
    revision_breadth,
    revision_history,
)

TICKER = "SYN_AAA"
METRIC = "eps"
PERIOD = "2027Q1"


def _ts(day):
    return datetime(2026, 10, day, 12, 0, 0, tzinfo=timezone.utc)


def _rec(idx, analyst, value, day, ticker=TICKER, metric=METRIC, period=PERIOD):
    return EstimateRecord(
        estimate_id="SYN_EST_%03d" % idx,
        ticker=ticker,
        metric=metric,
        period=period,
        analyst_id=analyst,
        value=value,
        knowledge_at=_ts(day),
        source_id="SYN_SRC_01",
    )


def test_revision_history_is_sorted_by_knowledge_time():
    # Records are deliberately written out of knowledge-time order.
    ledger = [
        _rec(1, "SYN_AN_A", 1.30, 20),
        _rec(2, "SYN_AN_A", 1.10, 5),
        _rec(3, "SYN_AN_A", 1.20, 12),
        _rec(4, "SYN_AN_B", 9.99, 1),  # other analyst, must be excluded
    ]
    hist = revision_history(ledger, TICKER, METRIC, PERIOD, "SYN_AN_A")
    assert [t for t, _ in hist] == [_ts(5), _ts(12), _ts(20)]
    assert [v for _, v in hist] == [1.10, 1.20, 1.30]


def test_revision_history_equal_knowledge_times_keep_ledger_order():
    ledger = [
        _rec(1, "SYN_AN_A", 2.0, 7),
        _rec(2, "SYN_AN_A", 3.0, 7),
    ]
    hist = revision_history(ledger, TICKER, METRIC, PERIOD, "SYN_AN_A")
    assert [v for _, v in hist] == [2.0, 3.0]


def test_revision_history_unknown_analyst_or_empty_ledger_is_empty():
    ledger = [_rec(1, "SYN_AN_A", 1.0, 3)]
    assert revision_history(ledger, TICKER, METRIC, PERIOD, "SYN_AN_Z") == []
    assert revision_history([], TICKER, METRIC, PERIOD, "SYN_AN_A") == []


def test_revision_breadth_counts_up_down_unchanged_on_hand_built_ledger():
    ledger = [
        # Analyst A: 1.0 before the window (day 5), 2.0 inside it -> up.
        _rec(1, "SYN_AN_A", 1.0, 1),
        _rec(2, "SYN_AN_A", 2.0, 8),
        # Analyst B: 3.0 before the window, 2.5 inside it -> down.
        _rec(3, "SYN_AN_B", 3.0, 2),
        _rec(4, "SYN_AN_B", 2.5, 9),
        # Analyst C: 5.0 before the window, re-published 5.0 inside it -> unchanged.
        _rec(5, "SYN_AN_C", 5.0, 3),
        _rec(6, "SYN_AN_C", 5.0, 10),
        # Analyst D: first estimate inside the window -> not a revision, skipped.
        _rec(7, "SYN_AN_D", 7.0, 11),
        # Analyst E: revised inside the window but then back to start value -> unchanged.
        _rec(8, "SYN_AN_E", 4.0, 2),
        _rec(9, "SYN_AN_E", 4.5, 6),
        _rec(10, "SYN_AN_E", 4.0, 12),
    ]
    counts = revision_breadth(
        ledger, TICKER, METRIC, PERIOD, start=_ts(5), end=_ts(12)
    )
    assert counts == {"up": 1, "down": 1, "unchanged": 2}


def test_revision_breadth_window_start_is_exclusive_and_end_inclusive():
    ledger = [
        _rec(1, "SYN_AN_A", 1.0, 2),
        _rec(2, "SYN_AN_A", 2.0, 10),
    ]
    # The revision lands exactly on the end time, so it counts.
    assert revision_breadth(ledger, TICKER, METRIC, PERIOD, _ts(4), _ts(10)) == {
        "up": 1,
        "down": 0,
        "unchanged": 0,
    }
    # The revision lands exactly on the start time, so it is not in the window.
    assert revision_breadth(ledger, TICKER, METRIC, PERIOD, _ts(10), _ts(20)) == {
        "up": 0,
        "down": 0,
        "unchanged": 0,
    }


def test_revision_breadth_with_no_revisions_gives_zero_up_and_down():
    # Each analyst publishes once, so nothing inside the window is a revision.
    ledger = [
        _rec(1, "SYN_AN_A", 1.0, 2),
        _rec(2, "SYN_AN_B", 2.0, 3),
        _rec(3, "SYN_AN_C", 3.0, 15),
    ]
    counts = revision_breadth(ledger, TICKER, METRIC, PERIOD, _ts(1), _ts(10))
    assert counts["up"] == 0
    assert counts["down"] == 0
    assert counts["unchanged"] == 0


def test_revision_breadth_on_empty_ledger_is_all_zero():
    counts = revision_breadth([], TICKER, METRIC, PERIOD, _ts(1), _ts(10))
    assert counts == {"up": 0, "down": 0, "unchanged": 0}


def test_revision_breadth_rejects_start_after_end():
    with pytest.raises(AsOfError):
        revision_breadth([], TICKER, METRIC, PERIOD, _ts(10), _ts(1))


def test_consensus_series_is_none_before_first_estimate():
    ledger = [
        _rec(1, "SYN_AN_A", 2.0, 5),
        _rec(2, "SYN_AN_B", 4.0, 8),
    ]
    dates = [_ts(1), _ts(4), _ts(5), _ts(7), _ts(8)]
    out = consensus_series(ledger, TICKER, METRIC, PERIOD, dates)
    assert out[0] is None
    assert out[1] is None
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(2.0)
    assert out[4] == pytest.approx(3.0)


def test_consensus_series_uses_each_analysts_latest_known_value():
    ledger = [
        _rec(1, "SYN_AN_A", 1.0, 2),
        _rec(2, "SYN_AN_A", 3.0, 9),
        _rec(3, "SYN_AN_B", 5.0, 4),
    ]
    out = consensus_series(ledger, TICKER, METRIC, PERIOD, [_ts(3), _ts(6), _ts(10)])
    assert out[0] == pytest.approx(1.0)
    assert out[1] == pytest.approx(3.0)  # (1.0 + 5.0) / 2
    assert out[2] == pytest.approx(4.0)  # (3.0 + 5.0) / 2


def test_consensus_series_empty_ledger_gives_none_for_every_date():
    out = consensus_series([], TICKER, METRIC, PERIOD, [_ts(1), _ts(2)])
    assert out == [None, None]


def test_consensus_series_ignores_other_tickers_metrics_and_periods():
    ledger = [
        _rec(1, "SYN_AN_A", 2.0, 3),
        _rec(2, "SYN_AN_A", 100.0, 3, ticker="SYN_BBB"),
        _rec(3, "SYN_AN_A", 100.0, 3, metric="revenue"),
        _rec(4, "SYN_AN_A", 100.0, 3, period="2027Q2"),
    ]
    out = consensus_series(ledger, TICKER, METRIC, PERIOD, [_ts(5)])
    assert out == [pytest.approx(2.0)]
