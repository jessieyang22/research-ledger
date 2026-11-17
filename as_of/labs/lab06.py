"""Lab 06: reconstruct a macro vintage as of a cutoff (synthetic data only).

What this lab does, in order:

1. Opens the macro vintages file as_of/labs/data/lab06_macro_vintages.csv. The
   file is written once from a fixed synthetic table if it is missing, and it
   is hashed on every run. It holds one row per release of one observation.
2. Sets the cutoff (2026-06-30T12:00:00Z by default). The CSV has date-only
   vintage fields, so each release is given a conservative release time of
   23:59:59Z on its vintage date. A release dated on the cutoff day therefore
   does not count, which is the safe side of a date-only boundary.
3. Groups rows by observation date, drops every vintage released after the
   cutoff, and selects the latest remaining vintage for each observation. The
   selected value goes in the as-of column. The latest available value of the
   same observation goes in a separate latest column, so later revisions stay
   visible. Series ID, unit, seasonal adjustment, source and retrieval time are
   carried on every row. If no vintage of an observation was released by the
   cutoff, the row gets status UNAVAILABLE_AS_OF_CUTOFF and a null as-of value.
   It never gets a guess.
4. Runs the verifier. It repeats the selection for every observation
   with macro_cutoff_rule.value_as_of, which is a second implementation, and
   compares the result with each output row. It also runs
   macro_cutoff_rule.cutoff_violations on each as-of value, so any output row
   whose selected vintage exceeds the cutoff is a FAIL. The verifier also
   checks the latest column, the unavailable status and row coverage.
5. Runs the numeric checks on the live output. These are the April case (as-of
   June 5, latest July 3), the verifier, the cutoff, the unavailable case and
   coverage.
6. Planted failure A: in a disposable in-memory output, the July 3 value is put
   into the as-of column for April. The verifier must fail on it.
7. Planted failure B: in memory only, the unit is blanked on the raw input rows
   for the series. The manifest type holds no unit field, so the unit reaches
   the output rows through the raw rows. The numeric checks must still pass, and
   the manual metadata gate must fail. The file on disk is not changed.
8. Records the official series page check as PENDING_MANUAL. This lab makes no
   network call, so it cannot check a live series page, its units, its
   adjustment or its vintage history.
9. Writes as_of/labs/results/lab06.json with a PASS or FAIL for each check.

Limits, stated in the JSON as well: a PASS shows only that the synthetic output
agrees with the synthetic vintages and the cutoff rule. It does not show that
any live series is correct, complete or released at the stated time.

Only as_of.core is imported statically. Every other piece is loaded with
core.component inside a function body. No network, no subprocess, no orders,
no git.
"""

import csv
import json
import os
import sys
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from as_of.core import AsOfError, component


LAB_DIR: str = os.path.dirname(os.path.abspath(__file__))
DATA_PATH: str = os.path.join(LAB_DIR, "data", "lab06_macro_vintages.csv")
RESULTS_PATH: str = os.path.join(LAB_DIR, "results", "lab06.json")

LAB_ID: str = "lab06"
SERIES_ID: str = "SYN_LAB_CPI"
SOURCE_ID: str = "SYN_LAB_SRC"
UNIT: str = "index points (synthetic)"
SEASONAL_ADJUSTMENT: str = "SA (synthetic)"
RETRIEVED_AT: str = "2026-10-27T00:00:00Z"
CUTOFF_TEXT: str = "2026-06-30T12:00:00Z"
UNAVAILABLE: str = "UNAVAILABLE_AS_OF_CUTOFF"
AUG_OBS: str = "2026-08-01"
APRIL_OBS: str = "2026-04-01"

CSV_FIELDS: Tuple[str, ...] = (
    "series_id",
    "obs_date",
    "vintage_date",
    "value",
    "unit",
    "seasonal_adjustment",
    "source_id",
    "retrieved_at",
)
OUTPUT_FIELDS: Tuple[str, ...] = (
    "series_id",
    "obs_date",
    "status",
    "as_of_vintage_date",
    "as_of_value",
    "latest_vintage_date",
    "latest_value",
    "unit",
    "seasonal_adjustment",
    "source_id",
    "retrieved_at",
)
REQUIRED_METADATA: Tuple[str, ...] = ("unit", "seasonal_adjustment", "source_id", "retrieved_at")

