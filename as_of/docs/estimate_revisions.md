# estimate_revisions: revision history, consensus and breadth as of a date

## What the module does
`as_of/estimate_revisions.py` reads analyst estimates from a ledger and answers questions as of a chosen time. It never uses a value whose `knowledge_at` is later than the date asked about. It returns one analyst's history, a consensus series, and revision breadth (how many analysts moved up, down or unchanged over a window). All data is synthetic.

## Design idea
The estimate-revision topic treats an estimate as something that becomes known at a time, and a revision as a newer estimate that replaces an older one from that moment on. Past consensus should be rebuilt from only what was visible then. The as-of discipline is the basis here.

## API
- `revision_history(ledger, ticker, metric, period, analyst_id)`: list of `(knowledge_at, value)`, earliest first.
- `consensus_series(ledger, ticker, metric, period, dates)`: mean of each analyst's latest known estimate on each date. `None` before any estimate.
- `revision_breadth(ledger, ticker, metric, period, start, end)`: `{"up", "down", "unchanged"}` counts. Only analysts with an estimate inside `(start, end]` and a prior estimate at `start` are counted.

`ledger` is a list of `EstimateRecord` from `as_of.core`, or an `EstimateLedger` object.

Example (run and checked against the repo; output shown in comments):
```python
from datetime import datetime, timedelta, timezone
from as_of.core import EstimateRecord
from as_of.estimate_revisions import consensus_series, revision_breadth

t = datetime(2026, 1, 10, 9, tzinfo=timezone.utc)
ledger = [
    EstimateRecord("SYN_E1", "SYN_TKR", "eps", "SYN_2026Q1", "SYN_A1", 10.0, t, "SYN_SRC_1"),
    EstimateRecord("SYN_E2", "SYN_TKR", "eps", "SYN_2026Q1", "SYN_A1", 12.0, t + timedelta(days=1), "SYN_SRC_1"),
    EstimateRecord("SYN_E3", "SYN_TKR", "eps", "SYN_2026Q1", "SYN_A2", 14.0, t, "SYN_SRC_1"),
]
d1 = t + timedelta(days=1)
print(consensus_series(ledger, "SYN_TKR", "eps", "SYN_2026Q1", [t - timedelta(days=1), t, d1]))
# [None, 12.0, 13.0]
print(revision_breadth(ledger, "SYN_TKR", "eps", "SYN_2026Q1", t, d1))
# {'up': 1, 'down': 0, 'unchanged': 0}
```

Run with: `PYTHONPATH=. .venv/bin/python example.py`

## Known limits
- Consensus is a plain mean, one vote per analyst. No weighting, staleness rules or outlier handling.
- Breadth ignores size of change and only uses `_EQUAL_TOL` (1e-12) to call a value unchanged.
- Naive datetimes, bools, strings, `None`, NaN and infinity raise `AsOfError`. Nothing is coerced.
- Pure in-memory computation. No persistence, no network, and no `estimate_ledger` import.
