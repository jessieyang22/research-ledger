"""Lab 10: saved scheduled-task contract and transcript-free handoff (synthetic data only).

What this lab does, in order:

1. Makes sure the synthetic files exist, writing each one only if it is
   missing: the saved task contract (labs/data/lab10_scheduled_task_contract.json),
   the ten-item handoff checklist (labs/data/lab10_handoff_checklist.json), and
   a sample folder with two small synthetic input files. It reads the files
   from disk on every run, so an edit on disk is what gets checked.
2. Runs the Laboratory 10 verifier (check_contract) on the saved contract, the
   sample folder and the checklist. The contract must keep the schedule Manual
   and paused, allow writes only to the queue-only output path, name only the
   verifier and queue write as tools, use the two outcome labels
   REVIEW_REQUIRED and FAILED, and name the three failure conditions (late,
   overlapping, partial input). The verifier checks the schedule against exact
   run datetimes (weekdays at 16:05, no weekend runs), checks that the required
   inputs are present, and splits the checklist into automated items and
   manual items. Automated items must be checked. Manual items must stay open
   and must point at a manual gate, so the lab cannot tick a desktop step it
   did not perform. It also builds and validates a handoff record with
   as_of.handoff, and runs a negative control that a broken handoff fails.
3. Classifies a synthetic run history with as_of.run_timeliness and routes
   each slot. The route is computed from the history: late and missed
   statuses come from classify_runs, overlap comes from run start and finish
   times, and partial input comes from the folder check. A grace-boundary probe
   and an overlap probe run the same way. The routing rule is a lab-side model
   of what the task should do. It is not the desktop routine's runtime behaviour.
4. Planted failures, in memory or in a disposable folder under results/. Each
   planted copy must make the specific check it targets fail. A copy with a
   failure elsewhere does not count as a detection. The unmodified files must
   pass. The plants are: a
   broader allowed-writes path (A), an unchecked handoff item (F), plus a
   manual-item self-claim (B), a moved due time (C), a dropped weekend rule
   (D), an unpaused task (E), a missing input (G) and a widened tool list (H).
5. Records the desktop and second-analyst steps as PENDING_MANUAL. These are the
   Manual routine creation, the Run now permission review, the run history
   check (actual time, folder, completion state, output, stall), the proof of
   REVIEW_REQUIRED and FAILED on real runs, and the second analyst's transcript-
   free rerun with hash comparison. This lab makes no desktop call and cannot
   perform them. The desktop routine interface was not tested for this
   edition, so these steps have no verified method.
6. Writes as_of/labs/results/lab10.json with a PASS or FAIL for each automated
   check, the planted results, the routing results, the handoff validation and
   the manual gates.

Limits, also stated in the JSON:
- A PASS shows that the saved files and the synthetic run history agree with
  the rules above. It does not show that a local schedule fired on any machine.
  Only Run now and the desktop task history can show that, and those steps are
  PENDING_MANUAL.
- The ten-item checklist is a local list written for this lab.
- The synthetic run history is in UTC. The contract schedule is naive local
  time, and the lab treats it as UTC only for the history probe.

Only as_of.core is imported statically. Every other piece is loaded with
core.component inside a function body. No network, no subprocess, no orders,
no git, no settings files.
"""

import copy
import hashlib
import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from as_of.core import AsOfError, ValidationStatus, component  # noqa: E402

LAB_DIR: str = os.path.dirname(os.path.abspath(__file__))
DATA_DIR: str = os.path.join(LAB_DIR, "data")
SAMPLE_REL: str = "as_of/labs/data/lab10_sample_folder"
SAMPLE_DIR: str = os.path.join(DATA_DIR, "lab10_sample_folder")
CONTRACT_PATH: str = os.path.join(DATA_DIR, "lab10_scheduled_task_contract.json")
CHECKLIST_PATH: str = os.path.join(DATA_DIR, "lab10_handoff_checklist.json")
QUEUE_REL: str = "as_of/labs/results/lab10_queue"
RESULTS_PATH: str = os.path.join(LAB_DIR, "results", "lab10.json")

