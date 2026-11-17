# claim_sampling: stratified, reproducible claim review

## What the module does
`as_of/claim_sampling.py` picks which claims a human reviewer checks by hand. The same population, seed and n always give the same claims. Claims are spread across strata (by default one stratum per `claim_kind`) so a rare kind is not missed. `sampling_log` returns a JSON-ready record of how the sample was drawn. The module does no I/O and imports only `as_of.core`.

## Design idea
The design treats review sampling as something an auditor must be able to repeat, so the draw has to be reproducible and cover each category of claim. The module follows that idea: fixed seed, sorted input, and at least one check per stratum when the sample size allows. The exact procedure is not reproduced here.

## API
- `sample_claims(claims, n, seed=SYNTHETIC_SEED, stratify_by="claim_kind") -> List[ClaimRecord]`. Returns n claims sorted by `claim_id`. Input order does not matter.
- `sampling_log(sample, seed, population_size) -> dict`. Holds seed, sizes, fraction, sorted ids, `sample_hash` (SHA-256 of the ids) and counts by `claim_kind`.
- Raises `AsOfError` for negative or non-int n, n above the population, duplicate `claim_id`, or a `stratify_by` that is not a `ClaimRecord` field.

Example (run with the repo on `PYTHONPATH`; output shown is from that run):
```python
from as_of.core import ClaimRecord
from as_of.claim_sampling import sample_claims, sampling_log

kinds = ["fact"] * 2 + ["estimate"] * 4 + ["opinion"] * 6
claims = [
    ClaimRecord(claim_id="SYN_CLM%02d" % i, text="synthetic claim %d" % i,
                claim_kind=k, source_ids=("SYN_SRC01",),
                status="unverified", section="summary")
    for i, k in enumerate(kinds)
]
sample = sample_claims(claims, 5, seed=7)
log = sampling_log(sample, seed=7, population_size=len(claims))
print([c.claim_id for c in sample])
print(log["claim_kind_counts"], log["sample_size"], log["sample_fraction"])
```
Output:
```
['SYN_CLM01', 'SYN_CLM02', 'SYN_CLM04', 'SYN_CLM06', 'SYN_CLM10']
{'estimate': 2, 'fact': 1, 'opinion': 2} 5 0.416667
```

The module's test files (`as_of/tests/test_claim_sampling.py` and `test_claim_sampling_attack.py`) pass: 33 tests.

## Known limits
- When n is smaller than the number of strata, the module picks n strata at random, so some kinds get no review that round.
- Allocation is proportional with largest-remainder rounding; it is not a tested statistical design.
- Strata are keyed on `type:repr`, so a NaN `claim_kind` forms one stratum.
- `sampling_log` does not record `stratify_by`, and its kind counts are always by `claim_kind`.
- Claim text is not read, so the sample cannot check whether a claim is true or dated correctly.
- Synthetic data only; no network calls, no trading code.
