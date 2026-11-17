"""Lab 01: route a task by its durable artifact (synthetic matrix only).

What this lab does, in order:

1. Makes sure the release copy of the task-routing matrix exists at
   as_of/labs/results/lab01_routing_matrix.json. If the file is missing, it is
   written once from the MATRIX_ROWS table below. The release copy is never
   rewritten after that. Every run loads it from disk and compares it with the
   authored table, so an edited release copy shows up as a FAIL.
2. Runs the verifier on the loaded rows. It checks that there are
   eight rows with ids ROUTE-001 to ROUTE-008, that each row has an
   authoritative artifact, a task, a rationale, a reversal condition and a
   reviewer, that the rationale names work-shape terms and does not praise a
   tool, and that the chosen surface equals the surface the routing rule derives
   from the native artifact owner, the five-condition count and the
   data_approved veto.
3. Runs negative checks on in-memory copies. Each planted defect must be caught
   by the named check with the expected message: a missing artifact, rationale
   or reviewer; a vetoed CODE route (data_approved unknown); a CODE-native row
   with one condition met, which the two-of-five rule sends to DOCS; a native
   surface that the artifact text does not name; and a True condition that the
   rationale does not argue. An untouched control row must still pass.
4. Planted failure: writes a disposable copy in a temporary folder, changes
   ROUTE-003 from EXCEL to CODE, reloads that copy from disk and runs the
   verifier. The verifier must report a FAIL with a wrong-surface message for
   ROUTE-003 and nothing else. The disposable copy is then deleted, the release
   copy is reloaded from disk and re-verified, its hash is compared with the
   hash taken before the planted run, and its bytes are compared with the
   pinned EXPECTED_RELEASE_SHA256.
5. Writes as_of/labs/results/lab01.json with one PASS, WARN or FAIL per check,
   and a completion record. A reviewer WARN does not fail the run. The overall
   label is PASS_STRUCTURE_ONLY_REVIEW_OPEN until a named human clears the rows.

Limits. The matrix, the rule and the reviewer field are synthetic and were
authored for this lab. The verifier checks structure and the rule only. It cannot establish
routing quality. A human must read each rationale and say whether it describes
the work shape. Until a named reviewer records that, the reviewer field is a
placeholder and the verifier reports a WARN for each row.

All data is synthetic. The script makes no network calls, starts no
subprocesses and places no orders.
"""

import copy
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from as_of.core import Finding, ValidationStatus, component, stable_hash  # noqa: E402

PASS = ValidationStatus.PASS
WARN = ValidationStatus.WARN
FAIL = ValidationStatus.FAIL

LAB_DIR: str = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR: str = os.path.join(LAB_DIR, "results")
RELEASE_PATH: str = os.path.join(RESULTS_DIR, "lab01_routing_matrix.json")
RESULT_PATH: str = os.path.join(RESULTS_DIR, "lab01.json")

SURFACES = ("CODE", "EXCEL", "DOCS", "SLIDES", "HOLD")
CONDITION_KEYS = (
    "cond_repeats",
    "cond_rebuild_old_state",
    "cond_schema_can_reject",
    "cond_artifacts_in_sync",
    "cond_reviewer_needs_delta",
)
ROUTE_IDS = tuple("ROUTE-%03d" % i for i in range(1, 9))
TEXT_KEYS = ("task", "authoritative_artifact", "rationale", "reversal_condition")
WORK_SHAPE_TERMS = ("repeat", "rebuild", "schema", "sync", "delta", "veto", "native")
PRAISE_TERMS = ("best", "powerful", "great", "excellent", "amazing", "perfect", "smart", "easy", "revolutionary", "superior")
PLACEHOLDER_REVIEWER = "PENDING_REVIEW"
PLANTED_ROUTE = "ROUTE-003"
# Pinned hash of the release copy as reviewed. A release file that is edited
# and then re-saved to match the authored table would still pass the table
# comparison, so the pin is the tamper check. Update only with a reviewed change.
EXPECTED_RELEASE_SHA256 = "3f8d360b383769c92df107661f730eb00cb44e2e58c58ab3e6cb1321d3050af4"
# A row whose condition is True must say so in its rationale. Each entry lists
# word-start patterns; at least one must appear.
CONDITION_TERMS = {
    "cond_repeats": (r"repeat", r"every", r"daily", r"monthly", r"each"),
    "cond_rebuild_old_state": (r"rebuild", r"old state", r"prior"),
    "cond_schema_can_reject": (r"schema", r"reject"),
    "cond_artifacts_in_sync": (r"sync",),
    "cond_reviewer_needs_delta": (r"delta",),
}
# A native non-CODE artifact must name its file type in the artifact text.
SURFACE_ARTIFACT_TERMS = {
    "EXCEL": (r"xlsx", r"workbook"),
    "DOCS": (r"document", r"draft", r"memo", r"note"),
    "SLIDES": (r"slide", r"deck"),
}

