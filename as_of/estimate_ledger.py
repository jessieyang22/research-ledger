"""Append-only ledger of analyst estimates with knowledge-time discipline.

Each row is an EstimateRecord whose knowledge_at says when the estimate
became known. Rows are never overwritten. A revision is a new row with a
later knowledge_at, and the earlier row stays in the ledger. That lets the
consensus be recomputed as of any date by ignoring rows that were not yet
known on that date.

Topic: "estimate ledger and revisions".

Only core.py is imported from the as_of package. The module depends on the
standard library and core.py only. All data handled here is synthetic.
"""

import dataclasses
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from as_of.core import (
    AsOfError,
    EstimateRecord,
    Finding,
    ValidationStatus,
    ensure_utc,
)

# Key that makes a row unique in the ledger.
RowKey = Tuple[str, str, str, str, datetime]


def _is_real_number(value: object) -> bool:
    """True for int or float values. Excludes bool, None, str and containers."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)

CHECK_NAIVE_TIME = "estimate.naive_knowledge_at"
CHECK_NON_FINITE = "estimate.non_finite_value"
CHECK_NO_ROWS = "estimate.empty_ledger"
CHECK_CLEAN = "estimate.ledger_clean"


class EstimateLedger:
    """In-memory, append-only store of EstimateRecord rows.

    Rows are kept in insertion order. Lookups filter by (ticker, metric,
    period). Knowledge time is normalised to aware UTC on append, so every
    comparison in this class is between aware datetimes.
    """

    def __init__(self) -> None:
        self._rows: List[EstimateRecord] = []
        self._keys: Dict[RowKey, int] = {}

    @property
    def records(self) -> Tuple[EstimateRecord, ...]:
        """All rows in insertion order, as an immutable snapshot (what reported_vs_expected_bridge reads)."""
        return tuple(self._rows)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def append(self, rec: EstimateRecord) -> None:
        """Add one estimate row. Never overwrites an earlier row.

        Raises AsOfError when a row with the same (analyst_id, ticker,
        metric, period, knowledge_at) is already present, or when
        knowledge_at is naive.
        """
        if not isinstance(rec, EstimateRecord):
            raise AsOfError("append expects an EstimateRecord, got %s" % type(rec).__name__)
        if not _is_real_number(rec.value):
            raise AsOfError("estimate value must be a real number, got %s" % type(rec.value).__name__)
        for field_name in ("estimate_id", "ticker", "metric", "period", "analyst_id"):
            field_value = getattr(rec, field_name)
            if not isinstance(field_value, str) or not field_value.strip():
                raise AsOfError("estimate field %s must be a non-blank string" % field_name)
        normalised = dataclasses.replace(rec, knowledge_at=ensure_utc(rec.knowledge_at))
        key = self._key(normalised)
        if key in self._keys:
            raise AsOfError(
                "duplicate estimate row for analyst=%s ticker=%s metric=%s period=%s knowledge_at=%s"
                % (key[0], key[1], key[2], key[3], key[4].isoformat())
            )
        self._keys[key] = len(self._rows)
        self._rows.append(normalised)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def rows(self, ticker: str, metric: str, period: str) -> List[EstimateRecord]:
        """Return every row for the series, sorted by knowledge_at then analyst_id.

        Rows are returned whether or not they were known at any particular
        date. Use latest_per_analyst for a point-in-time view.
        """
        selected = [
            r for r in self._rows
            if r.ticker == ticker and r.metric == metric and r.period == period
        ]
        selected.sort(key=lambda r: (r.knowledge_at, r.analyst_id))
        return selected

    def latest_per_analyst(
        self, ticker: str, metric: str, period: str, as_of: datetime
    ) -> List[EstimateRecord]:
        """Return each analyst's most recent row known on or before as_of.

        Rows with knowledge_at after as_of are ignored. An analyst with no
        row known by as_of does not appear in the result. The result is
        sorted by analyst_id.
        """
        cutoff = ensure_utc(as_of)
        latest: Dict[str, EstimateRecord] = {}
        for rec in self.rows(ticker, metric, period):
            if rec.knowledge_at > cutoff:
                continue
            current = latest.get(rec.analyst_id)
            if current is None or rec.knowledge_at >= current.knowledge_at:
                latest[rec.analyst_id] = rec
        return [latest[a] for a in sorted(latest)]

    def consensus_as_of(
        self, ticker: str, metric: str, period: str, as_of: datetime
    ) -> Optional[float]:
        """Return the mean of latest_per_analyst values as of as_of.

        Each analyst counts once, using their latest estimate known by
        as_of. Returns None when no analyst had an estimate known by then.
        """
        latest = self.latest_per_analyst(ticker, metric, period, as_of)
        if not latest:
            return None
        return float(sum(r.value for r in latest) / len(latest))

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> List[Finding]:
        """Check stored rows and return findings.

        Reports naive knowledge times, non-finite values, and an empty
        ledger. Returns one PASS finding when nothing is wrong.
        """
        findings: List[Finding] = []
        if not self._rows:
            findings.append(Finding(
                check_id=CHECK_NO_ROWS,
                status=ValidationStatus.WARN,
                message="ledger has no estimate rows",
                subject="ledger",
            ))
            return findings
        for rec in self._rows:
            subject = "%s/%s/%s/%s/%s" % (
                rec.analyst_id, rec.ticker, rec.metric, rec.period, rec.estimate_id
            )
            knowledge = rec.knowledge_at
            if knowledge.tzinfo is None or knowledge.utcoffset() is None:
                findings.append(Finding(
                    check_id=CHECK_NAIVE_TIME,
                    status=ValidationStatus.FAIL,
                    message="knowledge_at is naive",
                    subject=subject,
                ))
            if not _is_real_number(rec.value) or not math.isfinite(rec.value):
                findings.append(Finding(
                    check_id=CHECK_NON_FINITE,
                    status=ValidationStatus.FAIL,
                    message="value is not finite: %r" % (rec.value,),
                    subject=subject,
                ))
        if not findings:
            findings.append(Finding(
                check_id=CHECK_CLEAN,
                status=ValidationStatus.PASS,
                message="%d estimate rows checked" % len(self._rows),
                subject="ledger",
            ))
        return findings

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _key(rec: EstimateRecord) -> RowKey:
        return (rec.analyst_id, rec.ticker, rec.metric, rec.period, rec.knowledge_at)
