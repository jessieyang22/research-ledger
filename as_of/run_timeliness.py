"""Classify scheduled runs as on time, late or missed, and map each status to a handling action.

Each expected run is a slot (a UTC datetime). Each actual run is a UTC datetime
at which a run really finished. A run is ON_TIME when it lands inside the
slot's grace window (at or before slot + grace), LATE when it lands after that
window, and MISSED when no actual run can be assigned to the slot.

Matching is one-to-one. An actual run is claimed by at most one slot. Slots are
processed in ascending order. A slot may claim any unclaimed run that is
earlier than the next slot's time (any run, for the last slot) and not earlier
than the previous slot's time (any run, for the first slot). It takes the
candidate closest to its own time. The lower bound stops a later slot from
taking a leftover run from before an earlier slot, which would hide a missed
run as on time. The upper bound keeps a late run for slot N from being claimed
by slot N-1 when slot N-1 already has its own run.

Handling actions are advisory strings for the caller: 'none' for ON_TIME,
'rerun_and_log' for LATE and 'escalate_incident' for MISSED.

Topic: "missed and late run handling". Only synthetic data is used. This
module makes no network calls and has no trading or order logic.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from as_of.core import (
    AsOfError,
    Finding,
    RunStatus,
    ValidationStatus,
    ensure_utc,
    fmt_ts,
    require,
)


@dataclass(frozen=True)
class ScheduleContract:
    """Timeliness terms for one scheduled run.

    This type is local to run_timeliness. It is not defined in as_of.core.

    name: label for the caller's own records. It is not written into findings,
        because late_or_missed_findings receives only the rows.
    grace_minutes: how many minutes after a slot a run may finish and still be ON_TIME.
    """

    name: str
    grace_minutes: int


_HANDLING: Dict[RunStatus, str] = {
    RunStatus.ON_TIME: "none",
    RunStatus.LATE: "rerun_and_log",
    RunStatus.MISSED: "escalate_incident",
}


def classify_runs(
    contract: ScheduleContract,
    expected: Sequence[datetime],
    actual: Sequence[datetime],
) -> List[Dict[str, Any]]:
    """Return one row per expected slot, in ascending slot order.

    Each row has keys: 'slot' (UTC datetime), 'status' (RunStatus) and
    'actual_at' (the matched UTC run time, or None when MISSED).
    """
    require(
        isinstance(contract.grace_minutes, int) and not isinstance(contract.grace_minutes, bool),
        "grace_minutes must be an int",
    )
    require(contract.grace_minutes >= 0, "grace_minutes must not be negative")
    require(expected is not None and actual is not None, "expected and actual must be sequences")
    try:
        grace = timedelta(minutes=contract.grace_minutes)
    except OverflowError as exc:
        raise AsOfError("grace_minutes is out of range: %s" % exc)

    slots = sorted(ensure_utc(s) for s in expected)
    runs = [ensure_utc(a) for a in actual]
    claimed = set()  # indices into runs that are already matched to a slot

    rows: List[Dict[str, Any]] = []
    for i, slot in enumerate(slots):
        upper: Optional[datetime] = slots[i + 1] if i + 1 < len(slots) else None
        lower: Optional[datetime] = slots[i - 1] if i > 0 else None

        best_idx: Optional[int] = None
        best_gap: Optional[timedelta] = None
        for j, run_at in enumerate(runs):
            if j in claimed:
                continue
            if upper is not None and run_at >= upper:
                continue
            if lower is not None and run_at < lower:
                continue
            gap = abs(run_at - slot)
            if best_gap is None or gap < best_gap:
                best_idx = j
                best_gap = gap

        if best_idx is None:
            rows.append({"slot": slot, "status": RunStatus.MISSED, "actual_at": None})
            continue

        claimed.add(best_idx)
        run_at = runs[best_idx]
        try:
            window_end = slot + grace
        except OverflowError as exc:
            raise AsOfError("slot plus grace window is out of range: %s" % exc)
        status = RunStatus.ON_TIME if run_at <= window_end else RunStatus.LATE
        rows.append({"slot": slot, "status": status, "actual_at": run_at})

    return rows


def late_or_missed_findings(rows: Sequence[Dict[str, Any]]) -> List[Finding]:
    """Turn LATE rows into WARN findings and MISSED rows into FAIL findings.

    ON_TIME rows produce no finding.
    """
    findings: List[Finding] = []
    for row in rows:
        status = row["status"]
        if not isinstance(status, RunStatus):
            raise AsOfError("row status must be a RunStatus, got %r" % (status,))
        slot_text = fmt_ts(row["slot"])
        if status is RunStatus.LATE:
            actual_text = fmt_ts(row["actual_at"])
            findings.append(
                Finding(
                    check_id="run_late",
                    status=ValidationStatus.WARN,
                    message="run at %s finished after its grace window for slot %s"
                    % (actual_text, slot_text),
                    subject=slot_text,
                )
            )
        elif status is RunStatus.MISSED:
            findings.append(
                Finding(
                    check_id="run_missed",
                    status=ValidationStatus.FAIL,
                    message="no run found for expected slot %s" % slot_text,
                    subject=slot_text,
                )
            )
    return findings


def handling_action(status: RunStatus) -> str:
    """Return 'none', 'rerun_and_log' or 'escalate_incident' for a RunStatus."""
    if not isinstance(status, RunStatus) or status not in _HANDLING:
        raise AsOfError("unknown run status: %r" % (status,))
    return _HANDLING[status]
