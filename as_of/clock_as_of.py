"""Point-in-time visibility filters for clock-stamped records.

A record is visible at time T only when its knowledge clock is set and is at
or before T. A record with knowledge_at None is never visible, because nothing
says when it became known. Comparisons use aware UTC datetimes through
core.ensure_utc, so a naive datetime raises AsOfError instead of silently
comparing against the wrong zone.

All data used with this module is synthetic (ids start with SYN_).

Public API:
    known_as_of(cs, as_of) -> bool
    visible_at(records, as_of) -> list of ClockSet
    latest_known(records, as_of) -> ClockSet or None
"""

from datetime import datetime
from typing import List, Optional, Sequence

from as_of.core import AsOfError, ClockSet, ensure_utc


def _as_of_utc(as_of: datetime) -> datetime:
    """Validate the decision time once, so a bad as_of always raises AsOfError.

    This runs before any record is inspected, so an empty input or a record
    with an unknown knowledge clock cannot hide a naive or wrong-type as_of.
    """
    return ensure_utc(as_of)


def known_as_of(cs: ClockSet, as_of: datetime) -> bool:
    """Return True when cs.knowledge_at is set and is at or before as_of.

    A knowledge_at equal to as_of counts as known. A knowledge_at of None
    always returns False, but as_of is still validated first. A cs that is
    not a ClockSet (a dict, None, or any other type) raises AsOfError.
    """
    if not isinstance(cs, ClockSet):
        raise AsOfError("expected ClockSet, got %s" % type(cs).__name__)
    cutoff = _as_of_utc(as_of)
    if cs.knowledge_at is None:
        return False
    return ensure_utc(cs.knowledge_at) <= cutoff


def visible_at(records: Sequence[ClockSet], as_of: datetime) -> List[ClockSet]:
    """Return the records known as of as_of, in their original order.

    as_of is validated even when records is empty. Any non-ClockSet row raises
    AsOfError through known_as_of.
    """
    cutoff = _as_of_utc(as_of)
    return [rec for rec in records if known_as_of(rec, cutoff)]


def latest_known(records: Sequence[ClockSet], as_of: datetime) -> Optional[ClockSet]:
    """Return the visible record with the largest knowledge_at, or None.

    Only records with knowledge_at at or before as_of are candidates. When two
    visible records share the same knowledge_at, the one that appears first in
    records is returned, so the result is deterministic.
    """
    cutoff = _as_of_utc(as_of)
    best: Optional[ClockSet] = None
    best_at: Optional[datetime] = None
    for rec in visible_at(records, cutoff):
        rec_at = ensure_utc(rec.knowledge_at)
        if best_at is None or rec_at > best_at:
            best = rec
            best_at = rec_at
    return best
