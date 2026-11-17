# synthetic_calendar: business days and schedule dates for 2026

## What the module does
`as_of/synthetic_calendar.py` answers three calendar questions: is a date a business day, what is the next business day, and how many business days lie in a range. It also lists scheduled dates. A business day is a Monday to Friday that is not in `HOLIDAYS_2026`, a fixed hand-written set of 12 dates. All data is synthetic. The module imports only `as_of.core`.

## Design idea
The module docstring points to the "scheduling contract" topic. The idea this module uses is that a run's due dates depend on one named, fixed calendar rule, so a past schedule can be replayed with the same rule.

## API
- `is_business_day(d) -> bool`
- `next_business_day(d) -> date`: first business day strictly after `d`.
- `business_days_between(start, end) -> int`: counts the half-open range `[start, end)`. A reversed range returns the negated count.
- `scheduled_dates(start, end, weekdays_only) -> List[date]`: half-open range. Holidays are kept when `weekdays_only` is True. `start > end` raises `AsOfError`.
- Every function requires `datetime.date`. A `datetime` raises `TypeError`.

Example (run and verified):
```python
from datetime import date
from as_of.synthetic_calendar import (
    is_business_day, next_business_day, business_days_between, scheduled_dates)

is_business_day(date(2026, 10, 26))                       # True (Monday)
next_business_day(date(2026, 10, 2))                      # date(2026, 10, 5)
business_days_between(date(2026, 10, 26), date(2026, 11, 2))  # 5
scheduled_dates(date(2026, 10, 23), date(2026, 10, 27), weekdays_only=True)
# [date(2026, 10, 23), date(2026, 10, 26)]
```
Tests: `as_of/tests/test_synthetic_calendar.py` (26 passed in this session).

## Known limits
- The docstring says this module is used by scheduling and timeliness checks. No module in `as_of` currently imports it; only tests do. `schedule_contract.py` states it applies no holiday calendar.
- The holiday set covers 2026 only. Any other year returns holidays as ordinary weekdays.
- Good Friday is a local choice, not a federal holiday.
- `scheduled_dates` with `weekdays_only=True` keeps holidays by design.
