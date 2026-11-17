"""Lab 05: reconcile earnings and an estimate revision (synthetic data only).

What this lab does, in order:

1. Writes a synthetic fixture under as_of/labs/results/lab05_inputs/:
   a pre-print estimate file (estimates.csv), a reported-result file
   (reported.csv) and a revision-driver file (revision_drivers.csv). The
   baseline estimate row E001 is never edited. A later revision is written as
   a new row, E004. Driver labels are "synthetic_judgment".
2. Runs verify_dir, a verifier that parses the three CSVs with the standard csv
   module and recomputes everything itself. It does not import any as_of
   module. It matches company, metric, period and unit before any arithmetic,
   recomputes the revenue, EPS and gross-margin surprises from the rows known
   before each report time, checks that the baseline row has its exact expected
   fields, and checks that the driver sum equals the revision between the two
   estimate rows.
3. Cross-checks the verifier's numbers against the as_of modules
   (estimate_ledger, estimate_revisions, reported_vs_expected_bridge).
4. Planted failures, each in a disposable copy under
   as_of/labs/results/lab05_disposable/:
   A. Overwrite the baseline row E001 with the revised value. The verifier must
      report that the baseline changed. The repair restores the baseline row
      from the canonical source file. The revision row stays as its own row.
   B. Change driver D001 from +5 to 0 cents. The driver-sum check must fail.
      The repair restores the driver judgment from the canonical driver file.
      No balancing row is added to force a tie.
   C. Run the verifier in a deliberately leaky mode that admits post-report
      rows (E009, and the boundary row E010 stamped at the report time) into
      the EPS expected value. The no-lookahead check must fail. The clean
      verifier must still pass, with E009 and E010 left in the fixture.
   D. Change the reported revenue unit to usd_thousands. The unit-match check
      must fail. The repair restores the unit; the value is not rescaled.
   E. Mark the reported gross-margin row as amended. The original-filing check
      must fail. The repair restores the original state.
   Each planted failure must produce its own set of failing checks.
5. Writes as_of/labs/results/lab05.json with a PASS or FAIL for every check.

Limits, stated in the JSON as well. A PASS shows that the fixture is internally
consistent and that the verifier and the modules agree. It does not show that
the fixture matches any filing or release. A correct sum for the wrong fiscal
quarter still fails the period-match check, but only inside this fixture. For
live work, each decision-critical value must be tied to the full filing or
release by entity, period, unit, table, amendment state and retrieval time.

The calculation artifact records no recommendation.

Python 3.9 syntax only. Standard library plus the as_of modules named above.
"""

import csv
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

LAB_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(LAB_DIR))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from as_of.core import EstimateRecord, parse_ts  # noqa: E402
from as_of.estimate_ledger import EstimateLedger  # noqa: E402
from as_of.estimate_revisions import revision_history  # noqa: E402
from as_of.reported_vs_expected_bridge import build_bridge  # noqa: E402

RESULTS_DIR = os.path.join(LAB_DIR, "results")
INPUT_DIR = os.path.join(RESULTS_DIR, "lab05_inputs")
DISPOSABLE_DIR = os.path.join(RESULTS_DIR, "lab05_disposable")
OUT_PATH = os.path.join(RESULTS_DIR, "lab05.json")

TOL = 1e-9
SYNTHETIC_TICKER = "SYN_T01"
SYNTHETIC_PERIOD = "2026Q3"
SYNTHETIC_ANALYST_A1 = "SYN_A1"
DRIVER_LABEL = "synthetic_judgment"

ESTIMATES_FILE = "estimates.csv"
REPORTED_FILE = "reported.csv"
DRIVERS_FILE = "revision_drivers.csv"
INPUT_FILES = (ESTIMATES_FILE, REPORTED_FILE, DRIVERS_FILE)