# Synthetic routing matrix. Each row records the suggested surface (the first
# guess), the native surface (the tool that owns the durable artifact), the
# five-condition answers, the data_approved value, and the chosen surface.
# The condition answers are the five keys in CONDITION_KEYS. The earlier
# comment said six; the code and this table use five.
MATRIX_ROWS: List[Dict[str, Any]] = [
    {
        "route_id": "ROUTE-001",
        "task": "Refresh the estimate ledger from the morning consensus pull",
        "suggested_surface": "CODE",
        "native_surface": "CODE",
        "authoritative_artifact": "synthetic estimate ledger JSONL file",
        "data_approved": "yes",
        "cond_repeats": True,
        "cond_rebuild_old_state": True,
        "cond_schema_can_reject": True,
        "cond_artifacts_in_sync": True,
        "cond_reviewer_needs_delta": True,
        "rationale": "The job repeats every trading morning, so it must rebuild the ledger from prior rows rather than reuse old state. The schema rejects malformed estimate rows before they land, and the ledger must stay in sync with the revision summary. The reviewer reads the day's revision delta that the job emits.",
        "reversal_condition": "Move to DOCS if the pull runs less than once a quarter, or if the source stops delivering rows in the agreed schema.",
        "reviewer": PLACEHOLDER_REVIEWER,
        "chosen_surface": "CODE",
    },
    {
        "route_id": "ROUTE-002",
        "task": "Write the one-off position memo for the investment committee",
        "suggested_surface": "DOCS",
        "native_surface": "DOCS",
        "authoritative_artifact": "synthetic position memo word-processing draft",
        "data_approved": "yes",
        "cond_repeats": False,
        "cond_rebuild_old_state": False,
        "cond_schema_can_reject": False,
        "cond_artifacts_in_sync": False,
        "cond_reviewer_needs_delta": True,
        "rationale": "The memo is written once for one position, so there is no repeat and no old state to rebuild. The reviewer needs a delta against the last memo version, and the native document holds the redline. Nothing in the memo is schema-checked, so the native document route stands.",
        "reversal_condition": "Move to CODE if the memo is regenerated from position data on a schedule.",
        "reviewer": PLACEHOLDER_REVIEWER,
        "chosen_surface": "DOCS",
    },
    {
        "route_id": "ROUTE-003",
        "task": "Update the sensitivity table in the synthetic workbook after a new input",
        "suggested_surface": "CODE",
        "native_surface": "EXCEL",
        "authoritative_artifact": "synthetic workbook sensitivity sheet (xlsx)",
        "data_approved": "yes",
        "cond_repeats": False,
        "cond_rebuild_old_state": False,
        "cond_schema_can_reject": False,
        "cond_artifacts_in_sync": True,
        "cond_reviewer_needs_delta": False,
        "rationale": "The calculation is a native workbook formula chain, and the edit touches one sheet, so it is not a repeat job. The sync risk is between the sensitivity sheet and the memo table, and the workbook owns both. Code could read a CSV export of the sheet, but that export would be a second artifact that drifts out of sync with the native formulas, so the native workbook keeps the route.",
        "reversal_condition": "Move to CODE only if the sensitivity table is regenerated by a script on every input change, so the workbook is no longer the native artifact.",
        "reviewer": PLACEHOLDER_REVIEWER,
        "chosen_surface": "EXCEL",
    },
    {
        "route_id": "ROUTE-004",
        "task": "Pull the monthly macro vintage set for the cutoff review",
        "suggested_surface": "CODE",
        "native_surface": "CODE",
        "authoritative_artifact": "synthetic macro vintage manifest",
        "data_approved": "unknown",
        "cond_repeats": True,
        "cond_rebuild_old_state": True,
        "cond_schema_can_reject": True,
        "cond_artifacts_in_sync": True,
        "cond_reviewer_needs_delta": True,
        "rationale": "The pull repeats every month and must rebuild the vintage set as of each cutoff, which is old state. The schema rejects vintages with a missing release time, and the manifest must stay in sync with the series file. The reviewer needs the delta of new vintages. The source has not been confirmed as approved, so the veto blocks a Code route and the row is held.",
        "reversal_condition": "Route to CODE once data_approved is set to yes for this source. Until then the route stays HOLD.",
        "reviewer": PLACEHOLDER_REVIEWER,
        "chosen_surface": "HOLD",
    },
    {
        "route_id": "ROUTE-005",
        "task": "Triage the catalyst exception queue each morning",
        "suggested_surface": "CODE",
        "native_surface": "CODE",
        "authoritative_artifact": "synthetic exception queue state file",
        "data_approved": "yes",
        "cond_repeats": True,
        "cond_rebuild_old_state": True,
        "cond_schema_can_reject": True,
        "cond_artifacts_in_sync": True,
        "cond_reviewer_needs_delta": True,
        "rationale": "The triage repeats daily and rebuilds open exceptions from the prior queue state. The schema rejects unlinked claims, and the queue, the claim links and the filing list must stay in sync. The reviewer reads the new and resolved delta each day.",
        "reversal_condition": "Move to DOCS if the queue is triaged by hand less than weekly.",
        "reviewer": PLACEHOLDER_REVIEWER,
        "chosen_surface": "CODE",
    },
    {
        "route_id": "ROUTE-006",
        "task": "Build the five-slide investment committee update deck",
        "suggested_surface": "SLIDES",
        "native_surface": "SLIDES",
        "authoritative_artifact": "synthetic slide deck file",
        "data_approved": "yes",
        "cond_repeats": False,
        "cond_rebuild_old_state": False,
        "cond_schema_can_reject": False,
        "cond_artifacts_in_sync": False,
        "cond_reviewer_needs_delta": False,
        "rationale": "This is one deck for one meeting, so there is no repeat and no old state to rebuild. The native slide file owns the layout, and the reviewer reads the finished slides rather than a delta. Code is not needed on this route.",
        "reversal_condition": "Move to CODE if the deck is regenerated from data on every meeting.",
        "reviewer": PLACEHOLDER_REVIEWER,
        "chosen_surface": "SLIDES",
    },
    {
        "route_id": "ROUTE-007",
        "task": "Write the analyst handoff note for the next owner",
        "suggested_surface": "DOCS",
        "native_surface": "DOCS",
        "authoritative_artifact": "synthetic handoff note document",
        "data_approved": "yes",
        "cond_repeats": False,
        "cond_rebuild_old_state": True,
        "cond_schema_can_reject": False,
        "cond_artifacts_in_sync": True,
        "cond_reviewer_needs_delta": False,
        "rationale": "The note is written once per handover, but it must rebuild the state of open items from the last handoff. Its sync is with the open exception list, which the note cites. The native document owns the handoff text, and the reviewer has no delta to read.",
        "reversal_condition": "Move to CODE if handoffs become a scheduled job that rebuilds state every week.",
        "reviewer": PLACEHOLDER_REVIEWER,
        "chosen_surface": "DOCS",
    },
    {
        "route_id": "ROUTE-008",
        "task": "Tie out the internal synthetic book to the custodian book each day",
        "suggested_surface": "CODE",
        "native_surface": "CODE",
        "authoritative_artifact": "synthetic tie-out break report",
        "data_approved": "yes",
        "cond_repeats": True,
        "cond_rebuild_old_state": True,
        "cond_schema_can_reject": True,
        "cond_artifacts_in_sync": True,
        "cond_reviewer_needs_delta": True,
        "rationale": "The tie-out repeats at each close and must rebuild positions from the prior book. The schema rejects any position row without a price. The internal and custodian books must stay in sync, and the reviewer reads the break delta.",
        "reversal_condition": "Move to EXCEL if the tie-out is kept as a native workbook with no daily run.",
        "reviewer": PLACEHOLDER_REVIEWER,
        "chosen_surface": "CODE",
    },
]


