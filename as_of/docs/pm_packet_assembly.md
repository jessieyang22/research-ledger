# PM review packet assembly

## What the module does

`as_of/pm_packet_assembly.py` builds one fixed-order PM review packet from named sections, sources and check findings. It keeps only WARN and FAIL findings as open items and computes a SHA-256 `packet_hash`. It does not judge section content. It uses only the standard library and `as_of.core`. All data is synthetic (SYN_ prefix).

## Design idea

The design treats the PM review packet as one bundle a portfolio manager reads before a decision. Claims should trace to sources, expert-input claims stay off slides, and the packet should be comparable with the last approved one. The module covers only assembly and hashing.

## API

- `PACKET_SECTION_ORDER`: the seven required section names, in output order.
- `assemble_packet(title, as_of, sections, sources, findings) -> dict`: returns `title`, `as_of` (ISO date), `sections`, `open_findings` and `packet_hash`.

Missing or unknown sections, a datetime `as_of`, or non-list inputs raise `AsOfError`.

Runnable example (verified from the repo root):

```python
from datetime import date, datetime, timezone
from as_of.core import Finding, SourceRecord, SourceType, ValidationStatus
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER, assemble_packet

sections = {name: {"label": "SYN_%s" % name} for name in PACKET_SECTION_ORDER}
source = SourceRecord(
    source_id="SYN_SRC_01", source_type=SourceType.FILING,
    publisher="SYN_filing_desk", locator="synthetic://SYN_filing/01",
    retrieved_at=datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc),
    sha256="0" * 64, synthetic=True,
)
findings = [
    Finding(check_id="SYN_CHK_01", status=ValidationStatus.PASS, message="ok", subject="SYN_CL_01"),
    Finding(check_id="SYN_CHK_02", status=ValidationStatus.WARN, message="SYN_stale", subject="SYN_CL_02"),
]
packet = assemble_packet("SYN packet", date(2026, 10, 27), sections, [source], findings)
print(packet["packet_hash"])          # 64-character hex digest
print(len(packet["open_findings"]))   # 1 (the PASS finding is dropped)
```

## Known limits

- Assembly only: section content is not checked for accuracy.
- Sections must be mappings; one-shot iterators are refused.
- Rendering and deltas live in `pm_packet_render.py` and `pm_packet_deltas.py`.
