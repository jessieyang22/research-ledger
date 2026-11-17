"""Catalyst-to-claim link checks for the as_of package.

A claim in a research output should point at the catalyst that justifies it,
and every source the claim cites should be in the source register. This module
checks both halves and reports problems as Finding records:

* CLAIM_UNLINKED: a claim has no entry in the links mapping (FAIL).
* CLAIM_DANGLING_LINK: a claim links to a catalyst id that is not in the
  known catalyst set, or the links mapping names a claim that does not exist
  (FAIL).
* SRC_UNREGISTERED: a claim cites a source id that is not registered (FAIL).
  The finding comes from SourceRegister.check_sources_used, so the wording and
  check id match the rest of the package.

It uses synthetic data only and makes no network calls.

Shared types come from as_of.core. The only other as_of module used is
as_of.source_register, which is imported once at module load.
"""

from typing import List, Mapping, Sequence, Set

from as_of.core import AsOfError, ClaimRecord, Finding, ValidationStatus
from as_of.source_register import SourceRegister

UNLINKED_CHECK_ID: str = "CLAIM_UNLINKED"
DANGLING_LINK_CHECK_ID: str = "CLAIM_DANGLING_LINK"


def _require_str(value: object, field: str) -> None:
    """Raise AsOfError unless value is a str (blank strings are allowed)."""
    if not isinstance(value, str):
        raise AsOfError("%s must be a str, got %r" % (field, value))


def _require_id(value: object, field: str) -> None:
    """Raise AsOfError unless value is a non-blank str id."""
    _require_str(value, field)
    if not value.strip():
        raise AsOfError("%s must be a non-blank str, got %r" % (field, value))


def validate_links(
    claims: Sequence[ClaimRecord],
    links: Mapping[str, str],
    catalyst_ids: Set[str],
    register: SourceRegister,
) -> List[Finding]:
    """Check catalyst links and source registration for a set of claims.

    Args:
        claims: Claims to check, in the order findings should follow.
        links: Maps claim_id to the catalyst_id that justifies the claim.
        catalyst_ids: The catalyst ids that exist.
        register: Source register used to check each claim's source_ids.

    Returns:
        A list of FAIL findings. An empty list means every claim is linked to
        a known catalyst, every link names a known claim, and every cited
        source is registered.
    """
    # Reject wrong types up front. A str catalyst_ids would be matched by
    # substring, a str source_ids would be split into characters, and a
    # non-str link value (a list, or a bool that equals 1) would either crash
    # or match the wrong catalyst.
    if isinstance(catalyst_ids, str):
        raise AsOfError("catalyst_ids must be a set of str, not a str")
    for catalyst_id in catalyst_ids:
        _require_id(catalyst_id, "catalyst id")
    for claim in claims:
        if not isinstance(claim, ClaimRecord):
            raise AsOfError("claims must be ClaimRecord objects, got %r" % (claim,))
        _require_id(claim.claim_id, "claim_id")
        if not isinstance(claim.source_ids, (tuple, list)):
            raise AsOfError(
                "source_ids for claim %r must be a tuple or list" % (claim.claim_id,)
            )
    for claim_id, catalyst_id in links.items():
        _require_str(claim_id, "link claim_id")
        if not isinstance(catalyst_id, str):
            raise AsOfError("link for claim %r must be a str catalyst id" % (claim_id,))

    findings: List[Finding] = []
    known_claim_ids: Set[str] = set()

    for claim in claims:
        known_claim_ids.add(claim.claim_id)

        if claim.claim_id not in links:
            findings.append(
                Finding(
                    check_id=UNLINKED_CHECK_ID,
                    status=ValidationStatus.FAIL,
                    message="claim %r has no catalyst link" % (claim.claim_id,),
                    subject=claim.claim_id,
                )
            )
        else:
            catalyst_id = links[claim.claim_id]
            if catalyst_id not in catalyst_ids:
                findings.append(
                    Finding(
                        check_id=DANGLING_LINK_CHECK_ID,
                        status=ValidationStatus.FAIL,
                        message="claim %r links to unknown catalyst %r"
                        % (claim.claim_id, catalyst_id),
                        subject=claim.claim_id,
                    )
                )

        for source_finding in register.check_sources_used(claim.source_ids):
            findings.append(
                Finding(
                    check_id=source_finding.check_id,
                    status=source_finding.status,
                    message="claim %r: %s" % (claim.claim_id, source_finding.message),
                    subject=claim.claim_id,
                )
            )

    for claim_id in sorted(links):
        if claim_id not in known_claim_ids:
            findings.append(
                Finding(
                    check_id=DANGLING_LINK_CHECK_ID,
                    status=ValidationStatus.FAIL,
                    message="link refers to unknown claim %r" % (claim_id,),
                    subject=str(claim_id),
                )
            )

    return findings
