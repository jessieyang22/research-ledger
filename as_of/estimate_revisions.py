"""Estimate revision history, consensus time series and revision breadth.

This module reads an estimate ledger as of a point in time. It never looks
at a value before its knowledge time, so every answer is what a reader could
have known on that date.

Conventions used throughout:

* A ledger is either a plain sequence of EstimateRecord values from
  as_of.core, or an as_of.estimate_ledger.EstimateLedger object. The second
  form is detected by its rows() method, so this module never imports
  estimate_ledger. Both forms give the same answers for the same rows.
* Each record carries a knowledge_at time. A record counts as known at time
  t when knowledge_at <= t.
* Each analyst's latest known value is their current estimate. Consensus is
  the mean of those current estimates across analysts.
* Breadth compares each analyst's estimate at the start of a window with
  their estimate at the end. Only analysts who published a new estimate
  inside the window are counted, so a first estimate is not a revision.

All data handled here is synthetic. Fixture ids start with SYN_.
"""

import math
import numbers
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from as_of.core import EstimateRecord, ensure_utc, require

# A plain sequence of records, or an as_of.estimate_ledger.EstimateLedger.
EstimateLedger = Sequence[EstimateRecord]

# Two values closer than this are treated as the same estimate.
_EQUAL_TOL: float = 1e-12


def _finite_value(raw: object) -> float:
    """Return raw as a float. Non-numeric, bool, NaN and infinity raise AsOfError.

    Strings and bools are rejected rather than converted, so "2.5" and True
    never become estimates. A non-finite estimate would otherwise leak into
    consensus means and make revision_breadth count NaN deltas as downward
    revisions.
    """
    require(
        isinstance(raw, numbers.Real) and not isinstance(raw, bool),
        "estimate value must be a real number, got %s" % type(raw).__name__,
    )
    value = float(raw)
    require(math.isfinite(value), "estimate value must be finite, got %r" % (raw,))
    return value


def _matching(
    ledger: EstimateLedger,
    ticker: str,
    metric: str,
    period: str,
    analyst_id: Optional[str] = None,
) -> List[EstimateRecord]:
    """Return records for one ticker, metric and period, optionally one analyst."""
    out: List[EstimateRecord] = []
    # EstimateLedger objects from as_of.estimate_ledger expose rows() and are
    # not iterable. Plain sequences are iterated directly.
    source = ledger.rows(ticker, metric, period) if hasattr(ledger, "rows") else ledger
    for rec in source:
        if rec.ticker != ticker or rec.metric != metric or rec.period != period:
            continue
        if analyst_id is not None and rec.analyst_id != analyst_id:
            continue
        out.append(rec)
    return out


def _latest_by_analyst(
    records: Sequence[EstimateRecord], cutoff: datetime
) -> Dict[str, float]:
    """Map each analyst to their latest value known at or before cutoff.

    Records are taken in knowledge-time order, so a later record replaces an
    earlier one for the same analyst. Ties keep the record that comes later
    in the ledger.
    """
    latest: Dict[str, Tuple[datetime, float]] = {}
    for rec in sorted(records, key=lambda r: ensure_utc(r.knowledge_at)):
        known = ensure_utc(rec.knowledge_at)
        if known > cutoff:
            continue
        latest[rec.analyst_id] = (known, _finite_value(rec.value))
    return {analyst: value for analyst, (_, value) in latest.items()}


def revision_history(
    ledger: EstimateLedger,
    ticker: str,
    metric: str,
    period: str,
    analyst_id: str,
) -> List[Tuple[datetime, float]]:
    """Return one analyst's estimates for a ticker, metric and period.

    The result is a list of (knowledge_at, value) pairs sorted by knowledge
    time, earliest first. Records with equal knowledge times keep their
    ledger order.
    """
    rows = _matching(ledger, ticker, metric, period, analyst_id)
    rows.sort(key=lambda r: ensure_utc(r.knowledge_at))
    return [(ensure_utc(r.knowledge_at), _finite_value(r.value)) for r in rows]


def consensus_series(
    ledger: EstimateLedger,
    ticker: str,
    metric: str,
    period: str,
    dates: Sequence[datetime],
) -> List[Optional[float]]:
    """Return the consensus value on each requested date.

    For each date, consensus is the mean of every analyst's latest estimate
    known on that date. The value is None when no estimate was known yet,
    so dates before the first estimate give None.
    """
    records = _matching(ledger, ticker, metric, period)
    out: List[Optional[float]] = []
    for when in dates:
        latest = _latest_by_analyst(records, ensure_utc(when))
        if not latest:
            out.append(None)
            continue
        values = list(latest.values())
        out.append(sum(values) / float(len(values)))
    return out


def revision_breadth(
    ledger: EstimateLedger,
    ticker: str,
    metric: str,
    period: str,
    start: datetime,
    end: datetime,
) -> Dict[str, int]:
    """Count analysts whose estimate went up, down or stayed the same.

    An analyst is counted when they published an estimate with knowledge time
    in (start, end]. Their value at start is the latest estimate known at or
    before start, and their value at end is the latest known at or before end.
    Analysts with no estimate known at start are skipped, because their first
    estimate is not a revision. A window with no revisions returns zeros.
    """
    start_utc = ensure_utc(start)
    end_utc = ensure_utc(end)
    require(start_utc <= end_utc, "start must not be after end")

    records = _matching(ledger, ticker, metric, period)
    before = _latest_by_analyst(records, start_utc)
    after = _latest_by_analyst(records, end_utc)

    touched = {
        rec.analyst_id
        for rec in records
        if start_utc < ensure_utc(rec.knowledge_at) <= end_utc
    }

    counts: Dict[str, int] = {"up": 0, "down": 0, "unchanged": 0}
    for analyst in sorted(touched):
        if analyst not in before or analyst not in after:
            continue
        delta = after[analyst] - before[analyst]
        if abs(delta) <= _EQUAL_TOL:
            counts["unchanged"] += 1
        elif delta > 0:
            counts["up"] += 1
        else:
            counts["down"] += 1
    return counts
