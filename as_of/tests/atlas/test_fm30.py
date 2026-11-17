"""Failure mode fm30: session stalls on a manual permission.

A scheduled session reaches a permission prompt that nobody approves, so the run
never finishes and the task never completes. Detection is to open the scheduled
session and look for a pending prompt. Remedy is to pre-approve only a bounded
action, or to pause the task.

Fixtures use the SYN_ prefix. Times are fixed UTC datetimes. Nothing here runs
a session, reads a settings file, or touches the real home folder.

What the repo has today:
  - run_timeliness.classify_runs marks a slot MISSED when no actual run can be
    assigned to it. A session stalled on a permission prompt never records a
    finish time, so its slot is MISSED. late_or_missed_findings turns that into a
    FAIL run_missed finding, and handling_action maps it to escalate_incident.
  - readiness_record.build_readiness blocks go when any FAIL finding is passed.
    So a stalled scheduled run blocks readiness through that FAIL.
  - controls_checklist has a repo permissions control (ctl_repo_permissions_reviewed).
    A missing evidence reference for it is a FAIL. The control is a checklist
    item only. It does not see a live prompt.

What the repo does not have:
  - No module observes a pending permission prompt, or a session state such as
    "awaiting approval". Detection here is by absence of a finish, not by
    identifying the prompt. The prompt-specific check is marked xfail below.
"""

from datetime import datetime, timedelta, timezone

import pytest

from as_of import run_timeliness
from as_of.controls_checklist import CHECK_ID as CONTROLS_CHECK_ID
from as_of.controls_checklist import missing_evidence
from as_of.core import ReadinessItem, RunStatus, ValidationStatus, fmt_ts
from as_of.readiness_record import build_readiness
from as_of.run_timeliness import (
    ScheduleContract,
    classify_runs,
    handling_action,
    late_or_missed_findings,
)

SYN_CONTRACT = ScheduleContract(name="SYN_daily_scheduled_session", grace_minutes=30)

SYN_SLOT_1 = datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)
SYN_SLOT_2 = datetime(2026, 10, 6, 13, 0, tzinfo=timezone.utc)
SYN_SLOT_3 = datetime(2026, 10, 7, 13, 0, tzinfo=timezone.utc)


def _fails(findings):
    return [f for f in findings if f.status == ValidationStatus.FAIL]


def _warns(findings):
    return [f for f in findings if f.status == ValidationStatus.WARN]


def test_planted_stalled_session_is_classified_missed():
    """Planted: slot 2 is waiting on an unapproved prompt, so no run finishes for it.

    Slots 1 and 3 run on time. The stalled slot must come back MISSED, with no
    actual run assigned to it.
    """
    actual = [
        SYN_SLOT_1 + timedelta(minutes=2),
        SYN_SLOT_3 + timedelta(minutes=3),
    ]
    rows = classify_runs(SYN_CONTRACT, [SYN_SLOT_1, SYN_SLOT_2, SYN_SLOT_3], actual)
    assert [r["status"] for r in rows] == [RunStatus.ON_TIME, RunStatus.MISSED, RunStatus.ON_TIME]
    assert rows[1]["actual_at"] is None


def test_planted_stalled_session_raises_run_missed_fail():
    """The MISSED slot becomes exactly one FAIL run_missed finding on that slot."""
    actual = [
        SYN_SLOT_1 + timedelta(minutes=2),
        SYN_SLOT_3 + timedelta(minutes=3),
    ]
    rows = classify_runs(SYN_CONTRACT, [SYN_SLOT_1, SYN_SLOT_2, SYN_SLOT_3], actual)
    fails = _fails(late_or_missed_findings(rows))
    assert len(fails) == 1
    assert fails[0].check_id == "run_missed"
    assert fails[0].subject == fmt_ts(SYN_SLOT_2)


def test_planted_stalled_session_maps_to_escalation():
    """The stalled slot's handling action is escalate_incident, not a silent rerun."""
    assert handling_action(RunStatus.MISSED) == "escalate_incident"


