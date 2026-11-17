# readiness_record: go or no-go record for an as-of run

## What the module does
`as_of/readiness_record.py` combines three kinds of evidence into one decision for a research run: readiness items (each with a pass flag and an evidence reference), validation findings (only FAIL blocks), and a count of open incidents (any open incident blocks). It returns a dict with `go`, a list of `blocking` reasons, and a `digest` that hashes the inputs. `render_readiness` turns that dict into plain text for a review packet. All data is synthetic (`SYN_` prefix).

## Design idea
The design treats a readiness record as the gate before a run proceeds, with the answer naming its evidence so a reviewer can replay it. This module follows that idea: an empty checklist blocks, blocking reasons are listed in fixed order, and a digest ties sign-off to the inputs.

## API
- `build_readiness(items, findings, open_incident_count)` returns `{"go", "blocking", "digest"}`. Raises `AsOfError` on bad types or a negative or bool incident count.
- `render_readiness(rec)` returns text starting with `Readiness decision: GO` or `NO-GO`. Raises `AsOfError` on a malformed record.

Example (run from repo root; verified):
```python
from as_of.core import Finding, ReadinessItem, ValidationStatus
from as_of.readiness_record import build_readiness, render_readiness

items = [
    ReadinessItem(item_id="SYN_SOURCE_REGISTER", passed=True, evidence_ref="SYN_EV_001"),
    ReadinessItem(item_id="SYN_VINTAGE_MANIFEST", passed=False, evidence_ref="SYN_EV_002"),
]
findings = [
    Finding(check_id="SYN_PRICE_CHECK", status=ValidationStatus.WARN,
            message="synthetic warning", subject="SYN_TICKER_A"),
]
rec = build_readiness(items, findings, open_incident_count=0)
print(render_readiness(rec))
```
Output:
```
Readiness decision: NO-GO
Digest: a1c9b7ecaf52bd47af40e0db67f8de9f2009a3d5688611099999ba672386bd0d
Blocking reasons:
  - item_failed: SYN_VINTAGE_MANIFEST (evidence SYN_EV_002)
```

## Known limits
- Coverage is not checked: an empty list blocks, but nothing confirms the items are the right checks.
- `evidence_ref` need only be a non-empty string; existence is not verified.
- WARN and INFO findings never block, by design.
- Incidents enter as a count, not as records.
- The digest covers the inputs, not the rendered text. `render_readiness` does not recompute it.
- No persistence or sign-off workflow.
- Tests: `as_of/tests/test_readiness_record.py` (20 passing).
