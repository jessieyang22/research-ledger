# incident_records: timeline, severity, root cause

## What the module does
`as_of/incident_records.py` tracks one operational problem from open to close. A record holds a severity, a time-sorted timeline of UTC events, and a root cause once closed. Each call returns a new frozen `IncidentRecord`. Synthetic data only.

## Design idea
The incident procedure treats some failures as control incidents: unexpected changes to protected inputs, failed validators summarized as passes, and automated artifacts approved without a named human. The response is to stop, preserve evidence, find the smallest affected boundary, notify the owner, repair the control, and document the outcome. The module covers only the record-keeping part. The response steps are not coded.

## API
- `open_incident(incident_id, summary, severity, opened_on)`: open record. `severity` is a `Severity` member.
- `add_timeline_event(rec, at, text)`: adds an event, sorted by UTC time. Naive datetimes raise `AsOfError`.
- `close_incident(rec, closed_on, root_cause)`: needs a root cause and at least one event. `closed_on` is checked, not stored.
- `validate_incident(rec)`: four findings (`incident.timeline_present`, `timeline_sorted`, `root_cause`, `status`).

Verified example (repo root on `sys.path`):
```python
from datetime import date, datetime, timezone
from as_of.incident_records import open_incident, add_timeline_event, close_incident, validate_incident
from as_of.core import Severity

rec = open_incident("SYN_INC_001", "SYN feed delivered late", Severity.WARN, date(2026, 10, 1))
rec = add_timeline_event(rec, datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc), "SYN file after cutoff")
rec = add_timeline_event(rec, datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc), "SYN late run seen")
rec = close_incident(rec, date(2026, 10, 2), "SYN vendor schedule changed")
print(rec.status, rec.root_cause)
for f in validate_incident(rec):
    print(f.status.value, f.check_id)
```
Output: `closed SYN vendor schedule changed`, then four `pass` lines.

## Tests
`as_of/tests/test_incident_records.py` and `test_incident_records_attack.py`: 57 pass.

## Known limits
- `closed_on` is not stored.
- Events dated before `opened_on` are not flagged.
- No owner, approver, or notification is recorded.
- In memory only; nothing is persisted.
- Stopping runs and rerunning tests happen outside this module.
