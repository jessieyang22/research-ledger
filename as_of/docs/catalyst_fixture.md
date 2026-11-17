# catalyst_fixture: synthetic catalyst inputs with planted faults

## What the module does
`as_of/catalyst_fixture.py` builds a small, seeded, synthetic set of catalyst inputs for invented tickers (`SYN_T01`, `SYN_T02`). It returns sources, claims, catalyst ids, claim-to-catalyst links, filings, and the exceptions a correct queue should report. It plants three known faults: one claim with no link, one link to a catalyst id that does not exist, and one filing per covered ticker. It does no I/O or network calls and names no real company.

## Design idea
The synthetic-fixture idea is that a test fixture should contain known faults, so a check can be shown to find them. This module follows that idea.

## API
- `make_catalyst_fixture(seed=20261027) -> dict` with keys:
  - `sources`: one catalyst calendar source and one filing source per filing (`synthetic=True`, `SYN_` ids).
  - `claims`: three `ClaimRecord`s. `SYN_CLM_03` has no link.
  - `catalyst_ids`: `{SYN_CAT_01, SYN_CAT_02}`.
  - `links`: `SYN_CLM_01 -> SYN_CAT_01` and `SYN_CLM_02 -> SYN_CAT_99` (dangling).
  - `filings`: two `FilingRecord`s (8-K), with UTC `filed_at` before `accepted_at`.
  - `exceptions_expected`: `(kind, subject_id)` pairs for `CLAIM_UNLINKED`, `CHECK_FAILED`, and `FILING_OCCURRED`.
- A non-int or negative seed (including a bool) raises `AsOfError`.

Example (run and verified with the repo root on `PYTHONPATH`):
```python
from as_of.catalyst_fixture import make_catalyst_fixture
fx = make_catalyst_fixture(seed=20261027)
print([c.claim_id for c in fx["claims"] if c.claim_id not in fx["links"]])  # ['SYN_CLM_03']
dangling = fx["links"]["SYN_CLM_02"]
print(dangling, dangling in fx["catalyst_ids"])                             # SYN_CAT_99 False
print(len(fx["filings"]), fx["filings"][0].accepted_at.isoformat())         # 2 2026-09-01T17:24:00+00:00
```

## Known limits
- Three claims and two catalysts only. This is a test input, not a real calendar.
- Seed changes only filing hour and minute offsets. Source hashes digest the source id and seed, not document bodies, and nothing checks them against a manifest.
- Expected exceptions are the planted faults only. The dangling link is expected as `CHECK_FAILED` because the vocabulary has no dedicated kind for it.
- Tests: `as_of/tests/test_catalyst_fixture.py` (12 passed) and `as_of/tests/test_catalyst_fixture_attack.py`.
