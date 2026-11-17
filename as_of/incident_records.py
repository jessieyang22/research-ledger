"""Incident records: timeline, severity and root cause.

An incident record tracks one operational problem from the moment it is
opened until it is closed. It keeps a severity, a time-sorted timeline of
events and, once closed, a root cause. The helpers here are pure: each call
returns a new frozen IncidentRecord and never mutates its input.

Rules enforced by this module:

* A closed incident needs a non-empty root cause and at least one timeline
  event. close_incident raises AsOfError otherwise.
* Timeline entries are (UTC datetime, text) pairs kept sorted by time.
* validate_incident reports findings. A BLOCK-severity incident with an empty
  timeline is a FAIL, because a blocking problem with no recorded history
  cannot be reviewed.


All data handled here is synthetic. Fixture ids start with SYN_.
"""

import dataclasses
from datetime import date, datetime
from typing import List, Optional

from as_of.core import (
    AsOfError,
    Finding,
    IncidentRecord,
    Severity,
    ValidationStatus,
    ensure_utc,
)


STATUS_OPEN: str = "open"
STATUS_CLOSED: str = "closed"

CHECK_TIMELINE: str = "incident.timeline_present"
CHECK_SORTED: str = "incident.timeline_sorted"
CHECK_ROOT_CAUSE: str = "incident.root_cause"
CHECK_STATUS: str = "incident.status"


def open_incident(
    incident_id: str,
    summary: str,
    severity: Severity,
    opened_on: date,
) -> IncidentRecord:
    """Return a new open incident with an empty timeline and no root cause.

    Raises AsOfError if incident_id or summary is empty, if severity is not a
    Severity member, or if opened_on is not a date.
    """
    if not isinstance(incident_id, str) or not incident_id.strip():
        raise AsOfError("incident_id must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise AsOfError("summary must be a non-empty string")
    if not isinstance(severity, Severity):
        raise AsOfError("severity must be a Severity member")
    if not isinstance(opened_on, date) or isinstance(opened_on, datetime):
        raise AsOfError("opened_on must be a date")
    return IncidentRecord(
        incident_id=incident_id,
        summary=summary,
        severity=severity,
        opened_on=opened_on,
        status=STATUS_OPEN,
        timeline=(),
        root_cause=None,
    )


def add_timeline_event(rec: IncidentRecord, at: datetime, text: str) -> IncidentRecord:
    """Return a new record with one timeline event added, kept sorted by time.

    The timestamp is converted to aware UTC. Naive datetimes raise AsOfError.
    Events with equal timestamps keep the order in which they were added.
    """
    if not isinstance(text, str) or not text.strip():
        raise AsOfError("timeline text must be a non-empty string")
    at_utc = ensure_utc(at)
    combined = list(rec.timeline) + [(at_utc, text)]
    combined.sort(key=lambda event: event[0])
    return dataclasses.replace(rec, timeline=tuple(combined))


def close_incident(rec: IncidentRecord, closed_on: date, root_cause: str) -> IncidentRecord:
    """Return a new record with status 'closed' and the given root cause.

    Raises AsOfError when:
    * root_cause is empty or only whitespace,
    * the timeline is empty,
    * closed_on is not a date, or it falls before the opened_on date.

    IncidentRecord has no closed_on field, so closed_on is checked but not
    stored. The caller keeps the closing date elsewhere if it is needed.
    """
    if not isinstance(root_cause, str) or not root_cause.strip():
        raise AsOfError("root_cause must be a non-empty string to close an incident")
    if not rec.timeline:
        raise AsOfError("cannot close an incident with an empty timeline")
    if not isinstance(closed_on, date) or isinstance(closed_on, datetime):
        raise AsOfError("closed_on must be a date")
    if closed_on < rec.opened_on:
        raise AsOfError("closed_on %s is before opened_on %s" % (closed_on, rec.opened_on))
    return dataclasses.replace(rec, status=STATUS_CLOSED, root_cause=root_cause)


def _finding(check_id: str, status: ValidationStatus, message: str, subject: str) -> Finding:
    return Finding(check_id=check_id, status=status, message=message, subject=subject)


def validate_incident(rec: IncidentRecord) -> List[Finding]:
    """Return one Finding per check for an incident record.

    Checks:
    * timeline_present: a BLOCK incident with no timeline is FAIL. Any other
      incident with no timeline is WARN. A severity that is not a Severity
      member is treated as BLOCK (fail closed).
    * timeline_sorted: the timeline must be in non-decreasing time order.
    * root_cause: a closed incident must have a non-empty root cause.
    * status: status must be 'open' or 'closed'. A closed incident must also
      have a timeline.
    """
    subject = rec.incident_id
    findings: List[Finding] = []

    if not rec.timeline:
        # Fail closed: a severity that is not a Severity member (for example the
        # string "block") cannot be shown to be non-blocking, so it is treated as BLOCK.
        blocking = not isinstance(rec.severity, Severity) or rec.severity == Severity.BLOCK
        if blocking:
            presence = _finding(
                CHECK_TIMELINE, ValidationStatus.FAIL,
                "BLOCK incident has an empty timeline (or severity is not a Severity member)",
                subject,
            )
        else:
            presence = _finding(
                CHECK_TIMELINE, ValidationStatus.WARN,
                "incident has an empty timeline", subject,
            )
    else:
        presence = _finding(
            CHECK_TIMELINE, ValidationStatus.PASS,
            "timeline has %d event(s)" % len(rec.timeline), subject,
        )
    findings.append(presence)

    times = [event[0] for event in rec.timeline]
    # Records built outside this module may hold naive or non-datetime stamps.
    # Those must yield a FAIL finding, not a TypeError from the comparison.
    typed = all(isinstance(t, datetime) and t.utcoffset() is not None for t in times)
    in_order = typed and all(earlier <= later for earlier, later in zip(times, times[1:]))
    if in_order:
        findings.append(_finding(CHECK_SORTED, ValidationStatus.PASS, "timeline is sorted", subject))
    else:
        findings.append(_finding(
            CHECK_SORTED, ValidationStatus.FAIL,
            "timeline is not sorted by time or has untyped or naive timestamps", subject,
        ))

    root_cause_ok = isinstance(rec.root_cause, str) and bool(rec.root_cause.strip())
    if rec.status == STATUS_CLOSED and not root_cause_ok:
        findings.append(_finding(
            CHECK_ROOT_CAUSE, ValidationStatus.FAIL,
            "closed incident has no root cause", subject,
        ))
    else:
        findings.append(_finding(
            CHECK_ROOT_CAUSE, ValidationStatus.PASS, "root cause check passed", subject,
        ))

    if rec.status not in (STATUS_OPEN, STATUS_CLOSED):
        findings.append(_finding(
            CHECK_STATUS, ValidationStatus.FAIL,
            "unknown status %r" % (rec.status,), subject,
        ))
    elif rec.status == STATUS_CLOSED and not rec.timeline:
        findings.append(_finding(
            CHECK_STATUS, ValidationStatus.FAIL,
            "closed incident has an empty timeline", subject,
        ))
    else:
        findings.append(_finding(
            CHECK_STATUS, ValidationStatus.PASS, "status %r is valid" % rec.status, subject,
        ))

    return findings
