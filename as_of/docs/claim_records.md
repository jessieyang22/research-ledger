# claim_records: claim kinds, statuses and source checks

## What the module does
`as_of/claim_records.py` builds `ClaimRecord` objects (one statement an output makes, with a kind, a status and source ids) and checks each one. `validate_claim` returns `Finding` objects. A clean claim gets one PASS finding. `status_counts` tallies claims by status so the counts sum to the number of claims.

## Design idea
The design treats each claim in a research output as something to trace back to its support, and separates facts, estimates, opinions and expert input. Expert-call input is kept out of the verified state until someone checks it. The module applies these ideas as three rules.

## API
- `make_claim(claim_id, text, claim_kind, source_ids, status="unverified", section="") -> ClaimRecord`. Stores values as given; does not reject bad kinds or statuses. A bare string becomes one source id.
- `validate_claim(rec) -> List[Finding]`
- `status_counts(claims) -> Dict[str, int]`
- Vocabularies: `CLAIM_KINDS` = fact, estimate, opinion, expert_input; `CLAIM_STATUSES` = unverified, verified, rejected.
- Check ids: `CLM_UNKNOWN_KIND`, `CLM_UNKNOWN_STATUS`, `CLM_FACT_NO_SOURCE`, `CLM_EXPERT_VERIFIED`, `CLM_OK`.

Example (verified by running, with the repo on `PYTHONPATH`):
```python
from as_of.claim_records import make_claim, validate_claim, status_counts

claims = [
    make_claim("SYN_C1", "SYN_TKR revenue rose 5 percent", "fact", ["SYN_S1"], status="verified"),
    make_claim("SYN_C2", "SYN_TKR margin will hold", "estimate", ["SYN_S2"]),
    make_claim("SYN_C3", "SYN_TKR order backlog grew", "fact", []),
    make_claim("SYN_C4", "SYN_EXPERT said channel checks were soft", "expert_input", ["SYN_S3"], status="verified"),
]
for rec in claims:
    for f in validate_claim(rec):
        print(f.status.value.upper(), f.check_id, f.subject, "|", f.message)
print(status_counts(claims))
```
Output:
```
PASS CLM_OK SYN_C1 | claim passes all checks
PASS CLM_OK SYN_C2 | claim passes all checks
FAIL CLM_FACT_NO_SOURCE SYN_C3 | fact claim has no source_ids
FAIL CLM_EXPERT_VERIFIED SYN_C4 | expert_input cannot have status 'verified'
{'unverified': 2, 'verified': 2, 'rejected': 0}
```

## Known limits
- A fact needs at least one non-blank source id. The module does not check that the source exists or supports the claim; `catalyst_claim_links` and the source register do that.
- Rule 2 blocks only `expert_input` marked verified. It does not check how a claim becomes verified.
- Opinions and estimates are not checked for sources.
- No as-of date is stored or checked on claims.
- Synthetic data only; no network calls, no trading code.
