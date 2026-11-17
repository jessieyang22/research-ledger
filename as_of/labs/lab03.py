"""Lab 03: freeze and verify the first checkpoint (synthetic data only).

What this lab does, in order:

1. Builds a synthetic sample project under as_of/labs/work/ with six immutable
   inputs, a prior-state file, an append-only estimate ledger, a read-only
   orientation file and an empty queue folder.
2. Reads the orientation (cutoff, evidence label, immutable paths, append-only
   paths, queue-only output, validation action).
3. Freezes the project: one state-manifest step holds the SHA-256 of each
   immutable input. The manifest is saved with its own digest, and a sibling
   digest file holds one line per immutable input plus one line for the
   manifest body.
4. Runs frozen_input_verifier, which recomputes SHA-256 over the current bytes
   of the six inputs and compares them with the manifest and the sibling file.
   This is a lab-local verifier for the six frozen inputs.
5. Runs a read-only-input pipeline stub that writes one report into queue/,
   then reviews the before and after snapshots. A new file under queue/ is
   allowed. A changed input, changed prior state or changed prior ledger row is
   a violation.
6. Planted failure: in a disposable copy, adds one space before a price value.
   The value parses to the same float, the digest must still fail. Then the
   clean bytes are restored in the copy and the verifier is rerun.
7. Negative controls on disposable copies: a ledger edit, a prior-state edit, a
   pipeline that edits an immutable input, a pipeline that writes outside queue/,
   a tampered manifest body and a tampered sibling digest. Each must FAIL.
8. Writes as_of/labs/results/lab03.json with a per-check PASS or FAIL.

Limits, stated in the JSON as well: a PASS shows only that current bytes match
the frozen bytes. It does not show that a source was correct, legally acquired
or complete. The Manual-mode session and the fresh-session start are not run by
this script. Run the script in two separate processes and compare the two JSON
outputs for the fresh-run check.

Only as_of.core is imported statically. Every other piece is loaded with
core.component inside a function body. No network, no subprocess, no orders.
"""

import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional

from as_of.core import AsOfError, component


LAB_DIR: str = os.path.dirname(os.path.abspath(__file__))
WORK_DIR: str = os.path.join(LAB_DIR, "work")
PROJECT_DIR: str = os.path.join(WORK_DIR, "sample_project")
PLANTED_DIR: str = os.path.join(WORK_DIR, "planted_copy")
RESULTS_PATH: str = os.path.join(LAB_DIR, "results", "lab03.json")

PROJECT_NAME: str = "SYN_sample_project"
CUTOFF: str = "2026-10-27T00:00:00Z"
CODE_VERSION: str = "lab03-v1"
QUEUE_DIR: str = "queue"
ORIENTATION_REL: str = "PROJECT_ORIENTATION.json"
PRIOR_STATE_REL: str = "state/prior_state.json"
MANIFEST_REL: str = "state/frozen_state_manifest.json"
DIGEST_REL: str = "state/frozen_state_manifest.sha256"
LEDGER_REL: str = "ledger/estimate_ledger.jsonl"
MANIFEST_LINE: str = "MANIFEST_BODY"
REPORT_REL: str = "queue/report_lab03.md"
PLANTED_REL: str = "inputs/prices.csv"

IMMUTABLE_INPUTS: tuple = (
    "inputs/prices.csv",
    "inputs/estimates.csv",
    "inputs/filings.csv",
    "inputs/macro_vintages.csv",
    "inputs/catalysts.csv",
    "inputs/sources.csv",
)
APPEND_ONLY_PATHS: tuple = (LEDGER_REL,)
PROTECTED_PATHS: tuple = (PRIOR_STATE_REL, MANIFEST_REL, DIGEST_REL, ORIENTATION_REL) + IMMUTABLE_INPUTS

