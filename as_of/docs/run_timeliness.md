# run_timeliness: on-time, late, or missed scheduled runs

## What the module does
`as_of/run_timeliness.py` compares expected run slots (UTC datetimes) with actual finish times. Each slot gets ON_TIME, LATE, or MISSED, an advisory handling action, and findings for late or missed rows. Synthetic data only; standard library and `as_of.core`. No network, no order logic.

## Design idea
The design treats a scheduled job as a promise with a time window. A run counts only inside that window, and one run cannot satisfy two promises. Late and missed runs get different responses, so a gap cannot pass silently. Topic: "missed and late run handling".

## Matching rule
- Slots are processed in ascending order. Each claims one unclaimed run that is not before the previous slot and before the next slot, choosing the closest.
- Grace is inclusive: a run at slot + grace is ON_TIME.
- Actions: ON_TIME gives `none`, LATE gives `rerun_and_log`, MISSED gives `escalate_incident`.

## API
- `ScheduleContract(name, grace_minutes)`: frozen dataclass.
- `classify_runs(contract, expected, actual)`: rows with `slot`, `status`, `actual_at` (None when MISSED).
- `late_or_missed_findings(rows)`: LATE gives WARN `run_late`; MISSED gives FAIL `run_missed`.
- `handling_action(status)`: returns the action string.

Example (run from the repo root; output verified):
```python
from datetime import datetime, timezone
from as_of.run_timeliness import ScheduleContract, classify_runs, late_or_missed_findings

def t(h, m=0):
    return datetime(2026, 1, 1, h, m, tzinfo=timezone.utc)

rows = classify_runs(ScheduleContract("synthetic_close", 15),
                     [t(9), t(10), t(11)], [t(9, 10), t(10, 20), t(11, 5)])
for r in rows:
    print(r["slot"].isoformat(), r["status"].name)
print([f.check_id for f in late_or_missed_findings(rows)])
```
Output: `09:00 ON_TIME`, `10:00 LATE`, `11:00 ON_TIME`, then `['run_late']`.

## Known limits
- Extra runs with no slot are ignored (no row, no finding).
- Greedy closest-first matching is not globally optimal; results depend on slot order.
- No retries, durations, or calendar logic (weekends, holidays); the caller supplies slots.
- Python 3.9 only. Tests: `tests/test_run_timeliness.py`, `tests/test_run_timeliness_attack.py`.
