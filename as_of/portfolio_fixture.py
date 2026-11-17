"""Synthetic portfolio fixture for the as_of portfolio tie-out checks.

The fixture builds two position books that describe the same holdings on the
same as-of date, but with one deliberate break in one ticker's quantity. It
also builds a daily price panel with one deliberate gap (a single missing
ticker-date cell), plus factor and asset return series that generate those
prices. The tie-out checks can then be tested against known answers.

Conventions:
    * Tickers default to SYN_A, SYN_B and SYN_C. Every id is synthetic.
    * The internal book is labelled SYN_BOOK and the custodian file is
      labelled SYN_CUSTODIAN. Both use the same as-of date, which is the
      last trading day in the series.
    * Exactly one ticker has a quantity break between the two books. The
      ticker is chosen from the seeded generator. The break size is fixed at
      _BREAK_SIZE and is always added to the custodian quantity, so the sign
      of the break is always positive.
    * Prices are missing for exactly one (ticker, trading date) cell, reported
      as missing_price. That cell is absent from the prices list. The date is
      drawn from day 1 onward, so it can be the as-of date. At the default
      n_days of 60 that chance is 1 in 59.
    * Trading days are weekdays starting 2025-01-02. No holiday calendar is
      applied, which is acceptable for synthetic data.

The module does no I/O and no network access. Every random draw comes from
one numpy generator seeded by the caller, so equal arguments give equal
output. Imports are limited to the standard library, numpy and as_of.core.

The design is an original implementation of the idea that a tie-out needs a
fixture with a known, planted break.
"""

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Tuple

import numpy as np

from as_of.core import (
    SYNTHETIC_SEED,
    PositionRecord,
    PriceRecord,
    require,
)

BOOK_LABEL: str = "SYN_BOOK"
CUSTODIAN_LABEL: str = "SYN_CUSTODIAN"
PRICE_SOURCE_ID: str = "SYN_SRC_PX"
FACTOR_NAMES: Tuple[str, ...] = ("SYN_FACTOR_MKT", "SYN_FACTOR_STYLE")
_FIRST_DAY: date = date(2025, 1, 2)
_START_PRICE: float = 100.0
_IDIO_VOL: float = 0.004
_FACTOR_VOL: float = 0.01
_BREAK_SIZE: float = 250.0
_TICKER_RE = re.compile(r"SYN_[A-Z0-9_]+")


def _trading_days(n_days: int) -> List[date]:
    """Return n_days consecutive weekdays beginning at _FIRST_DAY."""
    days: List[date] = []
    cursor = _FIRST_DAY
    while len(days) < n_days:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor = cursor + timedelta(days=1)
    return days


def make_portfolio_fixture(
    seed: int = SYNTHETIC_SEED,
    n_days: int = 60,
    tickers: Tuple[str, ...] = ("SYN_A", "SYN_B", "SYN_C"),
) -> Dict[str, Any]:
    """Build a deterministic synthetic portfolio fixture.

    Returns a dict with these keys:
        positions_book: List[PositionRecord] for the internal book.
        positions_custodian: List[PositionRecord] for the custodian file.
            It matches positions_book except for one ticker's quantity.
        prices: List[PriceRecord], one row per ticker and trading day,
            except the single missing cell named by missing_price.
        factor_returns: np.ndarray of shape (n_days, 2), daily factor returns.
        asset_returns: np.ndarray of shape (n_days, len(tickers)), daily
            asset returns, which are factor exposure plus idiosyncratic noise.
        missing_price: Tuple[str, date], the (ticker, trading date) cell that
            is absent from prices. The date is never the first trading day,
            but it may equal the as-of date.
    """
    require(isinstance(n_days, int) and n_days >= 2, "n_days must be an int >= 2")
    require(
        isinstance(seed, (int, np.integer)) and not isinstance(seed, bool) and seed >= 0,
        "seed must be a non-negative int",
    )
    require(isinstance(tickers, tuple) and len(tickers) >= 1, "tickers must be a non-empty tuple")
    require(
        all(isinstance(t, str) and _TICKER_RE.fullmatch(t) for t in tickers),
        "tickers must be strings of the form SYN_<A-Z0-9_>",
    )
    require(len(set(tickers)) == len(tickers), "tickers must be unique")

    rng = np.random.default_rng(seed)
    n_assets = len(tickers)
    n_factors = len(FACTOR_NAMES)

    # Factor returns and exposures generate asset returns.
    factor_returns = rng.normal(0.0, _FACTOR_VOL, size=(n_days, n_factors))
    exposures = rng.uniform(0.2, 1.4, size=(n_assets, n_factors))
    idio = rng.normal(0.0, _IDIO_VOL, size=(n_days, n_assets))
    asset_returns = factor_returns @ exposures.T + idio

    days = _trading_days(n_days)
    as_of = days[-1]

    # Prices are compounded from a fixed starting level.
    closes = _START_PRICE * np.cumprod(1.0 + asset_returns, axis=0)

    # Holdings: whole-share quantities with one nonzero break on the custodian side.
    base_qty = rng.integers(100, 1000, size=n_assets).astype(float)
    break_idx = int(rng.integers(0, n_assets))
    custodian_qty = base_qty.copy()
    custodian_qty[break_idx] = base_qty[break_idx] + _BREAK_SIZE

    positions_book: List[PositionRecord] = []
    positions_custodian: List[PositionRecord] = []
    for i, ticker in enumerate(tickers):
        positions_book.append(
            PositionRecord(
                book=BOOK_LABEL,
                ticker=ticker,
                quantity=float(base_qty[i]),
                as_of=as_of,
            )
        )
        positions_custodian.append(
            PositionRecord(
                book=CUSTODIAN_LABEL,
                ticker=ticker,
                quantity=float(custodian_qty[i]),
                as_of=as_of,
            )
        )

    # One gap in the price panel. Day 0 is excluded so the gap is never the first row.
    gap_asset = int(rng.integers(0, n_assets))
    gap_day = int(rng.integers(1, n_days))
    missing_cell: Tuple[str, date] = (tickers[gap_asset], days[gap_day])

    prices: List[PriceRecord] = []
    for d_idx, day in enumerate(days):
        for a_idx, ticker in enumerate(tickers):
            if (ticker, day) == missing_cell:
                continue
            prices.append(
                PriceRecord(
                    ticker=ticker,
                    as_of=day,
                    close=round(float(closes[d_idx, a_idx]), 4),
                    source_id=PRICE_SOURCE_ID,
                )
            )

    return {
        "positions_book": positions_book,
        "positions_custodian": positions_custodian,
        "prices": prices,
        "factor_returns": factor_returns,
        "asset_returns": asset_returns,
        "missing_price": missing_cell,
    }