REQUIRED_INPUTS: List[str] = ["synthetic_positions.csv", "synthetic_prices.csv"]
ALLOWED_TOOLS: List[str] = ["verifier", "queue_write"]
OUTCOME_LABELS: Dict[str, str] = {"success": "REVIEW_REQUIRED", "failure": "FAILED"}
FAILURE_CONDITIONS: List[str] = ["late", "overlapping", "partial_input"]
# Phrases the instructions must contain. Each one names a rule the verifier relies on.
INSTRUCTION_PHRASES: List[str] = [
    "write REVIEW_REQUIRED",
    "write FAILED",
    "is late",
    "overlaps an earlier run",
    "any required input is missing",
]
CHECKLIST_SIZE: int = 10

SCHEDULE: Dict[str, Any] = {
    "name": "lab10_daily_close",
    "cadence": "daily",
    "due_time": "16:05",
    "grace_minutes": 10,
    "business_days_only": True,
}
GRACE_MINUTES: int = SCHEDULE["grace_minutes"]

WINDOW_START: date = date(2026, 10, 19)
WINDOW_END: date = date(2026, 10, 23)
WEEKEND_START: date = date(2026, 10, 24)
WEEKEND_END: date = date(2026, 10, 25)
EXPECTED_WINDOW_RUNS: List[datetime] = [datetime(2026, 10, d, 16, 5) for d in (19, 20, 21, 22, 23)]

FIXED_CONTRACT: Dict[str, Any] = {
    "task_name": "lab10 synthetic close review",
    "mode": "Manual",
    "paused": True,
    "folder": SAMPLE_REL,
    "schedule": SCHEDULE,
    "required_inputs": REQUIRED_INPUTS,
    "allowed_tools": ALLOWED_TOOLS,
    "allowed_writes": [QUEUE_REL],
    "outcome_labels": OUTCOME_LABELS,
    "failure_conditions": FAILURE_CONDITIONS,
    "instructions": (
        "Run the lab10 verifier on the folder named above. If every required input "
        "is present and the run is on time and does not overlap an earlier run, "
        "write REVIEW_REQUIRED to the queue file. If the run is late, overlaps an "
        "earlier run, or any required input is missing, write FAILED to the queue "
        "file. Write nothing else. Do not use the network. Do not change settings "
        "or schedules."
    ),
}

# evidence "automated": the verifier can check it from disk.
# evidence "manual": only the desktop or second-analyst step can close it, so it
# must stay checked False and name its gate until that step is recorded.
FIXED_CHECKLIST: List[Dict[str, Any]] = [
    {"item_id": "HC01", "text": "Task name and instructions copied from the saved contract", "checked": True, "evidence": "automated", "gate_id": None},
    {"item_id": "HC02", "text": "Schedule left Manual and the task paused until the proof passes", "checked": True, "evidence": "automated", "gate_id": None},
    {"item_id": "HC03", "text": "Sample folder selected and matches the contract folder", "checked": True, "evidence": "automated", "gate_id": None},
    {"item_id": "HC04", "text": "Allowed writes limited to the queue-only output", "checked": True, "evidence": "automated", "gate_id": None},
    {"item_id": "HC05", "text": "Every permission request inspected and decided", "checked": False, "evidence": "manual", "gate_id": "desk.run_now_permissions"},
    {"item_id": "HC06", "text": "Run now and run history recorded (time, folder, completion, output, stall)", "checked": False, "evidence": "manual", "gate_id": "desk.run_history"},
    {"item_id": "HC07", "text": "REVIEW_REQUIRED confirmed on a clean run", "checked": False, "evidence": "manual", "gate_id": "desk.clean_run_review_required"},
    {"item_id": "HC08", "text": "FAILED confirmed for late, overlapping and partial-input runs", "checked": False, "evidence": "manual", "gate_id": "desk.failure_runs_failed"},
    {"item_id": "HC09", "text": "Second analyst reran the verifier from the folder and checklist only", "checked": False, "evidence": "manual", "gate_id": "handoff.second_analyst_rerun"},
    {"item_id": "HC10", "text": "Packet hashes compared and discrepancies recorded", "checked": False, "evidence": "manual", "gate_id": "handoff.second_analyst_rerun"},
]

