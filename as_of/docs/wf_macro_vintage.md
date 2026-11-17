# wf_macro_vintage: as-of macro value selection

## What it does
`as_of/wf_macro_vintage.py` builds a synthetic macro series (six monthly observations, ids prefixed `SYN_`). First releases land 30 days after each observation date. Every second observation gets a revision 60 days after its first release. All releases go into a `VintageManifest`. For each decision time (noon UTC on each release day), the module picks the value known then, checks that no used value was released later, and writes a manifest hash and state digest. Output is a `ProofResult`. Nothing is read from disk or the network.

## Design idea
- A revised number is usable only after its own release time has passed.
- Keep the full vintage set so you can answer "what was known on this date," not only "what is the latest value."
- Planted fault: picking the newest vintage while ignoring release time must fail the cutoff check. The tests confirm this.

## API
```
run_macro_proof(seed: int = SYNTHETIC_SEED, inject_lookahead: bool = False) -> ProofResult
```
- `seed` must be a non-negative `int`. Bools, floats and negatives raise `AsOfError`.
- `ProofResult`: `proof_name`, `passed`, `findings` (check_id, status, message, subject), `metrics`.
- Metrics: `vintage_count`, `observation_count`, `decision_count`, `violation_count`, `revised_observation_count`, `inject_lookahead`.

Example (run from the repo root or set `PYTHONPATH` to it):
```python
from as_of.wf_macro_vintage import run_macro_proof

ok = run_macro_proof()
print(ok.passed, ok.metrics["violation_count"])    # True 0.0

bad = run_macro_proof(inject_lookahead=True)
print(bad.passed, bad.metrics["violation_count"])  # False 3.0
```
Both lines were run and produced this output. `tests/test_wf_macro_vintage.py`: 14 passed.

## Known limits
- Synthetic data only. No real agency revisions, calendars or latency.
- Release times are day offsets at midnight UTC. Decisions are at noon UTC. No intraday timing.
- One series, one source, at most one revision per observation.
- The cutoff check trusts manifest release timestamps. It does not verify them against a source.
