"""Go or no-go readiness record for an as-of research run.

The record gathers three kinds of evidence into one decision:

* readiness items, each with a pass or fail flag and an evidence reference;
* validation findings from earlier checks, where a FAIL finding blocks and a
  WARN or INFO finding does not;
* a count of open incidents, where any open incident blocks.

Readiness is a go only when every item passed, no finding failed, no incident
is open, and the item list is not empty. An empty item list blocks because it
means nothing was checked. Every blocking reason is written into the
``blocking`` list so a reviewer can see why the answer is no-go.

The record also carries a ``digest``, a stable hash of the inputs. Two runs
with the same inputs give the same digest, so a sign-off can name the exact
evidence it relied on.

Topic: readiness record.

All data handled here is synthetic. Only the shared types and helpers in
as_of.core are used. No other as_of module is imported.
"""

import re
from typing import Any, Dict, List, Sequence

from as_of.core import (
    AsOfError,
    Finding,
    ReadinessItem,
    ValidationStatus,
    require,
    stable_hash,
)

_DIGEST_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)


def _blocking_reasons(
    items: Sequence[ReadinessItem],
    findings: Sequence[Finding],
    open_incident_count: int,
) -> List[str]:
    """Return the list of reasons the run is blocked, in a fixed order."""
    reasons: List[str] = []
    if len(items) == 0:
        reasons.append("empty_item_list: no readiness items were supplied")
    for item in items:
        if not item.passed:
            reasons.append("item_failed: %s (evidence %s)" % (item.item_id, item.evidence_ref))
    for finding in findings:
        if finding.status == ValidationStatus.FAIL:
            reasons.append(
                "finding_failed: %s on %s: %s" % (finding.check_id, finding.subject, finding.message)
            )
    if open_incident_count > 0:
        reasons.append("open_incidents: %d open incident(s)" % open_incident_count)
    return reasons


def build_readiness(
    items: Sequence[ReadinessItem],
    findings: Sequence[Finding],
    open_incident_count: int,
) -> Dict[str, Any]:
    """Build the go or no-go record.

    Returns a dict with these keys:

    * ``go``: True only when nothing blocks readiness.
    * ``blocking``: a list of text reasons, empty when ``go`` is True.
    * ``digest``: a hex sha256 of the canonical form of the inputs.

    Raises AsOfError when open_incident_count is not a non-negative int
    (a bool is rejected even though it is an int subclass).
    """
    require(
        isinstance(open_incident_count, int) and not isinstance(open_incident_count, bool),
        "open_incident_count must be an int, got %s" % type(open_incident_count).__name__,
    )
    require(open_incident_count >= 0, "open_incident_count must be >= 0")
    try:
        item_list = list(items)
    except TypeError:
        raise AsOfError("items must be a sequence of ReadinessItem, got %s" % type(items).__name__)
    try:
        finding_list = list(findings)
    except TypeError:
        raise AsOfError("findings must be a sequence of Finding, got %s" % type(findings).__name__)
    for item in item_list:
        if not isinstance(item, ReadinessItem):
            raise AsOfError("items must be ReadinessItem, got %s" % type(item).__name__)
        # A truthy string such as "false" must not count as a pass.
        require(isinstance(item.passed, bool), "item %r passed flag must be a bool" % (item.item_id,))
        require(isinstance(item.item_id, str) and item.item_id.strip() != "", "item_id must be a non-empty str")
        # Every item carries an evidence reference, so a pass with no reference is unverifiable.
        require(
            isinstance(item.evidence_ref, str) and item.evidence_ref.strip() != "",
            "item %r evidence_ref must be a non-empty str" % (item.item_id,),
        )
    for finding in finding_list:
        if not isinstance(finding, Finding):
            raise AsOfError("findings must be Finding, got %s" % type(finding).__name__)
        # A non-enum status would otherwise never equal FAIL and never block.
        require(
            isinstance(finding.status, ValidationStatus),
            "finding %r status must be a ValidationStatus, got %r" % (finding.check_id, finding.status),
        )

    blocking = _blocking_reasons(item_list, finding_list, open_incident_count)
    digest = stable_hash(
        {
            "items": item_list,
            "findings": finding_list,
            "open_incident_count": open_incident_count,
        }
    )
    return {
        "go": len(blocking) == 0,
        "blocking": blocking,
        "digest": digest,
    }


def render_readiness(rec: Dict[str, Any]) -> str:
    """Render a readiness record as plain text for a review packet.

    The output starts with the decision (GO or NO-GO), then the digest, then
    one line per blocking reason. Raises AsOfError when a required key is
    missing from rec.
    """
    require(isinstance(rec, dict), "readiness record must be a dict")
    for key in ("go", "blocking", "digest"):
        require(key in rec, "readiness record is missing key %r" % key)
    require(isinstance(rec["go"], bool), "readiness record go must be a bool")
    require(isinstance(rec["blocking"], list), "readiness record blocking must be a list")
    require(
        rec["go"] == (len(rec["blocking"]) == 0),
        "readiness record go disagrees with its blocking list",
    )
    # The digest is always a hex sha256 from build_readiness. Anything else
    # could carry a newline and forge an extra decision line in the packet.
    require(
        isinstance(rec["digest"], str) and _DIGEST_RE.fullmatch(rec["digest"]) is not None,
        "readiness record digest must be a 64-character lowercase hex sha256",
    )
    lines: List[str] = []
    lines.append("Readiness decision: %s" % ("GO" if rec["go"] else "NO-GO"))
    lines.append("Digest: %s" % rec["digest"])
    if rec["blocking"]:
        lines.append("Blocking reasons:")
        for reason in rec["blocking"]:
            # Keep each reason on one line so ids cannot forge extra packet lines.
            flat = " ".join(str(reason).splitlines())
            lines.append("  - %s" % flat)
    else:
        lines.append("Blocking reasons: none")
    return "\n".join(lines) + "\n"
