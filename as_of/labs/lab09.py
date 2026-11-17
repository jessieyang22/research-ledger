"""Lab 09: assemble and sample the PM review packet (synthetic data only).

What this lab does, in order:

1. Runs every lab verifier that exists under as_of/labs, each as its own
   Python subprocess: lab01, lab02, lab03, lab05 and lab06. Labs 4, 7 and 8
   are not run here, and lab10 has data files but no script. Both gaps are written
   into the packet's Validation section and into the JSON, not hidden.
2. Runs the packet input proofs in process: wf_earnings_reconciliation,
   wf_macro_vintage, wf_catalyst_exception_queue, wf_portfolio_tieout_factor
   and wf_pm_packet (the last one is used as a validator only). It also checks
   the protected hash of the lab06 input file against the value recorded in
   lab06.json.
3. Looks for a packet-build prompt file in as_of. None exists in the repo, so
   the input list is the fixed INPUT_SPEC below. The JSON records that no
   prompt was found. The lab refuses to build the normal packet if the list of
   inputs it actually ran differs from INPUT_SPEC.
4. Applies the input validators. A proof's own passed flag is its validator.
   WARN and FAIL findings that a proof reports as expected fixture items (for
   example the deliberate tie-out break) are carried into the Exceptions
   section. They do not fail the validator. If any validator fails, the lab
   writes a failure-only packet and no normal sections.
5. Writes the normal packet to as_of/labs/results/lab09_packet.md. The packet
   has a control header (state cutoff, evidence labels, validation status and
   REVIEW_REQUIRED), then Changed sources, Earnings, Macro, Catalyst,
   Portfolio, Exceptions, Validation and Decision sections. Each section holds
   only summary lines, deltas and open items, and a path to its evidence JSON
   under as_of/labs/results/lab09_evidence/. Every open exception carries its
   smallest repair. The lab does not apply any repair.
6. Samples one item from each class: reported value, estimate change, macro
   vintage, catalyst delta, portfolio total and protected hash. The rule is
   described in the Validation section. Each sample records its path and its
   result. Every WARN or FAIL item is also reviewed (risk-based), and each one
   is listed under Exceptions.
6b. Plants a known fault in a copy of each sampled input (a tampered price, a
    shifted value, a duplicated knowledge time, an out-of-set subject, a wrong
    hash, a shifted proof total). Each sampling judge must reject its planted
    fault. A judge that accepts a planted fault is vacuous, and the lab fails.
7. Runs the packet verifier (verify_packet_text) on the written packet. The
   verifier requires the control header and the nine required sections in
   order, a path that exists for each section, a PASS validation status, a
   REVIEW_REQUIRED review state, and a repair on every exception line.
8. Planted failure A: in memory only, a disposable copy of the packet has its
   "## Macro" heading deleted. The schema check must fail, and only that check.
9. Planted failure B: in memory only, the disposable copy's review status is
   set to APPROVED. The review-state check must fail, and only that check.
10. In memory only, a forced validator failure must produce a failure-only
    packet with no normal sections.
11. Checks that the human approval record exists in as_of/labs/signoffs as
    PENDING_HUMAN. This lab never writes an approval. Approval is a human step.
12. Writes as_of/labs/results/lab09.json with a PASS or FAIL for each check.

Limits, also stated in the JSON: a PASS shows only that the synthetic packet
agrees with the synthetic proofs, the cutoff label and the packet schema
rules in this file. It does not show that any live portfolio, source or
decision is correct. The packet is not approved by this lab.

Topic: PM review packet.

Only as_of.core is imported statically. Every other piece is loaded with
core.component inside a function body. No network calls, no orders, no git,
no settings files. Writes go only under as_of/labs/results and
as_of/labs/signoffs.
"""

import json
import os
import subprocess
import sys
from datetime import timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


