# Exception queue (`as_of/exception_queue.py`)

## What it does
`ExceptionQueue` is an in-memory list of flagged problems, each tied to a subject (a catalyst, a source, a price, a filing). Each record has a kind, a severity, an open time and an optional resolve time. It makes no I/O and no network calls and uses synthetic data only.

## Design idea
The catalyst exception queue idea is that problems found during research should be written down as items with an owner-visible severity and age, and that they should be closed explicitly rather than silently dropped.

## API
- `ExceptionQueue().open(kind, subject_id, opened_at, note="", severity=None)`: idempotent on (kind, subject_id, opened_at). A `str` kind defaults to INFO; an `ExceptionKind` takes its vocabulary default (`exception_vocabulary.py`).
- `resolve(exception_id, resolved_at, note)`: closes a record once. A second resolve, an unknown id, or a `resolved_at` before `opened_at` raises `AsOfError`.
- `open_items()`: unresolved records, insertion order.
- `prioritized()`: open records, BLOCK then WARN then INFO, oldest first within a severity.
- `counts()`: `{"open", "resolved", "total"}`.

## Example (run and verified)
```python
from as_of.exception_queue import ExceptionQueue
from as_of.exception_vocabulary import ExceptionKind
from as_of.core import parse_ts

q = ExceptionQueue()
r = q.open(ExceptionKind.MISSING_PRICE, "SYN_T01", parse_ts("2026-10-27T00:00:00Z"),
           note="no close on 2026-10-26")
q.open(ExceptionKind.FILING_OCCURRED, "SYN_T02", parse_ts("2026-10-26T12:00:00Z"))
print(q.counts())                      # {'open': 2, 'resolved': 0, 'total': 2}
print([x.kind for x in q.prioritized()])  # ['MISSING_PRICE', 'FILING_OCCURRED']
q.resolve(r.exception_id, parse_ts("2026-10-27T01:00:00Z"), "price backfilled")
print(q.counts())                      # {'open': 1, 'resolved': 1, 'total': 2}
```
Verified: this exact code was run with the repo venv and gave the outputs shown.

## Known limits
- State lives only in memory; nothing is saved between runs.
- `ExceptionKind` values are fixed by the vocabulary; a `str` kind is accepted but always INFO unless a severity is passed.
- Records are not deduplicated across different `opened_at` times for the same subject.
- The queue does not decide whether an item is material; a person resolves it.
