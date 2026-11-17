# portfolio_fixture: synthetic books, prices and returns with one planted break

## What the module does
`as_of/portfolio_fixture.py` builds a deterministic synthetic portfolio. It produces two position books for the same as-of date that differ in exactly one ticker's quantity, a daily price panel with exactly one missing ticker-date cell, and factor and asset return series that generate the prices. It does no I/O and no network access. All ids use the `SYN_` prefix.

## Design idea
A tie-out check needs test data whose correct answer is known in advance. Plant one break and one gap, then confirm the checks find exactly those.

## API
`make_portfolio_fixture(seed=SYNTHETIC_SEED, n_days=60, tickers=("SYN_A", "SYN_B", "SYN_C"))` returns a dict:
- `positions_book`, `positions_custodian`: lists of `PositionRecord`. The custodian quantity for the breaking ticker is the book quantity plus 250.0.
- `prices`: list of `PriceRecord`, one per ticker per weekday, minus the missing cell.
- `factor_returns`: array of shape (n_days, 2). `asset_returns`: array of shape (n_days, len(tickers)).
- `missing_price`: `(ticker, date)` absent from `prices`. The date can equal the as-of date.

Trading days are weekdays starting 2025-01-02, with no holiday calendar. Equal arguments give equal output. Invalid arguments raise `AsOfError`.

Example (run and verified with the repo on the path):
```python
from as_of.portfolio_fixture import make_portfolio_fixture

fx = make_portfolio_fixture()
book = {r.ticker: r.quantity for r in fx["positions_book"]}
cust = {r.ticker: r.quantity for r in fx["positions_custodian"]}
breaks = [t for t in book if book[t] != cust[t]]
print(breaks, cust[breaks[0]] - book[breaks[0]])  # ['SYN_A'] 250.0
print(fx["missing_price"])                        # ('SYN_A', datetime.date(2025, 3, 25))
print(len(fx["prices"]))                          # 179
```

## Known limits
- Synthetic only. Prices and returns are Gaussian draws, not market data.
- Each fixture has exactly one quantity break and one missing price. No multi-break or multi-gap scenarios.
- The break is always positive (+250.0). The breaking ticker is chosen by the seed.
- The missing cell is never the first trading day.
- No holiday calendar, cost basis, cash or corporate actions.
- Tests: `as_of/tests/test_portfolio_fixture.py` (25 passed).
