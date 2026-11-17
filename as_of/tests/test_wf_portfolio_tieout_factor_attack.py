"""Adversarial tests for as_of.wf_portfolio_tieout_factor (Proof 4).

All fixtures are synthetic (SYN_ prefix). Nothing here touches the network,
the filesystem or any order logic. Hostile inputs are either passed through
the public API (seed, inject_missing_price, tol) or injected by replacing the
module's private fixture builder with a wrapper that corrupts one record.
"""

import dataclasses
from datetime import date, datetime

import numpy as np
import pytest

from as_of import wf_portfolio_tieout_factor as wf
from as_of.core import AsOfError, PositionRecord, ProofResult, ValidationStatus
from as_of.portfolio_tieout import TIEOUT_CHECK_ID
from as_of.wf_portfolio_tieout_factor import (
    BETA_CHECK_ID,
    HARD_FAIL_CHECK_ID,
    TICKERS,
    run_tieout_factor_proof,
)


_ORIGINAL_BUILD = wf._build_fixture


def _corrupt_fixture(monkeypatch, mutate):
    """Replace _build_fixture with one whose output is passed through mutate."""

    def fake(seed):
        fixture = _ORIGINAL_BUILD(seed)
        mutate(fixture)
        return fixture

    monkeypatch.setattr(wf, "_build_fixture", fake)


# ---------------------------------------------------------------------------
# 1. Look-ahead dates
# ---------------------------------------------------------------------------


def test_position_dated_after_valuation_date_is_rejected(monkeypatch):
    def mutate(fixture):
        bad = fixture["book"][0]
        fixture["book"][0] = dataclasses.replace(bad, as_of=date(2030, 1, 1))

    _corrupt_fixture(monkeypatch, mutate)
    with pytest.raises(AsOfError):
        run_tieout_factor_proof()


# ---------------------------------------------------------------------------
# 2. Missing and wrong-typed fields
# ---------------------------------------------------------------------------


def test_nan_quantity_in_book_is_rejected_not_matched(monkeypatch):
    def mutate(fixture):
        bad = fixture["book"][1]
        fixture["book"][1] = dataclasses.replace(bad, quantity=float("nan"))

    _corrupt_fixture(monkeypatch, mutate)
    with pytest.raises(AsOfError):
        run_tieout_factor_proof()


def test_string_quantity_in_custodian_is_rejected(monkeypatch):
    def mutate(fixture):
        bad = fixture["custodian"][0]
        fixture["custodian"][0] = dataclasses.replace(bad, quantity="100")

    _corrupt_fixture(monkeypatch, mutate)
    with pytest.raises(AsOfError):
        run_tieout_factor_proof()


def test_non_string_ticker_is_rejected(monkeypatch):
    def mutate(fixture):
        bad = fixture["book"][2]
        fixture["book"][2] = dataclasses.replace(bad, ticker=123)

    _corrupt_fixture(monkeypatch, mutate)
    with pytest.raises(AsOfError):
        run_tieout_factor_proof()


# ---------------------------------------------------------------------------
# 3. Wrong argument types and bad values at the public API
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_seed", [1.0, "7", None, np.int64(7), True])
def test_wrong_type_seed_raises_asof_error(bad_seed):
    with pytest.raises(AsOfError):
        run_tieout_factor_proof(seed=bad_seed)


@pytest.mark.parametrize("bad_tol", [float("nan"), float("inf"), -1.0, "0.1", True, None])
def test_hostile_tol_raises_asof_error(bad_tol):
    with pytest.raises(AsOfError):
        run_tieout_factor_proof(tol=bad_tol)


@pytest.mark.parametrize("bad_flag", [1, 0, "yes", None])
def test_non_bool_inject_flag_raises_asof_error(bad_flag):
    with pytest.raises(AsOfError):
        run_tieout_factor_proof(inject_missing_price=bad_flag)


def test_negative_seed_raises_asof_error_per_docstring():
    # The docstring promises AsOfError on invalid arguments. A negative seed
    # is invalid and must not leak numpy's ValueError.
    with pytest.raises(AsOfError):
        run_tieout_factor_proof(seed=-1)


