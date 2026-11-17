# Macro fixture

Module: `as_of/macro_fixture.py`

## What it does

Builds synthetic macro releases for two made-up series, `SYN_GDP` and `SYN_CPI`: 12 monthly observations each in 2025. Each observation gets a first release after a fixed lag (30 days for GDP, 14 for CPI). Every third observation also gets a revision 60 days later. The same seed gives the same output.

## API

- `make_macro_fixture(seed=SYNTHETIC_SEED)` returns a list of `MacroVintage`. A non-int or bool seed, or a negative seed, raises `AsOfError`.

Runnable example (from the repo root, with the venv Python; verified):

```python
from datetime import date, datetime, timezone
from as_of.macro_fixture import make_macro_fixture
from as_of.macro_vintage_manifest import VintageManifest
from as_of.macro_cutoff_rule import value_as_of, cutoff_violations

U = timezone.utc
manifest = VintageManifest()
for row in make_macro_fixture(seed=7):
    manifest.add_vintage(row)

obs = date(2025, 1, 1)
first = value_as_of(manifest, "SYN_GDP", obs, datetime(2025, 2, 15, tzinfo=U))
latest = value_as_of(manifest, "SYN_GDP", obs, datetime(2025, 5, 1, tzinfo=U))
print("first release:", first.value, first.vintage_date)     # 2.0 2025-01-31
print("latest as of May 1:", latest.value, latest.vintage_date)  # 2.2 2025-04-01
print("violations:", cutoff_violations([first], datetime(2025, 2, 15, tzinfo=U)))  # []
```

## Known limits

- Only two series, 12 observations each, all in 2025.
- Release lags, revision timing and revision steps are fixed constants, not estimates of real release behavior.
- Revisions happen only on every third observation and always move the value by one of six fixed steps.
- Values are rounded to two decimals.
- Only `as_of.core` is imported by the fixture. Its output is not a real macro history and should not be used to judge a real series.
