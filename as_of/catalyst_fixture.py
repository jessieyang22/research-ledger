"""Synthetic catalyst fixture for the as_of catalyst exception queue.

Builds a small, fully known set of inputs with planted problems so that the
queue and the link checks have items to find:

    * One claim has no entry in the links mapping (CLAIM_UNLINKED).
    * One claim links to a catalyst id that is not in the catalyst set
      (a dangling link, reported as a failed check).
    * Two filings exist for covered names (FILING_OCCURRED).

The module does no I/O and no network access, and it names no real company.
The seeded numpy generator sets only the filing hour and minute offsets. The
other values are fixed, and each source sha256 is a digest of the source id
and seed, not of any document body. Two calls with the same seed return equal
output.

Conventions:
    * Tickers are SYN_T01 and SYN_T02.
    * Every source has synthetic=True and a SYN_ prefixed id.
    * Expected exceptions use kind names from as_of.exception_vocabulary.
      The dangling link has no dedicated kind there, so it is expected as
      CHECK_FAILED, which that vocabulary reserves for failing checks that
      do not fit a more specific kind.

The design is an original implementation of the idea that a fixture
should plant known faults so a check can be shown to find them.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Set, Tuple

from as_of.core import (
    SYNTHETIC_PREFIX,
    SYNTHETIC_SEED,
    ClaimRecord,
    FilingRecord,
    SourceRecord,
    SourceType,
    make_rng,
    require,
    sha256_text,
)

_RETRIEVED_AT: datetime = datetime(2025, 1, 1, tzinfo=timezone.utc)
_TICKERS: Tuple[str, ...] = (SYNTHETIC_PREFIX + "T01", SYNTHETIC_PREFIX + "T02")
_CATALYST_IDS: Tuple[str, ...] = (SYNTHETIC_PREFIX + "CAT_01", SYNTHETIC_PREFIX + "CAT_02")
_DANGLING_CATALYST_ID: str = SYNTHETIC_PREFIX + "CAT_99"


def make_catalyst_fixture(seed: int = SYNTHETIC_SEED) -> Dict[str, Any]:
    """Build a deterministic synthetic catalyst fixture.

    Args:
        seed: Seed for the numpy generator that sets filing times.

    Returns:
        A dict with these keys:
            sources: List[SourceRecord], one catalyst calendar source and one
                filing source per filing.
            claims: List[ClaimRecord], three claims. The third claim is
                deliberately absent from links.
            catalyst_ids: Set[str] of catalyst ids that exist.
            links: Dict[str, str] mapping claim_id to catalyst_id. It holds
                two claims. One value is a catalyst id that is not in
                catalyst_ids.
            filings: List[FilingRecord], one per covered ticker.
            exceptions_expected: List[Tuple[str, str]] of (kind name,
                subject_id) pairs that a correct queue should report.
    """
    require(
        isinstance(seed, int) and not isinstance(seed, bool) and seed >= 0,
        "seed must be a non-negative int",
    )

    rng = make_rng(seed)

    catalyst_src_id = SYNTHETIC_PREFIX + "SRC_CAT_01"
    sources: List[SourceRecord] = [
        SourceRecord(
            source_id=catalyst_src_id,
            source_type=SourceType.CATALYST,
            publisher="synthetic-catalyst-calendar",
            locator="fixture://catalyst/calendar",
            retrieved_at=_RETRIEVED_AT,
            sha256=sha256_text("%s|%d" % (catalyst_src_id, seed)),
            synthetic=True,
        )
    ]

    filings: List[FilingRecord] = []
    for t_idx, ticker in enumerate(_TICKERS):
        filing_src_id = SYNTHETIC_PREFIX + "SRC_FIL_%02d" % (t_idx + 1)
        filed_at = datetime(2026, 9, 1 + 7 * t_idx, 13, 0, 0, tzinfo=timezone.utc) + timedelta(
            hours=int(rng.integers(0, 6))
        )
        accepted_at = filed_at + timedelta(minutes=5 + int(rng.integers(0, 20)))
        # A filing source cannot be retrieved before the filing was accepted.
        sources.append(
            SourceRecord(
                source_id=filing_src_id,
                source_type=SourceType.FILING,
                publisher="synthetic-filings",
                locator="fixture://catalyst/filings/" + ticker,
                retrieved_at=accepted_at + timedelta(hours=1),
                sha256=sha256_text("%s|%d" % (filing_src_id, seed)),
                synthetic=True,
            )
        )
        filings.append(
            FilingRecord(
                filing_id=SYNTHETIC_PREFIX + "FIL_%02d" % (t_idx + 1),
                ticker=ticker,
                form_type="8-K",
                filed_at=filed_at,
                accepted_at=accepted_at,
                source_id=filing_src_id,
            )
        )

    claims: List[ClaimRecord] = [
        ClaimRecord(
            claim_id=SYNTHETIC_PREFIX + "CLM_01",
            text="Synthetic claim one tied to the first catalyst.",
            claim_kind="thesis",
            source_ids=(catalyst_src_id,),
            status="draft",
            section="summary",
        ),
        ClaimRecord(
            claim_id=SYNTHETIC_PREFIX + "CLM_02",
            text="Synthetic claim two tied to the second catalyst.",
            claim_kind="thesis",
            source_ids=(catalyst_src_id,),
            status="draft",
            section="summary",
        ),
        ClaimRecord(
            claim_id=SYNTHETIC_PREFIX + "CLM_03",
            text="Synthetic claim three with no catalyst link.",
            claim_kind="risk",
            source_ids=(catalyst_src_id,),
            status="draft",
            section="risks",
        ),
    ]

    catalyst_ids: Set[str] = set(_CATALYST_IDS)

    # CLM_01 links to a real catalyst. CLM_02 links to a catalyst id that does
    # not exist (the planted dangling link). CLM_03 is absent on purpose.
    links: Dict[str, str] = {
        SYNTHETIC_PREFIX + "CLM_01": _CATALYST_IDS[0],
        SYNTHETIC_PREFIX + "CLM_02": _DANGLING_CATALYST_ID,
    }

    exceptions_expected: List[Tuple[str, str]] = [
        ("CLAIM_UNLINKED", SYNTHETIC_PREFIX + "CLM_03"),
        ("CHECK_FAILED", SYNTHETIC_PREFIX + "CLM_02"),
    ]
    for filing in filings:
        exceptions_expected.append(("FILING_OCCURRED", filing.filing_id))

    return {
        "sources": sources,
        "claims": claims,
        "catalyst_ids": catalyst_ids,
        "links": links,
        "filings": filings,
        "exceptions_expected": exceptions_expected,
    }