def test_planted_stall_that_resumes_after_grace_is_late_not_on_time():
    """Planted: the prompt is approved late, so the run finishes after the grace window.

    It must be reported LATE and never ON_TIME, so the stall is not hidden.
    """
    late_finish = SYN_SLOT_2 + timedelta(minutes=45)
    rows = classify_runs(SYN_CONTRACT, [SYN_SLOT_2], [late_finish])
    assert rows[0]["status"] == RunStatus.LATE
    warns = _warns(late_or_missed_findings(rows))
    assert len(warns) == 1
    assert warns[0].check_id == "run_late"
    assert handling_action(RunStatus.LATE) == "rerun_and_log"


def test_planted_stall_blocks_readiness_even_when_all_items_pass():
    """Planted: every readiness item passes, but the stalled slot is a FAIL finding.

    The go record must be blocked by that FAIL, so a stalled run cannot be
    signed off as ready.
    """
    actual = [
        SYN_SLOT_1 + timedelta(minutes=2),
        SYN_SLOT_3 + timedelta(minutes=3),
    ]
    rows = classify_runs(SYN_CONTRACT, [SYN_SLOT_1, SYN_SLOT_2, SYN_SLOT_3], actual)
    findings = late_or_missed_findings(rows)
    items = [
        ReadinessItem(item_id="SYN_item_scheduled_run", passed=True, evidence_ref="SYN_ref_1"),
    ]
    rec = build_readiness(items, findings, open_incident_count=0)
    assert rec["go"] is False
    assert any("run_missed" in reason for reason in rec["blocking"])


def test_control_run_clean_when_every_slot_finishes():
    """Control: when every slot finishes on time, no stall is reported and the run can go."""
    actual = [
        SYN_SLOT_1 + timedelta(minutes=1),
        SYN_SLOT_2 + timedelta(minutes=1),
        SYN_SLOT_3 + timedelta(minutes=1),
    ]
    rows = classify_runs(SYN_CONTRACT, [SYN_SLOT_1, SYN_SLOT_2, SYN_SLOT_3], actual)
    findings = late_or_missed_findings(rows)
    assert findings == []
    rec = build_readiness(
        [ReadinessItem(item_id="SYN_item_scheduled_run", passed=True, evidence_ref="SYN_ref_1")],
        findings,
        open_incident_count=0,
    )
    assert rec["go"] is True


def test_planted_missing_permission_review_evidence_is_flagged():
    """Planted: the repo permissions control has no evidence recorded.

    controls_checklist must flag it FAIL, so the permission boundary cannot pass
    review by default. This is a checklist gate, not a live prompt check.
    """
    evidence = {}  # no reference recorded for any control
    findings = missing_evidence(evidence)
    perm = [f for f in findings if f.subject == "ctl_repo_permissions_reviewed"]
    assert len(perm) == 1
    assert perm[0].check_id == CONTROLS_CHECK_ID
    assert perm[0].status == ValidationStatus.FAIL


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm30 gap: no module observes a pending permission prompt or an "
        "'awaiting approval' session state. run_timeliness detects a stall only "
        "after the grace window passes, by the absence of a finish time. It "
        "cannot name the prompt or raise an alert while the session is still "
        "waiting. Pre-approval of a bounded action is not modeled either."
    ),
)
def test_pending_permission_prompt_is_reported_while_waiting(tmp_path):
    """Planted: a session is waiting on a prompt at slot time plus 5 minutes.

    A pending-prompt check should report it before the grace window expires.
    No such check exists, so this test is expected to fail.
    """
    waiting_since = SYN_SLOT_2 + timedelta(minutes=5)
    assert hasattr(run_timeliness, "pending_permission_findings"), (
        "no pending-permission check exists in run_timeliness"
    )
    findings = run_timeliness.pending_permission_findings(
        slot=SYN_SLOT_2, observed_at=waiting_since, prompt_text="SYN_approve_write"
    )
    assert _fails(findings) or _warns(findings)
