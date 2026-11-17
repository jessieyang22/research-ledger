"""Immutable clock timestamps for a record.

A record in the as_of package carries five clocks: event, knowledge,
report, release and ingest. Each clock answers a different question about
when something was true or became visible. This module holds those five
timestamps together as one frozen ClockSet value, and provides small
helpers to read a single clock, to derive a new ClockSet with one clock
changed, and to serialise the set to plain strings.

Topic: "five clocks".

Conventions:
- ClockSet and ClockName come from as_of.core. No other as_of module is used.
- Every non-None timestamp is stored as aware UTC. Naive datetimes raise
  AsOfError (via core.ensure_utc).
- ClockSet is frozen, so changes are made by building a new object with
  with_clock. The original is never modified.
- All data handled here is synthetic.
"""

from datetime import datetime
from typing import Dict, Optional

from as_of.core import CLOCK_NAMES, AsOfError, ClockName, ClockSet, ensure_utc, fmt_ts


def _normalise(value: Optional[datetime]) -> Optional[datetime]:
    """Return value as aware UTC, or None when value is None."""
    if value is None:
        return None
    try:
        return ensure_utc(value)
    except OverflowError as exc:
        # Converting an extreme datetime (e.g. year 1 with a positive offset)
        # to UTC overflows; report it as a bad timestamp, not a raw crash.
        raise AsOfError("timestamp out of range for UTC: %r" % (value,)) from exc


def _field_name(name: ClockName) -> str:
    """Map a ClockName to the matching ClockSet attribute name."""
    if not isinstance(name, ClockName):
        raise TypeError("expected ClockName, got %s" % type(name).__name__)
    return name.value + "_at"


def make_clockset(
    event_at: Optional[datetime] = None,
    knowledge_at: Optional[datetime] = None,
    report_at: Optional[datetime] = None,
    release_at: Optional[datetime] = None,
    ingest_at: Optional[datetime] = None,
) -> ClockSet:
    """Build a ClockSet from the five clock values.

    Any clock left as None is unknown for this record. Non-None values are
    normalised to aware UTC.
    """
    return ClockSet(
        event_at=_normalise(event_at),
        knowledge_at=_normalise(knowledge_at),
        report_at=_normalise(report_at),
        release_at=_normalise(release_at),
        ingest_at=_normalise(ingest_at),
    )


def clock_value(cs: ClockSet, name: ClockName) -> Optional[datetime]:
    """Return the timestamp held for clock name, or None if it is unset."""
    return getattr(cs, _field_name(name))


def with_clock(cs: ClockSet, name: ClockName, value: Optional[datetime]) -> ClockSet:
    """Return a new ClockSet with clock name set to value.

    The input cs is not modified. A None value clears that clock.
    """
    field = _field_name(name)
    values = {
        "event_at": cs.event_at,
        "knowledge_at": cs.knowledge_at,
        "report_at": cs.report_at,
        "release_at": cs.release_at,
        "ingest_at": cs.ingest_at,
    }
    values[field] = _normalise(value)
    return ClockSet(**values)


def clockset_to_dict(cs: ClockSet) -> Dict[str, Optional[str]]:
    """Return a plain dict of clock name to 'YYYY-MM-DDTHH:MM:SSZ' or None.

    The keys are exactly core.CLOCK_NAMES, in that order.
    """
    out: Dict[str, Optional[str]] = {}
    for key in CLOCK_NAMES:
        value = getattr(cs, key + "_at")
        out[key] = None if value is None else fmt_ts(value)
    return out
