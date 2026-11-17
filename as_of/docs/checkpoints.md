# checkpoints: resumable pipeline steps

## What the module does
`as_of/checkpoints.py` saves one JSON checkpoint per pipeline step. Each file holds the step name, input hash, `StateManifest` digest and a dict payload under one digest. A step is skipped on resume only when a verified checkpoint has the same input hash. Synthetic data only; no network or subprocess.

## Design idea
The resume idea: reuse a finished step only when its inputs are unchanged, and tie saved state to the run's state record.

## API
- `write_checkpoint(dir_path, step, payload, manifest, input_hash) -> str`: writes atomically and returns the file path.
- `read_checkpoint(dir_path, step) -> dict`: returns the payload, or raises `AsOfError` on a missing, invalid or altered file.
- `should_skip(dir_path, step, input_hash) -> bool`: True only for a verified checkpoint with a matching input hash.
- `latest_step(dir_path, ordered_steps) -> Optional[str]`: last step with a file present (existence only).

Example (verified by running it with the repo root on `PYTHONPATH`):
```python
import tempfile
from as_of.state_manifest import StateManifest
from as_of.checkpoints import write_checkpoint, read_checkpoint, should_skip, latest_step

m = StateManifest()
m.record_step("SYN_ingest", {"SYN_in.csv": "a" * 64}, {"SYN_out.csv": "b" * 64}, "v1")
d = tempfile.mkdtemp()
write_checkpoint(d, "SYN_ingest", {"rows": 3, "label": "synthetic"}, m, "SYN_hash_1")
print(read_checkpoint(d, "SYN_ingest"))              # {'label': 'synthetic', 'rows': 3}
print(should_skip(d, "SYN_ingest", "SYN_hash_1"))    # True
print(should_skip(d, "SYN_ingest", "SYN_hash_2"))    # False
print(latest_step(d, ["SYN_ingest", "SYN_build"]))   # SYN_ingest
```

## Known limits
- Payloads must be dicts of JSON-native values. Tuples come back as lists.
- The caller computes `input_hash`. The module does not hash inputs itself, so a wrong hash means a stale step is reused.
- `latest_step` checks file presence only. Use `read_checkpoint` or `should_skip` to verify content.
- Atomic replace guards against partial writes, not two concurrent runs of one step.
- Tests: 46 passed (`test_checkpoints*.py`).