INPUT_TEXT: Dict[str, str] = {
    "inputs/prices.csv": (
        "ticker,date,close\n"
        "SYN_A,2026-10-20,101.25\n"
        "SYN_A,2026-10-21,102.50\n"
        "SYN_B,2026-10-20,48.00\n"
        "SYN_B,2026-10-21,47.75\n"
    ),
    "inputs/estimates.csv": (
        "estimate_id,ticker,metric,period,value\n"
        "SYN_E1,SYN_A,eps,2026Q4,1.42\n"
        "SYN_E2,SYN_B,eps,2026Q4,0.91\n"
    ),
    "inputs/filings.csv": (
        "filing_id,ticker,form,filed_on\n"
        "SYN_F1,SYN_A,10-Q,2026-10-22\n"
    ),
    "inputs/macro_vintages.csv": (
        "series_id,obs_date,vintage_date,value\n"
        "SYN_M1,2026-09-01,2026-10-05,3.10\n"
        "SYN_M1,2026-09-01,2026-10-19,3.14\n"
    ),
    "inputs/catalysts.csv": (
        "catalyst_id,ticker,date,kind\n"
        "SYN_C1,SYN_B,2026-11-03,earnings\n"
    ),
    "inputs/sources.csv": (
        "source_id,type,locator\n"
        "SYN_S1,filing,SYN_locator_1\n"
        "SYN_S2,price,SYN_locator_2\n"
    ),
}

LEDGER_ROWS: List[Dict[str, Any]] = [
    {"row_id": "L1", "estimate_id": "SYN_E1", "value": 1.40, "knowledge_at": "2026-10-01T00:00:00Z"},
    {"row_id": "L2", "estimate_id": "SYN_E1", "value": 1.42, "knowledge_at": "2026-10-15T00:00:00Z"},
    {"row_id": "L3", "estimate_id": "SYN_E2", "value": 0.91, "knowledge_at": "2026-10-16T00:00:00Z"},
]


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.loads(handle.read())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_ledger(root: str) -> List[Dict[str, Any]]:
    try:
        return component("jsonl_store").read_records(os.path.join(root, LEDGER_REL))
    except AsOfError:
        return []


def build_project(root: str) -> None:
    """Write the synthetic sample project under root."""
    for sub in ("inputs", "state", "ledger", QUEUE_DIR):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    for rel, text in INPUT_TEXT.items():
        _write_text(os.path.join(root, rel), text)
    prior = {"cutoff": CUTOFF, "evidence_label": "synthetic", "note": "prior state for lab 03"}
    _write_text(os.path.join(root, PRIOR_STATE_REL), json.dumps(prior, sort_keys=True, indent=2) + "\n")
    ledger_path = os.path.join(root, LEDGER_REL)
    for row in LEDGER_ROWS:
        component("jsonl_store").append_record(ledger_path, row)
    orientation = {
        "project": PROJECT_NAME,
        "cutoff": CUTOFF,
        "evidence_label": "synthetic",
        "immutable_paths": list(IMMUTABLE_INPUTS),
        "append_only_paths": list(APPEND_ONLY_PATHS),
        "queue_only_output": QUEUE_DIR,
        "validation_action": "report_only",
    }
    _write_text(os.path.join(root, ORIENTATION_REL), json.dumps(orientation, sort_keys=True, indent=2) + "\n")


def read_orientation(root: str) -> Dict[str, Any]:
    """Read-only orientation. Returns the fields and a list of PASS or FAIL checks."""
    data = _read_json(os.path.join(root, ORIENTATION_REL)) or {}
    checks = []
    required = ("cutoff", "evidence_label", "immutable_paths", "append_only_paths", "queue_only_output", "validation_action")
    for key in required:
        checks.append((
            "orientation_has_" + key,
            key in data,
            "field present" if key in data else "field missing",
        ))
    checks.append((
        "orientation_immutable_paths_are_the_six_inputs",
        data.get("immutable_paths") == list(IMMUTABLE_INPUTS),
        "immutable_paths equals the six lab inputs" if data.get("immutable_paths") == list(IMMUTABLE_INPUTS) else "mismatch",
    ))
    checks.append((
        "orientation_queue_only_output",
        data.get("queue_only_output") == QUEUE_DIR,
        "output is queue/ only",
    ))
    checks.append((
        "orientation_append_only_includes_ledger",
        LEDGER_REL in (data.get("append_only_paths") or []),
        "ledger is append-only",
    ))
    checks.append((
        "orientation_validation_action_report_only",
        data.get("validation_action") == "report_only",
        "validation action is report_only",
    ))
    return {"fields": data, "checks": checks}


