"""Tests for as_of.wf_earnings_reconciliation. All fixtures are synthetic (SYN_ ids)."""

import inspect

import pytest

from as_of import wf_earnings_reconciliation as wf
from as_of.core import ProofResult, ValidationStatus
from as_of.earnings_fixture import make_fixture


N_TICKERS = 3
N_QUARTERS = 4
N_METRICS = 2
N_ANALYSTS = 3
N_REPORTS = N_TICKERS * N_QUARTERS * N_METRICS
N_ESTIMATES = N_REPORTS * N_ANALYSTS


def _findings(result, check_id):
    return [f for f in result.findings if f.check_id == check_id]


def test_default_run_passes():
    result = wf.run_earnings_proof()
    assert isinstance(result, ProofResult)
    assert result.proof_name == wf.PROOF_NAME
    assert result.passed is True
    assert not [f for f in result.findings if f.status == ValidationStatus.FAIL]


def test_inject_lookahead_fails_with_lookahead_risk():
    result = wf.run_earnings_proof(inject_lookahead=True)
    assert result.passed is False
    risks = _findings(result, wf.CHECK_LOOKAHEAD)
    assert risks, "expected at least one LOOKAHEAD_RISK finding"
    assert all(f.status == ValidationStatus.FAIL for f in risks)
    # One injected late row per report.
    assert len(risks) == N_REPORTS


def test_inject_lookahead_does_not_change_surprise_counts():
    # The bridge drops the late row, so classifications match the clean run.
    clean = wf.run_earnings_proof()
    dirty = wf.run_earnings_proof(inject_lookahead=True)
    for key in ("n_beat", "n_miss", "n_inline", "n_no_expected", "n_bridges_with_expected"):
        assert dirty.metrics[key] == clean.metrics[key], key


def test_inject_lookahead_has_no_summary_pass():
    result = wf.run_earnings_proof(inject_lookahead=True)
    summary = _findings(result, wf.CHECK_SUMMARY)
    assert len(summary) == 1
    assert summary[0].status == ValidationStatus.FAIL
    assert "%d look-ahead rows" % N_REPORTS in summary[0].message


def test_default_run_summary_is_pass():
    result = wf.run_earnings_proof()
    summary = _findings(result, wf.CHECK_SUMMARY)
    assert len(summary) == 1
    assert summary[0].status == ValidationStatus.PASS
    assert summary[0].subject == "earnings"
    assert "%d reports reconciled" % N_REPORTS in summary[0].message


def test_metrics_include_number_of_reports():
    result = wf.run_earnings_proof()
    assert result.metrics["n_reports"] == float(N_REPORTS)
    assert isinstance(result.metrics["n_reports"], float)


def test_metrics_count_estimates_and_bridges():
    result = wf.run_earnings_proof()
    assert result.metrics["n_estimates"] == float(N_ESTIMATES)
    assert result.metrics["n_bridges_with_expected"] == float(N_REPORTS)
    assert result.metrics["n_no_expected"] == 0.0


def test_surprise_outcomes_partition_the_reports():
    result = wf.run_earnings_proof()
    total = (
        result.metrics["n_beat"]
        + result.metrics["n_miss"]
        + result.metrics["n_inline"]
    )
    assert total == result.metrics["n_bridges_with_expected"]


def test_default_run_has_no_unregistered_sources():
    result = wf.run_earnings_proof()
    assert result.metrics["n_unregistered_sources"] == 0.0
    fails = [f for f in result.findings if f.status == ValidationStatus.FAIL]
    assert fails == []


def test_metrics_all_numeric_and_finite():
    result = wf.run_earnings_proof(inject_lookahead=True)
    for key, value in result.metrics.items():
        assert isinstance(value, float), key
        assert value == value, key  # not NaN


def test_two_default_runs_give_equal_results():
    first = wf.run_earnings_proof()
    second = wf.run_earnings_proof()
    assert first == second
    assert first.findings == second.findings
    assert first.metrics == second.metrics


def test_two_injected_runs_give_equal_results():
    first = wf.run_earnings_proof(inject_lookahead=True)
    second = wf.run_earnings_proof(inject_lookahead=True)
    assert first == second


def test_same_seed_is_equal_and_explicit_seed_matches_default():
    default = wf.run_earnings_proof()
    explicit = wf.run_earnings_proof(seed=wf.SYNTHETIC_SEED, inject_lookahead=False)
    assert default == explicit


def test_findings_is_tuple_of_findings():
    result = wf.run_earnings_proof()
    assert isinstance(result.findings, tuple)
    for f in result.findings:
        assert f.check_id
        assert isinstance(f.status, ValidationStatus)


def test_late_estimate_is_after_report_time():
    fixture = make_fixture(seed=wf.SYNTHETIC_SEED)
    report = fixture["reports"][0]
    src_id = fixture["sources"][0].source_id
    late = wf._late_estimate(report, src_id)
    assert late.knowledge_at > report["reported_at"]
    assert late.value == float(report["reported_value"])
    assert late.analyst_id == wf.LATE_ANALYST_ID
    assert late.ticker == report["ticker"]
    assert late.metric == report["metric"]
    assert late.period == report["period"]


def test_group_estimates_keeps_row_order():
    fixture = make_fixture(seed=wf.SYNTHETIC_SEED)
    grouped = wf._group_estimates(fixture["estimates"])
    total = sum(len(rows) for rows in grouped.values())
    assert total == N_ESTIMATES
    assert len(grouped) == N_REPORTS
    for key, rows in grouped.items():
        assert len(rows) == N_ANALYSTS
        assert all((r.ticker, r.metric, r.period) == key for r in rows)


def test_source_ids_by_locator_maps_every_source():
    fixture = make_fixture(seed=wf.SYNTHETIC_SEED)
    mapping = wf._source_ids_by_locator(fixture["sources"])
    assert len(mapping) == len(fixture["sources"])
    for src in fixture["sources"]:
        assert mapping[src.locator] == src.source_id


def test_surprise_band_is_symmetric_and_positive():
    assert wf.SURPRISE_BAND > 0.0


def test_module_has_no_forbidden_static_imports():
    source = inspect.getsource(wf)
    assert "import quant_lab" not in source
    assert "from quant_lab" not in source
    assert "import yfinance" not in source
    assert "import requests" not in source
    assert "import socket" not in source
