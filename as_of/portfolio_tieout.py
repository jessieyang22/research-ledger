"""Portfolio tie-out between the internal book and the custodian book.

The tie-out compares share quantities per ticker between the internal
(book) record set and the custodian record set. A quantity difference
larger than a tolerance is a break. The module also values positions at a
given date. Valuation uses require_price, so a missing or invalid price
stops the run instead of being filled in.

Topic: portfolio tie-out.

Public API:
    tie_out(book, custodian, tol=0.0) -> Dict[str, Any]
        Return {"breaks": [...], "matched": int}. Each break is a dict with
        ticker, book_qty, custodian_qty and delta (book minus custodian).
        A ticker that appears on only one side counts as zero on the other.
    market_value(positions, prices, as_of) -> float
        Sum of quantity times close at as_of. Raises HardFailError through
        require_price when a price is missing or invalid.
    tieout_findings(result) -> List[Finding]
        One FAIL finding with check_id 'tieout.break' per break.

All data handled here is synthetic. This module imports only the standard
library and as_of.core, plus as_of.price_hard_fail for require_price. It
makes no network calls and holds no order or trading logic.
"""

import math
import numbers
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from as_of.core import Finding, PositionRecord, PriceRecord, ValidationStatus, require
from as_of.price_hard_fail import require_price


TIEOUT_CHECK_ID: str = "tieout.break"


def _checked_quantity(position: PositionRecord) -> float:
    """Return the position quantity as a float, or raise AsOfError.

    NaN and infinite quantities are rejected here, because a NaN delta
    compares as 'not greater than tol' and would otherwise count as a match.
    """
    quantity = position.quantity
    require(
        isinstance(quantity, numbers.Real) and not isinstance(quantity, bool),
        "quantity must be a real number for %r" % (position.ticker,),
    )
    value = float(quantity)
    require(math.isfinite(value), "quantity must be finite for %r" % (position.ticker,))
    return value


def _sum_by_ticker(positions: Sequence[PositionRecord]) -> Dict[str, float]:
    """Return total quantity per ticker. Repeated tickers are summed."""
    totals: Dict[str, float] = defaultdict(float)
    for position in positions:
        require(isinstance(position.ticker, str), "ticker must be a string, got %r" % (position.ticker,))
        totals[position.ticker] += _checked_quantity(position)
    return dict(totals)


def tie_out(
    book: Sequence[PositionRecord],
    custodian: Sequence[PositionRecord],
    tol: float = 0.0,
) -> Dict[str, Any]:
    """Compare book and custodian quantities ticker by ticker.

    A ticker is a break when the absolute difference between the two
    quantities is strictly greater than tol. A difference equal to tol, or
    smaller, is not a break. Tickers are checked in sorted order so the
    result is deterministic.

    Returns a dict with:
        breaks: list of {"ticker", "book_qty", "custodian_qty", "delta"}
            where delta is book_qty minus custodian_qty.
        matched: number of tickers on either side that are not breaks.
    """
    require(isinstance(tol, (int, float)) and not isinstance(tol, bool), "tol must be a number")
    require(math.isfinite(float(tol)) and float(tol) >= 0.0, "tol must be a finite non-negative number")

    book_totals = _sum_by_ticker(book)
    custodian_totals = _sum_by_ticker(custodian)
    tickers = sorted(set(book_totals) | set(custodian_totals))

    breaks: List[Dict[str, Any]] = []
    matched = 0
    for ticker in tickers:
        book_qty = book_totals.get(ticker, 0.0)
        custodian_qty = custodian_totals.get(ticker, 0.0)
        delta = book_qty - custodian_qty
        if abs(delta) > float(tol):
            breaks.append(
                {
                    "ticker": ticker,
                    "book_qty": book_qty,
                    "custodian_qty": custodian_qty,
                    "delta": delta,
                }
            )
        else:
            matched += 1
    return {"breaks": breaks, "matched": matched}


def market_value(
    positions: Sequence[PositionRecord],
    prices: Mapping[Tuple[str, date], PriceRecord],
    as_of: date,
) -> float:
    """Return the total market value of positions at as_of.

    Each position is valued at quantity times the close for (ticker, as_of).
    The price lookup goes through require_price, so a missing, NaN,
    infinite or non-positive price raises HardFailError. Nothing is
    forward-filled.
    """
    # datetime is a subclass of date, so it is rejected explicitly. Comparing a
    # date with a datetime otherwise fails with a bare TypeError.
    require(
        isinstance(as_of, date) and not isinstance(as_of, datetime),
        "as_of must be a date, got %r" % (as_of,),
    )
    total = 0.0
    for position in positions:
        require(
            isinstance(position.as_of, date) and not isinstance(position.as_of, datetime),
            "position as_of must be a date for %r" % (position.ticker,),
        )
        # A position dated after the valuation date would be look-ahead data.
        require(
            position.as_of <= as_of,
            "position for %r is dated %s, after valuation date %s"
            % (position.ticker, position.as_of.isoformat(), as_of.isoformat()),
        )
        quantity = _checked_quantity(position)
        record = require_price(prices, position.ticker, as_of)
        total += quantity * float(record.close)
    return total


def tieout_findings(result: Dict[str, Any]) -> List[Finding]:
    """Turn a tie_out result into one FAIL finding per break.

    Each finding has check_id 'tieout.break', its subject is the ticker, and
    its message gives the book quantity, custodian quantity and delta.
    A result with no breaks returns an empty list.
    """
    findings: List[Finding] = []
    for item in result.get("breaks", []):
        findings.append(
            Finding(
                check_id=TIEOUT_CHECK_ID,
                status=ValidationStatus.FAIL,
                message="[block] book_qty=%r custodian_qty=%r delta=%r"
                % (item["book_qty"], item["custodian_qty"], item["delta"]),
                subject=str(item["ticker"]),
            )
        )
    return findings
