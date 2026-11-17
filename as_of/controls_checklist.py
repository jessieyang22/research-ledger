"""Control catalog for the as_of package.

A control is a named thing the research process must be able to show evidence
for. Each ControlSpec says what the control is, what kind of evidence proves it,
and which role owns it. missing_evidence() takes a mapping from control_id to an
evidence reference and flags every catalog control that has no entry, or an
empty one. checklist_markdown() writes the catalog as a Markdown checklist with
one checkbox per control.

Desktop and permission concerns are handled as repo checklist items only. This
module never changes Claude or IDE settings files, never reads secrets, and
never runs commands. A control about permissions asks a person to review the
repo and record evidence. It does not edit any configuration.

Rules:
- control_id values are unique across the catalog.
- No ControlSpec uses the evidence kind 'settings_change'.
- Every evidence kind is one of EVIDENCE_KINDS below.

Topic: controls. The wording here is original. All data handled here is
synthetic. This module imports only the standard library and as_of.core.
"""

from typing import Dict, List, Mapping, Tuple

from as_of.core import Finding, ValidationStatus


CHECK_ID: str = "controls.missing_evidence"

# Evidence kinds a control may point to. 'settings_change' is deliberately absent:
# this package never records or makes changes to settings files.
EVIDENCE_KINDS: Tuple[str, ...] = (
    "test_report",
    "vintage_manifest",
    "source_register_entry",
    "reviewer_signoff",
    "checklist_review",
    "run_log",
    "handoff_note",
)

OWNER_ROLES: Tuple[str, ...] = (
    "analyst",
    "reviewer",
    "portfolio_manager",
    "operations",
)


class ControlSpec:
    """One control in the catalog. Instances are immutable."""

    __slots__ = ("control_id", "description", "evidence_kind", "owner_role")

    def __init__(self, control_id: str, description: str, evidence_kind: str, owner_role: str) -> None:
        if not isinstance(control_id, str) or not control_id.strip():
            raise ValueError("control_id must be a non-empty string")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description must be a non-empty string")
        if evidence_kind not in EVIDENCE_KINDS:
            raise ValueError("unknown evidence_kind: %r" % (evidence_kind,))
        if owner_role not in OWNER_ROLES:
            raise ValueError("unknown owner_role: %r" % (owner_role,))
        object.__setattr__(self, "control_id", control_id)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "evidence_kind", evidence_kind)
        object.__setattr__(self, "owner_role", owner_role)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ControlSpec is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ControlSpec is immutable")

    def __repr__(self) -> str:
        return "ControlSpec(control_id=%r, evidence_kind=%r, owner_role=%r)" % (
            self.control_id,
            self.evidence_kind,
            self.owner_role,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ControlSpec):
            return NotImplemented
        return (
            self.control_id == other.control_id
            and self.description == other.description
            and self.evidence_kind == other.evidence_kind
            and self.owner_role == other.owner_role
        )

    def __hash__(self) -> int:
        return hash((self.control_id, self.description, self.evidence_kind, self.owner_role))


