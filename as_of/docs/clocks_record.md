# clocks_record: five timestamps per record

## What the module does
`as_of/clocks_record.py` holds the five clocks of a record (event, knowledge, report, release, ingest) in one frozen `ClockSet`. It normalises every timestamp to aware UTC, builds new sets instead of editing old ones, and serialises to plain strings. It does not decide visibility; that is `as_of/clock_as_of.py`. Ordering checks live in `as_of/clock_ordering.py`.

## Design idea
The as-of discipline asks that each record say when something was true, when it was known, and when it became visible in the pipeline, so a past decision can be replayed without future information. This module implements the separate-clocks idea.

## API
- `make_clockset(event_at=None, knowledge_at=None, report_at=None, release_at=None, ingest_at=None)`: `None` means unknown; other values become aware UTC (naive raises `AsOfError`).
- `clock_value(cs, name)`: returns one clock; `name` must be a `ClockName`.
- `with_clock(cs, name, value)`: returns a new `ClockSet`; `None` clears the clock.
- `clockset_to_dict(cs)`: `{clock: "YYYY-MM-DDTHH:MM:SSZ" or None}` in core order.

Example (verified by running it):
```python
from datetime import datetime, timezone
from as_of.clocks_record import make_clockset, with_clock, clock_value, clockset_to_dict
from as_of.core import ClockName

u = timezone.utc
cs = make_clockset(event_at=datetime(2026, 10, 1, 9, tzinfo=u),
                   knowledge_at=datetime(2026, 10, 1, 10, tzinfo=u),
                   report_at=datetime(2026, 10, 1, 11, tzinfo=u),
                   release_at=datetime(2026, 10, 1, 12, tzinfo=u),
                   ingest_at=datetime(2026, 10, 1, 13, tzinfo=u))
print(clockset_to_dict(cs))
# {'event': '2026-10-01T09:00:00Z', 'knowledge': '2026-10-01T10:00:00Z', ...}
cs2 = with_clock(cs, ClockName.RELEASE, datetime(2026, 10, 1, 12, 30, tzinfo=u))
print(clock_value(cs2, ClockName.RELEASE))  # 2026-10-01 12:30:00+00:00
print(clock_value(cs, ClockName.RELEASE))   # original unchanged: 12:00:00+00:00
```

## Known limits
- Synthetic data only; no network, no trading code.
- Fractional seconds are dropped by `clockset_to_dict`.
- A `None` clock means unknown, not zero; visibility checks treat a missing knowledge clock as not visible.
- Overflow on extreme dates raises `AsOfError`.
