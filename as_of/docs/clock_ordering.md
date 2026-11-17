# clock_ordering: ordering checks for the five clocks

## What the module does
`as_of/clock_ordering.py` takes a `ClockSet` (event, release, ingest, knowledge, report) and checks four ordering rules. It returns a list of `Finding` objects. An empty list means every rule held. It does not change the clocks and does not decide visibility (that is `as_of/clock_as_of.py`).

## Design idea
The as-of discipline keeps separate clocks for when something happened, when it was published, when the pipeline took it in, when the team knew it, and when a report was written. Keeping them apart lets a past decision be replayed without information that arrived later.

- event <= release (`clock.event_after_release`)
- release <= ingest (`clock.ingest_before_release`)
- release <= knowledge (`clock.knowledge_before_release`)
- knowledge <= report (`clock.report_before_knowledge`)

## API
- `check_clock_order(cs) -> List[Finding]`: checks every rule. Raises `AsOfError` if `cs` is not a `ClockSet`.
- `ORDER_RULES`: tuple of `(check_id, earlier, later)`.
- Status: FAIL when both clocks are set and out of order; WARN when either clock is None (rule not checked); PASS produces no finding.

Example (run and verified):
```python
from datetime import datetime, timezone
from as_of.clocks_record import make_clockset, with_clock
from as_of.clock_ordering import check_clock_order
from as_of.core import ClockName

u = timezone.utc
cs = make_clockset(
    event_at=datetime(2026, 10, 1, 9, tzinfo=u),
    release_at=datetime(2026, 10, 1, 12, tzinfo=u),
    ingest_at=datetime(2026, 10, 1, 13, tzinfo=u),
    knowledge_at=datetime(2026, 10, 1, 14, tzinfo=u),
    report_at=datetime(2026, 10, 1, 15, tzinfo=u),
)
print(check_clock_order(cs))  # []
bad = with_clock(cs, ClockName.KNOWLEDGE, datetime(2026, 10, 1, 11, tzinfo=u))
for f in check_clock_order(bad):
    print(f.status.value, f.check_id, f.message)
# fail clock.knowledge_before_release release clock is after knowledge clock
```
Run with the repo root on `PYTHONPATH`.

## Known limits
- Only pairwise ordering is checked; it does not check clocks against other records.
- A None clock is treated as unknown and yields WARN, not FAIL.
- Synthetic data only; no network or trading code.