def freeze_project(root: str) -> str:
    """Write the frozen state manifest and its sibling digest file. Returns the body digest."""
    ch = component("content_hash")
    sm = component("state_manifest")
    inputs = {rel: ch.sha256_file(os.path.join(root, rel)) for rel in IMMUTABLE_INPUTS}
    manifest = sm.StateManifest()
    manifest.record_step(
        "freeze_immutable_inputs",
        inputs,
        {PRIOR_STATE_REL: ch.sha256_file(os.path.join(root, PRIOR_STATE_REL))},
        CODE_VERSION,
    )
    digest = manifest.save(os.path.join(root, MANIFEST_REL))
    lines = ["%s  %s" % (inputs[rel], rel) for rel in IMMUTABLE_INPUTS]
    lines.append("%s  %s" % (digest, MANIFEST_LINE))
    _write_text(os.path.join(root, DIGEST_REL), "\n".join(lines) + "\n")
    return digest


def _parse_sibling(path: str) -> Dict[str, List[str]]:
    """Map each name in the sibling digest file to the list of digests stored for it."""
    out: Dict[str, List[str]] = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return out
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            out.setdefault("__malformed__", []).append(line)
            continue
        out.setdefault(parts[1], []).append(parts[0])
    return out


def frozen_input_verifier(root: str) -> Dict[str, Any]:
    """Lab-local verifier for the six frozen inputs.

    Recomputes SHA-256 over the current bytes of each immutable input and
    compares it with the manifest and the sibling digest file. Returns the
    status, per-input rows and coverage counts. Nothing is written.
    """
    ch = component("content_hash")
    sm = component("state_manifest")
    manifest_path = os.path.join(root, MANIFEST_REL)
    checks: List[Dict[str, Any]] = []

    def add(cid: str, ok: bool, detail: str) -> None:
        checks.append({"id": cid, "status": "PASS" if ok else "FAIL", "detail": detail})

    manifest_ok = sm.StateManifest.verify(manifest_path)
    add("manifest_verifies", manifest_ok, "saved manifest digest matches its body" if manifest_ok else "manifest failed verify()")

    loaded = None
    try:
        loaded = sm.StateManifest.load(manifest_path)
    except (AsOfError, OSError):
        loaded = None
    steps = loaded.steps() if loaded is not None else []
    add("manifest_has_one_step", len(steps) == 1, "step count %d" % len(steps))
    step_inputs: Dict[str, str] = steps[0]["inputs"] if len(steps) == 1 else {}

    sibling = _parse_sibling(os.path.join(root, DIGEST_REL))
    body_lines = sibling.get(MANIFEST_LINE, [])
    manifest_digest = loaded.digest() if loaded is not None else None
    body_ok = len(body_lines) == 1 and manifest_digest is not None and body_lines[0] == manifest_digest
    add("sibling_manifest_body_digest", body_ok, "sibling file holds one body digest equal to the manifest digest")

    rows: List[Dict[str, Any]] = []
    for rel in IMMUTABLE_INPUTS:
        full = os.path.join(root, rel)
        try:
            current: Optional[str] = ch.sha256_file(full)
        except OSError:
            current = None
        stored_manifest = step_inputs.get(rel)
        sibling_digests = sibling.get(rel, [])
        one_digest = len(sibling_digests) == 1
        match = (
            current is not None
            and stored_manifest is not None
            and stored_manifest == current
            and one_digest
            and sibling_digests[0] == current
        )
        rows.append({
            "path": rel,
            "stored_digests_in_sibling_file": len(sibling_digests),
            "stored_sha256": stored_manifest,
            "current_sha256": current,
            "match": match,
        })
        add(
            "input_bytes_match:" + rel,
            match,
            "current bytes match frozen bytes" if match else "digest mismatch or missing",
        )

    manifest_keys = sorted(step_inputs.keys())
    keys_match = manifest_keys == sorted(IMMUTABLE_INPUTS)
    coverage = {
        "immutable_inputs": len(IMMUTABLE_INPUTS),
        "manifest_input_keys": len(manifest_keys),
        "manifest_keys_equal_immutable_list": keys_match,
        "inputs_with_exactly_one_stored_digest": sum(1 for r in rows if r["stored_digests_in_sibling_file"] == 1),
        "inputs_matching": sum(1 for r in rows if r["match"]),
    }
    add(
        "checksum_coverage_matches_manifest",
        keys_match and coverage["inputs_with_exactly_one_stored_digest"] == len(IMMUTABLE_INPUTS),
        "manifest keys equal the immutable list and each input has one stored digest",
    )
    status = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
    return {"status": status, "checks": checks, "inputs": rows, "coverage": coverage, "manifest_digest": manifest_digest}


