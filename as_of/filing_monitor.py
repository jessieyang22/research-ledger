"""Filing occurrence monitor for the as_of package.

This module records that a filing happened: its form type, its filed and
accepted dates, and the registered source it came from. It answers questions
such as "which filings were accepted for ticker X between two timestamps" and
"how many filings of each form type were accepted in a window".

It does not score significance. There is no materiality, sentiment, or
ranking logic here. Deciding whether a filing matters is a separate step that
belongs to a human reviewer or to another module, not to this recorder.

It uses synthetic data only and makes no network calls.

Only core.py and source_register.py are imported. Every source_id must already
be present in the SourceRegister passed to FilingMonitor.
"""

from datetime import datetime
from typing import Dict, List

from as_of.core import AsOfError, FilingRecord, ensure_utc
from as_of.source_register import SourceRegister


class FilingMonitor:
    """In-memory log of filing occurrences keyed by filing_id.

    A filing is accepted only when its source_id is registered. A repeated
    filing_id is not stored again, so the first recorded occurrence stays
    fixed.
    """

    def __init__(self, register: SourceRegister) -> None:
        if not isinstance(register, SourceRegister):
            raise AsOfError(
                "FilingMonitor expects a SourceRegister, got %s" % type(register).__name__
            )
        self._register: SourceRegister = register
        self._filings: Dict[str, FilingRecord] = {}

    def ingest_filing(self, rec: FilingRecord) -> bool:
        """Record one filing occurrence.

        Returns True when the filing_id is new and was stored, and False when
        that filing_id was already recorded (the stored copy is not replaced).
        Raises AsOfError when rec is not a FilingRecord, or when its source_id
        is not registered.
        """
        if not isinstance(rec, FilingRecord):
            raise AsOfError("ingest_filing expects a FilingRecord, got %s" % type(rec).__name__)
        for field in ("filing_id", "ticker", "form_type", "source_id"):
            value = getattr(rec, field)
            if not isinstance(value, str) or not value.strip():
                raise AsOfError("filing field %s must be a non-empty str, got %r" % (field, value))
        # Reject naive, non-datetime and out-of-range timestamps here. A bad
        # value stored now would make every later query raise.
        ensure_utc(rec.filed_at)
        ensure_utc(rec.accepted_at)
        if not self._register.has_source(rec.source_id):
            raise AsOfError("filing %r uses unregistered source_id %r" % (rec.filing_id, rec.source_id))
        if rec.filing_id in self._filings:
            return False
        self._filings[rec.filing_id] = rec
        return True

    def occurrences(self, ticker: str, start: datetime, end: datetime) -> List[FilingRecord]:
        """Return filings for ticker whose accepted_at lies within [start, end].

        Both bounds are inclusive. Naive datetimes raise AsOfError. Results are
        sorted by accepted_at, then by filing_id, so the order is stable.
        """
        lo = ensure_utc(start)
        hi = ensure_utc(end)
        matched = [
            rec
            for rec in self._filings.values()
            if rec.ticker == ticker and lo <= ensure_utc(rec.accepted_at) <= hi
        ]
        matched.sort(key=lambda r: (ensure_utc(r.accepted_at), r.filing_id))
        return matched

    def occurrence_summary(self, start: datetime, end: datetime) -> Dict[str, int]:
        """Count filings by form_type for accepted_at within [start, end].

        Both bounds are inclusive. Form types with no filings in the window are
        absent from the result. Naive datetimes raise AsOfError.
        """
        lo = ensure_utc(start)
        hi = ensure_utc(end)
        counts: Dict[str, int] = {}
        for rec in self._filings.values():
            if lo <= ensure_utc(rec.accepted_at) <= hi:
                counts[rec.form_type] = counts.get(rec.form_type, 0) + 1
        return counts
