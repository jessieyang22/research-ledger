# Catalyst exception queue workflow (`as_of/wf_catalyst_exception_queue.py`)

## What it does
`run_catalyst_proof()` runs the catalyst checks end to end on the synthetic catalyst fixture. It registers the sources, validates claim-to-catalyst links, ingests the filings, and opens every result in a fresh `ExceptionQueue`. It then compares the open (kind, subject) pairs with the fixture's expected list. It uses synthetic data only, makes no network calls and does no I/O.

## Design idea
The workflow follows the catalyst exception queue idea: plant known faults in a fixture, check that the checks find them, and route each finding into a queue with a severity so that it is handled rather than dropped.

## API
`run_catalyst_proof(seed=SYNTHETIC_SEED, inject_unlinked=False) -> ProofResult`
- `passed` is True only when the queue matches the expected list and no FILING_OCCURRED item is above INFO.
- `findings` holds one Finding per open item. BLOCK maps to FAIL, WARN to WARN and INFO to PASS.
- `metrics` holds `queue_size`, `expected_count`, `matched`, `filing_occurred_count` and `filing_occurred_non_info`, all floats.
- `inject_unlinked=True` adds one unlinked claim without changing the expected list, so the run fails.

## Example (run and verified)
```python
from as_of.wf_catalyst_exception_queue import run_catalyst_proof

r = run_catalyst_proof()
print(r.passed, r.metrics["matched"])          # True 1.0
for f in r.findings:
    print(f.check_id, f.subject)
bad = run_catalyst_proof(inject_unlinked=True)
print(bad.passed, bad.metrics["queue_size"])   # False 5.0
```
Verified: this code was run with the repo venv. Output: `True 1.0`, then `CLAIM_UNLINKED SYN_CLM_03`, `CHECK_FAILED SYN_CLM_02`, `FILING_OCCURRED SYN_FIL_01`, `FILING_OCCURRED SYN_FIL_02`, then `False 5.0`. Repeated calls return equal metrics.

## Known limits
- The dangling link (SYN_CLM_02) has no dedicated kind, so it is reported as CHECK_FAILED.
- The expected list is written by hand in the fixture. A match shows agreement with that list, not that the checks are complete.
- Queue timestamps are fixed (2026-10-27 for claims). The current clock is never read.
- Nothing is saved between runs. Severity comes only from the vocabulary.
