# wf_portfolio_tieout_factor (Proof 4)

## What the module does
`as_of/wf_portfolio_tieout_factor.py` runs one synthetic proof in three parts. (1) It ties out quantities ticker by ticker between an internal book and a custodian book; the fixture plants exactly one break. (2) It values the book through the hard-fail price rule, optionally with one required close removed. (3) It re-estimates factor betas by OLS from a noise-free return panel and checks them against the planted exposures within 1e-6. The proof passes only if there is no hard failure, no duplicate rows, exactly one break on the planted ticker, and every beta reproduces. All data is synthetic (SYN_ ids). The module does no I/O, no network calls, and holds no order logic.

## Design idea
The portfolio tie-out topic treats the internal book and the custodian book as two sources that must agree before any valuation built on them is trusted. A reproduced exposure should also be checked against a fixture with known answers.

## API
`run_tieout_factor_proof(seed=SYNTHETIC_SEED, inject_missing_price=False, tol=1e-9) -> ProofResult`

- Metrics: `tieout_break_count`, `tieout_matched`, `hard_fail_count`, `duplicate_rows`, `beta_max_abs_error`, `beta_tol`, `n_assets`, `n_factors`, `tol`, and `book_value` when valuation succeeds.
- Finding check IDs: `tieout.break`, `price.hard_fail`, `factor.beta_reproduce`.
- Invalid arguments raise `AsOfError`.

Example (run from the repo root, verified):
```python
from as_of.wf_portfolio_tieout_factor import run_tieout_factor_proof

ok = run_tieout_factor_proof()
print(ok.passed, ok.metrics["tieout_break_count"])        # True 1.0
bad = run_tieout_factor_proof(inject_missing_price=True)
print(bad.passed, bad.metrics["hard_fail_count"])         # False 1.0
```

## Known limits
- Synthetic fixture only. The planted break and exposures are generated, so a pass shows the code handles known answers, not that real books reconcile.
- Betas come from a noise-free panel, so the 1e-6 check tests the OLS arithmetic, not estimation under noise.
- Quantities only. Prices, cost basis and cash are not reconciled.
- One tolerance applies to every ticker. A `tol` at or above the break size (250) hides the break, and the proof then fails.
