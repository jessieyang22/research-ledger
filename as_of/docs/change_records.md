# change_records: a fixed status flow for research-process changes

## What the module does
`as_of/change_records.py` tracks one change to the research process, model, or data pipeline from proposal to verification. Records are frozen `ChangeRecord` objects, and each move returns a new record. Synthetic data only; no network, no trading code.

## Design idea
The method below is the module's own design: proposal, approval, application, and verification, with evidence required before a change counts as applied or verified.

## API
- `open_change(change_id, summary, reason, opened_on)`: new record in `proposed`, no evidence. `opened_on` must be a `date`, not a `datetime`.
- `transition(rec, new_status, on, evidence_ref=None)`: returns a new record. Illegal moves, unknown statuses, and dates before `opened_on` raise `AsOfError`. A `None` evidence_ref keeps the stored one.
- `validate_change(rec)`: returns `change.status` and `change.evidence` findings. Applied or verified without a non-blank string evidence_ref gives FAIL.
- `LEGAL_MOVES`, `ALL_STATUSES`, `EVIDENCE_REQUIRED`: the flow tables.

Verified example (run with the repo root on `sys.path`):
```python
from datetime import date
from as_of.change_records import open_change, transition, validate_change

rec = open_change("SYN_CHG_001", "SYN add factor check", "SYN missing check", date(2026, 10, 1))
rec = transition(rec, "approved", date(2026, 10, 2))
rec = transition(rec, "applied", date(2026, 10, 3), evidence_ref="SYN_EV_001")
rec = transition(rec, "verified", date(2026, 10, 4))
print(rec.status, rec.evidence_ref)   # verified SYN_EV_001
for f in validate_change(rec):
    print(f.status.value, f.check_id) # pass change.status / pass change.evidence
```

## Tests
`as_of/tests/test_change_records_attack.py` and related tests: all 59 pass on the current code.

## Known limits
- In-memory only. Nothing is persisted.
- `transition()` does not check evidence type. Only `validate_change()` does, so a list or NaN can be stored through `transition()`.
- `validate_change()` checks that evidence is present, not that it exists or supports the change.
- No approver identity is recorded.
- A rejected or verified change cannot be reopened.