def snapshot(root: str) -> Dict[str, str]:
    """SHA-256 of every file under root, keyed by its relative path with forward slashes."""
    ch = component("content_hash")
    out: Dict[str, str] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            out[rel] = ch.sha256_file(full)
    return out


def review_diff(before: Dict[str, str], after: Dict[str, str], ledger_before: List[Dict[str, Any]], ledger_after: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify changes between two snapshots. Only new files under queue/ are allowed."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    violations: List[Dict[str, str]] = []
    for path in removed:
        violations.append({"path": path, "reason": "removed"})
    for path in modified:
        if path == LEDGER_REL:
            continue
        reason = "protected path changed" if path in PROTECTED_PATHS else "changed outside an allowed write"
        violations.append({"path": path, "reason": reason})
    for path in added:
        if not path.startswith(QUEUE_DIR + "/"):
            violations.append({"path": path, "reason": "added outside queue/"})
    if LEDGER_REL in before or LEDGER_REL in after:
        prefix_ok = ledger_after[: len(ledger_before)] == ledger_before
        if not prefix_ok:
            violations.append({"path": LEDGER_REL, "reason": "prior ledger row changed"})
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "allowed_added_under_queue": [p for p in added if p.startswith(QUEUE_DIR + "/")],
        "violations": violations,
        "status": "PASS" if not violations else "FAIL",
    }


def run_pipeline(root: str) -> None:
    """Read-only stub. Reads the price rows and writes one report into queue/."""
    with open(os.path.join(root, "inputs/prices.csv"), "r", encoding="utf-8") as handle:
        rows = [line for line in handle.read().splitlines() if line]
    body = "# Lab 03 report (synthetic)\n\nprice rows read: %d\n" % (len(rows) - 1)
    _write_text(os.path.join(root, REPORT_REL), body)


def planted_failure(clean_bytes: bytes) -> Dict[str, Any]:
    """Add one space to a price value in a disposable copy, then restore it and rerun."""
    if os.path.isdir(PLANTED_DIR):
        shutil.rmtree(PLANTED_DIR)
    shutil.copytree(PROJECT_DIR, PLANTED_DIR)
    target = os.path.join(PLANTED_DIR, PLANTED_REL)
    needle = b"SYN_A,2026-10-20,101.25"
    mutated = clean_bytes.replace(needle, b"SYN_A,2026-10-20, 101.25", 1)
    one_byte_added = len(mutated) - len(clean_bytes) == 1 and mutated != clean_bytes
    with open(target, "wb") as handle:
        handle.write(mutated)
    value_before = float(clean_bytes.split(b"SYN_A,2026-10-20,")[1].split(b"\n")[0])
    value_after = float(mutated.split(b"SYN_A,2026-10-20,")[1].split(b"\n")[0])
    economic_equal = value_before == value_after
    mutated_result = frozen_input_verifier(PLANTED_DIR)
    prices_row = [r for r in mutated_result["inputs"] if r["path"] == PLANTED_REL][0]
    others_ok = all(r["match"] for r in mutated_result["inputs"] if r["path"] != PLANTED_REL)
    with open(target, "wb") as handle:
        handle.write(clean_bytes)
    restored_result = frozen_input_verifier(PLANTED_DIR)
    return {
        "planted_copy": "labs/work/planted_copy",
        "mutated_input": PLANTED_REL,
        "one_byte_added": one_byte_added,
        "economic_value_equal": economic_equal,
        "mutated_run_status": mutated_result["status"],
        "digest_failed_for_mutated_input": not prices_row["match"],
        "other_inputs_still_match": others_ok,
        "restored_run_status": restored_result["status"],
    }


