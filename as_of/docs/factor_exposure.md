# factor_exposure: reproduce factor betas and compare with reported values

## What the module does
`as_of/factor_exposure.py` re-estimates linear factor exposures (betas) for a panel of asset returns by ordinary least squares, then compares them with exposures reported elsewhere. It returns betas, intercepts, R-squared and residual volatility. It uses synthetic data only (SYN_ ids), with no network access and no order logic.

## Design idea
The design treats a reported risk number as something to reproduce from its inputs before anyone relies on it. The module recomputes, then compares within a stated tolerance.

## API
- `reproduce_exposures(asset_returns, factor_returns, add_intercept=True)`: `asset_returns` is T x N, `factor_returns` is T x K. Returns a dict with `betas` (N x K), `intercept` (length N), `r2` and `resid_vol` (length N). Residual volatility is per period, not annualised. Raises `AsOfError` on bad shapes, NaN or infinite values, a rank-deficient design, or too few rows.
- `compare_reported(reported, recomputed, tol)`: one `Finding` per key. PASS when the absolute difference is at most `tol`, FAIL otherwise, WARN for a key present on only one side.

Example (run and verified with the repo on `PYTHONPATH`):
```python
import numpy as np
from as_of.factor_exposure import reproduce_exposures, compare_reported

rng = np.random.default_rng(7)
F = rng.standard_normal((120, 2))
B = np.array([[1.0, -0.5], [0.3, 0.8]])
Y = F @ B.T + 0.01 * rng.standard_normal((120, 2))

out = reproduce_exposures(Y, F)
print(np.round(out["betas"], 3))   # [[ 1.001 -0.501] [ 0.3    0.799]]
reported = {"SYN_A|f1": 1.0}
recomputed = {"SYN_A|f1": float(out["betas"][0, 0])}
for f in compare_reported(reported, recomputed, tol=0.05):
    print(f.subject, f.status, f.message)  # SYN_A|f1 PASS ...
```

## Known limits
- Caller must align dates. A one-row shift between returns and factors keeps the shape valid and changes the betas; the module cannot detect it.
- No as-of date parameter and no look-ahead check.
- Duplicated rows that still vary are not detected and inflate T.
- Plain OLS only: no standard errors, robust errors or weighting.
