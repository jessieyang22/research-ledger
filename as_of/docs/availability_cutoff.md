# availability_cutoff: when a record counts as known

## What the module does
`as_of/availability_cutoff.py` decides whether a record was available to a researcher at a decision time. It uses `ingest_at` (when the record entered our store). If that is missing, it falls back to `release_at` and counts the fallback. A record with neither clock is never usable and is counted as `no_clock`. Naive datetimes raise `AsOfError`.

## Design idea
The as-of discipline treats a record as usable only once the team could have read it. This module uses our ingest time, not the vendor release time, for that reason. No page is given.

## API
- `usable_at(cs, decision_at) -> bool`: True when the deciding clock is at or before `decision_at`.
- `filter_usable(records, decision_at) -> list`: usable ids, in input order.
- `cutoff_report(records, decision_at) -> dict`: keys `usable`, `unusable`, `fallback_to_release`, `no_clock`. The fallback count overlaps usable and unusable.

Example (run and verified with the repo on `PYTHONPATH`):
```python
from datetime import datetime, timedelta, timezone
from as_of.core import ClockSet
from as_of.availability_cutoff import usable_at, filter_usable, cutoff_report

u = timezone.utc
T = datetime(2026, 10, 1, 12, 0, tzinfo=u)
a = ClockSet(release_at=T - timedelta(hours=2), ingest_at=T - timedelta(hours=1))
b = ClockSet(release_at=T - timedelta(hours=2), ingest_at=T + timedelta(minutes=5))
c = ClockSet(release_at=T - timedelta(hours=3))
d = ClockSet(event_at=T - timedelta(days=1))
recs = [("SYN_A", a), ("SYN_B", b), ("SYN_C", c), ("SYN_D", d)]
print(usable_at(a, T))         # True
print(filter_usable(recs, T))  # ['SYN_A', 'SYN_C']
print(cutoff_report(recs, T))  # {'usable': 2, 'unusable': 1, 'fallback_to_release': 1, 'no_clock': 1}
```

## Known limits
- The release fallback is weaker: a release time can precede our ingest, so a fallback record may look usable too early. Check `fallback_to_release`.
- No check that ingest comes after release (see `as_of/clock_ordering.py`).
- One timestamp per record; revisions are not tracked.
- Both clocks missing means excluded, not early.
- Synthetic data only (`SYN_` ids); no network or trading code.
