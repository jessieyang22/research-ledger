"""Tests for as_of.wf_portfolio_tieout_factor (Proof 4). All fixtures are synthetic (SYN_ prefix)."""

import pytest

from as_of.core import SYNTHETIC_SEED, AsOfError, ProofResult, ValidationStatus
from as_of import wf_portfolio_tieout_factor as wf
from as_of.wf_portfolio_tieout_factor import (
    BETA_CHECK_ID,
    BETA_TOL,
    HARD_FAIL_CHECK_ID,
    PROOF_NAME,
    TICKERS,
    run_tieout_factor_proof,
)
from as_of.portfolio_tieout import TIEOUT_CHECK_ID


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_default_run_passes_with_exactly_one_tieout_break():
    result = run_tieout_factor_proof()
    assert isinstance(result, ProofResult)
    assert result.proof_name == PROOF_NAME
    assert result.passed is True
    breaks = [f for f in result.findings if f.check_id == TIEOUT_CHECK_ID]
    assert len(breaks) == 1
    assert breaks[0].status == ValidationStatus.FAIL
    assert breaks[0].subject in TICKERS
    assert result.metrics["tieout_break_count"] == 1.0


def test_inject_missing_price_fails_with_hard_fail_finding():
    result = run_tieout_factor_proof(inject_missing_price=True)
    assert result.passed is False
    hard = [f for f in result.findings if f.check_id == HARD_FAIL_CHECK_ID]
    assert len(hard) == 1
    assert hard[0].status == ValidationStatus.FAIL
    assert "HardFailError" in hard[0].message
    assert "missing price" in hard[0].message
    assert result.metrics["hard_fail_count"] == 1.0
    assert "book_value" not in result.metrics


def test_reproduced_betas_match_fixture_within_tolerance():
    result = run_tieout_factor_proof()
    beta_findings = [f for f in result.findings if f.check_id == BETA_CHECK_ID]
    assert len(beta_findings) == len(TICKERS)
    for finding in beta_findings:
        assert finding.status == ValidationStatus.PASS
    assert result.metrics["beta_max_abs_error"] <= 1e-6
    assert result.metrics["beta_tol"] == BETA_TOL == 1e-6


def test_metrics_include_break_count():
    result = run_tieout_factor_proof()
    assert "tieout_break_count" in result.metrics
    assert result.metrics["tieout_break_count"] == float(
        len([f for f in result.findings if f.check_id == TIEOUT_CHECK_ID])
    )
    assert result.metrics["tieout_matched"] == float(len(TICKERS) - 1)
    assert result.metrics["n_assets"] == float(len(TICKERS))


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_default_seed_is_deterministic():
    a = run_tieout_factor_proof()
    b = run_tieout_factor_proof()
    assert a.passed == b.passed
    assert a.metrics == b.metrics
    assert [(f.check_id, f.subject, f.status, f.message) for f in a.findings] == [
        (f.check_id, f.subject, f.status, f.message) for f in b.findings
    ]


@pytest.mark.parametrize("seed", [1, 2, 3, 17, 20261027])
def test_other_seeds_still_plant_exactly_one_break(seed):
    result = run_tieout_factor_proof(seed=seed)
    assert result.metrics["tieout_break_count"] == 1.0
    assert result.passed is True


def test_planted_break_ticker_is_the_reported_one():
    fixture = wf._build_fixture(SYNTHETIC_SEED)
    result = run_tieout_factor_proof()
    breaks = [f for f in result.findings if f.check_id == TIEOUT_CHECK_ID]
    assert breaks[0].subject == fixture["break_ticker"]


def test_tol_above_break_size_gives_no_break_and_fails():
    # BREAK_SIZE is 250, so a tolerance of 300 hides the planted break.
    result = run_tieout_factor_proof(tol=300.0)
    assert result.metrics["tieout_break_count"] == 0.0
    assert result.passed is False


def test_betas_still_reproduce_when_price_is_missing():
    result = run_tieout_factor_proof(inject_missing_price=True)
    beta_findings = [f for f in result.findings if f.check_id == BETA_CHECK_ID]
    assert len(beta_findings) == len(TICKERS)
    assert all(f.status == ValidationStatus.PASS for f in beta_findings)


def test_invalid_seed_type_raises():
    with pytest.raises(AsOfError):
        run_tieout_factor_proof(seed="1")


def test_bool_seed_raises():
    with pytest.raises(AsOfError):
        run_tieout_factor_proof(seed=True)


def test_non_bool_inject_flag_raises():
    with pytest.raises(AsOfError):
        run_tieout_factor_proof(inject_missing_price=1)


def test_negative_tol_raises():
    with pytest.raises(AsOfError):
        run_tieout_factor_proof(tol=-1.0)
