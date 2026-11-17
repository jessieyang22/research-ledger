"""Failure mode fm35: citation laundering.

A claim carries a citation, but the cited source does not support the claim.
The citation looks valid because the source exists and is registered, so a
check that only asks "is there a source id?" passes. The expected detection is
to read a claim_supported signal for each claim and block or narrow any claim
whose support is missing.

Finding: the package checks that a citation EXISTS and is REGISTERED, not that
it SUPPORTS the claim text.
- as_of.claim_records requires at least one source id on a fact. It does not
  read the source content, and it has no support field on ClaimRecord.
- as_of.catalyst_claim_links flags unregistered source ids and unlinked claims.
  A laundered citation to a registered source passes it.
- as_of.estimate_ledger keeps a source_id on each EstimateRecord and does not
  check it at all.
No module has a claim_supported field, so the blocking test is a strict xfail.
The gap is reported rather than faked. The tests that do run document what the
existing checks catch (no citation, unregistered citation) and what they miss
(a registered citation that does not support the claim).

Fixtures use the SYN_ prefix.
"""

import hashlib
from datetime import datetime, timezone

import pytest

from as_of.catalyst_claim_links import DANGLING_LINK_CHECK_ID, validate_links
from as_of.claim_records import CHECK_FACT_SOURCE, make_claim, validate_claim
from as_of.core import (
    EstimateRecord,
    SourceRecord,
    SourceType,
    ValidationStatus,
)
from as_of.estimate_ledger import EstimateLedger
from as_of.source_register import SourceRegister

SYN_SOURCE = "SYN_FM35_FILING_001"
SYN_UNREGISTERED = "SYN_FM35_NOT_REGISTERED"
SYN_RETRIEVED = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
SYN_CATALYST = "SYN_FM35_CAT_1"

# The registered synthetic filing says the segment grew 4 percent.
SYN_SOURCE_TEXT = "SYN synthetic filing: segment revenue grew 4 percent year over year."
# The laundered claim says something the source never states.
SYN_LAUNDERED_TEXT = "SYN claim: segment margin expanded by 300 basis points."


def _register() -> SourceRegister:
    register = SourceRegister()
    register.add_source(
        SourceRecord(
            source_id=SYN_SOURCE,
            source_type=SourceType.FILING,
            publisher="SYN_publisher",
            locator="SYN_locator/filing_001",
            retrieved_at=SYN_RETRIEVED,
            sha256=hashlib.sha256(SYN_SOURCE_TEXT.encode("utf-8")).hexdigest(),
            synthetic=True,
        )
    )
    return register


def test_uncited_fact_is_flagged_by_claim_records():
    """Detected: a fact with no citation at all is a FAIL. This is the easy case."""
    claim = make_claim("SYN_FM35_C1", SYN_LAUNDERED_TEXT, "fact", source_ids=())
    check_ids = [f.check_id for f in validate_claim(claim) if f.status == ValidationStatus.FAIL]
    assert CHECK_FACT_SOURCE in check_ids


def test_unregistered_citation_is_flagged_by_link_check():
    """Detected: a citation to a source id that is not registered is a FAIL."""
    claim = make_claim("SYN_FM35_C2", SYN_LAUNDERED_TEXT, "fact", source_ids=(SYN_UNREGISTERED,))
    findings = validate_links(
        [claim],
        {"SYN_FM35_C2": SYN_CATALYST},
        {SYN_CATALYST},
        _register(),
    )
    assert any(f.status == ValidationStatus.FAIL for f in findings)


def test_laundered_citation_passes_claim_records_and_link_check():
    """Documents the gap: a claim whose text the registered source never states passes both checks.

    The source exists, is registered and has a matching hash, so no existing
    check can tell that the citation does not support the claim text.
    """
    register = _register()
    claim = make_claim("SYN_FM35_C3", SYN_LAUNDERED_TEXT, "fact", source_ids=(SYN_SOURCE,))
    assert not any(f.status == ValidationStatus.FAIL for f in validate_claim(claim))
    findings = validate_links([claim], {"SYN_FM35_C3": SYN_CATALYST}, {SYN_CATALYST}, register)
    assert not any(f.status == ValidationStatus.FAIL for f in findings)
    assert not any(f.check_id == DANGLING_LINK_CHECK_ID for f in findings)


def test_estimate_row_citing_unrelated_source_is_not_checked():
    """Documents the gap: the estimate ledger keeps source_id but validate() never checks it.

    The row cites a source id that is not in any register, and the ledger
    still reports clean.
    """
    ledger = EstimateLedger()
    ledger.append(
        EstimateRecord(
            estimate_id="SYN_FM35_E1",
            ticker="SYN_TKR",
            metric="SYN_revenue",
            period="SYN_2026Q4",
            analyst_id="SYN_ANALYST_A",
            value=100.0,
            knowledge_at=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
            source_id=SYN_UNREGISTERED,
        )
    )
    statuses = [f.status for f in ledger.validate()]
    assert statuses == [ValidationStatus.PASS]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm35 gap: no module records whether a claim is supported by its cited source. "
        "ClaimRecord has no support field, validate_claim does not read source content, "
        "and validate_links checks only that the citation is registered. A claim that "
        "cites a registered source it does not match therefore passes with no FAIL."
    ),
)
def test_laundered_claim_is_blocked():
    """Expected control: a claim whose text the registered source does not support is a FAIL."""
    register = _register()
    claim = make_claim("SYN_FM35_C4", SYN_LAUNDERED_TEXT, "fact", source_ids=(SYN_SOURCE,))
    claim_findings = validate_claim(claim)
    link_findings = validate_links([claim], {"SYN_FM35_C4": SYN_CATALYST}, {SYN_CATALYST}, register)
    blocked = any(f.status == ValidationStatus.FAIL for f in claim_findings + link_findings)
    assert blocked