ESTIMATE_HEADER = [
    "estimate_id", "ticker", "metric", "period", "unit",
    "analyst_id", "value", "knowledge_at", "source_id",
]
ESTIMATE_ROWS = [
    ["E001", "SYN_T01", "eps", "2026Q3", "usd_per_share", "SYN_A1", "1.20", "2026-09-01T12:00:00Z", "SYN_SRC_EST_01"],
    ["E002", "SYN_T01", "eps", "2026Q3", "usd_per_share", "SYN_A2", "1.10", "2026-09-02T12:00:00Z", "SYN_SRC_EST_01"],
    ["E003", "SYN_T01", "eps", "2026Q3", "usd_per_share", "SYN_A3", "1.30", "2026-09-03T12:00:00Z", "SYN_SRC_EST_01"],
    ["E004", "SYN_T01", "eps", "2026Q3", "usd_per_share", "SYN_A1", "1.25", "2026-10-10T12:00:00Z", "SYN_SRC_EST_02"],
    ["E005", "SYN_T01", "revenue", "2026Q3", "usd_millions", "SYN_A1", "500.0", "2026-09-01T12:00:00Z", "SYN_SRC_EST_01"],
    ["E006", "SYN_T01", "revenue", "2026Q3", "usd_millions", "SYN_A2", "520.0", "2026-09-02T12:00:00Z", "SYN_SRC_EST_01"],
    ["E007", "SYN_T01", "gross_margin", "2026Q3", "percent", "SYN_A1", "40.0", "2026-09-01T12:00:00Z", "SYN_SRC_EST_01"],
    ["E008", "SYN_T01", "gross_margin", "2026Q3", "percent", "SYN_A2", "40.4", "2026-09-02T12:00:00Z", "SYN_SRC_EST_01"],
    # Post-report row: known 5 days after the EPS report. It must never enter
    # the EPS expected value. Its value is deliberately far from the rest.
    ["E009", "SYN_T01", "eps", "2026Q3", "usd_per_share", "SYN_A4", "2.40", "2026-10-25T12:00:00Z", "SYN_SRC_EST_03"],
    # Boundary row: knowledge_at equals the EPS report time exactly. The
    # rule is strictly before the report, so this row must also be excluded.
    ["E010", "SYN_T01", "eps", "2026Q3", "usd_per_share", "SYN_A5", "2.00", "2026-10-20T20:00:00Z", "SYN_SRC_EST_03"],
]

REPORTED_HEADER = [
    "report_id", "ticker", "metric", "period", "unit", "reported_value",
    "reported_at", "table", "amendment_state", "source_id", "retrieved_at",
]
REPORTED_ROWS = [
    ["R001", "SYN_T01", "eps", "2026Q3", "usd_per_share", "1.27", "2026-10-20T20:00:00Z",
     "SYN_TABLE_SUMMARY", "original", "SYN_SRC_FILING_01", "2026-10-27T09:00:00Z"],
    ["R002", "SYN_T01", "revenue", "2026Q3", "usd_millions", "512.0", "2026-10-20T20:00:00Z",
     "SYN_TABLE_SUMMARY", "original", "SYN_SRC_FILING_01", "2026-10-27T09:00:00Z"],
    ["R003", "SYN_T01", "gross_margin", "2026Q3", "percent", "41.2", "2026-10-20T20:00:00Z",
     "SYN_TABLE_SUMMARY", "original", "SYN_SRC_FILING_01", "2026-10-27T09:00:00Z"],
]

DRIVER_HEADER = [
    "driver_id", "revision_id", "ticker", "metric", "period",
    "analyst_id", "driver_name", "amount_cents", "label",
]
DRIVER_ROWS = [
    ["D001", "E004", "SYN_T01", "eps", "2026Q3", "SYN_A1", "demand_outlook", "5", DRIVER_LABEL],
    ["D002", "E004", "SYN_T01", "eps", "2026Q3", "SYN_A1", "cost_timing", "2", DRIVER_LABEL],
    ["D003", "E004", "SYN_T01", "eps", "2026Q3", "SYN_A1", "share_count_assumption", "-2", DRIVER_LABEL],
]

