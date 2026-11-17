"""Change-management records with a fixed status flow.

A change record tracks one change to the research process, model, or data
pipeline from proposal to verification. The status flow is fixed:

    proposed -> approved -> applied -> verified
    proposed -> rejected

Rules enforced here:

* Only the moves in LEGAL_MOVES are allowed. Anything else raises AsOfError.
  In particular, 'rejected' is reachable only from 'proposed', and
  'verified' cannot be reached from 'proposed' in one step.
* transition() never mutates its input. It returns a new ChangeRecord.
* A change that is 'applied' or 'verified' needs an evidence reference.
  transition() records whatever evidence_ref it is given, and
  validate_change() returns a FAIL finding when that reference is missing.


All data handled here is synthetic. Standard library and as_of.core only.
"""

import dataclasses
from datetime import date, datetime
from typing import Dict, FrozenSet, List, Optional, Tuple

from as_of.core import AsOfError, ChangeRecord, Finding, ValidationStatus, require


# ---------------------------------------------------------------------------
# Status flow
# ---------------------------------------------------------------------------

STATUS_PROPOSED: str = "proposed"
STATUS_APPROVED: str = "approved"
STATUS_APPLIED: str = "applied"
STATUS_VERIFIED: str = "verified"
STATUS_REJECTED: str = "rejected"

ALL_STATUSES: Tuple[str, ...] = (
    STATUS_PROPOSED,
    STATUS_APPROVED,
    STATUS_APPLIED,
    STATUS_VERIFIED,
    STATUS_REJECTED,
)

# Statuses that must carry evidence before they are considered valid.
EVIDENCE_REQUIRED: FrozenSet[str] = frozenset({STATUS_APPLIED, STATUS_VERIFIED})

# Each key is a current status. Each value is the set of statuses it may move to.
LEGAL_MOVES: Dict[str, FrozenSet[str]] = {
    STATUS_PROPOSED: frozenset({STATUS_APPROVED, STATUS_REJECTED}),
    STATUS_APPROVED: frozenset({STATUS_APPLIED}),
    STATUS_APPLIED: frozenset({STATUS_VERIFIED}),
    STATUS_VERIFIED: frozenset(),
    STATUS_REJECTED: frozenset(),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def open_change(change_id: str, summary: str, reason: str, opened_on: date) -> ChangeRecord:
    """Open a new change record in status 'proposed' with no evidence."""
    require(isinstance(change_id, str) and change_id.strip() != "", "change_id must be a non-empty str")
    require(isinstance(opened_on, date) and not isinstance(opened_on, datetime), "opened_on must be a date, not a datetime")
    return ChangeRecord(
        change_id=change_id,
        summary=summary,
        reason=reason,
        status=STATUS_PROPOSED,
        opened_on=opened_on,
        evidence_ref=None,
    )


def transition(
    rec: ChangeRecord,
    new_status: str,
    on: date,
    evidence_ref: Optional[str] = None,
) -> ChangeRecord:
    """Move a change to new_status and return a new ChangeRecord.

    The input record is left unchanged. Raises AsOfError when new_status is
    unknown, when the move is not in LEGAL_MOVES, or when 'on' is earlier
    than the day the change was opened. An evidence_ref passed here replaces
    the stored one. When it is None, the stored evidence_ref is kept.
    """
    require(isinstance(rec, ChangeRecord), "rec must be a ChangeRecord")
    require(isinstance(new_status, str) and new_status in ALL_STATUSES, "unknown change status: %r" % (new_status,))
    require(isinstance(on, date) and not isinstance(on, datetime), "on must be a date, not a datetime")
    require(
        isinstance(rec.opened_on, date) and not isinstance(rec.opened_on, datetime),
        "stored opened_on must be a date, not a datetime",
    )
    require(on >= rec.opened_on, "transition date %s is before opened_on %s" % (on, rec.opened_on))

    allowed = LEGAL_MOVES.get(rec.status, frozenset()) if isinstance(rec.status, str) else frozenset()
    if new_status not in allowed:
        raise AsOfError(
            "illegal change transition for %r: %s -> %s" % (rec.change_id, rec.status, new_status)
        )

    new_evidence = evidence_ref if evidence_ref is not None else rec.evidence_ref
    return dataclasses.replace(rec, status=new_status, evidence_ref=new_evidence)


def validate_change(rec: ChangeRecord) -> List[Finding]:
    """Check one change record and return its findings.

    Two checks run:
    * change.status: the status must be one of ALL_STATUSES (FAIL otherwise).
    * change.evidence: a record in 'applied' or 'verified' must have a
      non-empty evidence_ref (FAIL otherwise).

    Each check returns a PASS finding when it is satisfied.
    """
    require(isinstance(rec, ChangeRecord), "rec must be a ChangeRecord")
    findings: List[Finding] = []

    known_status = isinstance(rec.status, str) and rec.status in ALL_STATUSES
    if known_status:
        findings.append(
            Finding(
                check_id="change.status",
                status=ValidationStatus.PASS,
                message="status %r is a known change status" % rec.status,
                subject=rec.change_id,
            )
        )
    else:
        findings.append(
            Finding(
                check_id="change.status",
                status=ValidationStatus.FAIL,
                message="unknown change status %r" % (rec.status,),
                subject=rec.change_id,
            )
        )

    has_evidence = isinstance(rec.evidence_ref, str) and rec.evidence_ref.strip() != ""
    needs_evidence = isinstance(rec.status, str) and rec.status in EVIDENCE_REQUIRED
    if needs_evidence and not has_evidence:
        findings.append(
            Finding(
                check_id="change.evidence",
                status=ValidationStatus.FAIL,
                message="change in status %r has no evidence_ref" % rec.status,
                subject=rec.change_id,
            )
        )
    else:
        findings.append(
            Finding(
                check_id="change.evidence",
                status=ValidationStatus.PASS,
                message="evidence requirement satisfied for status %r" % rec.status,
                subject=rec.change_id,
            )
        )

    return findings
