"""Tests for as_of.portfolio_fixture (synthetic portfolio data only)."""

from datetime import date

import numpy as np
import pytest

from as_of.core import SYNTHETIC_PREFIX, AsOfError, PositionRecord, PriceRecord
from as_of.portfolio_fixture import (
    BOOK_LABEL,
    CUSTODIAN_LABEL,
    FACTOR_NAMES,
    _BREAK_SIZE,
    make_portfolio_fixture,
)


@pytest.fixture(scope="module")
def fx():
    return make_portfolio_fixture()


def _qty_by_ticker(records):
    return {r.ticker: r.quantity for r in records}


# Acceptance: books differ in exactly one (ticker) quantity.
def test_books_differ_in_exactly_one_ticker_quantity(fx):
    book = fx["positions_book"]
    cust = fx["positions_custodian"]

    assert [r.ticker for r in book] == [r.ticker for r in cust]
    assert all(isinstance(r, PositionRecord) for r in book + cust)
    assert {r.book for r in book} == {BOOK_LABEL}
    assert {r.book for r in cust} == {CUSTODIAN_LABEL}
    assert {r.as_of for r in book + cust} == {book[0].as_of}

    diffs = [
        t for t, q in _qty_by_ticker(book).items()
        if q != _qty_by_ticker(cust)[t]
    ]
    assert len(diffs) == 1, "expected exactly one ticker with a quantity break"


def test_quantity_break_is_nonzero_and_has_planted_size(fx):
    book_q = _qty_by_ticker(fx["positions_book"])
    cust_q = _qty_by_ticker(fx["positions_custodian"])
    (ticker,) = [t for t in book_q if book_q[t] != cust_q[t]]
    delta = cust_q[ticker] - book_q[ticker]
    assert delta != 0
    assert delta == pytest.approx(_BREAK_SIZE)


def test_positions_are_whole_share_and_positive(fx):
    for r in fx["positions_book"] + fx["positions_custodian"]:
        assert r.quantity > 0
        assert float(r.quantity).is_integer()


# Acceptance: the cell named by missing_price is absent from prices.
def test_missing_price_cell_is_absent_from_prices(fx):
    ticker, day = fx["missing_price"]
    cells = {(p.ticker, p.as_of) for p in fx["prices"]}
    assert (ticker, day) not in cells


def test_only_the_missing_cell_is_absent_from_prices(fx):
    tickers = sorted({p.ticker for p in fx["prices"]})
    days = sorted({p.as_of for p in fx["prices"]})
    n_days = len(days)
    assert len(fx["prices"]) == n_days * len(tickers) - 1
    cells = {(p.ticker, p.as_of) for p in fx["prices"]}
    for t in tickers:
        for d in days:
            if (t, d) != fx["missing_price"]:
                assert (t, d) in cells


def test_missing_price_is_not_the_first_trading_day(fx):
    _, day = fx["missing_price"]
    first = min(p.as_of for p in fx["prices"])
    assert day != first


def test_price_records_are_well_formed(fx):
    for p in fx["prices"]:
        assert isinstance(p, PriceRecord)
        assert p.close > 0
        assert p.source_id.startswith(SYNTHETIC_PREFIX)
        assert p.ticker.startswith(SYNTHETIC_PREFIX)


# Acceptance: deterministic output for a fixed seed.
def test_output_is_deterministic_for_fixed_seed():
    a = make_portfolio_fixture(seed=7)
    b = make_portfolio_fixture(seed=7)

    assert a["positions_book"] == b["positions_book"]
    assert a["positions_custodian"] == b["positions_custodian"]
    assert a["prices"] == b["prices"]
    assert a["missing_price"] == b["missing_price"]
    assert np.array_equal(a["factor_returns"], b["factor_returns"])
    assert np.array_equal(a["asset_returns"], b["asset_returns"])


def test_different_seeds_give_different_output():
    a = make_portfolio_fixture(seed=1)
    b = make_portfolio_fixture(seed=2)
    assert not np.array_equal(a["asset_returns"], b["asset_returns"])


# Acceptance: asset_returns has shape (n_days, len(tickers)).
def test_asset_returns_shape_default(fx):
    assert fx["asset_returns"].shape == (60, len(("SYN_A", "SYN_B", "SYN_C")))


@pytest.mark.parametrize(
    "n_days,tickers",
    [
        (2, ("SYN_X",)),
        (10, ("SYN_A", "SYN_B")),
        (25, ("SYN_A", "SYN_B", "SYN_C", "SYN_D")),
    ],
)
def test_asset_returns_shape_varies(n_days, tickers):
    out = make_portfolio_fixture(n_days=n_days, tickers=tickers)
    assert out["asset_returns"].shape == (n_days, len(tickers))


def test_factor_returns_shape(fx):
    assert fx["factor_returns"].shape == (60, len(FACTOR_NAMES))


def test_positions_and_prices_cover_all_tickers_on_last_day():
    out = make_portfolio_fixture(n_days=5, tickers=("SYN_A", "SYN_B"))
    last = max(p.as_of for p in out["prices"])
    assert {p.as_of for p in out["positions_book"]} == {last}
    assert len(out["positions_book"]) == 2


def test_missing_price_names_a_real_ticker_and_date():
    out = make_portfolio_fixture(n_days=6, tickers=("SYN_A", "SYN_B", "SYN_C"))
    ticker, day = out["missing_price"]
    assert ticker in ("SYN_A", "SYN_B", "SYN_C")
    assert isinstance(day, date)
    assert day.weekday() < 5


def test_trading_days_skip_weekends():
    out = make_portfolio_fixture(n_days=10, tickers=("SYN_A",))
    days = sorted({p.as_of for p in out["prices"]} | {out["missing_price"][1]})
    assert all(d.weekday() < 5 for d in days)
    assert days[0] == date(2025, 1, 2)


# Edge cases: argument validation.
@pytest.mark.parametrize("n_days", [0, 1, 2.5, "10"])
def test_rejects_bad_n_days(n_days):
    with pytest.raises(AsOfError):
        make_portfolio_fixture(n_days=n_days)


def test_rejects_non_tuple_tickers():
    with pytest.raises(AsOfError):
        make_portfolio_fixture(tickers=["SYN_A", "SYN_B"])


def test_rejects_empty_tickers():
    with pytest.raises(AsOfError):
        make_portfolio_fixture(tickers=())


def test_rejects_duplicate_tickers():
    with pytest.raises(AsOfError):
        make_portfolio_fixture(tickers=("SYN_A", "SYN_A"))


def test_single_ticker_fixture_is_valid():
    out = make_portfolio_fixture(n_days=3, tickers=("SYN_Z",))
    assert out["asset_returns"].shape == (3, 1)
    assert len(out["positions_book"]) == 1
    assert len(out["positions_custodian"]) == 1
    assert len(out["prices"]) == 3 - 1
