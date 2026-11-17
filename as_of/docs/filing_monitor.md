# filing_monitor: filing occurrence log

## What the module does
`as_of/filing_monitor.py` records that a filing happened: ticker, form type, filed and accepted timestamps, and the registered source. It answers which filings were accepted for a ticker in a window, and how many of each form were accepted. It does not score significance. Synthetic data only, no network calls, imports only `core.py` and `source_register.py`.

## Design idea
The design keeps the occurrence of a filing separate from any judgment about it, so a reviewer can replay what was known and when.

## API
- `FilingMonitor(register)`: `register` is a `SourceRegister`.
- `ingest_filing(rec) -> bool`: stores a `FilingRecord`. A repeated `filing_id` returns `False` and keeps the first copy. Raises `AsOfError` on naive timestamps or an unregistered `source_id`.
- `occurrences(ticker, start, end)`: filings with `accepted_at` in `[start, end]`, sorted by `(accepted_at, filing_id)`.
- `occurrence_summary(start, end)`: counts by `form_type`.

Example (repo root, `PYTHONPATH` set to the repo; output verified):
```python
from datetime import datetime, timezone
from as_of.core import SourceRecord, SourceType, FilingRecord
from as_of.source_register import SourceRegister
from as_of.filing_monitor import FilingMonitor

reg = SourceRegister()
reg.add_source(SourceRecord(
    source_id="SYN_FILING_SRC_01", source_type=SourceType.FILING,
    publisher="SYN_PUBLISHER", locator="synthetic://filings/2026",
    retrieved_at=datetime(2026, 10, 27, tzinfo=timezone.utc),
    sha256="a" * 64, synthetic=True))
mon = FilingMonitor(reg)
ts = datetime(2026, 10, 20, 20, 5, tzinfo=timezone.utc)
mon.ingest_filing(FilingRecord("SYN_F001", "SYNA", "10-Q", ts, ts, "SYN_FILING_SRC_01"))
start = datetime(2026, 10, 1, tzinfo=timezone.utc)
end = datetime(2026, 10, 27, tzinfo=timezone.utc)
print([r.filing_id for r in mon.occurrences("SYNA", start, end)])  # ['SYN_F001']
print(mon.occurrence_summary(start, end))                          # {'10-Q': 1}
```

## Known limits
- In-memory only; nothing persists.
- The first copy of a `filing_id` wins, so a corrected filing with the same id is ignored.
- `filed_at` is not checked against `accepted_at`.
- Form types are free text (for example "10-Q/A" is its own type).
- Ticker matching is exact string equality.