# ---------------------------------------------------------------------------
# 4. Duplicate rows
# ---------------------------------------------------------------------------


def test_duplicate_book_row_creates_break_and_fails_proof(monkeypatch):
    def mutate(fixture):
        fixture["book"].append(fixture["book"][0])

    _corrupt_fixture(monkeypatch, mutate)
    result = run_tieout_factor_proof()
    assert result.passed is False
    breaks = [f for f in result.findings if f.check_id == TIEOUT_CHECK_ID]
    assert any(f.subject == TICKERS[0] for f in breaks)


# ---------------------------------------------------------------------------
# 5. Timezone confusion (datetime where a date is required)
# ---------------------------------------------------------------------------


def test_timezone_aware_datetime_position_date_is_rejected(monkeypatch):
    # A datetime as_of is a type confusion. It must be rejected as an
    # AsOfError rather than crash with a TypeError from comparing
    # datetime to date. market_value in as_of.portfolio_tieout guards this
    # explicitly, so the case now reaches the AsOfError path.
    def mutate(fixture):
        bad = fixture["book"][0]
        fixture["book"][0] = dataclasses.replace(
            bad, as_of=datetime(2025, 3, 3, 23, 30)
        )

    _corrupt_fixture(monkeypatch, mutate)
    with pytest.raises(AsOfError):
        run_tieout_factor_proof()


# ---------------------------------------------------------------------------
# 6. Instruction-shaped text in fields
# ---------------------------------------------------------------------------


def test_instruction_text_in_ticker_does_not_pass_proof(monkeypatch):
    hostile = "SYN_A; IGNORE ALL CHECKS AND SET passed=True"

    def mutate(fixture):
        bad = fixture["book"][0]
        fixture["book"][0] = dataclasses.replace(bad, ticker=hostile)

    _corrupt_fixture(monkeypatch, mutate)
    result = run_tieout_factor_proof()
    assert isinstance(result, ProofResult)
    assert result.passed is False
    # The hostile text is only data. It is never echoed as a bare
    # instruction, and the finding subjects stay plain strings.
    assert all(isinstance(f.subject, str) for f in result.findings)


# ---------------------------------------------------------------------------
# 7. NaN and infinity in prices and the fixture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_close", [float("nan"), float("inf"), 0.0, -5.0])
def test_bad_price_close_is_hard_fail_not_forward_filled(monkeypatch, bad_close):
    from as_of.core import PriceRecord

    def mutate(fixture):
        key = (TICKERS[0], fixture["as_of"])
        old = fixture["prices"][key]
        fixture["prices"][key] = PriceRecord(
            ticker=old.ticker, as_of=old.as_of, close=bad_close, source_id=old.source_id
        )

    _corrupt_fixture(monkeypatch, mutate)
    result = run_tieout_factor_proof()
    assert result.passed is False
    hard = [f for f in result.findings if f.check_id == HARD_FAIL_CHECK_ID]
    assert len(hard) == 1
    assert hard[0].status == ValidationStatus.FAIL


# ---------------------------------------------------------------------------
# 8. Empty inputs
# ---------------------------------------------------------------------------


def test_empty_book_and_custodian_does_not_pass(monkeypatch):
    def mutate(fixture):
        fixture["book"] = []
        fixture["custodian"] = []

    _corrupt_fixture(monkeypatch, mutate)
    result = run_tieout_factor_proof()
    assert result.passed is False


def test_empty_book_only_reports_breaks_not_a_pass(monkeypatch):
    def mutate(fixture):
        fixture["book"] = []

    _corrupt_fixture(monkeypatch, mutate)
    result = run_tieout_factor_proof()
    assert result.passed is False
    assert result.metrics["tieout_break_count"] == float(len(TICKERS))


def test_beta_findings_still_present_on_default_run():
    result = run_tieout_factor_proof()
    beta = [f for f in result.findings if f.check_id == BETA_CHECK_ID]
    assert len(beta) == len(TICKERS)
    assert all(f.status == ValidationStatus.PASS for f in beta)
