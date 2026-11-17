# Macro vintage manifest

## What it does

`as_of/macro_vintage_manifest.py` stores every release of every macro observation, not just the latest revised value. Each row is a `MacroVintage` keyed by (series_id, obs_date, vintage_date). A paired cutoff rule in `as_of/macro_cutoff_rule.py` answers "what was known at time T" and audits values a decision used. Data is synthetic.

## Design idea

- Keep revisions as separate records so a reader can rebuild the state of knowledge on a past date.
- A value counts only if the release that carries it was public at the decision time. A later revision does not count until its own release moment has passed.

## API

- `VintageManifest()`: `add_vintage(v)` rejects duplicate keys and bad fields; `entries(series_id)` returns rows sorted by vintage_date; `manifest_hash()` is a SHA-256 over rows in canonical order; `to_list()` returns plain dicts.
- `value_as_of(manifest, series_id, obs_date, decision_at)`: latest vintage released at or before `decision_at`, or None.
- `cutoff_violations(uses, decision_at)`: one FAIL finding per value released after `decision_at`.

Runnable example (verified; run with the repo root on `PYTHONPATH`):

```python
from datetime import date, datetime, timezone
from as_of.core import MacroVintage
from as_of.macro_vintage_manifest import VintageManifest
from as_of.macro_cutoff_rule import value_as_of, cutoff_violations

m = VintageManifest()
m.add_vintage(MacroVintage("SYN_GDP", date(2026, 1, 1), date(2026, 2, 1),
                           datetime(2026, 2, 1, 8, 30, tzinfo=timezone.utc), 2.0, "SYN_SRC_GDP"))
m.add_vintage(MacroVintage("SYN_GDP", date(2026, 1, 1), date(2026, 4, 1),
                           datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc), 1.8, "SYN_SRC_GDP"))
v = value_as_of(m, "SYN_GDP", date(2026, 1, 1), datetime(2026, 3, 1, tzinfo=timezone.utc))
print(v.value)  # 2.0
late = value_as_of(m, "SYN_GDP", date(2026, 1, 1), datetime(2026, 5, 1, tzinfo=timezone.utc))
print(late.value)  # 1.8
print(len(cutoff_violations([late], datetime(2026, 3, 1, tzinfo=timezone.utc))))  # 1
```

## Known limits

- In-memory only.
- Naive datetimes raise AsOfError.
- Only the release time is checked. Revision-policy and data-quality rules are not modeled.
- `value_as_of` scans all vintages of a series (linear time).
