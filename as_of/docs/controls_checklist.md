# controls_checklist: a catalog of controls and the evidence each one needs

## What the module does
`as_of/controls_checklist.py` holds a fixed catalog of 14 research-process controls. Each control is an immutable `ControlSpec` with an id, a plain-language description, the kind of evidence that proves it, and an owner role. `missing_evidence()` flags every control that has no evidence reference, and `checklist_markdown()` writes the catalog as a Markdown checklist. The module never reads secrets, never runs commands, and never edits Claude or IDE settings. Permission concerns appear only as repo checklist items.

## Design idea
The research-state discipline treats a research output as something a reviewer must be able to check against evidence. This module turns that idea into a checklist: each named control has evidence a person records, and a missing record is a visible gap.

## API
- `ControlSpec(control_id, description, evidence_kind, owner_role)`: validates inputs; `evidence_kind` must be in `EVIDENCE_KINDS`, `owner_role` in `OWNER_ROLES`.
- `CONTROL_CATALOG`: tuple of 14 unique `ControlSpec` objects.
- `missing_evidence(evidence)`: takes `{control_id: reference}` and returns one FAIL `Finding` per control whose key is absent, empty, or whitespace. Unknown keys are ignored.
- `checklist_markdown()`: one unchecked box per control.

Verified example (run from the repo root with `.venv/bin/python`):
```python
from as_of import controls_checklist as cc

evidence = {s.control_id: "synthetic-ref-1" for s in cc.CONTROL_CATALOG}
del evidence[cc.CONTROL_CATALOG[0].control_id]
for f in cc.missing_evidence(evidence):
    print(f.status.value, f.subject)
# fail ctl_source_register_current
```
The module's 21 tests pass (`pytest as_of/tests/test_controls_checklist.py`).

## Known limits
- The module checks only that a reference string exists. It does not open the file, confirm the evidence is real, or confirm it is current.
- The catalog is fixed in code. Adding or changing a control means editing the module.
- Nothing is written to disk; `checklist_markdown()` returns a string.
- Synthetic data only. No network calls, no trading or order code.
