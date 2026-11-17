"""Failure mode fm17: missing price becomes zero.

A null price is coerced to zero, which distorts totals and returns. The
detection procedure is to run a seeded test with a missing price and require a
hard failure, with no silent default. All fixtures are synthetic (SYN_
prefix), built from as_of.portfolio_fixture with a fixed seed, and no network
is used.

Detection points checked:
  - A seeded fixture with one missing price cell makes require_price raise
    HardFailError, and an earlier close for the same ticker is not reused.
    (detects, passing)
  - market_value over the book with the missing cell raises HardFailError
    instead of returning a total. (detects, passing)
  - A planted None close, a planted NaN close and a planted zero close each
    raise HardFailError from require_price and from market_value. (detects,
    passing)
  - check_price_panel reports exactly one FAIL for the missing cell and one
    FAIL for a null close, and never reports a valid panel as a gap.
    (detects, passing)
  - run_tieout_factor_proof with inject_missing_price=True does not pass and
    records a price.hard_fail FAIL finding. (detects, passing)
  - No module in the as_of package computes returns from closes, so a null
    close cannot distort a return series through any existing path. The
    return-distortion half of fm17 cannot be tested against real code.
    (gap, xfail)
"""

import copy
import dataclasses

import pytest

from as_of.core import HardFailError, PriceRecord, ValidationStatus
from as_of.portfolio_fixture import make_portfolio_fixture
from as_of.portfolio_tieout import market_value
from as_of.price_hard_fail import PRICE_CHECK_ID, check_price_panel, require_price
from as_of.wf_portfolio_tieout_factor import HARD_FAIL_CHECK_ID, run_tieout_factor_proof

SEED = 17
N_DAYS = 30


def _fixture():
    fx = make_portfolio_fixture(seed=SEED, n_days=N_DAYS)
    prices = {(p.ticker, p.as_of): p for p in fx["prices"]}
    return fx, prices


def _fails(findings):
    return [f for f in findings if f.status is ValidationStatus.FAIL]


def test_fm17_missing_cell_is_hard_fail_not_zero():
    fx, prices = _fixture()
    ticker, day = fx["missing_price"]
    assert (ticker, day) not in prices
    with pytest.raises(HardFailError) as excinfo:
        require_price(prices, ticker, day)
    assert "not forward-filled" in str(excinfo.value)


def test_fm17_missing_cell_is_not_replaced_by_earlier_close():
    fx, prices = _fixture()
    ticker, day = fx["missing_price"]
    earlier = [d for (t, d) in prices if t == ticker and d < day]
    assert earlier, "fixture must have an earlier close for the ticker"
    with pytest.raises(HardFailError):
        require_price(prices, ticker, day)


def test_fm17_valuation_over_missing_cell_raises_instead_of_totalling():
    fx, prices = _fixture()
    ticker, day = fx["missing_price"]
    held = [p for p in fx["positions_book"] if p.ticker == ticker]
    assert held, "missing ticker must be held in the book"
    # Re-date the holding to the gap date so the position check passes and the
    # price lookup is what gets exercised. Valuing on the missing date must
    # stop, not return a total that treats the holding as worth zero.
    positions = [dataclasses.replace(p, as_of=day) for p in held]
    with pytest.raises(HardFailError):
        market_value(positions, prices, day)


@pytest.mark.parametrize(
    "bad_close",
    [None, float("nan"), 0.0, -1.0],
    ids=["none", "nan", "zero", "negative"],
)
def test_fm17_planted_null_close_is_hard_fail(bad_close):
    fx, prices = _fixture()
    ticker, day = fx["positions_book"][0].ticker, fx["positions_book"][0].as_of
    planted = copy.copy(prices)
    planted[(ticker, day)] = PriceRecord(
        ticker=ticker, as_of=day, close=bad_close, source_id="SYN_SRC_PX"
    )
    with pytest.raises(HardFailError):
        require_price(planted, ticker, day)
    with pytest.raises(HardFailError):
        market_value(fx["positions_book"], planted, day)


def test_fm17_planted_zero_close_does_not_value_position_as_zero():
    fx, prices = _fixture()
    book = fx["positions_book"]
    ticker, day = book[0].ticker, book[0].as_of
    planted = dict(prices)
    planted[(ticker, day)] = PriceRecord(
        ticker=ticker, as_of=day, close=0.0, source_id="SYN_SRC_PX"
    )
    # A zero-valued holding would silently lower the total. It must raise.
    with pytest.raises(HardFailError):
        market_value(book, planted, day)


def test_fm17_panel_check_flags_missing_cell():
    fx, prices = _fixture()
    tickers = sorted({p.ticker for p in fx["positions_book"]})
    dates = sorted({d for (_, d) in prices} | {fx["missing_price"][1]})
    records = list(prices.values())
    findings = check_price_panel(records, tickers, dates)
    fails = _fails(findings)
    assert len(fails) == 1
    assert fails[0].check_id == PRICE_CHECK_ID
    ticker, day = fx["missing_price"]
    assert fails[0].subject == "%s@%s" % (ticker, day.isoformat())


def test_fm17_panel_check_flags_null_close():
    fx, prices = _fixture()
    tickers = sorted({p.ticker for p in fx["positions_book"]})
    dates = sorted({d for (_, d) in prices})
    ticker, day = tickers[0], dates[0]
    records = [r for r in prices.values() if (r.ticker, r.as_of) != (ticker, day)]
    records.append(PriceRecord(ticker=ticker, as_of=day, close=None, source_id="SYN_SRC_PX"))
    fails = _fails(check_price_panel(records, tickers, dates))
    subjects = sorted(f.subject for f in fails)
    # The planted null close and the fixture's own planted gap are both
    # reported. Nothing else is.
    gap_ticker, gap_day = fx["missing_price"]
    expected = sorted(
        [
            "%s@%s" % (ticker, day.isoformat()),
            "%s@%s" % (gap_ticker, gap_day.isoformat()),
        ]
    )
    assert subjects == expected


def test_fm17_completed_panel_has_no_findings():
    # Filling the planted gap with a real synthetic close makes the panel
    # complete, so the check must return no findings.
    fx, prices = _fixture()
    tickers = sorted({p.ticker for p in fx["positions_book"]})
    dates = sorted({d for (_, d) in prices} | {fx["missing_price"][1]})
    records = list(prices.values())
    gap_ticker, gap_day = fx["missing_price"]
    records.append(
        PriceRecord(ticker=gap_ticker, as_of=gap_day, close=50.0, source_id="SYN_SRC_PX")
    )
    assert check_price_panel(records, tickers, dates) == []


def test_fm17_proof_with_injected_missing_price_does_not_pass():
    result = run_tieout_factor_proof(seed=SEED, inject_missing_price=True)
    assert result.passed is False
    hard = [f for f in result.findings if f.check_id == HARD_FAIL_CHECK_ID]
    assert hard, "the hard failure must be recorded as a finding"
    assert all(f.status is ValidationStatus.FAIL for f in hard)


def test_fm17_gap_return_series_from_null_close_is_not_checked():
    # GAP: the as_of package has no function that turns closes into returns.
    # The fixture generates asset returns directly and never reads them back
    # from prices, so a null close cannot be shown to distort a return series
    # through any existing module. A future returns module needs its own
    # hard-fail test here.
    pytest.xfail(
        "GAP: no as_of module converts price closes into returns; "
        "the return-distortion half of fm17 is untested against real code"
    )