# Exact expected fields of the baseline row E001. The verifier compares the
# parsed row with these strings.
EXPECTED_BASELINE = {
    "estimate_id": "E001",
    "ticker": "SYN_T01",
    "metric": "eps",
    "period": "2026Q3",
    "unit": "usd_per_share",
    "analyst_id": "SYN_A1",
    "value": "1.20",
    "knowledge_at": "2026-09-01T12:00:00Z",
    "source_id": "SYN_SRC_EST_01",
}

BASELINE_ID = "E001"
REVISION_ID = "E004"
EPS_REVISION_DRIVER_ID = "D001"
POST_REPORT_IDS_EPS = ("E009", "E010")


# ---------------------------------------------------------------------------
# Fixture writing (canonical copy, written once per run)
# ---------------------------------------------------------------------------

def _write_csv(path, header, rows):
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)


def write_canonical_inputs(folder):
    os.makedirs(folder, exist_ok=True)
    _write_csv(os.path.join(folder, ESTIMATES_FILE), ESTIMATE_HEADER, ESTIMATE_ROWS)
    _write_csv(os.path.join(folder, REPORTED_FILE), REPORTED_HEADER, REPORTED_ROWS)
    _write_csv(os.path.join(folder, DRIVERS_FILE), DRIVER_HEADER, DRIVER_ROWS)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Independent verifier (csv module and plain arithmetic only)
# ---------------------------------------------------------------------------

