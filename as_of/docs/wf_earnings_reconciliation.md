# wf_earnings_reconciliation: as-of earnings proof

## What the module does
`as_of/wf_earnings_reconciliation.py` runs a proof on synthetic earnings data. For each reported figure it rebuilds the expected value using only estimates known before the report time, then classifies the surprise as beat, miss or inline. It also flags any estimate known at or after the report time (LOOKAHEAD_RISK) and checks that every source id used is in the source register. It makes no network calls and uses only synthetic `SYN_` ids.

## Design idea
The idea, as the module reads it: a reconciliation must be rebuilt as of each report time, not as of the day the check runs.

## API
- `run_earnings_proof(seed=SYNTHETIC_SEED, inject_lookahead=False) -> ProofResult`
- `passed` is True only when there is at least one report and no finding has FAIL status.
- `metrics` holds counts such as `n_reports`, `n_beat`, `n_miss`, `n_inline`, `n_lookahead_rows`.
- Surprise bands and the injected late analyst are set by `SURPRISE_BAND` (0.02) and `LATE_OFFSET_DAYS` (2).

Example (run and verified with the repo on `PYTHONPATH`):
```python
from as_of.wf_earnings_reconciliation import run_earnings_proof
r = run_earnings_proof()
print(r.passed, r.metrics["n_reports"], r.metrics["n_beat"], r.metrics["n_miss"], r.metrics["n_inline"])
# True 24.0 11.0 6.0 7.0
r2 = run_earnings_proof(inject_lookahead=True)
print(r2.passed, r2.metrics["n_lookahead_rows"])
# False 24.0
```

## Known limits
- Synthetic data only. Results say nothing about real companies.
- A knowledge time equal to the report time is known, not look-ahead. Only rows strictly after the report time are flagged (LOOKAHEAD_RISK). The proof passes report time plus one microsecond to the bridge, because the bridge's own rule is strictly before its bound. The bridge itself is unchanged and still excludes rows at its reported_at (see `as_of/tests/test_reported_vs_expected_bridge.py`). Two rules now coexist: the bridge is strict, the proof is inclusive. A human may want one convention everywhere.
- The bridge's expected value is a mean of each analyst's latest visible estimate. A real consensus may be built differently.