def negative_controls() -> Dict[str, Any]:
    """Change a ledger row and the prior state in disposable copies. review_diff must FAIL both."""
    results: Dict[str, Any] = {}
    cases = {
        "ledger_row_edit": (LEDGER_REL, b'"row_id":"L1","value":1.4}', b'"row_id":"L1","value":1.41}'),
        "prior_state_edit": (PRIOR_STATE_REL, b'"evidence_label": "synthetic"', b'"evidence_label": "synthetic "'),
    }
    for name, (rel, needle, replacement) in cases.items():
        neg_dir = os.path.join(WORK_DIR, "negative_" + name)
        if os.path.isdir(neg_dir):
            shutil.rmtree(neg_dir)
        shutil.copytree(PROJECT_DIR, neg_dir)
        target = os.path.join(neg_dir, rel)
        with open(target, "rb") as handle:
            original = handle.read()
        if needle not in original:
            results[name] = {"path": rel, "edited": False, "status": "FAIL", "reasons": ["needle not found"]}
            continue
        edited = original.replace(needle, replacement, 1)
        before = snapshot(neg_dir)
        ledger_before = _read_ledger(neg_dir)
        with open(target, "wb") as handle:
            handle.write(edited)
        after = snapshot(neg_dir)
        ledger_after = _read_ledger(neg_dir)
        diff = review_diff(before, after, ledger_before, ledger_after)
        reasons = sorted(set(v["reason"] for v in diff["violations"] if v["path"] == rel))
        results[name] = {
            "path": rel,
            "edited": edited != original,
            "status": diff["status"],
            "reasons": reasons,
        }
    return results


def _copy_project(name: str) -> str:
    """Make a disposable copy of the sample project under WORK_DIR and return its path."""
    neg_dir = os.path.join(WORK_DIR, name)
    if os.path.isdir(neg_dir):
        shutil.rmtree(neg_dir)
    shutil.copytree(PROJECT_DIR, neg_dir)
    return neg_dir


def pipeline_violation_controls() -> Dict[str, Any]:
    """Pipelines that break the rules must make review_diff FAIL with the expected reason.

    The real stub in run_pipeline is well behaved, so without these controls the
    diff review could never fail in the main run.
    """
    def bad_immutable_edit(root: str) -> None:
        with open(os.path.join(root, PLANTED_REL), "a", encoding="utf-8") as handle:
            handle.write("SYN_A,2026-10-22,103.00\n")

    def bad_write_outside_queue(root: str) -> None:
        _write_text(os.path.join(root, "ledger", "stray_output.txt"), "not allowed\n")

    cases = {
        "pipeline_edits_immutable_input": (bad_immutable_edit, PLANTED_REL, "protected path changed"),
        "pipeline_writes_outside_queue": (bad_write_outside_queue, "ledger/stray_output.txt", "added outside queue/"),
    }
    results: Dict[str, Any] = {}
    for name, (stub, rel, expected) in cases.items():
        neg_dir = _copy_project("negative_" + name)
        before = snapshot(neg_dir)
        ledger_before = _read_ledger(neg_dir)
        stub(neg_dir)
        after = snapshot(neg_dir)
        ledger_after = _read_ledger(neg_dir)
        diff = review_diff(before, after, ledger_before, ledger_after)
        reasons = sorted(set(v["reason"] for v in diff["violations"] if v["path"] == rel))
        results[name] = {
            "path": rel,
            "status": diff["status"],
            "reasons": reasons,
            "expected_reason": expected,
            "caught": diff["status"] == "FAIL" and expected in reasons,
        }
    return results


