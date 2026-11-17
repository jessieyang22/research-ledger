# earnings_fixture: synthetic as-of earnings data

## What the module does
`as_of/earnings_fixture.py` builds a seeded, synthetic earnings dataset for invented tickers (`SYN_T01`, `SYN_T02`, ...). It returns estimate rows, reported figures and source records. Every row carries its own timestamps, so the as-of rules can be tested. It does no I/O and no network calls, and it names no real company.

## Design idea
The synthetic fixtures topic says a fixture should carry its own as-of timestamps, so that a test can check whether any analyst estimate was known before the report it is compared against. This module follows that idea.

## API
- `make_fixture(seed=20261027, n_tickers=3, n_quarters=4)` returns a dict with:
  - `sources`: one estimate source and one report source per ticker. `source_type` is FIXTURE, `synthetic` is True, and `sha256` hashes the rows that source supplies.
  - `estimates`: `EstimateRecord` rows, one per ticker, metric, quarter and analyst. `knowledge_at` falls before the report date.
  - `reports`: dicts with `ticker`, `metric`, `period`, `reported_value` and `reported_at` (aware UTC).
- Bad types or values (bool counts, negative or non-int seed, NaN) raise `AsOfError`.

Example (run and verified with the repo on `PYTHONPATH`):
```python
from as_of.earnings_fixture import make_fixture
fx = make_fixture(seed=20261027, n_tickers=2, n_quarters=4)
print(len(fx["sources"]), len(fx["estimates"]), len(fx["reports"]))   # 4 48 16
r = fx["reports"][0]
print(r["ticker"], r["period"], r["reported_at"].isoformat())          # SYN_T01 2025Q1 2025-05-01T20:00:00+00:00
print(fx["estimates"][0].knowledge_at < r["reported_at"])              # True
```

## Known limits
- Two metrics only (`eps`, `revenue`) and three analysts per quarter.
- Report dates use a fixed lag window of 25 to 39 days after the 28th of the quarter-end month. Real filing calendars are not modeled.
- Values are drawn from a normal-noise generator. They do not reflect real company behavior.
- The `sha256` fields are hashes of the rows as generated. Nothing here checks them against an external manifest.
- Tests: `as_of/tests/test_earnings_fixture_attack.py` (18 passed).