# Fixed synthetic releases: (obs_date, vintage_date, value). Hand-set values,
# no random draws. Only one series is used.
SYNTHETIC_RELEASES: Tuple[Tuple[str, str, str], ...] = (
    ("2026-02-01", "2026-03-09", "2.41"),
    ("2026-02-01", "2026-04-07", "2.38"),
    ("2026-02-01", "2026-07-08", "2.35"),
    ("2026-03-01", "2026-04-08", "2.52"),
    ("2026-03-01", "2026-05-06", "2.49"),
    ("2026-04-01", "2026-05-08", "2.60"),
    ("2026-04-01", "2026-06-05", "2.66"),
    ("2026-04-01", "2026-07-03", "2.71"),
    ("2026-05-01", "2026-06-10", "2.74"),
    ("2026-05-01", "2026-08-07", "2.78"),
    ("2026-08-01", "2026-09-08", "2.90"),
)


# ---------------------------------------------------------------------------
# Input file
# ---------------------------------------------------------------------------


def _write_synthetic_csv(path: str) -> None:
    """Write the fixed synthetic vintages to path. Only called when the file is missing."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for obs_iso, vintage_iso, value in SYNTHETIC_RELEASES:
            writer.writerow(
                {
                    "series_id": SERIES_ID,
                    "obs_date": obs_iso,
                    "vintage_date": vintage_iso,
                    "value": value,
                    "unit": UNIT,
                    "seasonal_adjustment": SEASONAL_ADJUSTMENT,
                    "source_id": SOURCE_ID,
                    "retrieved_at": RETRIEVED_AT,
                }
            )


def load_vintage_rows(path: str) -> List[Dict[str, str]]:
    """Open the vintages file and return its rows as plain string dicts."""
    if not os.path.exists(path):
        _write_synthetic_csv(path)
    with open(path, "r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or tuple(reader.fieldnames) != CSV_FIELDS:
            raise AsOfError("unexpected columns in %s: %r" % (path, reader.fieldnames))
        return [dict(row) for row in reader]


# ---------------------------------------------------------------------------
# Time and manifest helpers
# ---------------------------------------------------------------------------


def conservative_release(vintage_date: date) -> datetime:
    """Release time used for a date-only vintage: 23:59:59Z on that day."""
    return datetime(vintage_date.year, vintage_date.month, vintage_date.day,
                    23, 59, 59, tzinfo=timezone.utc)


def build_manifest(raw_rows: Sequence[Dict[str, str]]) -> Any:
    """Load the raw rows into a macro_vintage_manifest.VintageManifest."""
    macro_vintage_manifest = component("macro_vintage_manifest")
    core = component("core")
    manifest = macro_vintage_manifest.VintageManifest()
    for row in raw_rows:
        vintage_day = date.fromisoformat(row["vintage_date"])
        manifest.add_vintage(
            core.MacroVintage(
                series_id=row["series_id"],
                obs_date=date.fromisoformat(row["obs_date"]),
                vintage_date=vintage_day,
                release_at=conservative_release(vintage_day),
                value=float(row["value"]),
                source_id=row["source_id"],
            )
        )
    return manifest


# ---------------------------------------------------------------------------
# Pipeline: as-of and latest selection
# ---------------------------------------------------------------------------


def select_as_of(raw_rows: Sequence[Dict[str, str]], cutoff: datetime) -> List[Dict[str, Any]]:
    """Build the output rows: one per (series, observation), with as-of and latest columns.

    Vintages released after the cutoff are dropped first. The latest remaining
    vintage is the as-of value. The latest vintage of the observation, before
    any cutoff, is the latest value.
    """
    groups: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
    for row in raw_rows:
        groups.setdefault((row["series_id"], row["obs_date"]), []).append(row)

    output: List[Dict[str, Any]] = []
    for series_id, obs_iso in sorted(groups):
        group = groups[(series_id, obs_iso)]
        latest_row = max(group, key=lambda r: date.fromisoformat(r["vintage_date"]))
        eligible = [
            r for r in group
            if conservative_release(date.fromisoformat(r["vintage_date"])) <= cutoff
        ]
        as_of_row = None
        if eligible:
            as_of_row = max(eligible, key=lambda r: date.fromisoformat(r["vintage_date"]))
        output.append(
            {
                "series_id": series_id,
                "obs_date": obs_iso,
                "status": "OK" if as_of_row is not None else UNAVAILABLE,
                "as_of_vintage_date": as_of_row["vintage_date"] if as_of_row else None,
                "as_of_value": float(as_of_row["value"]) if as_of_row else None,
                "latest_vintage_date": latest_row["vintage_date"],
                "latest_value": float(latest_row["value"]),
                "unit": latest_row["unit"],
                "seasonal_adjustment": latest_row["seasonal_adjustment"],
                "source_id": latest_row["source_id"],
                "retrieved_at": latest_row["retrieved_at"],
            }
        )
    return output


# ---------------------------------------------------------------------------
# Lab 6 verifier
# ---------------------------------------------------------------------------


def verify_output(
    rows: Sequence[Dict[str, Any]],
    raw_rows: Sequence[Dict[str, str]],
    cutoff: datetime,
) -> List[Tuple[str, str]]:
    """Repeat the selection for every output row and return (kind, message) problems.

    Kinds:
      mismatch            the output as-of value or vintage differs from the repeated one
      exceeds_cutoff      the output as-of vintage is released after the cutoff
      guess               an unavailable row carries a value, or an eligible vintage was missed
      latest              the latest column is not the latest vintage of the observation
      coverage            rows do not match the raw observations one for one
    """
    macro_cutoff_rule = component("macro_cutoff_rule")
    core = component("core")
    manifest = build_manifest(raw_rows)
    problems: List[Tuple[str, str]] = []

    raw_keys = set((r["series_id"], r["obs_date"]) for r in raw_rows)
    out_keys = [(r["series_id"], r["obs_date"]) for r in rows]
    if len(out_keys) != len(set(out_keys)) or set(out_keys) != raw_keys:
        problems.append(("coverage", "output rows do not match raw observations one for one"))

    for row in rows:
        label = "%s %s" % (row["series_id"], row["obs_date"])
        obs_day = date.fromisoformat(row["obs_date"])
        repeated = macro_cutoff_rule.value_as_of(manifest, row["series_id"], obs_day, cutoff)

        if row["status"] == "OK":
            if repeated is None:
                problems.append(("guess", "%s: output has a value but no vintage is eligible" % label))
                continue
            if row["as_of_vintage_date"] != repeated.vintage_date.isoformat():
                problems.append(("mismatch", "%s: as-of vintage %s, repeated selection %s"
                                 % (label, row["as_of_vintage_date"], repeated.vintage_date.isoformat())))
            elif abs(float(row["as_of_value"]) - repeated.value) > 1e-9:
                problems.append(("mismatch", "%s: as-of value %s, repeated selection %s"
                                 % (label, row["as_of_value"], repeated.value)))
            used_day = date.fromisoformat(row["as_of_vintage_date"])
            used = core.MacroVintage(
                series_id=row["series_id"],
                obs_date=obs_day,
                vintage_date=used_day,
                release_at=conservative_release(used_day),
                value=float(row["as_of_value"]),
                source_id=row["source_id"],
            )
            for finding in macro_cutoff_rule.cutoff_violations([used], cutoff):
                problems.append(("exceeds_cutoff", "%s: %s" % (label, finding.message)))
        else:
            if repeated is not None:
                problems.append(("guess", "%s: marked %s but a vintage is eligible" % (label, UNAVAILABLE)))
            if row["as_of_value"] is not None or row["as_of_vintage_date"] is not None:
                problems.append(("guess", "%s: unavailable row carries an as-of value" % label))

        group = [r for r in raw_rows if r["series_id"] == row["series_id"] and r["obs_date"] == row["obs_date"]]
        if group:
            newest = max(group, key=lambda r: date.fromisoformat(r["vintage_date"]))
            if (row["latest_vintage_date"] != newest["vintage_date"]
                    or abs(float(row["latest_value"]) - float(newest["value"])) > 1e-9):
                problems.append(("latest", "%s: latest column is not the newest vintage" % label))
    return problems


# Expected as-of picks at CUTOFF_TEXT, written by hand from SYNTHETIC_RELEASES
# (latest vintage on or before the cutoff). These are fixed expectations, so the
# check does not depend on the verifier or on the selection code under test.
GOLDEN_AS_OF: Dict[str, Tuple[Optional[str], Optional[float], str]] = {
    "2026-02-01": ("2026-04-07", 2.38, "OK"),
    "2026-03-01": ("2026-05-06", 2.49, "OK"),
    "2026-04-01": ("2026-06-05", 2.66, "OK"),
    "2026-05-01": ("2026-06-10", 2.74, "OK"),
    "2026-08-01": (None, None, UNAVAILABLE),
}


def golden_as_of_matches(rows: Sequence[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """Compare every output row with GOLDEN_AS_OF. Returns (passed, differences)."""
    diffs: List[str] = []
    seen = set()
    for row in rows:
        if row["series_id"] != SERIES_ID or row["obs_date"] not in GOLDEN_AS_OF:
            diffs.append("unexpected row %s %s" % (row["series_id"], row["obs_date"]))
            continue
        seen.add(row["obs_date"])
        want_vint, want_val, want_status = GOLDEN_AS_OF[row["obs_date"]]
        got = (row["as_of_vintage_date"], row["as_of_value"], row["status"])
        if got[0] != want_vint or got[2] != want_status or (
                (got[1] is None) != (want_val is None)
                or (got[1] is not None and abs(got[1] - want_val) > 1e-9)):
            diffs.append("%s: got %r want %r" % (row["obs_date"], got, (want_vint, want_val, want_status)))
    for obs in GOLDEN_AS_OF:
        if obs not in seen:
            diffs.append("missing row %s" % obs)
    return (not diffs, diffs)


def boundary_checks() -> List[Dict[str, Any]]:
    """Probe the release-time convention on in-memory vintages, not on the CSV.

    Two probes: the conservative release time is 23:59:59Z on the vintage day,
    and a vintage dated on the cutoff day (12:00Z cutoff) is excluded while the
    day before is kept. Without these, a change to the release convention can
    pass the other checks, because the verifier reuses conservative_release.
    """
    macro_cutoff_rule = component("macro_cutoff_rule")
    core = component("core")
    cutoff = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)
    release_ok = conservative_release(date(2026, 6, 30)) == datetime(
        2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc)

    probe_obs = date(2026, 1, 1)
    probe = component("macro_vintage_manifest").VintageManifest()
    for vint, val in ((date(2026, 6, 29), 1.0), (date(2026, 6, 30), 2.0)):
        probe.add_vintage(core.MacroVintage(
            series_id="SYN_BOUNDARY_PROBE", obs_date=probe_obs, vintage_date=vint,
            release_at=conservative_release(vint), value=val, source_id="SYN_PROBE"))
    picked = macro_cutoff_rule.value_as_of(probe, "SYN_BOUNDARY_PROBE", probe_obs, cutoff)
    # Same probe through the lab's own selector, so both selectors must agree on the boundary.
    own = select_as_of(
        [{"series_id": "SYN_BOUNDARY_PROBE", "obs_date": "2026-01-01", "vintage_date": v.isoformat(),
          "value": str(val), "unit": "u", "seasonal_adjustment": "s", "source_id": "p",
          "retrieved_at": RETRIEVED_AT}
         for v, val in ((date(2026, 6, 29), 1.0), (date(2026, 6, 30), 2.0))], cutoff)
    boundary_ok = (picked is not None and picked.vintage_date == date(2026, 6, 29)
                   and picked.value == 1.0 and own[0]["as_of_vintage_date"] == "2026-06-29")
    return [
        _check("conservative_release_is_2359_59_on_vintage_day", release_ok,
               "conservative_release(2026-06-30) must be 23:59:59Z"),
        _check("cutoff_day_vintage_excluded_day_before_kept", boundary_ok,
               "picked=%s; select_as_of=%s" % (
                   (picked.vintage_date.isoformat(), picked.value) if picked else None,
                   own[0]["as_of_vintage_date"])),
    ]


def metadata_gate(rows: Sequence[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """Return (passed, missing) for the metadata a reviewer needs on every row."""
    missing: List[str] = []
    for row in rows:
        for field in REQUIRED_METADATA:
            if not row.get(field):
                missing.append("%s %s: %s" % (row["series_id"], row["obs_date"], field))
    return (not missing, missing)


# ---------------------------------------------------------------------------
# Check assembly
# ---------------------------------------------------------------------------


def _check(check_id: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {"check_id": check_id, "passed": bool(passed), "detail": detail}


def numeric_checks(rows: Sequence[Dict[str, Any]], raw_rows: Sequence[Dict[str, str]],
                   cutoff: datetime) -> List[Dict[str, Any]]:
    """Run the numeric checks on one output. Shared by the live run and the planted run."""
    problems = verify_output(rows, raw_rows, cutoff)
    by_kind: Dict[str, List[str]] = {}
    for kind, message in problems:
        by_kind.setdefault(kind, []).append(message)

    checks: List[Dict[str, Any]] = []
    checks.append(_check(
        "repeat_selection_every_observation",
        not any(k in by_kind for k in ("mismatch", "guess", "coverage")),
        "rows=%d; problems=%s" % (len(rows), "; ".join(
            by_kind.get("mismatch", []) + by_kind.get("guess", []) + by_kind.get("coverage", [])) or "none"),
    ))
    checks.append(_check(
        "no_as_of_row_exceeds_cutoff",
        "exceeds_cutoff" not in by_kind,
        "cutoff=%s; violations=%s" % (CUTOFF_TEXT, "; ".join(by_kind.get("exceeds_cutoff", [])) or "none"),
    ))
    checks.append(_check(
        "latest_column_is_newest_vintage",
        "latest" not in by_kind,
        "problems=%s" % ("; ".join(by_kind.get("latest", [])) or "none"),
    ))

    april = [r for r in rows if r["obs_date"] == APRIL_OBS]
    april_ok = (len(april) == 1
                and april[0]["as_of_vintage_date"] == "2026-06-05"
                and april[0]["as_of_value"] == 2.66
                and april[0]["latest_vintage_date"] == "2026-07-03"
                and april[0]["latest_value"] == 2.71)
    checks.append(_check(
        "april_as_of_june5_latest_july3",
        april_ok,
        ("as_of=%s/%s latest=%s/%s" % (april[0]["as_of_vintage_date"], april[0]["as_of_value"],
                                       april[0]["latest_vintage_date"], april[0]["latest_value"]))
        if april else "no April row",
    ))

    aug = [r for r in rows if r["obs_date"] == AUG_OBS]
    aug_ok = (len(aug) == 1 and aug[0]["status"] == UNAVAILABLE
              and aug[0]["as_of_value"] is None and aug[0]["as_of_vintage_date"] is None)
    checks.append(_check(
        "no_pre_cutoff_history_returns_unavailable",
        aug_ok,
        ("August row status=%s as_of_value=%s" % (aug[0]["status"], aug[0]["as_of_value"]))
        if aug else "no August row",
    ))
    golden_ok, golden_diffs = golden_as_of_matches(rows)
    checks.append(_check(
        "golden_as_of_table_matches_hand_picks",
        golden_ok,
        "differences=%s" % ("; ".join(golden_diffs) or "none"),
    ))
    checks.extend(boundary_checks())
    return checks


def run_lab(cutoff: datetime) -> Dict[str, Any]:
    """Run the whole lab and return the results dict. Writes no files."""
    content_hash = component("content_hash")
    raw_rows = load_vintage_rows(DATA_PATH)
    input_sha = content_hash.sha256_file(DATA_PATH)
    rows = select_as_of(raw_rows, cutoff)

    numeric = numeric_checks(rows, raw_rows, cutoff)

    # Metadata of the live output. This is the manual gate, with a machine pre-check.
    meta_ok, meta_missing = metadata_gate(rows)
    manual_gates: List[Dict[str, Any]] = [
        {
            "gate_id": "manual_metadata_gate",
            "passed": meta_ok,
            "detail": "unit, seasonal adjustment, source and retrieval time present on every row"
            if meta_ok else "missing: " + "; ".join(meta_missing),
            "human_signoff": "PENDING",
        },
        {
            "gate_id": "official_series_page_check",
            "passed": None,
            "status": "PENDING_MANUAL",
            "detail": "not run: no network in this lab. Check the official series page for series ID, "
                      "units, seasonal adjustment and historical coverage, and the vintage history for "
                      "the release times of each value.",
        },
    ]

    # Planted failure A: disposable output with the later value in the as-of column.
    disposable = [dict(r) for r in rows]
    for row in disposable:
        if row["obs_date"] == APRIL_OBS:
            row["as_of_vintage_date"] = row["latest_vintage_date"]
            row["as_of_value"] = row["latest_value"]
    planted_a_problems = verify_output(disposable, raw_rows, cutoff)
    planted_a_kinds = sorted(set(kind for kind, _ in planted_a_problems))
    # Detection must name the planted April row and the mismatch kind, not any problem.
    planted_a_hit = any(kind == "mismatch" and (APRIL_OBS in msg or "2026-04-01" in msg)
                        for kind, msg in planted_a_problems)
    planted_a = _check(
        "planted_later_value_in_as_of_column_fails_validator",
        planted_a_hit,
        "validator problems=%d kinds=%s; April mismatch flagged=%s"
        % (len(planted_a_problems), planted_a_kinds, planted_a_hit),
    )
    planted_a["detected"] = planted_a_hit

    # Planted failure B: unit removed from the live manifest, in memory only.
    stripped_raw = [dict(r, unit="") if r["series_id"] == SERIES_ID else dict(r) for r in raw_rows]
    stripped_rows = select_as_of(stripped_raw, cutoff)
    stripped_numeric = numeric_checks(stripped_rows, stripped_raw, cutoff)
    numeric_still_pass = all(c["passed"] for c in stripped_numeric)
    stripped_meta_ok, stripped_meta_missing = metadata_gate(stripped_rows)
    planted_b = _check(
        "planted_unit_removed_numeric_passes_manual_gate_fails",
        numeric_still_pass and not stripped_meta_ok,
        "numeric checks still pass=%s; manual metadata gate passed=%s; missing=%d"
        % (numeric_still_pass, stripped_meta_ok, len(stripped_meta_missing)),
    )
    planted_b["detected"] = (not stripped_meta_ok) and numeric_still_pass

    numeric_passed = sum(1 for c in numeric if c["passed"])
    all_numeric = numeric_passed == len(numeric)
    planted = [planted_a, planted_b]
    all_planted = all(p["detected"] for p in planted)

    return {
        "lab": LAB_ID,
        "title": "Reconstruct a macro vintage",
        "data": "synthetic only (series %s)" % SERIES_ID,
        "input_file": os.path.relpath(DATA_PATH, LAB_DIR),
        "input_sha256": input_sha,
        "cutoff_utc": CUTOFF_TEXT,
        "release_time_convention": "date-only vintage is released at 23:59:59Z on its vintage date; "
                                   "a release dated on the cutoff day does not count",
        "output_rows": rows,
        "numeric_checks": numeric,
        "manual_gates": manual_gates,
        "planted_checks": planted,
        "summary": {
            "numeric_checks_passed": numeric_passed,
            "numeric_checks_total": len(numeric),
            "all_numeric_passed": all_numeric,
            "planted_detected": sum(1 for p in planted if p["detected"]),
            "planted_total": len(planted),
            "all_planted_detected": all_planted,
            "manual_gates_pending": [g["gate_id"] for g in manual_gates if g.get("status") == "PENDING_MANUAL"],
        },
        "notes": [
            "Output rows carry the as-of column (as_of_value) and the latest column (latest_value) separately.",
            "The planted disposable output and the planted unit-stripped manifest exist only in memory.",
            "The official series page, its units, adjustment and vintage history were not checked here.",
            "A PASS shows agreement with the synthetic vintages and the cutoff rule only.",
        ],
    }


def main() -> int:
    cutoff = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)
    result = run_lab(cutoff)
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")

    for row in result["output_rows"]:
        print("%s %-10s %-27s as_of=%s/%s latest=%s/%s unit=%r"
              % (row["series_id"], row["obs_date"], row["status"],
                 row["as_of_vintage_date"], row["as_of_value"],
                 row["latest_vintage_date"], row["latest_value"], row["unit"]))
    for check in result["numeric_checks"] + result["planted_checks"]:
        print("%s %s %s" % ("PASS" if check["passed"] else "FAIL", check["check_id"], check["detail"]))
    for gate in result["manual_gates"]:
        label = gate.get("status") or ("PASS" if gate["passed"] else "FAIL")
        print("%s %s %s" % (label, gate["gate_id"], gate["detail"]))

    summary = result["summary"]
    ok = summary["all_numeric_passed"] and summary["all_planted_detected"]
    print("results written to %s" % RESULTS_PATH)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