LAB_DIR: str = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT: str = os.path.abspath(os.path.join(LAB_DIR, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from as_of.core import AsOfError, SYNTHETIC_SEED, component, stable_hash  # noqa: E402


RESULTS_DIR: str = os.path.join(LAB_DIR, "results")
EVIDENCE_DIR: str = os.path.join(RESULTS_DIR, "lab09_evidence")
PACKET_PATH: str = os.path.join(RESULTS_DIR, "lab09_packet.md")
PRIOR_STATE_PATH: str = os.path.join(RESULTS_DIR, "lab09_prior_state.json")
RESULTS_PATH: str = os.path.join(RESULTS_DIR, "lab09.json")
SIGNOFF_PATH: str = os.path.join(LAB_DIR, "signoffs", "lab09_signoff.json")
LAB06_CSV_PATH: str = os.path.join(LAB_DIR, "data", "lab06_macro_vintages.csv")
LAB06_JSON_PATH: str = os.path.join(RESULTS_DIR, "lab06.json")
SELF_PATH: str = os.path.abspath(__file__)

LAB_ID: str = "lab09"
STATE_CUTOFF: str = "2026-10-27T00:00:00Z"
EVIDENCE_LABELS: str = "SYNTHETIC; NO_LIVE_DATA; NO_NETWORK"
REVIEW_REQUIRED: str = "REVIEW_REQUIRED"
PACKET_TITLE: str = "PM review packet (synthetic, lab09)"

# Lab verifiers run as subprocesses: (lab script, short label).
LAB_VERIFIERS: Tuple[Tuple[str, str], ...] = (
    ("lab01", "routing matrix"),
    ("lab02", "clock and field dictionary"),
    ("lab03", "freeze and checkpoint"),
    ("lab05", "earnings reconciliation and revision"),
    ("lab06", "macro vintage cutoff"),
)
COVERAGE_GAPS: Tuple[str, ...] = (
    "no lab verifier for labs 4, 7 and 8 under as_of/labs",
    "lab10 has data files under as_of/labs/data but no lab script",
)

# The exact input list for the packet. Each entry is (input id, kind).
INPUT_SPEC: Tuple[Tuple[str, str], ...] = (
    ("lab_verifier:lab01", "lab_verifier"),
    ("lab_verifier:lab02", "lab_verifier"),
    ("lab_verifier:lab03", "lab_verifier"),
    ("lab_verifier:lab05", "lab_verifier"),
    ("lab_verifier:lab06", "lab_verifier"),
    ("proof:earnings", "proof"),
    ("proof:macro", "proof"),
    ("proof:catalyst", "proof"),
    ("proof:portfolio", "proof"),
    ("proof:pm_packet", "proof"),
    ("protected_hash:lab06_input", "protected_hash"),
)

# Normal packet sections in the required order: (heading, key).
SECTION_SPEC: Tuple[Tuple[str, str], ...] = (
    ("Changed sources", "changed_sources"),
    ("Earnings", "earnings"),
    ("Macro", "macro"),
    ("Catalyst", "catalyst"),
    ("Portfolio", "portfolio"),
    ("Exceptions", "exceptions"),
    ("Validation", "validation"),
    ("Decision", "decision"),
)
REQUIRED_HEADINGS: Tuple[str, ...] = tuple(h for h, _ in SECTION_SPEC)
CONTROL_KEYS: Tuple[str, ...] = ("state_cutoff", "evidence_labels", "validation_status", "review_status")

SOURCE_SPEC: Tuple[Tuple[str, str], ...] = (
    ("SRC_LAB06_INPUT", "as_of/labs/data/lab06_macro_vintages.csv"),
    ("SRC_LAB06_RESULT", "as_of/labs/results/lab06.json"),
    ("SRC_PROOF_EARNINGS", "as_of/wf_earnings_reconciliation.py"),
    ("SRC_PROOF_MACRO", "as_of/wf_macro_vintage.py"),
    ("SRC_PROOF_CATALYST", "as_of/wf_catalyst_exception_queue.py"),
    ("SRC_PROOF_PORTFOLIO", "as_of/wf_portfolio_tieout_factor.py"),
    ("SRC_PROOF_PM_PACKET", "as_of/wf_pm_packet.py"),
)

# Smallest proposed repair for each kind of open finding. A repair is text for
# a person to act on. Nothing in this lab applies it.
REPAIR_BY_CHECK: Dict[str, str] = {
    "CLAIM_UNLINKED": "link the claim to a catalyst id in the register, or record why it has no catalyst link",
    "CHECK_FAILED": "repoint the claim's catalyst link to a registered catalyst id, or remove the link",
    "tieout.break": "reconcile the quantity gap named in the message against the booking or custodian record",
    "claim_open": "finish the claim review and set its status, so the claim is no longer open",
}
DEFAULT_REPAIR: str = "owner to decide the repair; none proposed by this lab"

PROOF_METRIC_KEYS: Dict[str, Tuple[str, ...]] = {
    "earnings": ("n_reports", "n_bridges_with_expected", "n_lookahead_rows", "n_unregistered_sources",
                 "n_beat", "n_miss", "n_inline"),
    "macro": ("vintage_count", "observation_count", "decision_count", "violation_count",
              "revised_observation_count"),
    "catalyst": ("queue_size", "expected_count", "matched", "filing_occurred_count"),
    "portfolio": ("tieout_matched", "tieout_break_count", "hard_fail_count", "beta_max_abs_error", "book_value"),
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _rel(path: str) -> str:
    """Repo-relative path with forward slashes."""
    return os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")


def _check(check_id: str, ok: bool, message: str) -> Dict[str, str]:
    """One check row for the JSON: PASS or FAIL with a message."""
    return {"check_id": check_id, "status": "PASS" if ok else "FAIL", "message": message}


def _finding_dict(finding: Any) -> Dict[str, str]:
    """Plain dict for a core.Finding."""
    return {
        "check_id": finding.check_id,
        "status": finding.status.value,
        "message": finding.message,
        "subject": finding.subject,
    }


def _draw(rng: Any, items: Sequence[Any]) -> Any:
    """Seeded uniform draw from a sorted, non-empty list."""
    if not items:
        raise AsOfError("cannot sample from an empty class")
    return items[int(rng.integers(0, len(items)))]


def _safe(fn: Any) -> Tuple[Optional[Any], Optional[str]]:
    """Run fn. Return (value, None) or (None, error text). A raise is never fatal."""
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001 - any failure becomes a validator FAIL
        return None, "%s: %s" % (type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# Inputs: lab verifiers, proofs, protected hash
# ---------------------------------------------------------------------------


def run_lab_verifiers() -> List[Dict[str, Any]]:
    """Run each lab script in a subprocess and record its exit code."""
    env = dict(os.environ)
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = REPO_ROOT + (os.pathsep + prior if prior else "")
    rows: List[Dict[str, Any]] = []
    for lab, label in LAB_VERIFIERS:
        script = os.path.join(LAB_DIR, lab + ".py")
        if not os.path.isfile(script):
            rows.append({"lab": lab, "label": label, "exit_code": None, "passed": False,
                         "last_line": "script missing"})
            continue
        proc = subprocess.run(
            [sys.executable, script],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        rows.append({
            "lab": lab,
            "label": label,
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "last_line": lines[-1][:200] if lines else "",
        })
    return rows


def run_proofs() -> Dict[str, Any]:
    """Run the five packet proofs in process. Each entry is a ProofResult or an error string."""
    specs = (
        ("earnings", "wf_earnings_reconciliation", "run_earnings_proof"),
        ("macro", "wf_macro_vintage", "run_macro_proof"),
        ("catalyst", "wf_catalyst_exception_queue", "run_catalyst_proof"),
        ("portfolio", "wf_portfolio_tieout_factor", "run_tieout_factor_proof"),
        ("pm_packet", "wf_pm_packet", "run_pm_packet_proof"),
    )
    out: Dict[str, Any] = {}
    for key, module_name, fn_name in specs:
        def _call(module_name: str = module_name, fn_name: str = fn_name) -> Any:
            return getattr(component(module_name), fn_name)()
        value, err = _safe(_call)
        out[key] = value if err is None else err
    return out


def read_hash_pair() -> Tuple[Optional[str], Optional[str], str]:
    """Current sha256 of the lab06 input and the recorded value. None when unreadable."""
    content_hash = component("content_hash")
    try:
        current = content_hash.sha256_file(LAB06_CSV_PATH)
        with open(LAB06_JSON_PATH, "r", encoding="utf-8") as handle:
            recorded = json.load(handle)["input_sha256"]
    except (OSError, KeyError, ValueError) as exc:
        return None, None, "cannot read protected hash inputs: %s" % exc
    return current, recorded, "current=%s recorded=%s" % (current[:16], str(recorded)[:16])


def protected_hash_check() -> Tuple[bool, str]:
    """The lab06 input file must still hash to the value lab06.json recorded."""
    current, recorded, detail = read_hash_pair()
    return judge_hash(current, recorded), detail


def gather_inputs() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Run every input and return validator rows plus the raw proof results."""
    lab_rows = run_lab_verifiers()
    proofs = run_proofs()
    hash_ok, hash_detail = protected_hash_check()

    validators: List[Dict[str, Any]] = []
    for row in lab_rows:
        validators.append({
            "input_id": "lab_verifier:%s" % row["lab"],
            "kind": "lab_verifier",
            "passed": bool(row["passed"]),
            "detail": "exit_code=%s last_line=%s" % (row["exit_code"], row["last_line"]),
            "path": "as_of/labs/%s.py" % row["lab"],
        })
    proof_paths = {
        "earnings": "as_of/wf_earnings_reconciliation.py",
        "macro": "as_of/wf_macro_vintage.py",
        "catalyst": "as_of/wf_catalyst_exception_queue.py",
        "portfolio": "as_of/wf_portfolio_tieout_factor.py",
        "pm_packet": "as_of/wf_pm_packet.py",
    }
    for key in ("earnings", "macro", "catalyst", "portfolio", "pm_packet"):
        result = proofs[key]
        if isinstance(result, str):
            validators.append({"input_id": "proof:%s" % key, "kind": "proof", "passed": False,
                               "detail": "raised %s" % result, "path": proof_paths[key]})
        else:
            validators.append({"input_id": "proof:%s" % key, "kind": "proof",
                               "passed": bool(result.passed),
                               "detail": "proof=%s passed=%s findings=%d" % (
                                   result.proof_name, result.passed, len(result.findings)),
                               "path": proof_paths[key]})
    validators.append({
        "input_id": "protected_hash:lab06_input",
        "kind": "protected_hash",
        "passed": hash_ok,
        "detail": hash_detail,
        "path": "as_of/labs/data/lab06_macro_vintages.csv",
    })
    return validators, {"lab_rows": lab_rows, "proofs": proofs, "hash_ok": hash_ok}


def input_list_matches_spec(validators: Sequence[Dict[str, Any]]) -> Tuple[bool, str]:
    """The inputs actually run must equal INPUT_SPEC, in order."""
    actual = tuple(v["input_id"] for v in validators)
    expected = tuple(item for item, _ in INPUT_SPEC)
    if actual == expected:
        return True, "%d inputs match INPUT_SPEC" % len(expected)
    return False, "actual=%s expected=%s" % (actual, expected)


def find_packet_build_prompt() -> Dict[str, Any]:
    """Search as_of for a packet-build prompt file. This file excludes itself."""
    needles = ("packet-build", "packet build prompt", "packet_build_prompt")
    hits: List[str] = []
    skip_dirs = {"results", "__pycache__", ".pytest_cache"}
    for root, dirs, files in os.walk(os.path.join(REPO_ROOT, "as_of")):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for name in files:
            path = os.path.join(root, name)
            if os.path.abspath(path) == SELF_PATH or not name.endswith((".md", ".txt", ".py", ".json")):
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    body = handle.read().lower()
            except (OSError, UnicodeDecodeError):
                continue
            if any(n in body for n in needles):
                hits.append(_rel(path))
    return {"found": bool(hits), "hits": sorted(hits),
            "note": "no packet-build prompt file exists in the repo; INPUT_SPEC was used instead"
            if not hits else "prompt-like text found; confirm it against INPUT_SPEC by hand"}


# ---------------------------------------------------------------------------
# Sampling: one item from each class
# ---------------------------------------------------------------------------


# Judges. Each takes the artifact a sample reads and returns True when the
# item agrees with the procedure. The negative controls call the same judges
# on tampered input, so a judge that cannot reject a planted fault is caught.

STRENGTH: Dict[str, str] = {
    "reported_value": "reproducibility only: the same fixture generator is run a second time",
    "estimate_change": "structural: no tied knowledge times inside the estimate group",
    "macro_vintage": "rule check: newest vintage released by the decision time, on the fixture",
    "catalyst_delta": "proof output against fixture expectations (not an independent recount)",
    "portfolio_total": "independent recount: book value re-summed from positions and close prices",
    "protected_hash": "same comparison as the input validator, not an independent check",
}
PORTFOLIO_TOL: float = 1e-6


def judge_reported(pick_value: Any, rebuilt: Sequence[Any]) -> bool:
    """Pass when a second build holds exactly one row for the item and it has the same value."""
    return len(rebuilt) == 1 and rebuilt[0] == pick_value


def judge_estimate(knowledge_times: Sequence[Any]) -> bool:
    """Pass when a group has at least two rows and no two share a knowledge time."""
    return len(knowledge_times) >= 2 and len(set(knowledge_times)) == len(knowledge_times)


def judge_macro(pick: Any, usable: Sequence[Any]) -> bool:
    """Pass when the sampled vintage is the newest one released by the decision time."""
    if not usable:
        return False
    return max(usable, key=lambda v: v.release_at) == pick


def judge_catalyst(subject: Any, expected_subjects: Any, matched: bool) -> bool:
    """Pass when an open catalyst item is an expected fixture exception and the open list matches."""
    return str(subject) in expected_subjects and bool(matched)


def independent_book_value(positions: Sequence[Any], prices: Mapping[Any, Any], as_of: Any) -> float:
    """Re-sum quantity times close for each position. Does not call market_value."""
    total = 0.0
    for pos in positions:
        rec = prices.get((pos.ticker, as_of))
        if rec is None:
            raise AsOfError("no close for %s on %s" % (pos.ticker, as_of))
        total += float(pos.quantity) * float(rec.close)
    return total


def judge_portfolio(proof_value: Any, independent_value: Any) -> bool:
    """Pass when the proof's book value matches the independent recount within tolerance."""
    if proof_value is None or independent_value is None:
        return False
    return abs(float(proof_value) - float(independent_value)) <= PORTFOLIO_TOL * max(1.0, abs(float(independent_value)))


def judge_hash(current: Any, recorded: Any) -> bool:
    """Pass when the current file hash equals the recorded hash."""
    return current is not None and recorded is not None and current == recorded


def _tieout_fixture() -> Dict[str, Any]:
    """The portfolio proof's own fixture for the default seed (same inputs the proof valued)."""
    tieout = component("wf_portfolio_tieout_factor")
    return tieout._build_fixture(SYNTHETIC_SEED)


def sample_items(proofs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Sample one item per class with a seeded draw. Rule: seed SYNTHETIC_SEED + class index,
    over items sorted by a stable key. Each sample reports its path, result and strength."""
    core = component("core")
    earnings_fixture = component("earnings_fixture")
    macro_fixture = component("macro_fixture")
    catalyst_fixture = component("catalyst_fixture")
    tieout = component("wf_portfolio_tieout_factor")
    samples: List[Dict[str, Any]] = []

    # 1. reported value
    rng = core.make_rng(SYNTHETIC_SEED + 1)
    fx = earnings_fixture.make_fixture()
    reports = sorted(fx["reports"], key=lambda r: (r["ticker"], r["metric"], r["period"]))
    pick = _draw(rng, reports)
    key = (pick["ticker"], pick["metric"], pick["period"])
    again = [r for r in earnings_fixture.make_fixture()["reports"]
             if (r["ticker"], r["metric"], r["period"]) == key]
    ok = judge_reported(pick["reported_value"], [r["reported_value"] for r in again])
    samples.append({
        "class": "reported_value",
        "item": "%s|%s|%s" % key,
        "path": "as_of/earnings_fixture.py",
        "strength": STRENGTH["reported_value"],
        "result": "PASS" if ok else "FAIL",
        "detail": "reported_value=%s; matching rows in a second fixture build=%d; value equal: %s" % (
            pick["reported_value"], len(again), ok),
    })

    # 2. estimate change: latest knowledge row against earliest for one estimate group
    rng = core.make_rng(SYNTHETIC_SEED + 2)
    groups: Dict[Tuple[str, str, str], List[Any]] = {}
    for est in fx["estimates"]:
        groups.setdefault((est.ticker, est.metric, est.period), []).append(est)
    multi = sorted(k for k, rows in groups.items() if len(rows) >= 2)
    gkey = _draw(rng, multi)
    rows = sorted(groups[gkey], key=lambda e: e.knowledge_at)
    change = rows[-1].value - rows[0].value
    ok = judge_estimate([e.knowledge_at for e in rows])
    samples.append({
        "class": "estimate_change",
        "item": "%s|%s|%s" % gkey,
        "path": "as_of/earnings_fixture.py",
        "strength": STRENGTH["estimate_change"],
        "result": "PASS" if ok else "FAIL",
        "detail": "%d rows; first=%s last=%s change=%s; knowledge times distinct: %s" % (
            len(rows), rows[0].value, rows[-1].value, round(change, 6), ok),
    })

    # 3. macro vintage: the vintage must be the newest one released by the decision time
    rng = core.make_rng(SYNTHETIC_SEED + 3)
    vintages = sorted(macro_fixture.make_macro_fixture(),
                      key=lambda v: (v.series_id, v.obs_date, v.vintage_date))
    vpick = _draw(rng, vintages)
    decision_at = vpick.release_at + timedelta(days=1)
    usable = [v for v in vintages if v.series_id == vpick.series_id and v.obs_date == vpick.obs_date
              and v.release_at <= decision_at]
    ok = judge_macro(vpick, usable)
    newest = max(usable, key=lambda v: v.release_at)
    samples.append({
        "class": "macro_vintage",
        "item": "%s|%s|%s" % (vpick.series_id, vpick.obs_date.isoformat(), vpick.vintage_date.isoformat()),
        "path": "as_of/macro_fixture.py",
        "strength": STRENGTH["macro_vintage"],
        "result": "PASS" if ok else "FAIL",
        "detail": "value=%s; newest vintage released by decision time %s is %s" % (
            vpick.value, decision_at.isoformat(), newest.vintage_date.isoformat()),
    })

    # 4. catalyst delta: an open WARN item must be one of the fixture's expected exceptions
    rng = core.make_rng(SYNTHETIC_SEED + 4)
    cat = proofs["catalyst"]
    warn_items = sorted(
        ((f.check_id, f.subject) for f in cat.findings if f.status.value != "pass"),
    )
    cpick = _draw(rng, warn_items)
    fixture = catalyst_fixture.make_catalyst_fixture()
    expected_subjects = {str(subject) for _, subject in fixture["exceptions_expected"]}
    matched = cat.metrics.get("matched") == 1.0
    ok = judge_catalyst(cpick[1], expected_subjects, matched)
    samples.append({
        "class": "catalyst_delta",
        "item": "%s|%s" % cpick,
        "path": "as_of/catalyst_fixture.py",
        "strength": STRENGTH["catalyst_delta"],
        "result": "PASS" if ok else "FAIL",
        "detail": "subject in expected exceptions: %s; open list matches expected multiset: %s" % (
            str(cpick[1]) in expected_subjects, matched),
    })

    # 5. portfolio total: the proof's book value against an independent re-sum of the book
    rng = core.make_rng(SYNTHETIC_SEED + 5)
    proof_value = proofs["portfolio"].metrics.get("book_value")
    tf = _tieout_fixture()
    recount = independent_book_value(tf["book"], tf["prices"], tf["as_of"])
    _ = _draw(rng, ["book_value"])  # the class has one item; the draw keeps the rule uniform
    ok = judge_portfolio(proof_value, recount)
    samples.append({
        "class": "portfolio_total",
        "item": "book_value",
        "path": "as_of/wf_portfolio_tieout_factor.py",
        "strength": STRENGTH["portfolio_total"],
        "result": "PASS" if ok else "FAIL",
        "detail": "proof book_value=%s; independent re-sum=%.4f; within tolerance: %s" % (
            proof_value, recount, ok),
    })

    # 6. protected hash: lab06 input file against the recorded hash
    _ = _draw(core.make_rng(SYNTHETIC_SEED + 6), ["lab06_input"])
    current, recorded, hash_detail = read_hash_pair()
    ok = judge_hash(current, recorded)
    samples.append({
        "class": "protected_hash",
        "item": "lab06_macro_vintages.csv",
        "path": "as_of/labs/data/lab06_macro_vintages.csv",
        "strength": STRENGTH["protected_hash"],
        "result": "PASS" if ok else "FAIL",
        "detail": hash_detail,
    })
    return samples


def negative_controls(proofs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Planted-fault controls. Each judge is run on a tampered copy of the input it reads.
    rejected=True means the judge caught the planted fault, as it must."""
    earnings_fixture = component("earnings_fixture")
    macro_fixture = component("macro_fixture")
    catalyst_fixture = component("catalyst_fixture")
    controls: List[Dict[str, Any]] = []

    def _row(cls: str, planted: str, rejected: bool, detail: str) -> None:
        controls.append({"class": cls, "planted": planted, "rejected": bool(rejected), "detail": detail})

    # reported value: a rebuilt value shifted by 1.0, and an empty rebuild
    fx = earnings_fixture.make_fixture()
    reports = sorted(fx["reports"], key=lambda r: (r["ticker"], r["metric"], r["period"]))
    value = reports[0]["reported_value"]
    rej = (not judge_reported(value, [value + 1.0])) and (not judge_reported(value, []))
    _row("reported_value", "rebuilt value +1.0 and empty rebuild", rej,
         "judge rejects both: %s" % rej)

    # estimate change: the same knowledge time twice in one group
    groups: Dict[Tuple[str, str, str], List[Any]] = {}
    for est in fx["estimates"]:
        groups.setdefault((est.ticker, est.metric, est.period), []).append(est)
    multi = sorted(k for k, rows in groups.items() if len(rows) >= 2)
    if multi:
        t0 = groups[multi[0]][0].knowledge_at
        rej = not judge_estimate([t0, t0])
        _row("estimate_change", "two rows with one knowledge time", rej, "judge rejects: %s" % rej)
    else:
        _row("estimate_change", "no multi-row group to plant in", False, "no control possible")

    # macro vintage: a group of at least two vintages, with the oldest picked as the sample
    mgroups: Dict[Tuple[str, Any], List[Any]] = {}
    for v in macro_fixture.make_macro_fixture():
        mgroups.setdefault((v.series_id, v.obs_date), []).append(v)
    mmulti = sorted(k for k, rows in mgroups.items() if len(rows) >= 2)
    if mmulti:
        members = sorted(mgroups[mmulti[0]], key=lambda v: v.release_at)
        rej = not judge_macro(members[0], members)
        _row("macro_vintage", "oldest vintage picked while a newer one is released", rej,
             "judge rejects: %s" % rej)
    else:
        _row("macro_vintage", "no multi-vintage group to plant in", False, "no control possible")

    # catalyst: an unexpected subject, and an expected subject with the open list not matching
    expected = {str(s) for _, s in catalyst_fixture.make_catalyst_fixture()["exceptions_expected"]}
    some_expected = sorted(expected)[0]
    rej = (not judge_catalyst("SYN_CONTROL_UNEXPECTED", expected, True)) and \
        (not judge_catalyst(some_expected, expected, False))
    _row("catalyst_delta", "unexpected subject; expected subject with open list mismatch", rej,
         "judge rejects both: %s" % rej)

    # portfolio: the proof value shifted by 1.0, and one close shifted by 1.0 in a copy of the prices
    tf = _tieout_fixture()
    proof_value = getattr(proofs["portfolio"], "metrics", {}).get("book_value")
    if proof_value is not None:
        clean = independent_book_value(tf["book"], tf["prices"], tf["as_of"])
        bad_prices = dict(tf["prices"])
        k = (tf["book"][0].ticker, tf["as_of"])
        rec = bad_prices[k]
        bad_prices[k] = rec.__class__(ticker=rec.ticker, as_of=rec.as_of,
                                      close=rec.close + 1.0, source_id=rec.source_id)
        tampered = independent_book_value(tf["book"], bad_prices, tf["as_of"])
        rej = (not judge_portfolio(proof_value + 1.0, clean)) and (not judge_portfolio(proof_value, tampered))
        _row("portfolio_total", "proof value +1.0; one close +1.0 in the recount", rej,
             "judge rejects both: %s" % rej)
    else:
        _row("portfolio_total", "no proof value to plant in", False, "no control possible")

    # protected hash: a wrong current hash, and a missing recorded value
    current, recorded, _ = read_hash_pair()
    rej = (not judge_hash("0" * 64, recorded)) and (not judge_hash(current, None))
    _row("protected_hash", "current hash replaced by zeros; recorded value missing", rej,
         "judge rejects both: %s" % rej)
    return controls


def risk_based_items(proofs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every WARN or FAIL item in the proofs is reviewed, not sampled."""
    items: List[Dict[str, Any]] = []
    for key in ("earnings", "macro", "catalyst", "portfolio", "pm_packet"):
        result = proofs[key]
        if isinstance(result, str):
            continue
        for f in result.findings:
            if f.status.value != "pass":
                items.append({"source": key, **_finding_dict(f)})
    return items


# ---------------------------------------------------------------------------
# Packet assembly
# ---------------------------------------------------------------------------


def _proof_summary(key: str, result: Any) -> Dict[str, Any]:
    """Plain payload for one proof section: pass flag, counts, metrics and open items."""
    if isinstance(result, str):
        return {"proof": key, "passed": False, "error": result, "findings_total": 0,
                "findings_open": 0, "metrics": {}, "open": []}
    open_items = [_finding_dict(f) for f in result.findings if f.status.value != "pass"]
    metrics = {k: float(v) for k, v in result.metrics.items() if k in PROOF_METRIC_KEYS[key]}
    return {
        "proof": result.proof_name,
        "passed": bool(result.passed),
        "findings_total": len(result.findings),
        "findings_open": len(open_items),
        "metrics": {k: metrics[k] for k in sorted(metrics)},
        "open": open_items,
    }


def _metrics_line(metrics: Dict[str, float]) -> str:
    return ", ".join("%s=%s" % (k, ("%g" % v)) for k, v in metrics.items()) or "none"


def build_evidence(validators: Sequence[Dict[str, Any]], raw: Dict[str, Any],
                   samples: Sequence[Dict[str, Any]], controls: Sequence[Dict[str, Any]],
                   risk_items: Sequence[Dict[str, Any]],
                   prior_state: Dict[str, Any], prompt: Dict[str, Any]) -> Dict[str, Any]:
    """Payloads for each normal section. Changed flags compare with the prior run."""
    summaries = {k: _proof_summary(k, raw["proofs"][k]) for k in ("earnings", "macro", "catalyst", "portfolio")}
    exceptions = []
    for item in risk_items:
        check_id = item["check_id"]
        exceptions.append({
            "source": item["source"],
            "check_id": check_id,
            "status": item["status"],
            "subject": item["subject"],
            "message": item["message"],
            "repair": REPAIR_BY_CHECK.get(check_id, DEFAULT_REPAIR),
            "repair_applied": False,
        })
    evidence: Dict[str, Any] = {
        "earnings": summaries["earnings"],
        "macro": summaries["macro"],
        "catalyst": summaries["catalyst"],
        "portfolio": summaries["portfolio"],
        "exceptions": {"open": exceptions},
        "validation": {
            "inputs": list(validators),
            "lab_verifiers": raw["lab_rows"],
            "coverage_gaps": list(COVERAGE_GAPS) + (
                [] if prompt["found"] else ["no packet-build prompt file in as_of; INPUT_SPEC was used"]),
            "samples": list(samples),
            "negative_controls": list(controls),
            "risk_based_rule": "every WARN or FAIL proof item is reviewed and listed under Exceptions",
            "sampling_rule": "one seeded draw per class (seed SYNTHETIC_SEED + class index) over items "
                             "sorted by a stable key; plus the risk-based review above",
        },
        "decision": {
            "decision": "NONE_RECORDED",
            "review_status": REVIEW_REQUIRED,
            "approval_record": _rel(SIGNOFF_PATH),
            "note": "this lab does not record approval; a named human reviewer does",
        },
    }
    # Section hashes compare with the prior run. The changed-sources section reads them.
    prior_sections = prior_state.get("sections", {})
    section_states: Dict[str, str] = {}
    for _, key in SECTION_SPEC:
        if key == "changed_sources":
            continue
        digest = stable_hash(evidence[key])
        if key not in prior_sections:
            section_states[key] = "baseline"
        else:
            section_states[key] = "changed" if prior_sections[key] != digest else "unchanged"
        evidence.setdefault("_section_hashes", {})[key] = digest
    sources = []
    prior_sources = prior_state.get("sources", {})
    source_hashes: Dict[str, str] = {}
    content_hash = component("content_hash")
    for src_id, rel in SOURCE_SPEC:
        digest = content_hash.sha256_file(os.path.join(REPO_ROOT, rel))
        source_hashes[src_id] = digest
        if src_id not in prior_sources:
            state = "baseline"
        else:
            state = "changed" if prior_sources[src_id] != digest else "unchanged"
        sources.append({"source_id": src_id, "path": rel, "sha256": digest, "state": state})
    evidence["changed_sources"] = {
        "sources": sources,
        "section_states": section_states,
        "source_hashes": source_hashes,
    }
    return evidence


def _evidence_rel(key: str) -> str:
    return _rel(os.path.join(EVIDENCE_DIR, key + ".json"))


def render_normal_packet(evidence: Dict[str, Any], packet_hash: str) -> str:
    """Markdown for the normal packet. Each section names its evidence path first."""
    lines: List[str] = []
    lines.append("# " + PACKET_TITLE)
    lines.append("")
    lines.append("## Control header")
    lines.append("- state_cutoff: %s" % STATE_CUTOFF)
    lines.append("- evidence_labels: %s" % EVIDENCE_LABELS)
    lines.append("- validation_status: PASS")
    lines.append("- review_status: %s" % REVIEW_REQUIRED)
    lines.append("- packet_type: normal")
    lines.append("- packet_hash: %s" % packet_hash)
    lines.append("- path: as_of/labs/results/lab09_packet.md")
    lines.append("")

    cs = evidence["changed_sources"]
    lines.append("## Changed sources")
    lines.append("- path: %s" % _evidence_rel("changed_sources"))
    for src in cs["sources"]:
        if src["state"] != "unchanged":
            lines.append("- source %s: %s (sha256 %s) state=%s" % (
                src["source_id"], src["path"], src["sha256"][:16], src["state"]))
    lines.append("- sources registered: %d; sources unchanged since prior run: %d" % (
        len(cs["sources"]), sum(1 for s in cs["sources"] if s["state"] == "unchanged")))
    changed_sections = [k for k, v in cs["section_states"].items() if v != "unchanged"]
    lines.append("- section hashes not unchanged (baseline or changed): %s" % (
        ", ".join(changed_sections) if changed_sections else "none"))
    lines.append("")

    for heading, key, label in (
        ("Earnings", "earnings", "earnings reconciliation"),
        ("Macro", "macro", "macro vintage"),
        ("Catalyst", "catalyst", "catalyst exception queue"),
        ("Portfolio", "portfolio", "portfolio tie-out and factor"),
    ):
        payload = evidence[key]
        lines.append("## " + heading)
        lines.append("- path: %s" % _evidence_rel(key))
        lines.append("- proof: %s (%s) passed=%s" % (payload["proof"], label, payload["passed"]))
        lines.append("- checks: %d run, %d open; only open items and key metrics are shown here" % (
            payload["findings_total"], payload["findings_open"]))
        lines.append("- key metrics: %s" % _metrics_line(payload["metrics"]))
        if payload["open"]:
            for item in payload["open"]:
                lines.append("- open: %s %s (%s): %s (see Exceptions)" % (
                    item["check_id"], item["subject"], item["status"], item["message"]))
        else:
            lines.append("- open: none")
        lines.append("")

    lines.append("## Exceptions")
    lines.append("- path: %s" % _evidence_rel("exceptions"))
    open_items = evidence["exceptions"]["open"]
    lines.append("- open exceptions: %d (each carries its smallest repair; no repair was applied)" % len(open_items))
    for item in open_items:
        lines.append("- exception: %s subject=%s status=%s source=%s message=%s | repair: %s" % (
            item["check_id"], item["subject"], item["status"], item["source"], item["message"], item["repair"]))
    lines.append("")

    val = evidence["validation"]
    lines.append("## Validation")
    lines.append("- path: %s" % _evidence_rel("validation"))
    lines.append("- validation_status: PASS (all %d inputs in INPUT_SPEC passed)" % len(val["inputs"]))
    for row in val["lab_verifiers"]:
        lines.append("- lab verifier %s (%s): passed=%s exit_code=%s" % (
            row["lab"], row["label"], row["passed"], row["exit_code"]))
    for row in val["inputs"]:
        if row["kind"] != "lab_verifier":
            lines.append("- input %s: passed=%s %s" % (row["input_id"], row["passed"], row["detail"]))
    for gap in val["coverage_gaps"]:
        lines.append("- coverage gap: %s" % gap)
    lines.append("- sampling rule: %s" % val["sampling_rule"])
    lines.append("- risk-based rule: %s" % val["risk_based_rule"])
    for sample in val["samples"]:
        lines.append("- sample %s: item=%s path=%s result=%s strength=%s detail=%s" % (
            sample["class"], sample["item"], sample["path"], sample["result"], sample["strength"], sample["detail"]))
    for ctl in val["negative_controls"]:
        lines.append("- negative control %s: planted=%s rejected=%s detail=%s" % (
            ctl["class"], ctl["planted"], ctl["rejected"], ctl["detail"]))
    lines.append("")

    dec = evidence["decision"]
    lines.append("## Decision")
    lines.append("- path: %s" % dec["approval_record"])
    lines.append("- decision: %s" % dec["decision"])
    lines.append("- review_status: %s" % dec["review_status"])
    lines.append("- note: %s" % dec["note"])
    lines.append("")
    return "\n".join(lines)


def render_failure_only_packet(failed: Sequence[Dict[str, Any]], all_inputs: Sequence[Dict[str, Any]]) -> str:
    """Failure-only packet: control header and the failed inputs, nothing else."""
    lines: List[str] = []
    lines.append("# " + PACKET_TITLE)
    lines.append("")
    lines.append("## Control header")
    lines.append("- state_cutoff: %s" % STATE_CUTOFF)
    lines.append("- evidence_labels: %s" % EVIDENCE_LABELS)
    lines.append("- validation_status: FAIL")
    lines.append("- review_status: %s" % REVIEW_REQUIRED)
    lines.append("- packet_type: failure_only")
    lines.append("")
    lines.append("## Failed inputs")
    lines.append("- inputs failed: %d of %d; the normal packet was not built" % (len(failed), len(all_inputs)))
    for row in failed:
        lines.append("- failed %s: %s | repair: re-run the input and fix the failure before any packet is built" % (
            row["input_id"], row["detail"]))
    lines.append("")
    return "\n".join(lines)


def assemble(validators: Sequence[Dict[str, Any]], build_normal: Any) -> Tuple[str, str]:
    """Return (packet_type, markdown). build_normal() is called only when every validator passes."""
    failed = [v for v in validators if not v["passed"]]
    if failed:
        return "failure_only", render_failure_only_packet(failed, validators)
    return "normal", build_normal()


# ---------------------------------------------------------------------------
# Packet verifier
# ---------------------------------------------------------------------------


def _split_sections(text: str) -> List[Tuple[str, List[str]]]:
    """(heading, body lines) for each '## ' heading in order."""
    sections: List[Tuple[str, List[str]]] = []
    current: Optional[Tuple[str, List[str]]] = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = (line[3:].strip(), [])
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    return sections


def _control_values(body: List[str]) -> Dict[str, str]:
    """Key: value lines of the control header body."""
    out: Dict[str, str] = {}
    for line in body:
        if line.startswith("- ") and ": " in line:
            key, value = line[2:].split(": ", 1)
            out[key.strip()] = value.strip()
    return out


def verify_packet_text(text: str, repo_root: str) -> List[Dict[str, str]]:
    """Packet schema and status checks for a packet given as Markdown text."""
    checks: List[Dict[str, str]] = []
    sections = _split_sections(text)
    names = [h for h, _ in sections]
    bodies = dict(sections)  # headings are unique in a valid packet; a duplicate is caught below

    # Control header keys and values.
    header = _control_values(bodies.get("Control header", []))
    missing_keys = [k for k in CONTROL_KEYS if k not in header]
    checks.append(_check("schema_control_header", "Control header" in bodies and not missing_keys,
                         "control header present with keys %s; missing=%s" % (
                             ", ".join(CONTROL_KEYS), missing_keys or "none")))

    # Required headings: present once each, in the required order.
    missing = [h for h in REQUIRED_HEADINGS if h not in names]
    dups = sorted({h for h in names if names.count(h) > 1})
    order_ok = False
    if not missing and not dups:
        idx = [names.index(h) for h in REQUIRED_HEADINGS]
        order_ok = idx == sorted(idx)
    checks.append(_check("schema_required_sections",
                         not missing and not dups and order_ok,
                         "required sections %s; missing=%s duplicated=%s order_ok=%s" % (
                             ", ".join(REQUIRED_HEADINGS), missing or "none", dups or "none", order_ok)))

    # Each required section links to a path that exists and has at least one bullet.
    bad_paths: List[str] = []
    for heading in REQUIRED_HEADINGS:
        body = bodies.get(heading, [])
        paths = [ln[len("- path: "):].strip() for ln in body if ln.startswith("- path: ")]
        if not paths:
            bad_paths.append("%s(no path)" % heading)
            continue
        for rel in paths:
            full = os.path.normpath(os.path.join(repo_root, rel))
            if os.path.isabs(rel) or rel.startswith("..") or not os.path.exists(full):
                bad_paths.append("%s(%s)" % (heading, rel))
        if not any(ln.startswith("- ") for ln in body):
            bad_paths.append("%s(empty)" % heading)
    checks.append(_check("schema_section_paths", not bad_paths,
                         "each required section links to an existing path; problems=%s" % (
                             bad_paths or "none")))

    # Every exception line carries a smallest repair.
    exc_lines = [ln for ln in bodies.get("Exceptions", []) if ln.startswith("- exception:")]
    no_repair = [ln[:60] for ln in exc_lines if "| repair:" not in ln]
    checks.append(_check("schema_exception_repairs", not no_repair,
                         "%d exception lines, each with a repair; without repair=%s" % (
                             len(exc_lines), no_repair or "none")))

    # Validation status must be PASS.
    vstatus = header.get("validation_status", "<missing>")
    checks.append(_check("validation_status_pass", vstatus == "PASS",
                         "control header validation_status=%s (required PASS)" % vstatus))

    # Review state must be REVIEW_REQUIRED. APPROVED is not allowed in a packet.
    rstatus = header.get("review_status", "<missing>")
    checks.append(_check("review_state_review_required", rstatus == REVIEW_REQUIRED,
                         "control header review_status=%s (required %s; approval lives in signoffs)" % (
                             rstatus, REVIEW_REQUIRED)))
    return checks


def verify_packet_file(path: str) -> List[Dict[str, str]]:
    """Read a packet file and run the packet verifier on it."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        return [_check("packet_readable", False, "cannot read packet: %s" % exc)]
    return verify_packet_text(text, REPO_ROOT)


def failing_ids(checks: Sequence[Dict[str, str]]) -> List[str]:
    return [c["check_id"] for c in checks if c["status"] == "FAIL"]


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------


def _load_prior_state() -> Dict[str, Any]:
    """Prior hashes from the last run. Missing or unreadable means a fresh baseline."""
    try:
        with open(PRIOR_STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def run_lab() -> Dict[str, Any]:
    checks: List[Dict[str, str]] = []
    prior_state = _load_prior_state()

    # Inputs and validators.
    validators, raw = gather_inputs()
    for row in validators:
        checks.append(_check("input.%s" % row["input_id"], row["passed"], row["detail"]))
    spec_ok, spec_msg = input_list_matches_spec(validators)
    checks.append(_check("input_list_matches_spec", spec_ok, spec_msg))
    prompt = find_packet_build_prompt()
    checks.append(_check("packet_build_prompt_checked", True,
                         "found=%s; %s" % (prompt["found"], prompt["note"])))

    all_valid = all(v["passed"] for v in validators) and spec_ok
    samples = sample_items(raw["proofs"])
    risk_items = risk_based_items(raw["proofs"])
    for sample in samples:
        checks.append(_check("sample.%s" % sample["class"], sample["result"] == "PASS",
                             "%s path=%s: %s" % (sample["item"], sample["path"], sample["detail"])))
    controls = negative_controls(raw["proofs"])
    for ctl in controls:
        checks.append(_check("control.%s" % ctl["class"], ctl["rejected"],
                             "planted=%s; %s" % (ctl["planted"], ctl["detail"])))

    # Build evidence and the packet. A normal packet is refused if any input failed.
    evidence = build_evidence(validators, raw, samples, controls, risk_items, prior_state, prompt)
    section_hashes = evidence.pop("_section_hashes", {})
    evidence_payload_hash = stable_hash(evidence)

    def _build_normal() -> str:
        packet_hash = stable_hash({"evidence": evidence, "section_hashes": section_hashes})
        return render_normal_packet(evidence, packet_hash)

    packet_type, text = assemble(validators, _build_normal)
    checks.append(_check("normal_packet_built_only_if_inputs_pass", (packet_type == "normal") == all_valid,
                         "packet_type=%s; all inputs valid=%s" % (packet_type, all_valid)))

    packet_written = False
    if packet_type == "normal":
        for key, payload in evidence.items():
            _write_json(os.path.join(EVIDENCE_DIR, key + ".json"), payload)
        _write_text(PACKET_PATH, text)
        packet_written = True

    live_checks = verify_packet_file(PACKET_PATH) if packet_written else [
        _check("packet_written", False, "normal packet not built; failure-only packet only")]
    checks.extend(live_checks)

    # Human approval is stored separately. This lab only checks that it is pending.
    try:
        with open(SIGNOFF_PATH, "r", encoding="utf-8") as handle:
            signoff = json.load(handle)
        sign_ok = signoff.get("status") == "PENDING_HUMAN" and not signoff.get("approved_by")
        sign_msg = "status=%s approved_by=%s" % (signoff.get("status"), signoff.get("approved_by"))
    except (OSError, ValueError) as exc:
        sign_ok, sign_msg = False, "cannot read signoff record: %s" % exc
    checks.append(_check("signoff_record_pending_separately", sign_ok, sign_msg))

    # Planted failure A: a disposable copy with the Macro heading removed (in memory only).
    if packet_written:
        with open(PACKET_PATH, "r", encoding="utf-8") as handle:
            live_text = handle.read()
    else:
        live_text = text
    heading_line = "## Macro\n"
    planted_a_text = live_text.replace(heading_line, "", 1)
    planted_a = verify_packet_text(planted_a_text, REPO_ROOT)
    a_fail = failing_ids(planted_a)
    # A missing heading must fail the required-sections check. The path check also fails,
    # because the Macro section has no path. No status check should fail.
    a_ok = "schema_required_sections" in a_fail and set(a_fail) <= {
        "schema_required_sections", "schema_section_paths"}
    checks.append(_check("planted.A_macro_heading_deleted_schema_fails",
                         a_ok,
                         "heading removed in memory; failing checks=%s" % (a_fail or "none")))

    # Planted failure B: a disposable copy with the review status set to APPROVED (in memory only).
    planted_b_text = live_text.replace("- review_status: %s\n" % REVIEW_REQUIRED,
                                       "- review_status: APPROVED\n", 1)
    planted_b = verify_packet_text(planted_b_text, REPO_ROOT)
    b_fail = failing_ids(planted_b)
    checks.append(_check("planted.B_review_status_approved_status_fails",
                         b_fail == ["review_state_review_required"],
                         "review_status set to APPROVED in memory; failing checks=%s" % (b_fail or "none")))

    # Planted failure C: validation_status set to FAIL in memory. Only the status check may fail.
    planted_c_text = live_text.replace("- validation_status: PASS\n", "- validation_status: FAIL\n", 1)
    c_fail = failing_ids(verify_packet_text(planted_c_text, REPO_ROOT))
    checks.append(_check("planted.C_validation_status_fail_status_fails",
                         c_fail == ["validation_status_pass"],
                         "validation_status set to FAIL in memory; failing checks=%s" % (c_fail or "none")))

    # Planted failure D: the repair clause stripped from one exception line. Only the repair check may fail.
    d_lines = [ln for ln in live_text.splitlines() if ln.startswith("- exception:") and "| repair:" in ln]
    if d_lines:
        planted_d_text = live_text.replace(d_lines[0], d_lines[0].split(" | repair:")[0], 1)
        d_fail = failing_ids(verify_packet_text(planted_d_text, REPO_ROOT))
        d_ok = d_fail == ["schema_exception_repairs"]
        d_msg = "one exception line stripped of its repair in memory; failing checks=%s" % (d_fail or "none")
    else:
        d_ok, d_msg = False, "no exception line with a repair to strip"
    checks.append(_check("planted.D_exception_repair_stripped_fails", d_ok, d_msg))

    # Refusal branch: a forced validator failure must give a failure-only packet with no normal sections.
    forced = [dict(v) for v in validators]
    forced[0]["passed"] = False
    forced[0]["detail"] = "forced in memory for the refusal test"
    refusal_type, refusal_text = assemble(forced, _build_normal)
    refusal_ok = (refusal_type == "failure_only"
                  and not any(("## " + h) in refusal_text for h in REQUIRED_HEADINGS)
                  and "forced in memory" in refusal_text)
    checks.append(_check("refusal_failure_only_when_input_fails", refusal_ok,
                         "packet_type=%s; normal headings absent=%s" % (
                             refusal_type, not any(("## " + h) in refusal_text for h in REQUIRED_HEADINGS))))

    # Save the hashes for the next run's changed-sources comparison.
    new_state = {
        "sources": {s["source_id"]: s["sha256"] for s in evidence["changed_sources"]["sources"]},
        "sections": section_hashes,
    }
    _write_json(PRIOR_STATE_PATH, new_state)

    overall_pass = all(c["status"] == "PASS" for c in checks)
    result = {
        "lab": LAB_ID,
        "data": "synthetic only (SYN_ identifiers; fixtures with fixed seeds)",
        "state_cutoff": STATE_CUTOFF,
        "packet_type": packet_type,
        "packet_path": _rel(PACKET_PATH) if packet_written else None,
        "packet_build_prompt": prompt,
        "input_spec": [item for item, _ in INPUT_SPEC],
        "lab_verifiers": raw["lab_rows"],
        "validators": validators,
        "samples": samples,
        "negative_controls": controls,
        "risk_based_items": risk_items,
        "coverage_gaps": list(COVERAGE_GAPS),
        "review_status": REVIEW_REQUIRED,
        "approval_record": _rel(SIGNOFF_PATH),
        "evidence_payload_sha256": evidence_payload_hash,
        "checks": checks,
        "overall": "PASS" if overall_pass else "FAIL",
        "limits": [
            "a PASS shows only that the synthetic packet agrees with the synthetic proofs, the state cutoff label and the packet schema rules in this file",
            "the packet is not approved; approval is a named human step recorded in as_of/labs/signoffs",
            "no packet-build prompt exists in the repo, so the input list is INPUT_SPEC, not a checked prompt",
            "labs 4, 7 and 8 have no lab verifier run by this lab; the packet records that gap",
            "sample strength differs by class (see STRENGTH); only the portfolio sample is an independent recount, and the reported value, estimate, macro, catalyst and hash samples are fixture or proof-output checks",
            "each sampling judge is tested by a planted-fault negative control; a control that is not rejected fails the lab",
            "no network call, no live data, no order or trading logic",
        ],
    }
    _write_json(RESULTS_PATH, result)
    return result


def main() -> int:
    result = run_lab()
    failed = [c for c in result["checks"] if c["status"] == "FAIL"]
    print("lab09 checks: %d total, %d failed" % (len(result["checks"]), len(failed)))
    for row in failed:
        print("FAIL %s: %s" % (row["check_id"], row["message"]))
    print("packet_type: %s" % result["packet_type"])
    print("overall: %s" % result["overall"])
    print("results: %s" % RESULTS_PATH)
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    sys.exit(main())
