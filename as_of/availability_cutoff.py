"""Availability cutoff for as-of research records.

A record is usable at a decision time only if it was available to the
researcher by then. This module decides availability from a record's
ClockSet:

* ingest_at is the preferred clock. It is when the record entered our own
  store, which is the moment a researcher could actually have read it.
* release_at is the fallback. It is used only when ingest_at is missing.
  Each use is counted so that a report can show how much of the universe
  depends on the weaker clock.
* A record with neither clock has no evidence of availability. It is never
  usable and is counted separately as no_clock.

The comparison is inclusive: a record ingested exactly at decision_at is
usable. Both timestamps must be timezone-aware. Naive datetimes raise
AsOfError through core.ensure_utc.

Topic: availability cutoff, the rule that a record counts only after it was
ingested, with release time as the fallback.

Depends only on as_of.core. All data handled here is synthetic.
"""

from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from as_of.core import AsOfError, ClockSet, ensure_utc


# Classification labels used internally. They are not part of the public API.
_BASIS_INGEST = "ingest"
_BASIS_RELEASE = "release"
_BASIS_NONE = "none"


def _availability_basis(cs: ClockSet) -> Tuple[str, Optional[datetime]]:
    """Return which clock decides availability and its UTC value.

    The result is ("ingest", ts) when ingest_at is set, ("release", ts) when
    only release_at is set, and ("none", None) when neither is set.
    A value that is not a ClockSet raises AsOfError.
    """
    if not isinstance(cs, ClockSet):
        raise AsOfError("expected ClockSet, got %s" % type(cs).__name__)
    if cs.ingest_at is not None:
        return _BASIS_INGEST, ensure_utc(cs.ingest_at)
    if cs.release_at is not None:
        return _BASIS_RELEASE, ensure_utc(cs.release_at)
    return _BASIS_NONE, None


def usable_at(cs: ClockSet, decision_at: datetime) -> bool:
    """Return True if the record described by cs was ingested by decision_at.

    Uses ingest_at when present. Falls back to release_at when ingest_at is
    None. Returns False when both clocks are None.
    """
    decision = ensure_utc(decision_at)
    basis, stamp = _availability_basis(cs)
    if basis == _BASIS_NONE or stamp is None:
        return False
    return stamp <= decision


def filter_usable(
    records: Sequence[Tuple[str, ClockSet]], decision_at: datetime
) -> List[str]:
    """Return the ids of the records that are usable at decision_at.

    The original order of records is kept. Each record is a pair of
    (record_id, ClockSet).
    """
    decision = ensure_utc(decision_at)
    return [rid for rid, cs in records if usable_at(cs, decision)]


def cutoff_report(
    records: Sequence[Tuple[str, ClockSet]], decision_at: datetime
) -> Dict[str, int]:
    """Summarise how the records fare against the availability cutoff.

    Keys:

    * usable: records with a clock that was ingested (or released, when no
      ingest clock exists) by decision_at.
    * unusable: records with a clock that was not yet available at
      decision_at.
    * fallback_to_release: records whose availability was judged by
      release_at because ingest_at was missing. This key overlaps with usable
      and unusable. A record in it is counted once there and once here.
    * no_clock: records with neither ingest_at nor release_at.

    usable + unusable + no_clock always equals len(records).
    """
    decision = ensure_utc(decision_at)
    report = {
        "usable": 0,
        "unusable": 0,
        "fallback_to_release": 0,
        "no_clock": 0,
    }
    for _rid, cs in records:
        basis, _stamp = _availability_basis(cs)
        if basis == _BASIS_NONE:
            report["no_clock"] += 1
            continue
        if basis == _BASIS_RELEASE:
            report["fallback_to_release"] += 1
        if usable_at(cs, decision):
            report["usable"] += 1
        else:
            report["unusable"] += 1
    return report
