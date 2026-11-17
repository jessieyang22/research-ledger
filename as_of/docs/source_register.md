# source_register: an id, locator and hash for every input

## What the module does
`as_of/source_register.py` keeps an in-memory registry of sources. Each entry is a frozen `SourceRecord` (id, type, publisher, locator, retrieval time, SHA-256, synthetic flag). Outputs list the source ids they used, and `check_sources_used` reports any id that is not registered as a FAIL finding. It makes no network calls and uses synthetic data only.

## Design idea
The research-state discipline asks that every input to an output be logged with where it came from and a content hash, so an output cannot rest on a source nobody recorded. This module implements that idea.

## API
- `SourceRegister()`: empty registry.
- `add_source(rec)`: registers a `SourceRecord`. Validates fields; a repeated `source_id` raises `AsOfError`, so a logged locator or hash cannot be overwritten silently.
- `get_source(source_id)` / `has_source(source_id)`: lookup; unknown ids raise or return False.
- `to_manifest()`: all sources as plain dicts, sorted by id.
- `check_sources_used(ids)`: one `SRC_UNREGISTERED` FAIL per distinct unregistered id.

Verified example (run with the repo root on `PYTHONPATH`):
```python
from datetime import datetime, timezone
from as_of.core import SourceRecord, SourceType, sha256_text
from as_of.source_register import SourceRegister

reg = SourceRegister()
reg.add_source(SourceRecord(
    source_id="SYN_PRICE_001", source_type=SourceType.PRICE,
    publisher="SYNTHETIC", locator="fixtures/syn_prices.csv",
    retrieved_at=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
    sha256=sha256_text("syn price file v1"), synthetic=True,
))
print(reg.has_source("SYN_PRICE_001"))  # True
for f in reg.check_sources_used(["SYN_PRICE_001", "SYN_EST_009", "SYN_EST_009"]):
    print(f.status.value, f.check_id, f.message)
# fail SRC_UNREGISTERED source 'SYN_EST_009' is used but not registered
```

## Known limits
- Storage is in memory only; nothing is written to disk.
- `sha256` is only checked for format (64 lowercase hex). The module does not re-hash the file at `locator`.
- Only ids are checked; it does not verify that an output's numbers came from the source.
- Synthetic data only. No network, no trading or order code.
