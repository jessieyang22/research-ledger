"""Failure mode fm31: two runs overlap.

A long prior session is still running when the next run starts, so two runs
write conflicting output. The expected detection is to inspect run history and
output timestamps for overlap, then skip the later run and record the overlap.

Finding: the nearest existing module is as_of.run_timeliness. It matches
actual run FINISH times to expected slots, one to one. It has no run start or
end times, no overlap check, and it silently drops any surplus run that no slot
claims. No module in the package records run intervals or takes a run lock.
The state_manifest and checkpoints modules record hashes, not run windows, so
they cannot see an overlap either. The blocking test is therefore a strict
xfail, and the gap is reported rather than faked.

Fixtures use the SYN_ prefix.
"""

from datetime import datetime, timezone

import pytest

from as_of.core import ValidationStatus
from as_of.run_timeliness import ScheduleContract, classify_runs, late_or_missed_findings

SLOT = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
NEXT_SLOT = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
CONTRACT = ScheduleContract(name="SYN_FM31_JOB", grace_minutes=10)


def _planted_overlap_runs():
    """Two finish times for one slot: a stale prior run and the new run, 1 minute apart.

    The stale run started long before the slot and was still writing when the
    new run began, so both wrote output for the same slot.
    """
    return [
        datetime(2026, 10, 1, 9, 2, tzinfo=timezone.utc),
        datetime(2026, 10, 1, 9, 3, tzinfo=timezone.utc),
    ]


def test_planted_overlap_is_silently_matched_to_one_run():
    """Documents the live behavior: the second overlapping run is dropped without a finding."""
    rows = classify_runs(CONTRACT, [SLOT, NEXT_SLOT], _planted_overlap_runs())
    assert len(rows) == 2
    assert rows[0]["status"].name == "ON_TIME"
    assert rows[0]["actual_at"] == datetime(2026, 10, 1, 9, 2, tzinfo=timezone.utc)
    # The surplus run is claimed by nothing and produces no finding.
    assert late_or_missed_findings(rows) == []


def test_run_timeliness_has_no_run_interval_input():
    """Documents the design: classify_runs takes finish times only, no start or end times."""
    import inspect

    params = list(inspect.signature(classify_runs).parameters)
    assert params == ["contract", "expected", "actual"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm31 gap: as_of.run_timeliness matches finish times only and drops surplus runs. "
        "No module records run start and end times, detects overlapping runs, or blocks "
        "the later run. Expected control: an overlap yields a FAIL finding."
    ),
)
def test_planted_overlap_is_flagged_and_later_run_is_skipped():
    """Expected control: the planted overlap yields a FAIL finding naming the overlap."""
    rows = classify_runs(CONTRACT, [SLOT, NEXT_SLOT], _planted_overlap_runs())
    findings = late_or_missed_findings(rows)
    overlap_fails = [
        f for f in findings
        if "overlap" in f.check_id.lower() and f.status is ValidationStatus.FAIL
    ]
    assert overlap_fails, "no overlap FAIL finding raised for planted overlapping runs"
