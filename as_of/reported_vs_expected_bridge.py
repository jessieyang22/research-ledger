"""Reported-vs-expected bridge for as-of research state.

Given an estimate ledger, a ticker, metric and period, and a reported actual
with its report time, this module builds the expected value from estimates
that were known before the report time. Estimates whose knowledge clock is
at or after reported_at are dropped before any averaging, so the expected value
cannot use information that arrived at or after the report (no look-ahead).

Expected value rule: among the visible estimates for the requested
ticker, metric and period, keep the latest visible estimate per analyst
(ties on knowledge_at go to the earlier record in the ledger), then take the
arithmetic mean of those per-analyst values. basis_as_of is the latest
knowledge_at among the estimates that entered the mean.

Surprise rule: surprise_abs = reported - expected, and surprise_pct =
(reported - expected) / abs(expected). When expected is zero the percent
surprise is undefined, so surprise_pct is None.

Classification: classify_surprise maps a percent surprise to 'beat', 'miss',
'inline', or 'no_expected' (for None). Values inside the symmetric band
[-threshold, +threshold] are 'inline'.

All data used with this module is synthetic (ids start with SYN_). The module
imports only the standard library and as_of.core.

Public API:
    build_bridge(ledger, ticker, metric, period, reported_value, reported_at)
        -> dict with keys expected, reported, surprise_abs, surprise_pct,
           basis_as_of
    classify_surprise(surprise_pct, threshold=0.0) -> str
"""

import math
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from as_of.core import EstimateRecord, ensure_utc, require

# The ledger is any iterable of EstimateRecord, or an object exposing such an
# iterable as a `records` attribute. No EstimateLedger class exists in the
# as_of package yet, so the parameter is typed loosely.
EstimateLedger = Any

CLASS_BEAT: str = "beat"
CLASS_MISS: str = "miss"
CLASS_INLINE: str = "inline"
CLASS_NO_EXPECTED: str = "no_expected"


def _ledger_records(ledger: EstimateLedger) -> Iterable[EstimateRecord]:
    """Return the EstimateRecord iterable behind a ledger argument."""
    if ledger is None:
        return []
    records = getattr(ledger, "records", None)
    if records is not None:
        return records
    return ledger


def _visible_estimates(
    ledger: EstimateLedger,
    ticker: str,
    metric: str,
    period: str,
    reported_at: datetime,
) -> List[EstimateRecord]:
    """Return matching estimates whose knowledge clock is strictly before reported_at.

    Records with a knowledge_at at or after reported_at are excluded here,
    before any averaging takes place. An estimate stamped at the report
    instant is not counted as known before the report.
    """
    visible: List[EstimateRecord] = []
    for rec in _ledger_records(ledger):
        if rec.ticker != ticker or rec.metric != metric or rec.period != period:
            continue
        if rec.knowledge_at is None:
            continue
        if not ensure_utc(rec.knowledge_at) < reported_at:
            continue
        visible.append(rec)
    return visible


def _latest_per_analyst(visible: List[EstimateRecord]) -> List[EstimateRecord]:
    """Keep, for each analyst_id, the visible estimate with the latest knowledge_at.

    Ties on knowledge_at keep the record that appears first in the ledger.
    The returned list is ordered by first appearance of each analyst.
    """
    chosen: Dict[str, EstimateRecord] = {}
    order: List[str] = []
    for rec in visible:
        current = chosen.get(rec.analyst_id)
        if current is None:
            chosen[rec.analyst_id] = rec
            order.append(rec.analyst_id)
            continue
        if ensure_utc(rec.knowledge_at) > ensure_utc(current.knowledge_at):
            chosen[rec.analyst_id] = rec
    return [chosen[a] for a in order]


def build_bridge(
    ledger: EstimateLedger,
    ticker: str,
    metric: str,
    period: str,
    reported_value: float,
    reported_at: datetime,
) -> Dict[str, Any]:
    """Bridge a reported actual to the expected value known before reported_at.

    Returns a dict with keys:
        expected: mean of the latest visible estimate per analyst, or None
            when no estimate was visible.
        reported: the reported value as a float.
        surprise_abs: reported - expected, or None when expected is None.
        surprise_pct: surprise_abs / abs(expected), or None when expected is
            None or zero.
        basis_as_of: latest knowledge_at among the estimates used, or None.

    Raises AsOfError when reported_value is not finite, or when reported_at
    is naive.
    """
    reported_at = ensure_utc(reported_at)
    require(
        isinstance(reported_value, (int, float)) and not isinstance(reported_value, bool),
        "reported_value must be a number",
    )
    reported = float(reported_value)
    require(math.isfinite(reported), "reported_value must be finite")

    visible = _visible_estimates(ledger, ticker, metric, period, reported_at)
    used = _latest_per_analyst(visible)

    if not used:
        return {
            "expected": None,
            "reported": reported,
            "surprise_abs": None,
            "surprise_pct": None,
            "basis_as_of": None,
        }

    for rec in used:
        value = rec.value
        require(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)),
            "estimate value must be a finite number (estimate_id=%r)" % (rec.estimate_id,),
        )
    expected = sum(float(rec.value) for rec in used) / float(len(used))
    surprise_abs = reported - expected
    require(math.isfinite(surprise_abs), "surprise_abs overflows float range")
    if expected == 0.0:
        surprise_pct: Optional[float] = None
    else:
        surprise_pct = surprise_abs / abs(expected)

    basis_as_of = max((ensure_utc(rec.knowledge_at) for rec in used))

    return {
        "expected": expected,
        "reported": reported,
        "surprise_abs": surprise_abs,
        "surprise_pct": surprise_pct,
        "basis_as_of": basis_as_of,
    }


def classify_surprise(surprise_pct: Optional[float], threshold: float = 0.0) -> str:
    """Classify a percent surprise as 'beat', 'miss', 'inline', or 'no_expected'.

    None returns 'no_expected'. A value above +threshold returns 'beat', a value
    below -threshold returns 'miss', and anything in the band between them,
    including the boundaries, returns 'inline'. threshold must be a finite,
    non-negative number.
    """
    require(
        isinstance(threshold, (int, float)) and not isinstance(threshold, bool)
        and math.isfinite(float(threshold)) and float(threshold) >= 0.0,
        "threshold must be a finite non-negative number",
    )
    if surprise_pct is None:
        return CLASS_NO_EXPECTED
    value = float(surprise_pct)
    require(math.isfinite(value), "surprise_pct must be finite or None")
    if value > threshold:
        return CLASS_BEAT
    if value < -threshold:
        return CLASS_MISS
    return CLASS_INLINE