def count_conditions(row: Mapping[str, Any]) -> int:
    """Return how many of the five work-shape conditions are True."""
    return sum(1 for key in CONDITION_KEYS if row.get(key) is True)


def derive_surface(row: Mapping[str, Any]) -> str:
    """Apply the routing rule and return the surface it allows.

    The native artifact owner decides first. A native EXCEL, DOCS or SLIDES
    artifact stays on that surface. A native CODE route needs data_approved to
    be exactly yes, because an unknown or negative value vetoes Code for that
    data, and at least two of the five conditions must hold. Otherwise the
    row is held.
    """
    native = row.get("native_surface")
    if native in ("EXCEL", "DOCS", "SLIDES"):
        return str(native)
    if row.get("data_approved") != "yes":
        return "HOLD"
    if count_conditions(row) >= 2:
        return "CODE"
    return "DOCS"


def _has_term(text: str, term: str) -> bool:
    """True when term starts at a word boundary in text (so 'sync' does not match 'async')."""
    return re.search(r"\b" + re.escape(term), text) is not None


def _text_missing(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def check_row(row: Mapping[str, Any]) -> List[Finding]:
    """Return the fields, reviewer and surface findings for one row."""
    rid = str(row.get("route_id", "UNKNOWN"))
    out: List[Finding] = []

    problems: List[str] = []
    for key in TEXT_KEYS:
        if _text_missing(row.get(key)):
            problems.append("missing %s" % key)
    for key in ("reviewer", "suggested_surface", "native_surface", "chosen_surface", "data_approved"):
        if _text_missing(row.get(key)):
            problems.append("missing %s" % key)
    for key in CONDITION_KEYS:
        if not isinstance(row.get(key), bool):
            problems.append("non-boolean %s" % key)
    if row.get("native_surface") not in SURFACES:
        problems.append("native_surface is not a known surface")

    rationale = row.get("rationale") if isinstance(row.get("rationale"), str) else ""
    lowered = rationale.lower()
    shape_hits = [term for term in WORK_SHAPE_TERMS if _has_term(lowered, term)]
    praise_hits = [term for term in PRAISE_TERMS if _has_term(lowered, term)]
    if praise_hits:
        problems.append("rationale praises a tool (%s)" % ", ".join(praise_hits))
    # Each True condition must be argued in the rationale. This ties the text
    # to the answers, so a rationale cannot pass on unrelated words alone.
    for key in CONDITION_KEYS:
        if row.get(key) is True and not any(_has_term(lowered, p) for p in CONDITION_TERMS[key]):
            problems.append("rationale does not argue %s" % key)
    # A native EXCEL, DOCS or SLIDES route must name its file type in the artifact.
    native = row.get("native_surface")
    artifact = row.get("authoritative_artifact") if isinstance(row.get("authoritative_artifact"), str) else ""
    if native in SURFACE_ARTIFACT_TERMS and not any(
        _has_term(artifact.lower(), p) for p in SURFACE_ARTIFACT_TERMS[native]
    ):
        problems.append("artifact %r does not name a %s file" % (artifact, native))

    if problems:
        out.append(Finding("%s.fields" % rid, FAIL, "; ".join(problems), rid))
    else:
        out.append(
            Finding(
                "%s.fields" % rid,
                PASS,
                "fields present; rationale argues every True condition; work-shape terms: %s"
                % (", ".join(shape_hits) or "none"),
                rid,
            )
        )

    if str(row.get("reviewer", "")).startswith("PENDING"):
        out.append(
            Finding(
                "%s.reviewer" % rid,
                WARN,
                "reviewer not assigned (placeholder); a named human must read the rationale",
                rid,
            )
        )

    chosen = row.get("chosen_surface")
    derived = derive_surface(row)
    if chosen not in SURFACES:
        out.append(Finding("%s.surface" % rid, FAIL, "%s: chosen surface %r is not a known surface" % (rid, chosen), rid))
    elif chosen != derived:
        veto = ""
        if row.get("data_approved") != "yes" and chosen == "CODE":
            veto = "; veto: data_approved is %r, so no Code route is allowed" % row.get("data_approved")
        out.append(
            Finding(
                "%s.surface" % rid,
                FAIL,
                "%s: wrong surface, chosen %s but the rule gives %s (native artifact owner %s, "
                "data_approved %r, conditions met %d of 5)%s"
                % (
                    rid,
                    chosen,
                    derived,
                    row.get("native_surface"),
                    row.get("data_approved"),
                    count_conditions(row),
                    veto,
                ),
                rid,
            )
        )
    else:
        out.append(
            Finding(
                "%s.surface" % rid,
                PASS,
                "%s: chosen %s matches the rule (native owner %s, conditions met %d of 5)"
                % (rid, chosen, row.get("native_surface"), count_conditions(row)),
                rid,
            )
        )
    return out


def verify_rows(rows: Sequence[Mapping[str, Any]]) -> List[Finding]:
    """Run the verifier over a list of matrix rows."""
    findings: List[Finding] = []
    ids = [row.get("route_id") for row in rows]
    by_id: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if isinstance(row.get("route_id"), str):
            by_id.setdefault(row["route_id"], row)
    count_ok = len(rows) == len(ROUTE_IDS) and tuple(sorted(str(i) for i in ids)) == ROUTE_IDS
    findings.append(
        Finding(
            "matrix.row_count",
            PASS if count_ok else FAIL,
            "matrix has %d rows; ids %s" % (len(rows), "match ROUTE-001 to ROUTE-008" if count_ok else "do not match ROUTE-001 to ROUTE-008"),
            "matrix",
        )
    )
    for rid in ROUTE_IDS:
        row = by_id.get(rid)
        if row is None:
            findings.append(Finding("%s.fields" % rid, FAIL, "row %s is missing" % rid, rid))
            findings.append(Finding("%s.surface" % rid, FAIL, "row %s is missing" % rid, rid))
            continue
        findings.extend(check_row(row))
    return findings


def _mutate(rows: Sequence[Mapping[str, Any]], rid: str, changes: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Return a deep copy of rows with the changes applied to route rid."""
    mutated = copy.deepcopy(list(rows))
    for row in mutated:
        if row.get("route_id") == rid:
            row.update(changes)
    return mutated


def negative_checks(rows: Sequence[Mapping[str, Any]]) -> List[Finding]:
    """Check that the verifier rejects each planted defect, on in-memory copies.

    Each case names the check that must FAIL and a message token it must carry.
    A case passes only when that exact check fails with that token.
    """
    # (name, route, changes, check_id that must FAIL, message token)
    cases = [
        ("negative.missing_artifact_rejected", "ROUTE-002", {"authoritative_artifact": ""},
         "ROUTE-002.fields", "missing authoritative_artifact"),
        ("negative.missing_rationale_rejected", "ROUTE-005", {"rationale": ""},
         "ROUTE-005.fields", "missing rationale"),
        ("negative.missing_reviewer_rejected", "ROUTE-008", {"reviewer": None},
         "ROUTE-008.fields", "missing reviewer"),
        # The veto: data_approved is unknown, so a CODE route must be refused.
        ("negative.veto_blocks_code", "ROUTE-004", {"chosen_surface": "CODE"},
         "ROUTE-004.surface", "veto: data_approved"),
        # Two-of-five threshold: a CODE-native row with one condition met must not stay CODE.
        ("negative.one_condition_not_code", "ROUTE-001",
         {"cond_rebuild_old_state": False, "cond_schema_can_reject": False,
          "cond_artifacts_in_sync": False, "cond_reviewer_needs_delta": False},
         "ROUTE-001.surface", "the rule gives DOCS"),
        # Artifact tie: a memo relabelled as an EXCEL route must be caught by the artifact text.
        ("negative.native_surface_not_in_artifact", "ROUTE-002",
         {"native_surface": "EXCEL", "chosen_surface": "EXCEL", "suggested_surface": "EXCEL"},
         "ROUTE-002.fields", "does not name a EXCEL file"),
        # Condition tie: a True schema condition the rationale never argues must be caught.
        ("negative.condition_not_argued", "ROUTE-006", {"cond_schema_can_reject": True},
         "ROUTE-006.fields", "does not argue cond_schema_can_reject"),
    ]
    out: List[Finding] = []
    for name, rid, changes, must_fail, token in cases:
        findings = verify_rows(_mutate(rows, rid, changes))
        hits = [f for f in findings if f.check_id == must_fail and f.status == FAIL and token in f.message]
        if hits:
            out.append(Finding(name, PASS, "rejected: %s" % hits[0].message, rid))
        else:
            out.append(Finding(name, FAIL, "verifier did not reject %s (expected %s with %r)" % (rid, must_fail, token), rid))
    # The two-of-five threshold must still pass for the untouched release row, so the negative
    # case above is not just a verifier that fails everything.
    clean = [f for f in verify_rows(rows) if f.check_id == "ROUTE-001.surface"]
    out.append(
        Finding(
            "negative.control_row_accepted",
            PASS if clean and clean[0].status == PASS else FAIL,
            "untouched ROUTE-001 still passes the surface check" if clean and clean[0].status == PASS
            else "untouched ROUTE-001 fails the surface check",
            "ROUTE-001",
        )
    )
    return out


def planted_checks(rows: Sequence[Mapping[str, Any]], release_path: str, release_hash_before: str) -> List[Finding]:
    """Plant a wrong surface in a disposable copy and confirm the verifier catches it."""
    out: List[Finding] = []
    scratch = tempfile.mkdtemp(prefix="lab01_planted_")
    try:
        planted = copy.deepcopy(list(rows))
        for row in planted:
            if row.get("route_id") == PLANTED_ROUTE:
                row["chosen_surface"] = "CODE"
        disposable = os.path.join(scratch, "lab01_routing_matrix.json")
        with open(disposable, "w", encoding="utf-8") as handle:
            json.dump(planted, handle, indent=2, sort_keys=True)
            handle.write("\n")
        with open(disposable, "r", encoding="utf-8") as handle:
            reloaded = json.load(handle)
        findings = verify_rows(reloaded)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    wrong = [
        f
        for f in findings
        if f.check_id == "%s.surface" % PLANTED_ROUTE and f.status == FAIL and "wrong surface" in f.message
    ]
    out.append(
        Finding(
            "planted.wrong_surface_detected",
            PASS if wrong else FAIL,
            wrong[0].message if wrong else "verifier did not report a wrong-surface FAIL for %s" % PLANTED_ROUTE,
            PLANTED_ROUTE,
        )
    )
    other_fails = [f for f in findings if f.status == FAIL and not f.check_id.startswith(PLANTED_ROUTE)]
    out.append(
        Finding(
            "planted.failure_isolated_to_route_003",
            PASS if not other_fails else FAIL,
            "no other row failed" if not other_fails else "other rows failed: %s" % ", ".join(f.check_id for f in other_fails),
            PLANTED_ROUTE,
        )
    )
    release_hash_after = _sha256(release_path)
    out.append(
        Finding(
            "planted.release_copy_untouched",
            PASS if release_hash_after == release_hash_before else FAIL,
            "release copy hash %s" % ("unchanged after planted run" if release_hash_after == release_hash_before else "CHANGED"),
            "release",
        )
    )
    return out


def _sha256(path: str) -> str:
    content_hash = component("content_hash")
    return content_hash.sha256_file(path)


def ensure_release_copy(path: str, authored: Sequence[Mapping[str, Any]]) -> List[Finding]:
    """Write the release copy once, then check it against the authored table."""
    findings: List[Finding] = []
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(list(authored), handle, indent=2, sort_keys=True)
            handle.write("\n")
        findings.append(Finding("release.written_once", PASS, "release copy written from the authored table", "release"))
    with open(path, "r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    same = stable_hash(loaded) == stable_hash(list(authored))
    pinned = _sha256(path) == EXPECTED_RELEASE_SHA256
    findings.append(
        Finding(
            "release.sha256_pinned",
            PASS if pinned else FAIL,
            "release copy bytes match the pinned hash" if pinned
            else "release copy bytes differ from the pinned hash %s" % EXPECTED_RELEASE_SHA256,
            "release",
        )
    )
    findings.append(
        Finding(
            "release.copy_matches_authored",
            PASS if same else FAIL,
            "release copy matches the authored table"
            if same
            else "release copy differs from the authored table; restore it from the untouched release copy",
            "release",
        )
    )
    return findings


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    validation_report = component("validation_report")

    release_findings = ensure_release_copy(RELEASE_PATH, MATRIX_ROWS)
    release_hash_before = _sha256(RELEASE_PATH)
    with open(RELEASE_PATH, "r", encoding="utf-8") as handle:
        release_rows = json.load(handle)

    row_findings = verify_rows(release_rows)
    negative_findings = negative_checks(release_rows)
    planted_findings = planted_checks(release_rows, RELEASE_PATH, release_hash_before)
    # Reload the release copy from disk after the planted run and verify that copy.
    # The earlier version re-checked the in-memory rows, which the planted step never touched.
    with open(RELEASE_PATH, "r", encoding="utf-8") as handle:
        reloaded_release = json.load(handle)
    restored_findings = [
        Finding(
            "release.verifier_after_restore",
            FAIL if any(f.status == FAIL for f in verify_rows(reloaded_release)) else PASS,
            "release copy reloaded from disk and re-verified after the planted run",
            "release",
        ),
        Finding(
            "release.reloaded_matches_before",
            PASS if _sha256(RELEASE_PATH) == release_hash_before else FAIL,
            "reloaded release copy hash equals the hash taken before the planted run",
            "release",
        ),
    ]

    groups = {
        "release": release_findings + restored_findings,
        "matrix": row_findings,
        "negative": negative_findings,
        "planted": planted_findings,
    }
    report = validation_report.build_report(
        "Lab 01: route a task by its durable artifact",
        groups,
        generated_for="synthetic matrix; no timestamp in the report text",
    )
    passes = validation_report.report_passes(report)
    print(validation_report.render_report_text(report))

    all_findings = [f for group in groups.values() for f in group]
    checks = [
        {"check_id": f.check_id, "status": f.status.name, "message": f.message}
        for f in all_findings
    ]

    route_changes = [
        {
            "route_id": row["route_id"],
            "suggested_surface": row["suggested_surface"],
            "chosen_surface": row["chosen_surface"],
            "native_surface": row["native_surface"],
        }
        for row in release_rows
        if row.get("suggested_surface") != row.get("chosen_surface")
    ]
    timestamp = _now()
    # WARN on the reviewer field does not fail the report, so a PASS here means
    # the structure and rule checks passed. It does not mean a human reviewed the rows.
    review_open = any(f.check_id.endswith(".reviewer") and f.status == WARN for f in all_findings)
    if not passes:
        overall = "FAIL"
    elif review_open:
        overall = "PASS_STRUCTURE_ONLY_REVIEW_OPEN"
    else:
        overall = "PASS"
    completion = {
        "matrix_path": RELEASE_PATH,
        "matrix_sha256": release_hash_before,
        "timestamp_utc": timestamp,
        "result": overall,
        "human_review_complete": not review_open,
        "reviewer": "UNASSIGNED. The reviewer field is a placeholder; no human has read the rationales.",
        "route_changed_after_five_condition_test": route_changes,
        "named_example": "ROUTE-003: suggested CODE, chosen EXCEL, because the native workbook owns the artifact even though Code could read a CSV export.",
    }
    payload = {
        "lab": "lab01",
        "title": "Route a task by its durable artifact",
        "timestamp_utc": timestamp,
        "overall": overall,
        "checks": checks,
        "completion_record": completion,
        "limits": [
            "Matrix, rule and reviewer field are synthetic and authored for this lab.",
            "The verifier checks structure and the routing rule. It does not establish routing quality.",
            "Rationales are checked for work-shape terms only. A human reviewer must confirm the work shape.",
        ],
    }
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("wrote %s: %s" % (RESULT_PATH, overall))
    return 0 if passes else 1


if __name__ == "__main__":
    sys.exit(main())
