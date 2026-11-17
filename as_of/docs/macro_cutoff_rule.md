# Macro cutoff rule

Module: `as_of/macro_cutoff_rule.py`

## What it does

A macro value can be used at a decision time only if the vintage carrying it was released at or before that time. A later revision of the same observation does not count until its own release moment has passed. The module picks the usable vintage and audits uses that break this rule. All data is synthetic.

## API

- `value_as_of(manifest, series_id, obs_date, decision_at)` returns the latest vintage of one observation released at or before `decision_at`, or `None`. Ties on `release_at` go to the later `vintage_date`. A naive `decision_at` or a non-date `obs_date` raises `AsOfError`.
- `cutoff_violations(uses, decision_at)` returns one FAIL `Finding` per used vintage released after `decision_at`. An empty list means no violations were found.
- `CHECK_ID` is `"macro_cutoff"`.

Runnable example (run from the repo root with the venv Python):

```python
from datetime import date, datetime, timezone
from as_of.core import MacroVintage
from as_of.macro_vintage_manifest import VintageManifest
from as_of.macro_cutoff_rule import value_as_of, cutoff_violations

U = timezone.utc
m = VintageManifest()
m.add_vintage(MacroVintage(series_id="SYN_GDP", obs_date=date(2026, 1, 1),
    vintage_date=date(2026, 2, 1), release_at=datetime(2026, 2, 1, 8, 30, tzinfo=U),
    value=2.1, source_id="SYN_SRC_SYN_GDP"))
m.add_vintage(MacroVintage(series_id="SYN_GDP", obs_date=date(2026, 1, 1),
    vintage_date=date(2026, 4, 1), release_at=datetime(2026, 4, 1, 8, 30, tzinfo=U),
    value=2.4, source_id="SYN_SRC_SYN_GDP"))

d = datetime(2026, 3, 15, 12, 0, tzinfo=U)
v = value_as_of(m, "SYN_GDP", date(2026, 1, 1), d)
print(v.value, v.vintage_date)                  # 2.1 2026-02-01
print(cutoff_violations([v], d))                # []
late = m.entries("SYN_GDP")[1]
print(cutoff_violations([late], d)[0].message)  # value released at 2026-04-01T08:30:00Z is after decision time 2026-03-15T12:00:00Z
```

## Known limits

- It checks release timestamps only. It does not verify that `release_at` is correct.
- `cutoff_violations` audits only the uses it is given. It does not find uses that were never recorded.
- Ties on `release_at` are broken by `vintage_date`, which is a fixed rule, not a judgment about which value was actually visible.
