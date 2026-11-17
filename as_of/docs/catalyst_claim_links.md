# catalyst_claim_links: claims tied to catalysts and sources

## What the module does
`as_of/catalyst_claim_links.py` checks that each research claim points at the catalyst that justifies it and that every source the claim cites is registered. It returns `Finding` objects, all FAIL; an empty list means the checks passed.

## Design idea
The catalyst-claim idea is that a claim in a research output should trace back to a named catalyst and to logged sources, so a reviewer can see what each statement rests on.

## API
- `validate_links(claims, links, catalyst_ids, register) -> List[Finding]`
  - `claims`: sequence of `ClaimRecord`.
  - `links`: mapping of `claim_id` to `catalyst_id`.
  - `catalyst_ids`: set of known catalyst ids.
  - `register`: a `SourceRegister` used for `source_ids`.
- Check ids: `CLAIM_UNLINKED`, `CLAIM_DANGLING_LINK`, `SRC_UNREGISTERED`.
Wrong types raise `AsOfError`.

Example (verified by running, with the repo on `PYTHONPATH`):
```python
from datetime import datetime, timezone
from as_of.core import ClaimRecord, SourceRecord, SourceType
from as_of.source_register import SourceRegister
from as_of.catalyst_claim_links import validate_links

reg = SourceRegister()
reg.add_source(SourceRecord(
    source_id="SYN_S1", source_type=SourceType.FILING, publisher="SYN_PUBLISHER",
    locator="SYN_LOCATOR/SYN_S1",
    retrieved_at=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
    sha256="0" * 64, synthetic=True))
claims = [
    ClaimRecord(claim_id="SYN_C1", text="SYN_TEXT one", claim_kind="SYN_KIND",
                source_ids=("SYN_S1",), status="draft", section="SYN_SECTION"),
    ClaimRecord(claim_id="SYN_C2", text="SYN_TEXT two", claim_kind="SYN_KIND",
                source_ids=("SYN_S9",), status="draft", section="SYN_SECTION"),
]
links = {"SYN_C1": "SYN_CAT1", "SYN_C3": "SYN_CAT1"}
for f in validate_links(claims, links, {"SYN_CAT1"}, reg):
    print(f.check_id, f.subject, "|", f.message)
```
Output:
```
CLAIM_UNLINKED SYN_C2 | claim 'SYN_C2' has no catalyst link
SRC_UNREGISTERED SYN_C2 | claim 'SYN_C2': source 'SYN_S9' is used but not registered
CLAIM_DANGLING_LINK SYN_C3 | link refers to unknown claim 'SYN_C3'
```

## Known limits
- It checks only that a link exists and names a known catalyst. It does not judge whether the catalyst really supports the claim.
- Dates are not checked against the claim's as-of time.
- Each claim gets one catalyst id; only FAIL findings are produced.
- Synthetic data only; no network calls, no trading code.