def manifest_tamper_controls() -> Dict[str, Any]:
    """Edit the saved manifest body, or one sibling digest, in disposable copies. The verifier must FAIL."""
    results: Dict[str, Any] = {}

    neg_dir = _copy_project("negative_manifest_body_tamper")
    mpath = os.path.join(neg_dir, MANIFEST_REL)
    with open(mpath, "r", encoding="utf-8") as handle:
        text = handle.read()
    tampered = text.replace('"code_version": "%s"' % CODE_VERSION, '"code_version": "lab03-v2"', 1)
    edited = tampered != text
    _write_text(mpath, tampered)
    res = frozen_input_verifier(neg_dir)
    manifest_check = [c["status"] for c in res["checks"] if c["id"] == "manifest_verifies"]
    results["manifest_body_tamper"] = {
        "edited": edited,
        "status": res["status"],
        "manifest_verifies_status": manifest_check[0] if manifest_check else None,
        "caught": edited and res["status"] == "FAIL" and manifest_check == ["FAIL"],
    }

    neg_dir = _copy_project("negative_sibling_digest_tamper")
    dpath = os.path.join(neg_dir, DIGEST_REL)
    with open(dpath, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    idx = [i for i, line in enumerate(lines) if line.endswith("  " + PLANTED_REL)]
    edited = len(idx) == 1
    if edited:
        lines[idx[0]] = "0" * 64 + lines[idx[0]][64:]
    _write_text(dpath, "\n".join(lines) + "\n")
    res = frozen_input_verifier(neg_dir)
    input_check = [c["status"] for c in res["checks"] if c["id"] == "input_bytes_match:" + PLANTED_REL]
    results["sibling_digest_tamper"] = {
        "edited": edited,
        "status": res["status"],
        "input_check_status": input_check[0] if input_check else None,
        "caught": edited and res["status"] == "FAIL" and input_check == ["FAIL"],
    }
    return results


def _relative_status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def run() -> Dict[str, Any]:
    if os.path.isdir(WORK_DIR):
        shutil.rmtree(WORK_DIR)
    os.makedirs(WORK_DIR, exist_ok=True)
    try:
        build_project(PROJECT_DIR)
        with open(os.path.join(PROJECT_DIR, PLANTED_REL), "rb") as handle:
            clean_prices = handle.read()

        orientation = read_orientation(PROJECT_DIR)
        freeze_digest = freeze_project(PROJECT_DIR)
        verified = frozen_input_verifier(PROJECT_DIR)

        before = snapshot(PROJECT_DIR)
        ledger_before = _read_ledger(PROJECT_DIR)
        run_pipeline(PROJECT_DIR)
        after = snapshot(PROJECT_DIR)
        ledger_after = _read_ledger(PROJECT_DIR)
        diff = review_diff(before, after, ledger_before, ledger_after)

        planted = planted_failure(clean_prices)
        real_after_planted = frozen_input_verifier(PROJECT_DIR)
        negatives = negative_controls()
        pipeline_controls = pipeline_violation_controls()
        tamper_controls = manifest_tamper_controls()

        checks: List[Dict[str, Any]] = []
        for cid, ok, detail in orientation["checks"]:
            checks.append({"id": cid, "status": _relative_status(ok), "detail": detail})
        checks.append({
            "id": "freeze_wrote_manifest_and_sibling_digest",
            "status": _relative_status(
                os.path.isfile(os.path.join(PROJECT_DIR, MANIFEST_REL))
                and os.path.isfile(os.path.join(PROJECT_DIR, DIGEST_REL))
                and verified["manifest_digest"] == freeze_digest
            ),
            "detail": "manifest and sibling digest file exist and agree",
        })
        for c in verified["checks"]:
            checks.append(dict(c, id="lab3_verifier:" + c["id"]))
        checks.append({
            "id": "lab3_verifier_status",
            "status": verified["status"],
            "detail": "frozen_input_verifier over the six immutable inputs",
        })
        checks.append({
            "id": "diff_review_no_forbidden_changes",
            "status": diff["status"],
            "detail": "only new files under queue/ are allowed; no input, prior state or prior ledger row changed",
        })
        checks.append({
            "id": "planted_space_breaks_digest",
            "status": _relative_status(
                planted["one_byte_added"]
                and planted["economic_value_equal"]
                and planted["digest_failed_for_mutated_input"]
                and planted["other_inputs_still_match"]
                and planted["mutated_run_status"] == "FAIL"
            ),
            "detail": "one added space fails the digest although the parsed value is unchanged",
        })
        checks.append({
            "id": "restored_copy_passes",
            "status": _relative_status(planted["restored_run_status"] == "PASS"),
            "detail": "clean bytes restored in the disposable copy and rerun",
        })
        checks.append({
            "id": "negative_control_ledger_row_edit_fails_diff_review",
            "status": _relative_status(
                negatives["ledger_row_edit"]["status"] == "FAIL"
                and "prior ledger row changed" in negatives["ledger_row_edit"]["reasons"]
            ),
            "detail": "a changed prior ledger row is rejected by review_diff",
        })
        checks.append({
            "id": "negative_control_prior_state_edit_fails_diff_review",
            "status": _relative_status(
                negatives["prior_state_edit"]["status"] == "FAIL"
                and "protected path changed" in negatives["prior_state_edit"]["reasons"]
            ),
            "detail": "a changed prior-state file is rejected by review_diff",
        })
        for case_name, case in sorted(pipeline_controls.items()):
            checks.append({
                "id": "negative_control_" + case_name + "_fails_diff_review",
                "status": _relative_status(case["caught"]),
                "detail": "a violating pipeline stub is rejected by review_diff with the expected reason",
            })
        for case_name, case in sorted(tamper_controls.items()):
            checks.append({
                "id": "negative_control_" + case_name + "_fails_verifier",
                "status": _relative_status(case["caught"]),
                "detail": "a tampered manifest or sibling digest makes frozen_input_verifier FAIL",
            })
        checks.append({
            "id": "real_project_still_passes_after_planted_run",
            "status": real_after_planted["status"],
            "detail": "the real sample project was not touched by the planted run",
        })

        overall = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
        return {
            "lab": "lab03",
            "title": "Freeze and verify the first checkpoint",
            "data": "synthetic",
            "project": PROJECT_NAME,
            "orientation": orientation["fields"],
            "freeze": {
                "manifest_path": MANIFEST_REL,
                "sibling_digest_path": DIGEST_REL,
                "manifest_digest": freeze_digest,
                "immutable_inputs": list(IMMUTABLE_INPUTS),
            },
            "lab3_verifier": {
                "note": "lab-local verifier for the six frozen inputs",
                "status": verified["status"],
                "coverage": verified["coverage"],
                "inputs": verified["inputs"],
            },
            "diff_review": diff,
            "planted_failure": planted,
            "negative_controls": negatives,
            "pipeline_violation_controls": pipeline_controls,
            "manifest_tamper_controls": tamper_controls,
            "checks": checks,
            "overall": overall,
            "fresh_session": {
                "status": "not_run_by_script",
                "method": "run this script in two separate processes and compare the two JSON files byte for byte",
            },
            "not_shown": [
                "A PASS shows only that current bytes match the frozen bytes.",
                "A PASS does not show the source was correct, legally acquired or complete.",
                "The Manual-mode session and a fresh Claude session are not started by this script.",
                "The Desktop path was not directly tested for this edition.",
            ],
        }
    finally:
        if os.path.isdir(WORK_DIR):
            shutil.rmtree(WORK_DIR)


def main() -> int:
    result = run()
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    text = json.dumps(result, sort_keys=True, indent=2) + "\n"
    with open(RESULTS_PATH, "w", encoding="utf-8") as handle:
        handle.write(text)
    failed = [c["id"] for c in result["checks"] if c["status"] != "PASS"]
    sys.stdout.write("lab03 overall: %s (%d checks, %d failed)\n" % (result["overall"], len(result["checks"]), len(failed)))
    for cid in failed:
        sys.stdout.write("  FAIL %s\n" % cid)
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
