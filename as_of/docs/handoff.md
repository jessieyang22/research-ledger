# handoff: a digest-tied record passed between roles

## What the module does
`as_of/handoff.py` builds, renders and validates a short handoff record. The record names a title, an owner role, open items, next steps, and a digest of the run state (`StateManifest`) at hand-off time. The digest is a hash of the record body, which has no timestamps or host details, so the same inputs give the same digest. Synthetic data only; standard library plus `as_of.core` and `as_of.state_manifest`. No network, no subprocess, no order code.

## Design idea
The design treats a handoff as a written record that ties the next person's work to one exact run state, with an explicit owner for the next step.

## API
- `build_handoff(title, state, open_items, next_steps, owner_role) -> dict`
- `render_handoff(h) -> str`: plain text, every value flattened to one line.
- `validate_handoff(h) -> List[Finding]`: checks format, state digest, owner role, list types, next steps (or explicit `"none"`), and digest match.

Example (verified by running it with the repo root on `PYTHONPATH`):
```python
from as_of.state_manifest import StateManifest
from as_of.handoff import build_handoff, render_handoff, validate_handoff

m = StateManifest()
m.record_step("synthetic_load", {"raw": "a" * 64}, {"clean": "b" * 64}, "v1")
h = build_handoff(
    title="SYN Week 1 handoff",
    state=m,
    open_items=["SYN_A estimate unconfirmed"],
    next_steps=["Confirm SYN_A estimate with source owner"],
    owner_role="analyst",
)
print(render_handoff(h))
print([(f.check_id, f.status.value) for f in validate_handoff(h)])
```
Output: six `pass` findings (`handoff.format`, `handoff.state_digest`, `handoff.owner_role`, `handoff.open_items`, `handoff.next_steps`, `handoff.digest`).

## Known limits
- Validation checks shape and digest consistency only. It cannot tell whether the open items or next steps are true.
- The digest covers the record body. It does not check that `state_digest` matches a saved manifest file.
- No persistence: the module returns dicts and text, and writes nothing.
- A handoff with `next_steps=["none"]` passes. Use it only when no action is needed.
