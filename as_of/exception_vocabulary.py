"""Fixed vocabulary of exception kinds for the as_of exception queue.

This module is the single source for what an exception kind is called, what
it means, and how severe it is by default. The queue reads from here, so no
other module should invent its own kind names or severities.

The kinds and severities below are an original taxonomy written for this
repo, not a copy of the text.

Imports come from as_of.core only. All data handled here is synthetic.
"""

from enum import Enum
from typing import Dict

from as_of.core import AsOfError, Finding, Severity, ValidationStatus


class ExceptionKind(Enum):
    """The closed set of exception kinds the queue accepts."""

    MISSING_SOURCE = "MISSING_SOURCE"
    STALE_ESTIMATE = "STALE_ESTIMATE"
    LOOKAHEAD_RISK = "LOOKAHEAD_RISK"
    TIEOUT_BREAK = "TIEOUT_BREAK"
    MISSING_PRICE = "MISSING_PRICE"
    FILING_OCCURRED = "FILING_OCCURRED"
    CLAIM_UNLINKED = "CLAIM_UNLINKED"
    SCHEDULE_LATE = "SCHEDULE_LATE"
    CHECK_FAILED = "CHECK_FAILED"


KIND_DESCRIPTIONS: Dict[ExceptionKind, str] = {
    ExceptionKind.MISSING_SOURCE: (
        "A number, claim or input has no registered source record, so its "
        "provenance cannot be traced."
    ),
    ExceptionKind.STALE_ESTIMATE: (
        "An estimate in use has not been refreshed within the allowed window "
        "before the as-of point of the analysis. A revision dated after the "
        "as-of point is a look-ahead problem and belongs to LOOKAHEAD_RISK."
    ),
    ExceptionKind.LOOKAHEAD_RISK: (
        "An input carries a timestamp that falls after the as-of point, so "
        "using it could leak information the analysis could not have seen."
    ),
    ExceptionKind.TIEOUT_BREAK: (
        "A total or derived figure does not reconcile to its component "
        "figures within tolerance."
    ),
    ExceptionKind.MISSING_PRICE: (
        "No usable price exists for a position or instrument on the required "
        "date, so valuation or sizing cannot be completed."
    ),
    ExceptionKind.FILING_OCCURRED: (
        "A new filing was observed for a covered name. This records that the "
        "event happened; it does not say whether the filing matters."
    ),
    ExceptionKind.CLAIM_UNLINKED: (
        "A claim in a review packet is not linked to any supporting source "
        "or estimate record."
    ),
    ExceptionKind.SCHEDULE_LATE: (
        "A scheduled run or deliverable finished after its deadline or did "
        "not start when planned."
    ),
    ExceptionKind.CHECK_FAILED: (
        "A control or validation check returned a failing or warning result "
        "that does not fit a more specific kind."
    ),
}


_DEFAULT_SEVERITY: Dict[ExceptionKind, Severity] = {
    ExceptionKind.MISSING_SOURCE: Severity.BLOCK,
    ExceptionKind.STALE_ESTIMATE: Severity.WARN,
    ExceptionKind.LOOKAHEAD_RISK: Severity.BLOCK,
    ExceptionKind.TIEOUT_BREAK: Severity.BLOCK,
    # Matches the hard stop in price_hard_fail.py: a missing required price is
    # never papered over, so the default is BLOCK, not WARN.
    ExceptionKind.MISSING_PRICE: Severity.BLOCK,
    # An occurrence is informational. Significance is judged later, by a person.
    ExceptionKind.FILING_OCCURRED: Severity.INFO,
    ExceptionKind.CLAIM_UNLINKED: Severity.WARN,
    ExceptionKind.SCHEDULE_LATE: Severity.WARN,
    ExceptionKind.CHECK_FAILED: Severity.WARN,
}

_FINDING_SEVERITY: Dict[ValidationStatus, Severity] = {
    ValidationStatus.FAIL: Severity.BLOCK,
    ValidationStatus.WARN: Severity.WARN,
    ValidationStatus.PASS: Severity.INFO,
}


def default_severity(kind: ExceptionKind) -> Severity:
    """Return the default severity for kind."""
    if not isinstance(kind, ExceptionKind):
        raise AsOfError("expected ExceptionKind, got %s" % type(kind).__name__)
    return _DEFAULT_SEVERITY[kind]


def describe(kind: ExceptionKind) -> str:
    """Return the one-line description for kind."""
    if not isinstance(kind, ExceptionKind):
        raise AsOfError("expected ExceptionKind, got %s" % type(kind).__name__)
    return KIND_DESCRIPTIONS[kind]


def parse_kind(text: str) -> ExceptionKind:
    """Map text to an ExceptionKind, ignoring case and surrounding spaces.

    Raises AsOfError when the text names no known kind.
    """
    if not isinstance(text, str):
        raise AsOfError("exception kind must be a str, got %s" % type(text).__name__)
    key = text.strip()
    # str.upper() folds some non-ASCII letters into ASCII (for example the
    # ligature U+FB01 becomes "FI"), so accept only ASCII names.
    if not key.isascii():
        raise AsOfError("unknown exception kind: %r" % (text,))
    key = key.upper()
    for kind in ExceptionKind:
        if kind.value == key:
            return kind
    raise AsOfError("unknown exception kind: %r" % (text,))


def finding_severity(f: Finding) -> Severity:
    """Map a validation Finding to a queue severity.

    FAIL maps to BLOCK, WARN maps to WARN, and PASS maps to INFO.
    """
    if not isinstance(f, Finding):
        raise AsOfError("expected Finding, got %s" % type(f).__name__)
    if not isinstance(f.status, ValidationStatus):
        raise AsOfError("expected ValidationStatus, got %s" % type(f.status).__name__)
    return _FINDING_SEVERITY[f.status]