def _read_rows(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def _parse_utc(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def verify_dir(folder, leak_post_report=False):
    """Recompute every check from the three CSVs in folder.

    Returns a dict with keys passed (bool), checks (list of dicts with
    check_id, status and detail) and values (recomputed numbers).

    leak_post_report=True is a deliberately wrong mode, used only by planted
    failure C. It lets rows known at or after the report time into the
    expected value, so the no-lookahead check has something to catch.
    """
    checks = []
    values = {}

    def add(check_id, ok, detail):
        checks.append({
            "check_id": check_id,
            "status": "pass" if ok else "fail",
            "detail": detail,
        })

    estimates = _read_rows(os.path.join(folder, ESTIMATES_FILE))
    reported = _read_rows(os.path.join(folder, REPORTED_FILE))
    drivers = _read_rows(os.path.join(folder, DRIVERS_FILE))

    # 1. Match company, metric, period and unit before any arithmetic.
    for rep in reported:
        matches = [
            e for e in estimates
            if e["ticker"] == rep["ticker"]
            and e["metric"] == rep["metric"]
            and e["period"] == rep["period"]
        ]
        units = sorted(set(e["unit"] for e in matches))
        ok = bool(matches) and units == [rep["unit"]]
        add(
            "match_keys_unit_period_%s" % rep["metric"],
            ok,
            "%d estimate rows for %s/%s/%s; estimate units %s; report unit %s"
            % (len(matches), rep["ticker"], rep["metric"], rep["period"], units, rep["unit"]),
        )
        add(
            "amendment_state_original_%s" % rep["metric"],
            rep["amendment_state"] == "original",
            "amendment_state=%s" % rep["amendment_state"],
        )

    # 2. Baseline row has its exact expected fields.
    baseline_rows = [e for e in estimates if e["estimate_id"] == BASELINE_ID]
    if len(baseline_rows) != 1:
        add("baseline_row_unchanged", False,
            "expected exactly one row %s, found %d" % (BASELINE_ID, len(baseline_rows)))
        baseline = None
    else:
        baseline = baseline_rows[0]
        diffs = [
            "%s expected %r found %r" % (field, want, baseline.get(field))
            for field, want in EXPECTED_BASELINE.items()
            if baseline.get(field) != want
        ]
        add(
            "baseline_row_unchanged",
            not diffs,
            "; ".join(diffs) if diffs else "%s matches all %d expected fields"
            % (BASELINE_ID, len(EXPECTED_BASELINE)),
        )

    # 3. The revision is a new row that is later than the baseline.
    revision_rows = [e for e in estimates if e["estimate_id"] == REVISION_ID]
    if len(revision_rows) != 1 or baseline is None:
        add("revision_is_new_row", False,
            "revision row %s count %d; baseline present %s"
            % (REVISION_ID, len(revision_rows), baseline is not None))
        revision = None
    else:
        revision = revision_rows[0]
        same_series = all(
            revision[f] == baseline[f]
            for f in ("ticker", "metric", "period", "unit", "analyst_id")
        )
        later = _parse_utc(revision["knowledge_at"]) > _parse_utc(baseline["knowledge_at"])
        distinct = revision["estimate_id"] != baseline["estimate_id"]
        add(
            "revision_is_new_row",
            same_series and later and distinct,
            "same series %s; knowledge later than baseline %s; distinct id %s"
            % (same_series, later, distinct),
        )

    # 4. Driver sum equals the revision between the two estimate rows.
    if baseline is not None and revision is not None:
        revision_cents = (float(revision["value"]) - float(baseline["value"])) * 100.0
        values["revision_cents"] = revision_cents
        own = [d for d in drivers if d["revision_id"] == REVISION_ID]
        labels_ok = bool(own) and all(d["label"] == DRIVER_LABEL for d in own)
        add(
            "driver_labels_synthetic",
            labels_ok,
            "%d drivers for %s; labels %s"
            % (len(own), REVISION_ID, sorted(set(d["label"] for d in own))),
        )
        keys_ok = bool(own) and all(
            d["ticker"] == revision["ticker"]
            and d["metric"] == revision["metric"]
            and d["period"] == revision["period"]
            and d["analyst_id"] == revision["analyst_id"]
            for d in own
        )
        add("driver_keys_match_revision", keys_ok,
            "driver rows carry the revision's ticker, metric, period and analyst")
        driver_sum = sum(float(d["amount_cents"]) for d in own)
        values["driver_sum_cents"] = driver_sum
        add(
            "driver_sum_equals_revision",
            abs(driver_sum - revision_cents) <= 1e-6,
            "driver sum %.6f cents; revision %.6f cents (%s - %s)"
            % (driver_sum, revision_cents, revision["value"], baseline["value"]),
        )

    # 5. Recalculate each surprise from rows known before the report time.
    for rep in reported:
        metric = rep["metric"]
        reported_at = _parse_utc(rep["reported_at"])
        reported_value = float(rep["reported_value"])
        series = [
            e for e in estimates
            if e["ticker"] == rep["ticker"]
            and e["metric"] == rep["metric"]
            and e["period"] == rep["period"]
        ]
        visible = [
            e for e in series
            if leak_post_report or _parse_utc(e["knowledge_at"]) < reported_at
        ]
        post_rows = [e for e in series if _parse_utc(e["knowledge_at"]) >= reported_at]
        latest = {}
        for e in visible:
            known = _parse_utc(e["knowledge_at"])
            current = latest.get(e["analyst_id"])
            if current is None or known > current[0]:
                latest[e["analyst_id"]] = (known, e)
        used = [pair[1] for pair in latest.values()]
        if not used:
            add("expected_available_%s" % metric, False, "no estimate known before report time")
            continue
        expected = sum(float(e["value"]) for e in used) / float(len(used))
        basis = max(_parse_utc(e["knowledge_at"]) for e in used)
        surprise = reported_value - expected
        pct = surprise / abs(expected) if expected != 0.0 else None
        used_ids = sorted(e["estimate_id"] for e in used)
        values[metric] = {
            "unit": rep["unit"],
            "reported": reported_value,
            "expected": expected,
            "surprise": surprise,
            "surprise_pct": pct,
            "estimate_ids_used": used_ids,
            "basis_as_of": basis.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reported_at": rep["reported_at"],
        }
        # Independent of the visibility filter above: no row known at or after
        # the report time may be among the rows used, and the latest basis
        # must be strictly earlier than the report.
        post_ids = sorted(e["estimate_id"] for e in post_rows)
        leaked = sorted(set(used_ids) & set(post_ids))
        add(
            "no_lookahead_%s" % metric,
            (not leaked) and basis < reported_at,
            "latest estimate used %s; report %s; post-report rows %s; leaked into expected %s"
            % (basis.strftime("%Y-%m-%dT%H:%M:%SZ"), rep["reported_at"],
               post_ids or "none", leaked or "none"),
        )
        if metric == "eps":
            add(
                "post_report_rows_present_eps",
                set(post_ids) == set(POST_REPORT_IDS_EPS),
                "post-report and boundary rows in the EPS series: %s (expected %s)"
                % (post_ids or "none", ", ".join(POST_REPORT_IDS_EPS)),
            )
        if metric == "eps" and revision is not None:
            add(
                "eps_expected_uses_revision",
                REVISION_ID in used_ids,
                "estimate ids used for EPS expected: %s" % ", ".join(used_ids),
            )

    passed = bool(checks) and all(c["status"] == "pass" for c in checks)
    return {"passed": passed, "checks": checks, "values": values}


# ---------------------------------------------------------------------------
# Cross-check against the as_of modules
# ---------------------------------------------------------------------------

def module_crosscheck(folder, verifier_values):
    """Rebuild the same numbers with the as_of modules and compare.

    Returns (checks, module_values). Each check compares one module output
    with the verifier's recalculated value. The lab does not use the module
    output to decide any verifier check.
    """
    checks = []
    estimates = _read_rows(os.path.join(folder, ESTIMATES_FILE))
    reported = _read_rows(os.path.join(folder, REPORTED_FILE))

    records = []
    ledger = EstimateLedger()
    for row in estimates:
        rec = EstimateRecord(
            estimate_id=row["estimate_id"],
            ticker=row["ticker"],
            metric=row["metric"],
            period=row["period"],
            analyst_id=row["analyst_id"],
            value=float(row["value"]),
            knowledge_at=parse_ts(row["knowledge_at"]),
            source_id=row["source_id"],
        )
        records.append(rec)
        ledger.append(rec)

    module_values = {}
    for rep in reported:
        metric = rep["metric"]
        bridge = build_bridge(
            records,
            rep["ticker"],
            metric,
            rep["period"],
            float(rep["reported_value"]),
            parse_ts(rep["reported_at"]),
        )
        basis = bridge["basis_as_of"]
        module_values[metric] = {
            "expected": bridge["expected"],
            "reported": bridge["reported"],
            "surprise_abs": bridge["surprise_abs"],
            "surprise_pct": bridge["surprise_pct"],
            "basis_as_of": basis.strftime("%Y-%m-%dT%H:%M:%SZ") if basis is not None else None,
        }
        if metric not in verifier_values:
            checks.append({"check_id": "module_matches_verifier_%s" % metric,
                           "status": "fail",
                           "detail": "verifier produced no value for %s" % metric})
            continue
        v = verifier_values[metric]
        exp_ok = bridge["expected"] is not None and abs(bridge["expected"] - v["expected"]) <= TOL
        sur_ok = bridge["surprise_abs"] is not None and abs(bridge["surprise_abs"] - v["surprise"]) <= TOL
        pct_ok = (
            (bridge["surprise_pct"] is None and v["surprise_pct"] is None)
            or (bridge["surprise_pct"] is not None and v["surprise_pct"] is not None
                and abs(bridge["surprise_pct"] - v["surprise_pct"]) <= TOL)
        )
        basis_ok = basis is not None and basis.strftime("%Y-%m-%dT%H:%M:%SZ") == v["basis_as_of"]
        checks.append({
            "check_id": "module_matches_verifier_%s" % metric,
            "status": "pass" if (exp_ok and sur_ok and pct_ok and basis_ok) else "fail",
            "detail": "module expected %r vs verifier %r; surprise %r vs %r; pct %r vs %r; basis %s vs %s"
            % (bridge["expected"], v["expected"], bridge["surprise_abs"], v["surprise"],
               bridge["surprise_pct"], v["surprise_pct"], basis, v["basis_as_of"]),
        })

    history = revision_history(ledger, SYNTHETIC_TICKER, "eps", SYNTHETIC_PERIOD, SYNTHETIC_ANALYST_A1)
    module_values["a1_eps_history"] = [
        [t.strftime("%Y-%m-%dT%H:%M:%SZ"), v] for t, v in history
    ]
    if len(history) == 2:
        base_ok = abs(history[0][1] - float(EXPECTED_BASELINE["value"])) <= TOL
        rev_ok = abs(history[1][1] - float(_find_value(folder, REVISION_ID))) <= TOL
        checks.append({
            "check_id": "module_revision_history_two_rows",
            "status": "pass" if (base_ok and rev_ok) else "fail",
            "detail": "module history for SYN_A1 eps has %d rows; first %r, last %r"
            % (len(history), history[0], history[-1]),
        })
    else:
        checks.append({
            "check_id": "module_revision_history_two_rows",
            "status": "fail",
            "detail": "module history for SYN_A1 eps has %d rows, expected 2" % len(history),
        })

    return checks, module_values


def _find_value(folder, estimate_id):
    for row in _read_rows(os.path.join(folder, ESTIMATES_FILE)):
        if row["estimate_id"] == estimate_id:
            return row["value"]
    return "nan"


# ---------------------------------------------------------------------------
# Planted failures in disposable copies
# ---------------------------------------------------------------------------

def _fresh_copy(name):
    dest = os.path.join(DISPOSABLE_DIR, name)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for filename in INPUT_FILES:
        shutil.copyfile(os.path.join(INPUT_DIR, filename), os.path.join(dest, filename))
    return dest


def _rewrite_rows(path, header_check, mutate):
    rows = _read_rows(path)
    with open(path, newline="") as handle:
        header = next(csv.reader(handle))
    assert header == header_check, "unexpected header in %s" % path
    for row in rows:
        mutate(row)
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _failed_ids(result):
    return [c["check_id"] for c in result["checks"] if c["status"] == "fail"]


def planted_baseline_overwrite():
    """Failure A: overwrite the baseline row with the revised value."""
    dest = _fresh_copy("a_baseline_overwrite")
    path = os.path.join(dest, ESTIMATES_FILE)

    def mutate(row):
        if row["estimate_id"] == BASELINE_ID:
            row["value"] = _find_value(INPUT_DIR, REVISION_ID)

    _rewrite_rows(path, ESTIMATE_HEADER, mutate)
    injected = verify_dir(dest)
    failed = _failed_ids(injected)
    detected = "baseline_row_unchanged" in failed

    # Repair A: restore the baseline row from the canonical source file.
    shutil.copyfile(os.path.join(INPUT_DIR, ESTIMATES_FILE), path)
    repaired = verify_dir(dest)
    return {
        "name": "A_baseline_overwrite",
        "injected_change": "estimate E001 value 1.20 replaced with the revised value 1.25 in the disposable copy",
        "failed_check_ids": failed,
        "detected_by_verifier": detected,
        "detected_detail": next(
            (c["detail"] for c in injected["checks"] if c["check_id"] == "baseline_row_unchanged"), ""
        ),
        "repair_kind": "restore_source_rows",
        "repair": "restore estimates.csv from the canonical source file so E001 holds 1.20; "
                  "keep E004 as its own row; do not edit the revision to hide the change",
        "repaired_passed": repaired["passed"],
        "repaired_failed_check_ids": _failed_ids(repaired),
    }


def planted_driver_change():
    """Failure B: change driver D001 from +5 to 0 cents with the baseline intact."""
    dest = _fresh_copy("b_driver_change")
    path = os.path.join(dest, DRIVERS_FILE)

    def mutate(row):
        if row["driver_id"] == EPS_REVISION_DRIVER_ID:
            assert row["amount_cents"] == "5", "fixture driver D001 should start at +5"
            row["amount_cents"] = "0"

    _rewrite_rows(path, DRIVER_HEADER, mutate)
    injected = verify_dir(dest)
    failed = _failed_ids(injected)
    detected = "driver_sum_equals_revision" in failed and "baseline_row_unchanged" not in failed

    # Repair B: restore the analyst judgment from the canonical driver file.
    shutil.copyfile(os.path.join(INPUT_DIR, DRIVERS_FILE), path)
    repaired = verify_dir(dest)
    return {
        "name": "B_driver_change",
        "injected_change": "driver D001 (demand_outlook) changed from +5 to 0 cents in the disposable copy",
        "failed_check_ids": failed,
        "detected_by_verifier": detected,
        "detected_detail": next(
            (c["detail"] for c in injected["checks"] if c["check_id"] == "driver_sum_equals_revision"), ""
        ),
        "repair_kind": "restore_driver_judgment",
        "repair": "restore D001 to the +5 cents judgment in the canonical driver file; "
                  "do not add a balancing driver or plug row to force the sum to tie",
        "repaired_passed": repaired["passed"],
        "repaired_failed_check_ids": _failed_ids(repaired),
    }


def planted_post_report_leak():
    """Failure C: a verifier that lets post-report rows into expected must fail.

    The canonical fixture holds E009 (known after the report) and E010 (known
    exactly at the report). The leaky mode of verify_dir admits them. The
    no-lookahead check must catch this, and the expected value must move.
    """
    dest = _fresh_copy("c_post_report_leak")
    leaky = verify_dir(dest, leak_post_report=True)
    failed = _failed_ids(leaky)
    clean = verify_dir(dest)
    return {
        "name": "C_post_report_leak",
        "injected_change": "verifier run in leaky mode: rows known at or after the EPS report enter the expected value",
        "failed_check_ids": failed,
        "detected_by_verifier": "no_lookahead_eps" in failed and clean["passed"],
        "detected_detail": next(
            (c["detail"] for c in leaky["checks"] if c["check_id"] == "no_lookahead_eps"), ""
        ),
        "repair_kind": "restore_visibility_rule",
        "repair": "drop leaky mode; keep the strict knowledge_at < reported_at filter; "
                  "do not delete E009 or E010 from the fixture to hide them",
        "repaired_passed": clean["passed"],
        "repaired_failed_check_ids": _failed_ids(clean),
    }


def _planted_row_change(name, injected_change, filename, header, mutate, expected_check,
                        repair_kind, repair_text):
    dest = _fresh_copy(name)
    path = os.path.join(dest, filename)
    _rewrite_rows(path, header, mutate)
    injected = verify_dir(dest)
    failed = _failed_ids(injected)
    detected = expected_check in failed
    shutil.copyfile(os.path.join(INPUT_DIR, filename), path)
    repaired = verify_dir(dest)
    return {
        "name": name,
        "injected_change": injected_change,
        "failed_check_ids": failed,
        "detected_by_verifier": detected,
        "detected_detail": next(
            (c["detail"] for c in injected["checks"] if c["check_id"] == expected_check), ""
        ),
        "repair_kind": repair_kind,
        "repair": repair_text,
        "repaired_passed": repaired["passed"],
        "repaired_failed_check_ids": _failed_ids(repaired),
    }


def planted_unit_mismatch():
    """Failure D: a reported revenue row in the wrong unit must fail the match check."""
    def mutate(row):
        if row["report_id"] == "R002":
            row["unit"] = "usd_thousands"
    return _planted_row_change(
        "D_unit_mismatch",
        "reported revenue row R002 unit changed from usd_millions to usd_thousands",
        REPORTED_FILE, REPORTED_HEADER, mutate,
        "match_keys_unit_period_revenue", "restore_reported_row",
        "restore R002 unit to usd_millions from reported.csv; do not rescale the value to hide the unit change",
    )


def planted_amendment_state():
    """Failure E: a reported row that is not the original filing must fail the amendment check."""
    def mutate(row):
        if row["report_id"] == "R003":
            row["amendment_state"] = "amended"
    return _planted_row_change(
        "E_amendment_state",
        "reported gross-margin row R003 amendment_state changed from original to amended",
        REPORTED_FILE, REPORTED_HEADER, mutate,
        "amendment_state_original_gross_margin", "restore_reported_row",
        "restore R003 to the original filing state; any amended figure needs its own tie-out, not a silent swap",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _lab_check(check_id, ok, detail):
    return {"check_id": check_id, "status": "pass" if ok else "fail", "detail": detail}


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    write_canonical_inputs(INPUT_DIR)
    input_hashes = {name: sha256_file(os.path.join(INPUT_DIR, name)) for name in INPUT_FILES}

    # Determinism: a second write into a scratch folder must hash identically.
    # A hash that is only computed and never compared proves nothing.
    scratch = os.path.join(DISPOSABLE_DIR, "_hash_rewrite")
    if os.path.isdir(scratch):
        shutil.rmtree(scratch)
    write_canonical_inputs(scratch)
    rewrite_hashes = {name: sha256_file(os.path.join(scratch, name)) for name in INPUT_FILES}
    checks = []
    checks.append(_lab_check(
        "inputs_written_and_hashed",
        all(len(h) == 64 for h in input_hashes.values()) and rewrite_hashes == input_hashes,
        "sha256 for %s is identical across two writes of the fixture"
        % ", ".join(INPUT_FILES),
    ))

    canonical = verify_dir(INPUT_DIR)
    checks.append(_lab_check(
        "canonical_verifier_passes",
        canonical["passed"],
        "%d of %d verifier checks pass" % (
            sum(1 for c in canonical["checks"] if c["status"] == "pass"), len(canonical["checks"])),
    ))

    module_checks, module_values = module_crosscheck(INPUT_DIR, canonical["values"])
    checks.extend(module_checks)
    module_ok = all(c["status"] == "pass" for c in module_checks)
    checks.append(_lab_check(
        "module_crosscheck_all_match", module_ok,
        "%d module comparisons" % len(module_checks),
    ))

    planted = [
        planted_baseline_overwrite(),
        planted_driver_change(),
        planted_post_report_leak(),
        planted_unit_mismatch(),
        planted_amendment_state(),
    ]
    for p in planted:
        tag = p["name"].split("_")[0]
        checks.append(_lab_check(
            "planted_%s_detected" % tag, p["detected_by_verifier"],
            p["detected_detail"] or "expected check not reported",
        ))
        checks.append(_lab_check(
            "planted_%s_repair_restores_pass" % tag, p["repaired_passed"],
            "failed after repair: %s" % (p["repaired_failed_check_ids"] or "none"),
        ))
    # Failure signatures are computed from the runs, not written by hand.
    signatures = [tuple(sorted(p["failed_check_ids"])) for p in planted]
    checks.append(_lab_check(
        "planted_failures_have_distinct_signatures",
        len(set(signatures)) == len(signatures) and all(signatures),
        "; ".join("%s -> %s" % (p["name"], list(s)) for p, s in zip(planted, signatures)),
    ))

    overall = all(c["status"] == "pass" for c in checks)
    artifact = {
        "lab": "lab05_earnings_reconciliation_and_estimate_revision",
        "synthetic_data_only": True,
        "overall_pass": overall,
        "checks": checks,
        "canonical_verifier": {
            "passed": canonical["passed"],
            "checks": canonical["checks"],
        },
        "canonical_values": canonical["values"],
        "module_values": module_values,
        "input_sha256": input_hashes,
        "planted_failures": planted,
        "live_tieout_fields_required": [
            "entity", "period", "unit", "table", "amendment_state", "retrieval_time",
        ],
        "limits": [
            "A PASS shows the fixture is internally consistent and that the verifier and the as_of modules agree.",
            "It does not show that the fixture matches any filing or release.",
            "A correct sum for the wrong fiscal quarter still fails the period-match check, within this fixture only.",
            "Analyst drivers are synthetic judgments, not sourced facts.",
            "The check list follows this script's own stated procedure.",
            "This calculation artifact records no recommendation.",
        ],
    }
    with open(OUT_PATH, "w") as handle:
        json.dump(artifact, handle, indent=2, sort_keys=True)
        handle.write("\n")

    for c in checks:
        print("%-42s %s  %s" % (c["check_id"], c["status"].upper(), c["detail"]))
    print("overall_pass=%s" % overall)
    print("wrote %s" % OUT_PATH)
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
