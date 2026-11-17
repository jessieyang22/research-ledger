# State manifest (as_of/state_manifest.py)

## What it does
`StateManifest` records the steps of one pipeline run in order. Each step holds a name, input hashes, output hashes and a code-version string. The whole manifest reduces to one SHA-256 digest. `save()` writes the body and digest to JSON. `verify()` recomputes the digest from the file and fails if either part was edited. Synthetic data only; standard library plus `as_of.core`.

## Design idea
The state-manifest and vintage-manifest topics ask that a run record what went in and what came out, pinned by content hash, so a later reviewer can tell whether the run changed.

## API
- `StateManifest()`; `record_step(step_name, inputs, outputs, code_version)`
- `steps()`, `to_dict()`, `digest()`
- `save(path) -> digest`; `StateManifest.load(path)`; `StateManifest.verify(path) -> bool`

Example (verified by running it, exit 0):
```python
import os, tempfile
from as_of.state_manifest import StateManifest

m = StateManifest()
m.record_step("load_prices", {"SYN_prices.csv": "a" * 64}, {"SYN_clean.csv": "b" * 64}, "SYN_v1")
path = os.path.join(tempfile.mkdtemp(), "run_manifest.json")
digest = m.save(path)
print(StateManifest.verify(path))              # True
print(StateManifest.load(path).digest() == digest)  # True
```

Tests: `as_of/tests/test_state_manifest.py` and `test_state_manifest_attack.py`, 30 passed.

## Known limits
- Hashes are taken as given. The module never reads or hashes the input or output files, so it cannot detect a stale hash.
- `code_version` is a label string, not a check of the code.
- No signature. Anyone who edits the body can recompute the digest and save again; `verify()` only catches edits made without that recomputation.
- Step order is part of the digest; reordering steps changes it.
- No timestamps or host data by design, so the digest is machine-independent.
- `load()` requires exact key sets and version 1; `verify()` returns False instead of raising on bad files.
