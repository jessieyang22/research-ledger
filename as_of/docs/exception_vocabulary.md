# exception_vocabulary: one closed list of exception kinds

## What the module does
`as_of/exception_vocabulary.py` defines the closed set of exception kinds the as_of exception queue accepts (`ExceptionKind`, nine kinds). For each kind it holds a one-line meaning and a default severity (`BLOCK`, `WARN` or `INFO`). It also maps validation `Finding`s to a severity. Other modules should use these names and not invent their own. All data is synthetic.

## Design idea
The exception vocabulary topic is the source of the idea: exceptions need a fixed set of names, each with a plain meaning and a default severity, so every reviewer reads a label the same way. The kinds and severities here are an original taxonomy written for this repo.

## API
- `ExceptionKind`: enum of the nine kinds, for example `TIEOUT_BREAK`, `LOOKAHEAD_RISK`, `FILING_OCCURRED`.
- `describe(kind)`: the one-line definition. Raises `AsOfError` for a non-kind.
- `default_severity(kind)`: the default `Severity`. Raises `AsOfError` for a non-kind.
- `parse_kind(text)`: maps text to a kind, ignoring case and outer spaces. Raises `AsOfError` on unknown, empty, non-string or non-ASCII input.
- `finding_severity(finding)`: FAIL maps to BLOCK, WARN to WARN, PASS to INFO.

Example (run and verified with the repo on `PYTHONPATH`):
```python
from as_of.core import Finding, ValidationStatus
from as_of.exception_vocabulary import ExceptionKind, parse_kind, default_severity, finding_severity

k = parse_kind(" tieout_break ")
print(k.value, default_severity(k).name)
print(default_severity(ExceptionKind.FILING_OCCURRED).name)
f = Finding(check_id="SYN_CHECK_1", status=ValidationStatus.WARN, message="synthetic", subject="SYN_SUBJECT")
print(finding_severity(f).name)
```
Expected output:
```
TIEOUT_BREAK BLOCK
INFO
WARN
```

## Known limits
- The list is fixed in code. Adding a kind means editing the enum, the description table and the severity table together.
- Severities are defaults only. Nothing here overrides them per run.
- Descriptions are English strings and are not checked against the queue.
- `parse_kind` accepts exact names only (after case and space folding), not aliases.
