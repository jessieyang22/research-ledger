# clock_as_of: point-in-time visibility

## What the module does
`as_of/clock_as_of.py` decides whether a clock-stamped record is visible at a decision time T. A record is visible only when its `knowledge_at` is set and is at or before T. Records with `knowledge_at = None` are never visible. All comparisons use aware UTC through `core.ensure_utc`, and a naive datetime raises `AsOfError`. It does not build or edit clocks; that is `as_of/clocks_record.py`.

## Design idea
The as-of discipline asks that each research input carry the time it became known, so that a past decision is replayed using only information available then. This module implements that visibility rule.

## API
- `known_as_of(cs, as_of) -> bool`: True when `cs.knowledge_at <= as_of`. Equal times count as known.
- `visible_at(records, as_of) -> list`: visible records, in original order.
- `latest_known(records, as_of) -> ClockSet or None`: the visible record with the largest `knowledge_at`. Ties go to the earlier record in the input.

Every function validates `as_of` first, even for empty input. A non-`ClockSet` row raises `AsOfError`.

Example (run and verified with the repo on `PYTHONPATH`):
```python
from datetime import datetime, timedelta, timezone
from as_of.core import ClockSet
from as_of.clock_as_of import known_as_of, visible_at, latest_known

u = timezone.utc
T = datetime(2026, 10, 1, 12, 0, tzinfo=u)
a = ClockSet(event_at=T - timedelta(days=2), knowledge_at=T - timedelta(hours=3))
b = ClockSet(event_at=T - timedelta(days=1), knowledge_at=T + timedelta(hours=1))
c = ClockSet(event_at=T - timedelta(days=1), knowledge_at=None)
d = ClockSet(event_at=T, knowledge_at=T - timedelta(hours=1))
recs = [a, b, c, d]
print(known_as_of(b, T))           # False
print(len(visible_at(recs, T)))    # 2
print(latest_known(recs, T) is d)  # True
print(latest_known([], T))         # None
```

## Known limits
- Visibility uses only `knowledge_at`. It does not check the event, report, release, or ingest clocks; ordering is in `as_of/clock_ordering.py`.
- A `None` knowledge clock means unknown, so the record is excluded, not treated as early.
- It filters one list at one time. It does not check whether a record was later revised.
- Synthetic data only (`SYN_` ids in tests); no network calls, no trading code.
