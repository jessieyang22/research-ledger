# portfolio_tieout: book vs custodian quantities and valuation

## What the module does
`as_of/portfolio_tieout.py` compares share quantities per ticker between an internal book and a custodian record set. A quantity gap above a tolerance is a break. It also values positions at a date, but only when every required close exists. All data is synthetic (SYN_ ids). No network, no orders.

## Design idea
The design treats the internal book and the custodian book as two sources that must agree before any valuation built on them is used (portfolio tie-out topic). The module reconciles first, then values, and never fills a missing price from an earlier day.

## API
- `tie_out(book, custodian, tol=0.0)`: returns `{"breaks": [...], "matched": int}`. Repeated tickers are summed first; a ticker on one side only counts as zero on the other. A break is `abs(delta) > tol`. Each break has `ticker`, `book_qty`, `custodian_qty`, `delta` (book minus custodian), sorted by ticker.
- `market_value(positions, prices, as_of)`: quantity times close at `as_of`. Raises `HardFailError` for a missing, NaN, infinite or non-positive price, or a position dated after `as_of`.
- `tieout_findings(result)`: one FAIL `Finding` per break, `check_id` `tieout.break`.

Example (run and verified with the repo on `PYTHONPATH`):
```python
from datetime import date
from as_of.core import PositionRecord, PriceRecord
from as_of.portfolio_tieout import tie_out, market_value, tieout_findings

D = date(2026, 1, 5)
book = [PositionRecord("SYN_BOOK", "SYN_AAA", 10.0, D), PositionRecord("SYN_BOOK", "SYN_BBB", 7.0, D)]
cust = [PositionRecord("SYN_CUST", "SYN_AAA", 10.0, D), PositionRecord("SYN_CUST", "SYN_BBB", 5.0, D)]
res = tie_out(book, cust)
print(res)                        # one break on SYN_BBB, delta 2.0, matched 1
print(len(tieout_findings(res)))  # 1
prices = {("SYN_AAA", D): PriceRecord("SYN_AAA", D, 10.0, "SYN_SRC1"),
          ("SYN_BBB", D): PriceRecord("SYN_BBB", D, 50.0, "SYN_SRC1")}
print(market_value(book, prices, D))  # 450.0
```

## Known limits
- In memory only. Nothing is read from or written to disk.
- Quantity only. Prices, cost basis and cash are not reconciled.
- One tolerance for every ticker; no relative or per-ticker tolerance.
- `market_value` does not detect stale or unit-mismatched prices.