CONTROL_CATALOG: Tuple[ControlSpec, ...] = (
    ControlSpec(
        "ctl_source_register_current",
        "Every source used in a memo is listed in the source register with a retrieval time and a checksum.",
        "source_register_entry",
        "analyst",
    ),
    ControlSpec(
        "ctl_estimate_ledger_dated",
        "Each estimate value carries the time it became known, so a past as-of view can be rebuilt without later revisions.",
        "test_report",
        "analyst",
    ),
    ControlSpec(
        "ctl_vintage_manifest_written",
        "Each macro or fundamental data pull writes a manifest with file hashes and release times before any model reads it.",
        "vintage_manifest",
        "operations",
    ),
    ControlSpec(
        "ctl_catalyst_exceptions_cleared",
        "Catalyst items that miss their window or lack a source are placed in the exception queue and closed with a note.",
        "run_log",
        "analyst",
    ),
    ControlSpec(
        "ctl_portfolio_tieout",
        "Position totals in the packet match the book records as of the same date, with differences explained.",
        "test_report",
        "operations",
    ),
    ControlSpec(
        "ctl_pm_packet_reviewed",
        "A reviewer has read the packet, checked each claim against its linked sources, and signed off.",
        "reviewer_signoff",
        "reviewer",
    ),
    ControlSpec(
        "ctl_price_hard_fail_checked",
        "Price inputs are checked for gaps and stale closes, and a hard failure stops the run.",
        "run_log",
        "operations",
    ),
    ControlSpec(
        "ctl_schedule_timeliness_logged",
        "Each scheduled run records whether it was on time, late, or missed, and the late runs are reviewed.",
        "run_log",
        "operations",
    ),
    ControlSpec(
        "ctl_secrets_scan_clean",
        "The repo has been scanned for credentials and none are present in tracked files.",
        "test_report",
        "operations",
    ),
    ControlSpec(
        "ctl_handoff_note_complete",
        "A handoff note states the as-of date, open exceptions, and the next owner before work changes hands.",
        "handoff_note",
        "analyst",
    ),
    ControlSpec(
        "ctl_change_record_approved",
        "Every change to a method, source, or threshold has a change record with a reason and an approver.",
        "reviewer_signoff",
        "portfolio_manager",
    ),
    ControlSpec(
        "ctl_repo_permissions_reviewed",
        "A person has reviewed the repo's permission boundaries by reading the checklist, with no settings files edited by this project.",
        "checklist_review",
        "reviewer",
    ),
    ControlSpec(
        "ctl_desktop_environment_noted",
        "The desktop environment used for runs (Python version, package set, OS) is written into the handoff note.",
        "handoff_note",
        "operations",
    ),
    ControlSpec(
        "ctl_synthetic_data_only",
        "Fixtures use only synthetic identifiers, and the test report confirms no live data source was called.",
        "test_report",
        "reviewer",
    ),
)


def _catalog_ids() -> List[str]:
    return [spec.control_id for spec in CONTROL_CATALOG]


# Enforced at import time so a duplicated control_id cannot ship silently.
if len(set(_catalog_ids())) != len(CONTROL_CATALOG):
    raise ValueError("CONTROL_CATALOG contains duplicate control_id values")


def missing_evidence(evidence: Mapping[str, str]) -> List[Finding]:
    """Return one FAIL finding for each catalog control with no evidence reference.

    evidence maps control_id to a reference string (for example a file path or a
    report id). A control is flagged when its key is absent or the value is empty
    or whitespace. Keys that match no control are ignored.
    """
    findings: List[Finding] = []
    for spec in CONTROL_CATALOG:
        ref = evidence.get(spec.control_id)
        if not isinstance(ref, str) or not ref.strip():
            findings.append(
                Finding(
                    check_id=CHECK_ID,
                    status=ValidationStatus.FAIL,
                    message="no %s evidence recorded for control %s (owner: %s)"
                    % (spec.evidence_kind, spec.control_id, spec.owner_role),
                    subject=spec.control_id,
                )
            )
    return findings


def checklist_markdown() -> str:
    """Return the catalog as a Markdown checklist with one checkbox line per control."""
    lines: List[str] = [
        "# Controls checklist",
        "",
        "Tick a box only when the named evidence exists in the repo or the handoff note.",
        "",
    ]
    for spec in CONTROL_CATALOG:
        lines.append(
            "- [ ] `%s` %s Evidence: %s. Owner: %s."
            % (spec.control_id, " ".join(spec.description.split()), spec.evidence_kind, spec.owner_role)
        )
    lines.append("")
    return "\n".join(lines)


def _check_catalog() -> Dict[str, int]:
    """Return counts used by the self-check. Not part of the public API."""
    return {"controls": len(CONTROL_CATALOG), "unique_ids": len(set(_catalog_ids()))}