SAMPLE_FILES: Dict[str, str] = {
    "synthetic_positions.csv": "ticker,shares\nSYN_A,100\nSYN_B,-50\n",
    "synthetic_prices.csv": "ticker,close\nSYN_A,10.00\nSYN_B,20.00\n",
}

MANUAL_GATES: List[Dict[str, str]] = [
    {"gate_id": "desk.routine_created_manual",
     "detail": "Create a local routine in the desktop app, paste the task name and instructions, choose Manual, select the sample folder, save. Not done by this lab."},
    {"gate_id": "desk.run_now_permissions",
     "detail": "Run now, inspect every permission request, allow only the verifier and the queue-only output. Not done by this lab."},
    {"gate_id": "desk.run_history",
     "detail": "Check run history for actual time, folder, completion state, output and any stall. Not done by this lab."},
    {"gate_id": "desk.clean_run_review_required",
     "detail": "Confirm a real clean run writes REVIEW_REQUIRED. Not done by this lab."},
    {"gate_id": "desk.failure_runs_failed",
     "detail": "Confirm real late, overlapping and partial-input runs write FAILED. Not done by this lab."},
    {"gate_id": "desk.left_paused_unless_proof",
     "detail": "Leave the task paused unless the proof succeeds. Depends on the proof results above."},
    {"gate_id": "handoff.second_analyst_rerun",
     "detail": "Second analyst gets the folder and checklist, not the transcript, reruns the full verifier, rebuilds the packet, compares hashes and records discrepancies. Not done by this lab."},
]
MANUAL_GATE_IDS: List[str] = [g["gate_id"] for g in MANUAL_GATES]


