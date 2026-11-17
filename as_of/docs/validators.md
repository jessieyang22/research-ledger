# validators

## What it does

`as_of/validators.py` is a named-check registry. A validator takes a subject and returns a list of `Finding` records from `as_of.core`. The registry runs validators, turns a raised exception into a FAIL finding, and reduces findings to one status (FAIL > WARN > PASS). `as_of/validation_report.py` turns named results into a deterministic report dict and text. The module includes two helper checks: `check_no_nan` and `check_sorted_dates`. All data is synthetic.

## Design idea

The design treats validation as a set of named checks whose results are written down, not just passed in your head.

## API

- `Validator(name, check)`: a named check.
- `ValidatorRegistry().register(v)`, `.run(subject, names=None)`, `.names()`.
- `overall_status(findings)`: module-level reduction.
- `check_no_nan(mapping)`, `check_sorted_dates(dates)`.
- `build_report(title, results, generated_for)`, `report_passes(report)`, `render_report_text(report)`.

Runnable example (run from the repo root; output checked):

```python
from datetime import date
from as_of.validators import check_no_nan, check_sorted_dates
from as_of.validation_report import build_report, render_report_text, report_passes

prices = {"AAA": 101.25, "BBB": float("nan")}
dates = [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 2)]
results = {"no_nan": check_no_nan(prices), "sorted_dates": check_sorted_dates(dates)}
report = build_report("Synthetic demo", results, "2026-10-27")
print(report_passes(report))   # False
print(render_report_text(report))
```

Output: `Overall: FAIL`, `no_nan [FAIL]` with `FAIL BBB: value is NaN`, and `sorted_dates [WARN]` for the repeated date.

## Known limits

- Duplicate registry names raise `AsOfError`. A check that returns `None` or non-Finding items becomes FAIL.
- `check_no_nan` takes a mapping only, and ints are never NaN.
- `check_sorted_dates` checks order only, not calendar gaps or as-of visibility.
- `report_passes` fails closed on unknown status values, and WARN does not fail a report.
- Python 3.9 syntax only.
