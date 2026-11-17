# PM packet renderer

## What the module does

`as_of/pm_packet_render.py` turns a packet dict from `assemble_packet` into Markdown, and turns a packet delta into Markdown. It only formats. It does not check content, change values, or write files. Output is deterministic, and every table cell is escaped so a pipe or line break cannot break the layout. All data is synthetic (SYN_ prefix).

## Design idea

The design treats the PM review packet as one bundle a portfolio manager reads before a decision, with claims tied back to sources and the packet comparable with the last approved one. The renderer only presents that bundle in a fixed reading order and ties the text to the packet hash. Treat this section as the module's reading, not a verified quote.

## API

- `render_markdown(packet) -> str`: needs keys `title`, `as_of`, `sections`, `open_findings`, `packet_hash`. Sections print in `PACKET_SECTION_ORDER`, then open findings. A missing section or key raises `AsOfError`.
- `render_delta_markdown(delta) -> str`: scalar fields go in a Field/Value table; a `changes` list of mappings gets its own table.
- `escape_cell(text) -> str`: escapes backslashes and pipes and flattens line breaks.

Runnable example (run from the repo root, output checked):

```python
from datetime import date
from as_of.core import Finding, ValidationStatus
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER, assemble_packet
from as_of.pm_packet_render import render_markdown

sections = {name: {"label": "SYN_%s" % name} for name in PACKET_SECTION_ORDER}
findings = [Finding(check_id="SYN_CHK_02", status=ValidationStatus.WARN,
                    message="SYN_stale|x", subject="SYN_CL_02")]
packet = assemble_packet("SYN packet", date(2026, 10, 27), sections, [], findings)
print(render_markdown(packet)[:120])
```

## Known limits

- Formatting only: section content is not checked for accuracy.
- Sections must be mappings; a non-mapping body raises `AsOfError` rather than showing "No entries".
- Non-finite floats are refused.
- Delta rendering expects `changes` to be a list of mappings for a table; other shapes fall back to canonical JSON.
- The renderer writes no files; saving the text is the caller's job.
- Tests: `as_of/tests/test_pm_packet_render.py` and `test_pm_packet_render_attack.py` (38 passing).
