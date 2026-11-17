"""Tests for as_of.earnings_fixture. All fixtures are synthetic (SYN_ prefix)."""

from datetime import timezone

import pytest

from as_of.core import AsOfError, EstimateRecord, SourceRecord, SourceType
from as_of.earnings_fixture import METRICS, N_ANALYSTS, make_fixture


def _report_key(rep):
    return (rep["ticker"], rep["metric"], rep["period"])


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_two_calls_with_same_seed_return_equal_output():
    first = make_fixture(seed=20261027)
    second = make_fixture(seed=20261027)
    assert first == second


def test_every_source_is_synthetic_fixture():
    fixture = make_fixture()
    assert fixture["sources"], "fixture should contain sources"
    for src in fixture["sources"]:
        assert isinstance(src, SourceRecord)
        assert src.synthetic is True
        assert src.source_type == SourceType.FIXTURE


def test_every_report_has_an_estimate_known_before_reported_at():
    fixture = make_fixture()
    by_key = {}
    for est in fixture["estimates"]:
        by_key.setdefault((est.ticker, est.metric, est.period), []).append(est)
    assert fixture["reports"], "fixture should contain reports"
    for rep in fixture["reports"]:
        matches = by_key.get(_report_key(rep), [])
        assert matches, "no estimates for report %r" % (_report_key(rep),)
        assert any(est.knowledge_at < rep["reported_at"] for est in matches), (
            "no estimate known before reported_at for %r" % (_report_key(rep),)
        )


def test_all_tickers_start_with_syn_prefix():
    fixture = make_fixture()
    tickers = {est.ticker for est in fixture["estimates"]}
    tickers |= {rep["ticker"] for rep in fixture["reports"]}
    assert tickers
    for ticker in tickers:
        assert ticker.startswith("SYN_"), ticker


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_default_call_shape_matches_defaults():
    fixture = make_fixture()
    n_tickers, n_quarters = 3, 4
    assert len(fixture["sources"]) == 2 * n_tickers
    assert len(fixture["reports"]) == n_tickers * n_quarters * len(METRICS)
    assert len(fixture["estimates"]) == (
        n_tickers * n_quarters * len(METRICS) * N_ANALYSTS
    )


def test_different_seed_changes_values():
    a = make_fixture(seed=1)
    b = make_fixture(seed=2)
    assert a["reports"] != b["reports"]


def test_record_types_and_timezones():
    fixture = make_fixture(n_tickers=1, n_quarters=2)
    for est in fixture["estimates"]:
        assert isinstance(est, EstimateRecord)
        assert est.knowledge_at.tzinfo is not None
        assert est.knowledge_at.utcoffset() == timezone.utc.utcoffset(None)
    for rep in fixture["reports"]:
        assert rep["reported_at"].tzinfo is not None
        assert rep["reported_at"].utcoffset() == timezone.utc.utcoffset(None)


def test_every_estimate_references_a_registered_source():
    fixture = make_fixture()
    source_ids = {src.source_id for src in fixture["sources"]}
    for est in fixture["estimates"]:
        assert est.source_id in source_ids


def test_every_estimate_maps_to_a_report():
    fixture = make_fixture()
    report_keys = {_report_key(rep) for rep in fixture["reports"]}
    for est in fixture["estimates"]:
        assert (est.ticker, est.metric, est.period) in report_keys


def test_single_ticker_single_quarter_is_valid():
    fixture = make_fixture(n_tickers=1, n_quarters=1)
    tickers = {rep["ticker"] for rep in fixture["reports"]}
    assert tickers == {"SYN_T01"}
    assert {rep["period"] for rep in fixture["reports"]} == {"2025Q1"}


def test_ticker_names_are_sequential():
    fixture = make_fixture(n_tickers=4, n_quarters=1)
    tickers = sorted({rep["ticker"] for rep in fixture["reports"]})
    assert tickers == ["SYN_T01", "SYN_T02", "SYN_T03", "SYN_T04"]


def test_periods_roll_over_to_next_year():
    fixture = make_fixture(n_tickers=1, n_quarters=5)
    periods = sorted({rep["period"] for rep in fixture["reports"]})
    assert periods == ["2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1"]


@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_n_tickers_raises(bad):
    with pytest.raises(AsOfError):
        make_fixture(n_tickers=bad)


@pytest.mark.parametrize("bad", [0, -2])
def test_non_positive_n_quarters_raises(bad):
    with pytest.raises(AsOfError):
        make_fixture(n_quarters=bad)


def test_non_int_n_tickers_raises():
    with pytest.raises(AsOfError):
        make_fixture(n_tickers=2.0)
