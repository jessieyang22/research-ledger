"""Hard-fail price lookup for the as_of package.

A price that is missing, NaN or non-positive stops the run. It is never
forward-filled from an earlier date, never interpolated and never replaced
with a default. The design treats a missing price on a required date as a
hard stop rather than a value to paper over.

Public API:
    require_price(prices, ticker, as_of) -> PriceRecord
        Return the record for (ticker, as_of) or raise HardFailError.
    check_price_panel(records, tickers, dates) -> List[Finding]
        Return one BLOCK-level FAIL finding per missing or invalid
        (ticker, date) cell of a price panel. An empty list means the
        panel is complete and valid.

All data handled here is synthetic. This module imports only the standard
library and as_of.core. It makes no network calls.
"""

import math
import numbers
from datetime import date
from decimal import Decimal
from typing import Dict, List, Mapping, Sequence, Tuple

from as_of.core import Finding, HardFailError, PriceRecord, Severity, ValidationStatus


PRICE_CHECK_ID: str = "PRICE_HARD_FAIL"
PRICE_SEVERITY: Severity = Severity.BLOCK


def _close_problem(close: float) -> str:
    """Return a short reason when close is unusable, or '' when it is valid.

    NaN, infinite and non-positive closes are all unusable. A value that
    cannot be read as a number is also unusable.
    """
    if isinstance(close, bool):
        return "close is not a number: %r" % (close,)
    if isinstance(close, Decimal):
        # Decimal is not numbers.Real, so it is handled here. It is valid
        # when it is a finite, positive number.
        if close.is_nan():
            return "close is NaN"
        if close.is_infinite():
            return "close is infinite"
        if close <= 0:
            return "close is non-positive (%r)" % (close,)
        return ""
    if not isinstance(close, numbers.Real):
        return "close is not a number: %r" % (close,)
    try:
        value = float(close)
    except (TypeError, ValueError, OverflowError):
        return "close is not a number: %r" % (close,)
    if math.isnan(value):
        return "close is NaN"
    if math.isinf(value):
        return "close is infinite"
    if value <= 0.0:
        return "close is non-positive (%r)" % (close,)
    return ""


def require_price(
    prices: Mapping[Tuple[str, date], PriceRecord],
    ticker: str,
    as_of: date,
) -> PriceRecord:
    """Return the price record for (ticker, as_of) or stop the run.

    Raises HardFailError when there is no record for that key, or when the
    record's close is NaN, infinite or <= 0. The function never looks at
    earlier dates, so a gap is never forward-filled.
    """
    key = (ticker, as_of)
    if key not in prices:
        raise HardFailError(
            "missing price for %s on %s; not forward-filled" % (ticker, as_of)
        )
    record = prices[key]
    if getattr(record, "ticker", None) != ticker or getattr(record, "as_of", None) != as_of:
        raise HardFailError(
            "price record for %s on %s does not match its key; not used" % (ticker, as_of)
        )
    problem = _close_problem(getattr(record, "close", None))
    if problem:
        raise HardFailError(
            "invalid price for %s on %s: %s" % (ticker, as_of, problem)
        )
    return record


def check_price_panel(
    records: Sequence[PriceRecord],
    tickers: Sequence[str],
    dates: Sequence[date],
) -> List[Finding]:
    """Check every (ticker, date) cell of a panel and report each gap.

    One Finding is returned per cell that has no record or whose record has
    an invalid close. Every finding is a FAIL, which carries BLOCK severity
    in its message because the Finding type has no severity field. Cells
    are checked in the order of tickers, then dates. A complete, valid panel
    returns an empty list.

    When several records share one cell, the cell is valid only if every
    record for it is valid. A conflict between duplicate records is not
    resolved here.
    """
    by_cell: Dict[Tuple[str, date], List[PriceRecord]] = {}
    for record in records:
        by_cell.setdefault((record.ticker, record.as_of), []).append(record)

    findings: List[Finding] = []
    for ticker in tickers:
        for as_of in dates:
            subject = "%s@%s" % (ticker, as_of.isoformat())
            cell = by_cell.get((ticker, as_of))
            if not cell:
                findings.append(
                    Finding(
                        check_id=PRICE_CHECK_ID,
                        status=ValidationStatus.FAIL,
                        message="[%s] missing price; not forward-filled" % PRICE_SEVERITY.value,
                        subject=subject,
                    )
                )
                continue
            reasons = [r for r in (_close_problem(rec.close) for rec in cell) if r]
            if reasons:
                findings.append(
                    Finding(
                        check_id=PRICE_CHECK_ID,
                        status=ValidationStatus.FAIL,
                        message="[%s] %s" % (PRICE_SEVERITY.value, "; ".join(reasons)),
                        subject=subject,
                    )
                )
    return findings
