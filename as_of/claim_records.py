"""Claim records for the as_of package.

A claim is one statement that an output makes, such as a fact about a filing,
an analyst estimate, an opinion, or something an expert said on a call. Each
claim carries a kind, a status, and the source ids it rests on. This module
builds claim records and checks them against three rules:

1. A fact must cite at least one source id. A fact with no source is a FAIL.
2. Expert-call input is never allowed to reach status 'verified'. Such a claim
   is a FAIL if it is marked verified. It may stay 'unverified' or be
   'rejected'.
3. The claim kind and the status must come from the allowed vocabularies.
   An unknown value is a FAIL.

validate_claim returns one Finding per check. A claim that passes every check
gets a single PASS finding, so every claim produces at least one finding.
status_counts tallies claims by status and always sums to the number of claims.

It uses synthetic data only and makes no network calls.

Only core.py is imported. No other as_of module is needed.
"""

from typing import Dict, List, Sequence, Tuple

from as_of.core import ClaimRecord, Finding, ValidationStatus

CLAIM_KINDS: Tuple[str, ...] = ("fact", "estimate", "opinion", "expert_input")
CLAIM_STATUSES: Tuple[str, ...] = ("unverified", "verified", "rejected")

CHECK_KIND: str = "CLM_UNKNOWN_KIND"
CHECK_STATUS: str = "CLM_UNKNOWN_STATUS"
CHECK_FACT_SOURCE: str = "CLM_FACT_NO_SOURCE"
CHECK_EXPERT_VERIFIED: str = "CLM_EXPERT_VERIFIED"
CHECK_CLEAN: str = "CLM_OK"


def make_claim(
    claim_id: str,
    text: str,
    claim_kind: str,
    source_ids: Sequence[str],
    status: str = "unverified",
    section: str = "",
) -> ClaimRecord:
    """Build a ClaimRecord. Values are stored as given and checked later.

    make_claim does not reject bad kinds or statuses. validate_claim reports
    them as FAIL findings, so a bad claim can still be recorded and reviewed.
    source_ids is copied into a tuple so the record stays immutable. A bare
    string is treated as one source id, not as a sequence of characters.
    """
    if isinstance(source_ids, (str, bytes)):
        source_ids = (source_ids,)
    return ClaimRecord(
        claim_id=claim_id,
        text=text,
        claim_kind=claim_kind,
        source_ids=tuple(source_ids),
        status=status,
        section=section,
    )


def _has_source(source_ids: Tuple[str, ...]) -> bool:
    """True when at least one source id is a non-blank string."""
    return any(isinstance(s, str) and s.strip() != "" for s in source_ids)


def validate_claim(rec: ClaimRecord) -> List[Finding]:
    """Check one claim record and return the findings.

    Every failed rule adds a FAIL finding. If no rule fails, a single PASS
    finding is returned. The subject of each finding is the claim_id.
    """
    subject = rec.claim_id
    findings: List[Finding] = []

    if rec.claim_kind not in CLAIM_KINDS:
        findings.append(
            Finding(
                check_id=CHECK_KIND,
                status=ValidationStatus.FAIL,
                message="unknown claim_kind %r; allowed: %s"
                % (rec.claim_kind, ", ".join(CLAIM_KINDS)),
                subject=subject,
            )
        )

    if rec.status not in CLAIM_STATUSES:
        findings.append(
            Finding(
                check_id=CHECK_STATUS,
                status=ValidationStatus.FAIL,
                message="unknown status %r; allowed: %s"
                % (rec.status, ", ".join(CLAIM_STATUSES)),
                subject=subject,
            )
        )

    if rec.claim_kind == "fact" and not _has_source(rec.source_ids):
        findings.append(
            Finding(
                check_id=CHECK_FACT_SOURCE,
                status=ValidationStatus.FAIL,
                message="fact claim has no source_ids",
                subject=subject,
            )
        )

    if rec.claim_kind == "expert_input" and rec.status == "verified":
        findings.append(
            Finding(
                check_id=CHECK_EXPERT_VERIFIED,
                status=ValidationStatus.FAIL,
                message="expert_input cannot have status 'verified'",
                subject=subject,
            )
        )

    if not findings:
        findings.append(
            Finding(
                check_id=CHECK_CLEAN,
                status=ValidationStatus.PASS,
                message="claim passes all checks",
                subject=subject,
            )
        )
    return findings


def status_counts(claims: Sequence[ClaimRecord]) -> Dict[str, int]:
    """Count claims by status.

    Every allowed status appears as a key, even with a zero count. A claim
    whose status is not in CLAIM_STATUSES is counted under its own value, so
    the counts always sum to len(claims).
    """
    counts: Dict[str, int] = {status: 0 for status in CLAIM_STATUSES}
    for rec in claims:
        key = rec.status
        try:
            hash(key)
        except TypeError:
            # Unhashable status (for example a list): count it under its repr
            # so the tally still sums to len(claims) instead of crashing.
            key = repr(key)
        counts[key] = counts.get(key, 0) + 1
    return counts
