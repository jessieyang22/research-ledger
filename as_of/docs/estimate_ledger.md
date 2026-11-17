# estimate_ledger: point-in-time analyst estimates

## What the module does
`as_of/estimate_ledger.py` stores analyst estimates in an append-only, in-memory ledger. Each row is an `EstimateRecord` with a `knowledge_at` time saying when that estimate became known. Rows are never overwritten. A revision is a new row with a later `knowledge_at`, and the earlier row stays. Consensus can be recomputed as of any date by ignoring rows not yet known on that date. All data is synthetic.

## Design idea
The estimate ledger topic asks that analyst estimates and their revisions be kept with the time each became known, so that consensus at a past date can be rebuilt from only what was visible then. This module implements that rule.

## API
- `EstimateLedger.append(rec)`: adds one row. Raises `AsOfError` on a naive `knowledge_at`, a non-numeric value, a blank identifier, or a duplicate key.
- `rows(ticker, metric, period)`: every row for a series, sorted by `knowledge_at`.
- `latest_per_analyst(ticker, metric, period, as_of)`: each analyst's latest row known on or before `as_of`.
- `consensus_as_of(ticker, metric, period, as_of)`: mean of those latest values, one vote per analyst. Returns `None` if nobody had an estimate yet.
- `validate()`: returns `Finding` objects for naive times, non-finite values, or an empty ledger.

Example (run and verified with the repo on `PYTHONPATH`):
```python
from datetime import datetime, timedelta, timezone
from as_of.core import EstimateRecord
from as_of.estimate_ledger import EstimateLedger

t = datetime(2026, 1, 10, 9, tzinfo=timezone.utc)
L = EstimateLedger()
L.append(EstimateRecord("SYN_E1", "SYN_TKR", "eps", "SYN_2026Q1", "SYN_A1", 10.0, t, "SYN_SRC_1"))
L.append(EstimateRecord("SYN_E2", "SYN_TKR", "eps", "SYN_2026Q1", "SYN_A1", 12.0, t + timedelta(days=1), "SYN_SRC_1"))
L.append(EstimateRecord("SYN_E3", "SYN_TKR", "eps", "SYN_2026Q1", "SYN_A2", 14.0, t, "SYN_SRC_1"))
print(L.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", t))                        # 12.0
print(L.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", t + timedelta(days=1)))    # 13.0
print(L.consensus_as_of("SYN_TKR", "eps", "SYN_2026Q1", t - timedelta(days=1)))    # None
```

## Known limits
- In memory only. Nothing persists between runs.
- Consensus is a plain mean. No weighting, staleness decay, or outlier handling.
- Only exact-key duplicates are rejected. Two analysts' rows with the same timestamp both count.
- `validate()` does not flag stale estimates or unit mismatches.
- Only `core.py` is imported from the `as_of` package.
