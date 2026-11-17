# schedule_contract: when a recurring run is due

## What the module does
`as_of/schedule_contract.py` holds a named schedule: a cadence (`daily`, `weekly` or `monthly`), a due time as `HH:MM`, a grace window in minutes, and a flag that drops weekends. `expected_runs()` turns that contract and a date range into the naive datetimes when runs are due. It does not decide whether a run was on time, late or missed. Grace minutes are stored but not applied. All data is synthetic, and the module imports only `as_of.core`.

## Design idea
The scheduling-contract idea is that a recurring research run should have a written, fixed rule for when it is due, so a later reviewer can check whether each run happened on time. The module follows that idea.

## API
- `ScheduleContract(name, cadence, due_time, grace_minutes, business_days_only)`. Validates each field and raises `AsOfError` on bad input.
- `expected_runs(contract, start, end) -> List[datetime]`. Inclusive range, chronological. Both arguments must be `date`, not `datetime`.

Example (run and verified):
```python
from datetime import date
from as_of.schedule_contract import ScheduleContract, expected_runs

c = ScheduleContract(name="synthetic_daily_close", cadence="daily",
                     due_time="16:05", grace_minutes=10, business_days_only=True)
expected_runs(c, date(2026, 10, 23), date(2026, 10, 27))
# [datetime(2026, 10, 23, 16, 5), datetime(2026, 10, 26, 16, 5), datetime(2026, 10, 27, 16, 5)]
```
Tests: `as_of/tests/test_schedule_contract.py` and `test_schedule_contract_attack.py` (48 passed in this session).

## Conventions (local choices)
- Weekly runs fall on the weekday of `start`, every 7 days.
- Monthly runs use the day of month of `start`, clamped to shorter months. Starting on Jan 31 gives Feb 28.
- `business_days_only` drops Saturday and Sunday. It does not roll runs forward and applies no holiday calendar.

## Known limits
- Grace minutes are not used here. A status check must apply them.
- No holiday calendar. `synthetic_calendar.py` has a 2026 holiday set, but this module does not import it.
- `run_timeliness.py` defines its own, different `ScheduleContract`. Do not mix the two.
- Only the three cadences above are supported. Intraday cadences are not.
