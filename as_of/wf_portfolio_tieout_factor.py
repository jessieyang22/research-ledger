"""Proof 4: portfolio tie-out and factor exposure reproduction.

This workflow module runs one synthetic proof with three parts.

1. Tie-out. An internal book and a custodian book are compared ticker by
   ticker. The synthetic fixture plants exactly one quantity break, so a
   correct run finds exactly one break and reports it as a FAIL finding.
2. Hard-fail valuation. When inject_missing_price is True, one required price
   cell is removed before valuation. The resulting HardFailError is caught
   and turned into a finding, and the proof does not pass. Nothing is
   forward-filled.
3. Factor exposure reproduction. Betas are re-estimated by ordinary least
   squares from a noise-free synthetic return panel built from planted
   exposures. The reproduced betas must match the planted values within
   BETA_TOL (1e-6). The noise-free panel is used on purpose: with idiosyncratic
   noise, OLS betas differ from the planted values by estimation error, so
   they could not match within 1e-6.

The proof passes only when all of these hold: no hard failure, exactly one
tie-out break and that break is the planted ticker, and every beta is within
BETA_TOL of its planted value.

The design is an original implementation of the idea that a tie-out and a
reproduced exposure should be checked against a fixture with known answers.

Public API:
    run_tieout_factor_proof(seed, inject_missing_price, tol) -> ProofResult

Apart from numpy, only as_of.core and as_of.portfolio_tieout are imported. The
tie-out module brings in as_of.price_hard_fail itself, which is a transitive
dependency and not a direct import here. All data is synthetic (SYN_ ids). The module does
no I/O, makes no network calls and holds no order or trading logic.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from as_of.core import (
    SYNTHETIC_SEED,
    Finding,
    HardFailError,
    PositionRecord,
    PriceRecord,
    ProofResult,
    ValidationStatus,
    require,
)
from as_of.portfolio_tieout import market_value, tie_out, tieout_findings


PROOF_NAME: str = "proof4_portfolio_tieout_factor"
BETA_TOL: float = 1e-6
BETA_CHECK_ID: str = "factor.beta_reproduce"
HARD_FAIL_CHECK_ID: str = "price.hard_fail"

BOOK_LABEL: str = "SYN_BOOK"
CUSTODIAN_LABEL: str = "SYN_CUSTODIAN"
PRICE_SOURCE_ID: str = "SYN_SRC_PX"
TICKERS: Tuple[str, ...] = ("SYN_A", "SYN_B", "SYN_C")
FACTOR_NAMES: Tuple[str, ...] = ("SYN_FACTOR_MKT", "SYN_FACTOR_STYLE")
N_DAYS: int = 40
FIRST_DAY: date = date(2025, 1, 2)
START_PRICE: float = 100.0
FACTOR_VOL: float = 0.01
IDIO_VOL: float = 0.004
BREAK_SIZE: float = 250.0


def _weekdays(n_days: int) -> List[date]:
    """Return n_days consecutive weekdays starting at FIRST_DAY."""
    days: List[date] = []
    cursor = FIRST_DAY
    while len(days) < n_days:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor = cursor + timedelta(days=1)
    return days


def _build_fixture(seed: int) -> Dict[str, Any]:
    """Build the synthetic book, custodian, price, and factor fixture.

    The same seed always gives the same fixture. Every random draw comes from
    one numpy generator.
    """
    rng = np.random.default_rng(seed)
    n_assets = len(TICKERS)
    n_factors = len(FACTOR_NAMES)

    days = _weekdays(N_DAYS)
    as_of = days[-1]

    factor_returns = rng.normal(0.0, FACTOR_VOL, size=(N_DAYS, n_factors))
    exposures = rng.uniform(0.2, 1.4, size=(n_assets, n_factors))
    idio = rng.normal(0.0, IDIO_VOL, size=(N_DAYS, n_assets))
    asset_returns = factor_returns @ exposures.T + idio
    closes = START_PRICE * np.cumprod(1.0 + asset_returns, axis=0)

    # Noise-free panel used for the beta reproduction check.
    exact_returns = factor_returns @ exposures.T

    base_qty = rng.integers(100, 1000, size=n_assets).astype(float)
    break_idx = int(rng.integers(0, n_assets))
    custodian_qty = base_qty.copy()
    custodian_qty[break_idx] = base_qty[break_idx] + BREAK_SIZE

    book: List[PositionRecord] = []
    custodian: List[PositionRecord] = []
    for i, ticker in enumerate(TICKERS):
        book.append(
            PositionRecord(book=BOOK_LABEL, ticker=ticker, quantity=float(base_qty[i]), as_of=as_of)
        )
        custodian.append(
            PositionRecord(
                book=CUSTODIAN_LABEL, ticker=ticker, quantity=float(custodian_qty[i]), as_of=as_of
            )
        )

    prices: Dict[Tuple[str, date], PriceRecord] = {}
    for d_idx, day in enumerate(days):
        for a_idx, ticker in enumerate(TICKERS):
            prices[(ticker, day)] = PriceRecord(
                ticker=ticker,
                as_of=day,
                close=round(float(closes[d_idx, a_idx]), 4),
                source_id=PRICE_SOURCE_ID,
            )

    return {
        "as_of": as_of,
        "book": book,
        "custodian": custodian,
        "break_ticker": TICKERS[break_idx],
        "prices": prices,
        "factor_returns": factor_returns,
        "exact_returns": exact_returns,
        "planted_betas": exposures,
    }


def _ols_betas(returns: np.ndarray, factors: np.ndarray) -> np.ndarray:
    """Estimate betas by least squares with no intercept.

    returns is T x N, factors is T x K. The result is N x K. Invalid shapes
    or a rank-deficient design raise AsOfError through require.
    """
    require(factors.shape[0] == returns.shape[0], "row count mismatch in beta estimation")
    require(
        np.linalg.matrix_rank(factors) == factors.shape[1],
        "factor design is rank deficient",
    )
    coef, _, _, _ = np.linalg.lstsq(factors, returns, rcond=None)
    return coef.T.copy()


def _beta_findings(
    tickers: Sequence[str],
    estimated: np.ndarray,
    planted: np.ndarray,
) -> List[Finding]:
    """Return one PASS or FAIL finding per asset comparing betas to the plant."""
    findings: List[Finding] = []
    for i, ticker in enumerate(tickers):
        err = float(np.max(np.abs(estimated[i] - planted[i])))
        ok = bool(np.isfinite(err) and err <= BETA_TOL)
        findings.append(
            Finding(
                check_id=BETA_CHECK_ID,
                status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
                message="max beta abs error %.3g (tol %.3g)" % (err, BETA_TOL),
                subject=ticker,
            )
        )
    return findings


def run_tieout_factor_proof(
    seed: int = SYNTHETIC_SEED,
    inject_missing_price: bool = False,
    tol: float = 1e-9,
) -> ProofResult:
    """Run Proof 4 on synthetic data and return a ProofResult.

    Args: seed: seed for the synthetic fixture. The valuation then hits
    require_price, which raises HardFailError. The result is caught, recorded
    as a finding, and the proof does not pass. tol: non-negative quantity
    tolerance for the tie-out. A difference larger than tol is a break.

    Returns:
        ProofResult with proof_name, passed, findings and metrics. The
        metrics include tieout_break_count, the number of tie-out breaks, and
        beta_max_abs_error, the largest beta error across assets.

    Raises:
        AsOfError: on invalid arguments.
    """
    require(isinstance(seed, int) and not isinstance(seed, bool), "seed must be an int")
    require(seed >= 0, "seed must be non-negative")
    require(isinstance(inject_missing_price, bool), "inject_missing_price must be a bool")
    require(isinstance(tol, (int, float)) and not isinstance(tol, bool), "tol must be a number")

    fixture = _build_fixture(seed)
    as_of: date = fixture["as_of"]
    findings: List[Finding] = []

    # 1. Tie-out between the internal book and the custodian book.
    tie = tie_out(fixture["book"], fixture["custodian"], tol=float(tol))
    findings.extend(tieout_findings(tie))
    break_count = len(tie["breaks"])
    planted_found = any(b["ticker"] == fixture["break_ticker"] for b in tie["breaks"])
    # tie_out sums repeated tickers, so a duplicated row can hide inside the
    # planted break. Duplicate rows on either side are counted here and block
    # a pass.
    duplicate_rows = 0
    for side in (fixture["book"], fixture["custodian"]):
        tickers_seen = [p.ticker for p in side]
        duplicate_rows += len(tickers_seen) - len(set(tickers_seen))

    # 2. Valuation through the hard-fail price rule.
    prices: Dict[Tuple[str, date], PriceRecord] = dict(fixture["prices"])
    if inject_missing_price:
        del prices[(TICKERS[0], as_of)]
    hard_fail_count = 0
    book_value = None
    try:
        book_value = market_value(fixture["book"], prices, as_of)
    except HardFailError as exc:
        hard_fail_count = 1
        findings.append(
            Finding(
                check_id=HARD_FAIL_CHECK_ID,
                status=ValidationStatus.FAIL,
                message="[block] HardFailError: %s" % (exc,),
                subject="valuation@%s" % as_of.isoformat(),
            )
        )

    # 3. Factor beta reproduction on the noise-free panel.
    estimated = _ols_betas(fixture["exact_returns"], fixture["factor_returns"])
    planted = fixture["planted_betas"]
    max_err = float(np.max(np.abs(estimated - planted)))
    findings.extend(_beta_findings(TICKERS, estimated, planted))

    passed = (
        hard_fail_count == 0
        and duplicate_rows == 0
        and break_count == 1
        and planted_found
        and max_err <= BETA_TOL
    )

    metrics: Dict[str, float] = {
        "tieout_break_count": float(break_count),
        "tieout_matched": float(tie["matched"]),
        "hard_fail_count": float(hard_fail_count),
        "duplicate_rows": float(duplicate_rows),
        "beta_max_abs_error": max_err,
        "beta_tol": BETA_TOL,
        "n_assets": float(len(TICKERS)),
        "n_factors": float(len(FACTOR_NAMES)),
        "tol": float(tol),
    }
    if book_value is not None:
        metrics["book_value"] = float(book_value)

    return ProofResult(
        proof_name=PROOF_NAME,
        passed=bool(passed),
        findings=tuple(findings),
        metrics=metrics,
    )
