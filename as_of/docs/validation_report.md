# validation_report: build and render check results

## What the module does
`as_of/validation_report.py` turns a mapping of check names to `Finding` records into a plain dict report. It sorts checks by name, rolls up an overall status (FAIL if any finding fails, WARN if any warns, else PASS), counts findings by status, and renders the report as deterministic text. No timestamp is written; the caller passes `generated_for`. It imports only `as_of.core`. All data is synthetic (`SYN_`).

## Design idea
The design treats a validation report as a reviewable record of checks run against a dated state, with each finding traceable to a named check. The module follows that idea.

## API
- `build_report(title, results, generated_for) -> dict`: `results` maps check name to a list of `Finding`. Empty results give a passing report.
- `report_passes(report) -> bool`: fails closed. Missing or unknown statuses return False. WARN does not fail.
- `render_report_text(report) -> str`: plain text, one newline at the end. Control characters are escaped.

Example (run from the repo root; output verified with the project venv):
```python
from as_of.core import Finding, ValidationStatus
from as_of.validation_report import build_report, report_passes, render_report_text

results = {
    "price_hard_fail": [
        Finding("price_hard_fail", ValidationStatus.PASS, "all prices present", "SYN_PX_001"),
    ],
    "source_register": [
        Finding("source_register", ValidationStatus.WARN, "source older than 30 days", "SYN_SRC_002"),
    ],
}
report = build_report("Synthetic check", results, generated_for="SYN_RUN_2026-10-27")
print(report["status"], report_passes(report))   # warn True
print(render_report_text(report))
```

## Known limits
- Only `Finding` objects are accepted; `Finding.check_id` is not checked against the dict key.
- `report_passes` checks the report dict's shape and status values, not whether the findings are true.
- The report stores plain dicts and text. It does not write files, sign output or store history.
- Output is deterministic only if the caller keeps `title` and `generated_for` fixed.
- Python 3.9 syntax only. No network, no trading code, no real data.
