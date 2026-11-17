# price_hard_fail: stop the run on a bad price

## What the module does
`as_of/price_hard_fail.py` checks price records before a run uses them. A price that is missing, NaN, infinite, non-numeric or non-positive stops the run. It is never forward-filled, interpolated or defaulted. Data is synthetic (`SYN_` prefix). Standard library and `as_of.core` only; no network calls.

## Design idea
The design treats a missing price on a required date as a hard stop, not a gap to fill, so a reviewer can see exactly which input was absent.

## API
- `require_price(prices, ticker, as_of) -> PriceRecord`: returns the record, or raises `HardFailError`. It never looks at earlier dates.
- `check_price_panel(records, tickers, dates) -> List[Finding]`: one `FAIL` finding per bad (ticker, date) cell. An empty list means the panel is complete and valid. Messages start with `[block]` because `Finding` has no severity field.

Example (repo root; output verified):
```python
from datetime import date
from as_of.core import PriceRecord, HardFailError
from as_of.price_hard_fail import require_price, check_price_panel

D1, D2 = date(2026, 1, 5), date(2026, 1, 6)
records = [
    PriceRecord(ticker="SYN_AAA", as_of=D1, close=10.0, source_id="SYN_SRC1"),
    PriceRecord(ticker="SYN_AAA", as_of=D2, close=float("nan"), source_id="SYN_SRC1"),
    PriceRecord(ticker="SYN_BBB", as_of=D1, close=20.0, source_id="SYN_SRC1"),
]
prices = {(r.ticker, r.as_of): r for r in records}

print(require_price(prices, "SYN_AAA", D1).close)   # 10.0
try:
    require_price(prices, "SYN_AAA", D2)            # NaN close: raises
except HardFailError as exc:
    print(exc)
print(len(check_price_panel(records, ["SYN_AAA", "SYN_BBB"], [D1, D2])))  # 2
```

## Known limits
- `require_price` checks the record's ticker and date against its key, not `source_id`.
- Duplicate records in one panel cell fail if any one fails. Conflicts are not resolved.
- Dates are not checked against a trading calendar.
- `check_price_panel` ignores records outside the requested grid.
- Python 3.9 only. Tests: `as_of/tests/test_price_hard_fail.py` (20 passed).