def _check(check_id: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {"check_id": check_id, "passed": bool(passed), "detail": detail}


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()


def _ensure_data() -> None:
    """Write each synthetic fixture only if it is missing. Never overwrites."""
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    for name, text in SAMPLE_FILES.items():
        path = os.path.join(SAMPLE_DIR, name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
    if not os.path.exists(CONTRACT_PATH):
        with open(CONTRACT_PATH, "w", encoding="utf-8") as handle:
            json.dump(FIXED_CONTRACT, handle, indent=2, sort_keys=True)
            handle.write("\n")
    if not os.path.exists(CHECKLIST_PATH):
        with open(CHECKLIST_PATH, "w", encoding="utf-8") as handle:
            json.dump(FIXED_CHECKLIST, handle, indent=2)
            handle.write("\n")


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def missing_inputs(folder: str, required: List[str]) -> List[str]:
    return [name for name in required if not os.path.isfile(os.path.join(folder, name))]


def check_checklist(checklist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Checklist rules: ten items, unique ids, automated items checked, manual items open."""
    checks: List[Dict[str, Any]] = []
    ids = [item.get("item_id") for item in checklist]
    checks.append(_check("c10.checklist.ten_items",
                         len(checklist) == CHECKLIST_SIZE,
                         "items=%d" % len(checklist)))
    checks.append(_check("c10.checklist.unique_ids",
                         len(set(ids)) == len(ids),
                         "unique ids: %d of %d" % (len(set(ids)), len(ids))))

    automated = [i for i in checklist if i.get("evidence") == "automated"]
    manual = [i for i in checklist if i.get("evidence") == "manual"]
    unclassified = [i.get("item_id") for i in checklist if i.get("evidence") not in ("automated", "manual")]
    unchecked_auto = [i.get("item_id") for i in automated if i.get("checked") is not True]
    checks.append(_check("c10.checklist.automated_items_checked",
                         bool(automated) and not unchecked_auto and not unclassified,
                         "unchecked automated: %r; unclassified: %r" % (unchecked_auto, unclassified)))

    self_checked = [i.get("item_id") for i in manual if i.get("checked") is not False]
    bad_gate = [i.get("item_id") for i in manual if i.get("gate_id") not in MANUAL_GATE_IDS]
    checks.append(_check("c10.checklist.manual_items_open",
                         bool(manual) and not self_checked and not bad_gate
                         and len(automated) + len(manual) == CHECKLIST_SIZE,
                         "manual items claimed checked: %r; manual items without a known gate: %r"
                         % (self_checked, bad_gate)))
    return checks


def check_contract(contract: Dict[str, Any], checklist: List[Dict[str, Any]], folder: str) -> List[Dict[str, Any]]:
    """Laboratory 10 verifier: returns one check dict per rule. Reads nothing from disk."""
    schedule_mod = component("schedule_contract")
    handoff_mod = component("handoff")
    state_mod = component("state_manifest")

    checks: List[Dict[str, Any]] = []
    checks.append(_check("c10.contract.mode_manual",
                         contract.get("mode") == "Manual",
                         "mode=%r" % (contract.get("mode"),)))
    checks.append(_check("c10.contract.paused_until_proof",
                         contract.get("paused") is True,
                         "paused=%r" % (contract.get("paused"),)))

    writes = contract.get("allowed_writes")
    checks.append(_check("c10.contract.allowed_writes_queue_only",
                         writes == [QUEUE_REL],
                         "allowed_writes=%r" % (writes,)))

    write_ok = isinstance(writes, list) and len(writes) > 0 and all(
        isinstance(p, str) and p.startswith("as_of/") and not os.path.isabs(p)
        and ".." not in p.split("/") for p in writes)
    checks.append(_check("c10.contract.writes_inside_as_of",
                         write_ok,
                         "every allowed write is a relative path under as_of/ with no '..'"))

    tools = contract.get("allowed_tools")
    checks.append(_check("c10.contract.tools_limited",
                         isinstance(tools, list) and len(tools) > 0 and set(tools) <= set(ALLOWED_TOOLS),
                         "allowed_tools=%r" % (tools,)))

    checks.append(_check("c10.contract.outcome_labels",
                         contract.get("outcome_labels") == OUTCOME_LABELS,
                         "outcome_labels=%r" % (contract.get("outcome_labels"),)))

    conds = contract.get("failure_conditions")
    checks.append(_check("c10.contract.failure_conditions",
                         isinstance(conds, list) and set(conds) == set(FAILURE_CONDITIONS),
                         "failure_conditions=%r" % (conds,)))

    text = contract.get("instructions") or ""
    missing_phrases = [p for p in INSTRUCTION_PHRASES if p not in text]
    checks.append(_check("c10.contract.instructions_name_rules",
                         not missing_phrases,
                         "missing phrases: %r" % (missing_phrases,)))

    checks.append(_check("c10.contract.folder_is_sample",
                         contract.get("folder") == SAMPLE_REL,
                         "folder=%r" % (contract.get("folder"),)))

    sched = contract.get("schedule") or {}
    checks.append(_check("c10.contract.schedule_matches_lab_expectation",
                         sched == SCHEDULE,
                         "schedule=%r" % (sched,)))

    try:
        sc = schedule_mod.ScheduleContract(
            name=sched.get("name"), cadence=sched.get("cadence"), due_time=sched.get("due_time"),
            grace_minutes=sched.get("grace_minutes"),
            business_days_only=sched.get("business_days_only"))
        runs = schedule_mod.expected_runs(sc, WINDOW_START, WINDOW_END)
        weekend_runs = schedule_mod.expected_runs(sc, WEEKEND_START, WEEKEND_END)
        ok = runs == EXPECTED_WINDOW_RUNS and weekend_runs == []
        detail = "window runs=%r; weekend runs=%r" % ([r.isoformat() for r in runs],
                                                        [r.isoformat() for r in weekend_runs])
    except (AsOfError, TypeError, ValueError) as exc:
        ok = False
        detail = "schedule rejected: %s" % (exc,)
    checks.append(_check("c10.contract.schedule_expands", ok, detail))

    missing = missing_inputs(folder, contract.get("required_inputs") or [])
    checks.append(_check("c10.inputs.required_present",
                         not missing and bool(contract.get("required_inputs")),
                         "missing inputs: %r" % (missing,)))

    checks.extend(check_checklist(checklist))

    state = state_mod.StateManifest()
    state.record_step("lab10_contract_and_checklist",
                      {"contract_json": _json_hash(contract)},
                      {"checklist_json": _json_hash(checklist)},
                      "lab10-v1")
    handoff = handoff_mod.build_handoff(
        title="lab10 handoff",
        state=state,
        open_items=["Desktop routine not created or run in this lab (PENDING_MANUAL)"],
        next_steps=["Run the desktop proof with the Manual routine and record run history",
                    "Give the second analyst the folder and checklist only"],
        owner_role="analyst")
    findings = handoff_mod.validate_handoff(handoff)
    bad = [f.check_id for f in findings if f.status is ValidationStatus.FAIL]
    checks.append(_check("c10.handoff.validates", not bad and len(findings) >= 5,
                         "findings=%d; failing: %r" % (len(findings), bad)))

    broken = dict(handoff)
    broken["owner_role"] = ""
    neg = handoff_mod.validate_handoff(broken)
    neg_fail = [f.check_id for f in neg if f.status is ValidationStatus.FAIL]
    checks.append(_check("c10.handoff.negative_control_fails", "handoff.owner_role" in neg_fail,
                         "broken owner_role flagged: %r" % (neg_fail,)))

    return checks


def _json_hash(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def route_run(status_name: str, overlapping: bool, partial_input: bool) -> str:
    """Lab-side model of the task outcome rule. Not the desktop routine's runtime."""
    if overlapping or partial_input or status_name != "ON_TIME":
        return OUTCOME_LABELS["failure"]
    return OUTCOME_LABELS["success"]


def run_overlaps(runs: Sequence[Tuple[datetime, datetime]]) -> Dict[datetime, bool]:
    """Map each actual run's finish time to True when it started before the previous run had finished.

    runs is a sequence of (start, finish) pairs, aware UTC datetimes. Runs are
    ordered by finish time before the comparison.
    """
    flags: Dict[datetime, bool] = {}
    prev_finish: Optional[datetime] = None
    for start, finish in sorted(runs, key=lambda r: r[1]):
        flags[finish] = prev_finish is not None and start < prev_finish
        prev_finish = finish
    return flags


def timeliness_scenario() -> Dict[str, Any]:
    """Synthetic run history: on time, late, missed, on time, on time. Routes are computed from it."""
    sched = component("schedule_contract")
    tl = component("run_timeliness")
    sc = sched.ScheduleContract(name=SCHEDULE["name"], cadence=SCHEDULE["cadence"],
                                due_time=SCHEDULE["due_time"], grace_minutes=GRACE_MINUTES,
                                business_days_only=SCHEDULE["business_days_only"])
    slots = [s.replace(tzinfo=timezone.utc)
             for s in sched.expected_runs(sc, WINDOW_START, WINDOW_END)]
    offsets = [3, 35, None, 1, 2]     # minutes after slot finish; None means no run at all
    durations = [4, 6, None, 3, 2]    # minutes each run took
    runs: List[Tuple[datetime, datetime]] = []
    for slot, off, dur in zip(slots, offsets, durations):
        if off is not None:
            finish = slot + timedelta(minutes=off)
            runs.append((finish - timedelta(minutes=dur), finish))
    rc = tl.ScheduleContract(SCHEDULE["name"], GRACE_MINUTES)
    rows = tl.classify_runs(rc, slots, [finish for _, finish in runs])
    overlap = run_overlaps(runs)
    partial = bool(missing_inputs(SAMPLE_DIR, REQUIRED_INPUTS))
    statuses = [row["status"].name for row in rows]
    routes = [route_run(row["status"].name, overlap.get(row["actual_at"], False), partial) for row in rows]
    return {"slots": [s.isoformat() for s in slots], "statuses": statuses,
            "overlapping": [overlap.get(row["actual_at"], False) for row in rows],
            "partial_input": partial, "routes": routes}


def overlap_probe() -> Dict[str, Any]:
    """Two slots; the second run starts before the first run has finished."""
    tl = component("run_timeliness")
    slot1 = datetime(2026, 10, 19, 16, 5, tzinfo=timezone.utc)
    slot2 = datetime(2026, 10, 20, 16, 5, tzinfo=timezone.utc)
    runs = [(slot1 - timedelta(minutes=1), slot1 + timedelta(minutes=3)),
            (slot1 + timedelta(minutes=2), slot2 + timedelta(minutes=1))]
    rc = tl.ScheduleContract("lab10_overlap_probe", GRACE_MINUTES)
    rows = tl.classify_runs(rc, [slot1, slot2], [finish for _, finish in runs])
    flags = run_overlaps(runs)
    flagged = [flags.get(row["actual_at"], False) for row in rows]
    routes = [route_run(row["status"].name, flagged[i], False) for i, row in enumerate(rows)]
    return {"statuses": [row["status"].name for row in rows], "overlapping": flagged, "routes": routes}


def grace_boundary_probe() -> Dict[str, str]:
    """A run finishing exactly at slot + grace is ON_TIME; one minute later is LATE."""
    tl = component("run_timeliness")
    slot = datetime(2026, 10, 19, 16, 5, tzinfo=timezone.utc)
    rc = tl.ScheduleContract("lab10_boundary_probe", GRACE_MINUTES)
    at_edge = tl.classify_runs(rc, [slot], [slot + timedelta(minutes=GRACE_MINUTES)])[0]["status"].name
    past_edge = tl.classify_runs(rc, [slot], [slot + timedelta(minutes=GRACE_MINUTES + 1)])[0]["status"].name
    return {"at_edge": at_edge, "past_edge": past_edge}


def routing_checks(scenario: Dict[str, Any], overlap: Dict[str, Any], boundary: Dict[str, str]) -> List[Dict[str, Any]]:
    expected_statuses = ["ON_TIME", "LATE", "MISSED", "ON_TIME", "ON_TIME"]
    expected_routes = [OUTCOME_LABELS["success"], OUTCOME_LABELS["failure"], OUTCOME_LABELS["failure"],
                       OUTCOME_LABELS["success"], OUTCOME_LABELS["success"]]
    checks = [
        _check("c10.timeliness.scenario_statuses", scenario["statuses"] == expected_statuses,
               "statuses=%r" % (scenario["statuses"],)),
        _check("c10.timeliness.grace_boundary_inclusive",
               boundary["at_edge"] == "ON_TIME" and boundary["past_edge"] == "LATE",
               "at edge=%s, one minute past=%s" % (boundary["at_edge"], boundary["past_edge"])),
        _check("c10.route.scenario_routes_from_history", scenario["routes"] == expected_routes,
               "routes=%r" % (scenario["routes"],)),
        _check("c10.route.scenario_has_no_overlap_or_partial",
               not any(scenario["overlapping"]) and not scenario["partial_input"],
               "overlapping=%r partial_input=%r" % (scenario["overlapping"], scenario["partial_input"])),
        _check("c10.route.overlap_probe_failed",
               overlap["overlapping"] == [False, True]
               and overlap["routes"] == [OUTCOME_LABELS["success"], OUTCOME_LABELS["failure"]],
               "overlapping=%r routes=%r" % (overlap["overlapping"], overlap["routes"])),
    ]
    absent = missing_inputs(SAMPLE_DIR, REQUIRED_INPUTS + ["synthetic_absent_input.csv"])
    partial_route = route_run("ON_TIME", False, bool(absent))
    checks.append(_check("c10.route.partial_input_failed",
                         bool(absent) and partial_route == OUTCOME_LABELS["failure"],
                         "absent inputs=%r route=%s" % (absent, partial_route)))
    checks.append(_check("c10.route.clean_on_time_review_required",
                         route_run("ON_TIME", False, False) == OUTCOME_LABELS["success"], "clean on-time run"))
    checks.append(_check("c10.route.late_failed",
                         route_run("LATE", False, False) == OUTCOME_LABELS["failure"], "late run"))
    checks.append(_check("c10.route.missed_failed",
                         route_run("MISSED", False, False) == OUTCOME_LABELS["failure"], "missed run"))
    return checks


def planted_checks(contract: Dict[str, Any], checklist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each planted copy is in memory only. Its named check must fail; a failure elsewhere does not count."""
    cases: List[Tuple[str, str, Dict[str, Any], List[Dict[str, Any]], List[str]]] = []

    widened = copy.deepcopy(contract)
    widened["allowed_writes"] = ["as_of"]
    cases.append(("A_widened_allowed_writes",
                  "allowed_writes widened to the whole as_of folder in a disposable copy",
                  widened, checklist,
                  ["c10.contract.allowed_writes_queue_only", "c10.contract.writes_inside_as_of"]))

    self_claimed = copy.deepcopy(checklist)
    for item in self_claimed:
        if item["item_id"] == "HC07":
            item["checked"] = True
    cases.append(("B_manual_item_self_claimed",
                  "manual item HC07 marked checked without a recorded desktop run",
                  contract, self_claimed,
                  ["c10.checklist.manual_items_open"]))

    moved = copy.deepcopy(contract)
    moved["schedule"]["due_time"] = "16:15"
    cases.append(("C_due_time_moved",
                  "due time moved from 16:05 to 16:15 in a disposable copy",
                  moved, checklist,
                  ["c10.contract.schedule_matches_lab_expectation", "c10.contract.schedule_expands"]))

    weekend = copy.deepcopy(contract)
    weekend["schedule"]["business_days_only"] = False
    cases.append(("D_weekend_rule_dropped",
                  "business_days_only set to False in a disposable copy",
                  weekend, checklist,
                  ["c10.contract.schedule_matches_lab_expectation", "c10.contract.schedule_expands"]))

    unpaused = copy.deepcopy(contract)
    unpaused["paused"] = False
    cases.append(("E_task_unpaused",
                  "paused set to False in a disposable copy",
                  unpaused, checklist,
                  ["c10.contract.paused_until_proof"]))

    unchecked_auto = copy.deepcopy(checklist)
    for item in unchecked_auto:
        if item["item_id"] == "HC02":
            item["checked"] = False
    cases.append(("F_automated_item_unchecked",
                  "automated item HC02 unchecked in a disposable copy",
                  contract, unchecked_auto,
                  ["c10.checklist.automated_items_checked"]))

    results = [_planted_result(pid, desc, c_copy, cl_copy, expected, SAMPLE_DIR)
               for pid, desc, c_copy, cl_copy, expected in cases]

    incomplete_dir = _make_incomplete_folder()
    results.append(_planted_result(
        "G_required_input_missing",
        "disposable copy of the sample folder with synthetic_prices.csv removed",
        contract, checklist, ["c10.inputs.required_present"], incomplete_dir))

    wider_tools = copy.deepcopy(contract)
    wider_tools["allowed_tools"] = ALLOWED_TOOLS + ["network_fetch"]
    results.append(_planted_result(
        "H_widened_allowed_tools",
        "allowed_tools widened with a network_fetch tool in a disposable copy",
        wider_tools, checklist, ["c10.contract.tools_limited"], SAMPLE_DIR))
    return results


def _planted_result(planted_id: str, description: str, c_copy: Dict[str, Any],
                    cl_copy: List[Dict[str, Any]], expected: List[str], folder: str) -> Dict[str, Any]:
    fails = [c["check_id"] for c in check_contract(c_copy, cl_copy, folder) if not c["passed"]]
    return {
        "planted_id": planted_id,
        "description": description,
        "expected_failing": expected,
        "failing_checks": fails,
        "detected": all(e in fails for e in expected),
    }


DISPOSABLE_DIR: str = os.path.join(LAB_DIR, "results", "lab10_disposable")


def _make_incomplete_folder() -> str:
    """Rebuild a disposable folder with only the positions file. Written under results/, never the sample."""
    os.makedirs(DISPOSABLE_DIR, exist_ok=True)
    for name in os.listdir(DISPOSABLE_DIR):
        full = os.path.join(DISPOSABLE_DIR, name)
        if os.path.isfile(full):
            os.remove(full)
    with open(os.path.join(DISPOSABLE_DIR, "synthetic_positions.csv"), "w", encoding="utf-8") as handle:
        handle.write(SAMPLE_FILES["synthetic_positions.csv"])
    return DISPOSABLE_DIR


def packet_hashes() -> Dict[str, str]:
    files = {
        os.path.relpath(CONTRACT_PATH, LAB_DIR): _sha256_file(CONTRACT_PATH),
        os.path.relpath(CHECKLIST_PATH, LAB_DIR): _sha256_file(CHECKLIST_PATH),
    }
    for name in sorted(os.listdir(SAMPLE_DIR)):
        full = os.path.join(SAMPLE_DIR, name)
        if os.path.isfile(full):
            files[os.path.relpath(full, LAB_DIR)] = _sha256_file(full)
    return files


def run_lab() -> Dict[str, Any]:
    _ensure_data()
    contract = _load_json(CONTRACT_PATH)
    checklist = _load_json(CHECKLIST_PATH)

    live = check_contract(contract, checklist, SAMPLE_DIR)
    hashes = packet_hashes()
    transcript_names = [p for p in hashes if "transcript" in os.path.basename(p).lower()]
    live.append(_check("c10.handoff.no_transcript_in_packet", not transcript_names,
                       "transcript files in packet: %r" % (transcript_names,)))

    scenario = timeliness_scenario()
    routing = routing_checks(scenario, overlap_probe(), grace_boundary_probe())
    planted = planted_checks(contract, checklist)

    automated_ok = all(c["passed"] for c in live + routing)
    planted_ok = all(p["detected"] for p in planted)
    pending = [g["gate_id"] for g in MANUAL_GATES]
    manual_open = [i["item_id"] for i in checklist if i.get("evidence") == "manual" and i.get("checked") is False]

    return {
        "lab": "lab10",
        "title": "Saved scheduled-task contract and transcript-free handoff",
        "limits": [
            "A PASS does not show that a local schedule fired on any machine. Only Run now and desktop task history can show that (PENDING_MANUAL).",
            "The ten-item checklist is a local list written for this lab. Manual items stay open until their gate is recorded.",
            "The desktop routine interface was not tested for this edition; no method is verified for it.",
            "The routing rule is a lab-side model, not the desktop routine's runtime behaviour. Route checks test that model on a synthetic history.",
            "Overlap is computed from synthetic start and finish times, not from a real run log.",
            "The synthetic history is in UTC. The contract schedule is naive local time; the lab treats it as UTC only for the history probes.",
        ],
        "contract_path": os.path.relpath(CONTRACT_PATH, LAB_DIR),
        "checklist_path": os.path.relpath(CHECKLIST_PATH, LAB_DIR),
        "automated_checks": live,
        "routing_checks": routing,
        "timeliness_scenario": scenario,
        "planted_checks": planted,
        "manual_gates": [dict(g, status="PENDING_MANUAL") for g in MANUAL_GATES],
        "checklist_items_open_manual": manual_open,
        "packet_hashes": hashes,
        "summary": {
            "automated_passed": sum(1 for c in live + routing if c["passed"]),
            "automated_total": len(live) + len(routing),
            "all_automated_passed": automated_ok,
            "all_planted_detected": planted_ok,
            "manual_gates_pending": pending,
            "lab_status": "PASS" if (automated_ok and planted_ok) else "FAIL",
            "note": "Lab PASS is not a proof that the desktop routine ran. Manual gates remain open.",
        },
    }


def main() -> int:
    result = run_lab()
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")

    for check in result["automated_checks"] + result["routing_checks"]:
        print("%s %s %s" % ("PASS" if check["passed"] else "FAIL", check["check_id"], check["detail"]))
    for p in result["planted_checks"]:
        print("%s %s %s" % ("DETECTED" if p["detected"] else "MISSED", p["planted_id"],
                            ",".join(p["failing_checks"])))
    for g in result["manual_gates"]:
        print("PENDING_MANUAL %s" % g["gate_id"])
    print("lab10 status: %s" % result["summary"]["lab_status"])
    print("results written to %s" % RESULTS_PATH)
    return 0 if result["summary"]["lab_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
