# core: shared constants, records and helpers

## What the module does
`as_of/core.py` holds the pieces every other `as_of` module uses: the five clock names, source and severity enums, frozen record types, timestamp parsing and formatting, canonical JSON, and SHA-256 hashing. It imports only the standard library and numpy. Other modules are loaded lazily through `component(name)`. All data is synthetic (`SYN_` prefix).

## Design idea
The as-of discipline keeps each fact's timestamps explicit, so a past decision can be replayed without later information. Core supplies the shared vocabulary for that: named clocks, source records and hashes that let a reviewer confirm which input was used.

## API
- `parse_ts(text)`: accepts `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SSZ` and returns aware UTC. Anything else raises `AsOfError`.
- `fmt_ts(dt)`: formats an aware datetime as `YYYY-MM-DDTHH:MM:SSZ`. Naive datetimes raise.
- `canonical_json(obj)` and `stable_hash(obj)`: sorted-key JSON and its SHA-256. NaN is rejected.
- `to_plain(obj)`: converts records, enums, dates and numpy scalars to JSON-ready values.
- `ClockName`, `SourceType`, `Severity`, `ValidationStatus`, `RunStatus`: enums.
- Frozen records: `SourceRecord`, `ClockSet`, `EstimateRecord`, `ClaimRecord`, `ExceptionRecord`, and others.
- `require(cond, msg)`, `component(name)`, `make_rng(seed)`, `sha256_text(text)`.

Example (run from the repo root; output verified):
```python
from datetime import datetime, timezone
from as_of.core import parse_ts, fmt_ts, stable_hash

print(parse_ts("2026-10-27"))                                  # 2026-10-27 00:00:00+00:00
print(fmt_ts(datetime(2026, 10, 27, 12, tzinfo=timezone.utc))) # 2026-10-27T12:00:00Z
print(stable_hash({"b": 1, "a": [1, 2]}))                      # 94a786c3662bc7beeb598efa7d8cb58d7bea25d6c275ea9785a0230ff1f8c2ba
```

## Known limits
- Timestamps must be UTC-style strings. Fractional seconds, numeric offsets and lowercase `z` are rejected.
- `fmt_ts` drops fractional seconds.
- `canonical_json` only accepts dict keys that convert to strings.
- Hashes cover canonical JSON only, not raw file bytes.
- Records are descriptive containers. Core does no validation beyond type and format checks.
- Python 3.9 only.
