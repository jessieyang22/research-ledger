# PM packet deltas

## What the module does

`as_of/pm_packet_deltas.py` compares the current PM review packet with the prior one. It reports added, removed and changed sections, changed fields inside dict sections, and new or resolved findings. It is pure: it reads two dicts and returns a dict, with no file, network or clock access. It imports only `as_of.core`. All data is synthetic (SYN_ prefix).

## Design idea

The design treats the PM packet as something a portfolio manager reads before deciding, so the PM needs to see what moved since the last packet, not only the current state. The module implements that comparison.

## API

- `diff_packets(prev, curr) -> dict` with keys `DELTA_KEYS`: `added_sections`, `removed_sections`, `changed_sections`, `changed_fields`, `findings_new`, `findings_resolved`.
- `render_delta_lines(delta) -> List[str]`: plain-text lines; an empty delta renders as "No changes since prior packet."

Sections come from `packet["sections"]` if present, otherwise from every top-level key except `findings`. Findings are matched by `(check_id, subject)`, or by a stable hash when those fields are absent. A finding whose message changed is paired, so it is neither new nor resolved.

Runnable example (verified from the repo root):

```python
from as_of.core import Finding, ValidationStatus
from as_of.pm_packet_deltas import diff_packets, render_delta_lines

prev = {"sections": {"thesis": {"view": "SYN_a"}, "old_sec": {"x": 1}},
        "findings": [Finding(check_id="SYN_CHK_01", status=ValidationStatus.WARN,
                             message="SYN_stale", subject="SYN_CL_01")]}
curr = {"sections": {"thesis": {"view": "SYN_b"}, "new_sec": {"y": 2}},
        "findings": [Finding(check_id="SYN_CHK_02", status=ValidationStatus.FAIL,
                             message="SYN_gap", subject="SYN_CL_02")]}
print("\n".join(render_delta_lines(diff_packets(prev, curr))))
```

Output: added `new_sec`, removed `old_sec`, changed `thesis: view`, new finding `SYN_CHK_02 / SYN_CL_02: SYN_gap`. The resolved `SYN_CL_01` warning is listed under "Resolved findings".

## Known limits

- Only top-level section values are compared; nested changes show up as changed fields of that section.
- Findings must pass `canonical_json`, so NaN values raise `AsOfError`.
- It reports differences; it does not judge whether a change is correct.
