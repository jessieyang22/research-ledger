"""Proof 1: earnings reconciliation for the as_of research state.

The proof builds a synthetic earnings fixture, then walks every reported
figure and computes its expected value as of the report time. For each
report it does three things:

    1. Assembles the expected set, which is every estimate row for the
       ticker, metric and period. When inject_lookahead is True, one
       deliberately late estimate (knowledge time after the report) is
       added to that set so the look-ahead check can be exercised.
    2. Flags any row in the expected set whose knowledge time is after the
       report time as a LOOKAHEAD_RISK finding. A row known exactly at the
       report time is allowed. The bridge also refuses to use rows after the
       report time, and the proof checks the bridge's basis timestamp
       separately.
    3. Calls the reported-vs-expected bridge and records the surprise
       classification, then checks that every source id used by an estimate
       or a report is present in the source register.

The proof passes when no finding has FAIL status. Metrics count the reports,
the bridges that produced an expected value, the look-ahead rows, the
unregistered sources and the beat, miss, inline and no-expected outcomes.

Only as_of.core is imported statically. The fixture, bridge, and source
register modules are loaded through core.component inside the function
bodies, so this module's only static dependency is core.py. All data is
synthetic (ids start with SYN_) and the proof makes no network calls.

The design is an original implementation of the idea that a reconciliation
must be rebuilt as of each report time, not as of the date the check runs.

Public API:
    run_earnings_proof(seed=SYNTHETIC_SEED, inject_lookahead=False) -> ProofResult
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Sequence, Tuple

from as_of.core import (
    SYNTHETIC_SEED,
    EstimateRecord,
    Finding,
    ProofResult,
    ValidationStatus,
    component,
    ensure_utc,
)

PROOF_NAME: str = "earnings_reconciliation"
CHECK_LOOKAHEAD: str = "LOOKAHEAD_RISK"
CHECK_BASIS_AFTER_REPORT: str = "RECON_BASIS_AFTER_REPORT"
CHECK_NO_EXPECTED: str = "RECON_NO_EXPECTED"
CHECK_SUMMARY: str = "RECON_SUMMARY"

# Surprise inside the symmetric band [-BAND, +BAND] counts as inline.
SURPRISE_BAND: float = 0.02

# Injected late estimate: analyst id, and how long after the report it is known.
LATE_ANALYST_ID: str = "SYN_AN_LATE"
LATE_OFFSET_DAYS: int = 2

# Timestamps have microsecond resolution. The bridge keeps rows whose
# knowledge time is strictly before its reported_at. Passing report_at plus
# one microsecond as that bound therefore keeps exactly the rows known at or
# before the report instant, which is the rule this proof uses.
_ONE_MICROSECOND: timedelta = timedelta(microseconds=1)

SeriesKey = Tuple[str, str, str]


def _series_key(rec: EstimateRecord) -> SeriesKey:
    """Return the (ticker, metric, period) key that identifies one series."""
    return (rec.ticker, rec.metric, rec.period)


def _group_estimates(estimates: Sequence[EstimateRecord]) -> Dict[SeriesKey, List[EstimateRecord]]:
    """Group estimate rows by series, keeping the fixture's row order."""
    grouped: Dict[SeriesKey, List[EstimateRecord]] = {}
    for rec in estimates:
        grouped.setdefault(_series_key(rec), []).append(rec)
    return grouped


def _source_ids_by_locator(sources: Sequence[Any]) -> Dict[str, str]:
    """Map each fixture source locator to its source id."""
    return {src.locator: src.source_id for src in sources}


def _late_estimate(
    report: Dict[str, Any],
    estimate_source_id: str,
) -> EstimateRecord:
    """Build one estimate that becomes known after its report time.

    Its value equals the reported figure, so a pipeline that averaged it in
    would show a visible shift. The bridge must exclude it.
    """
    report_at: datetime = report["reported_at"]
    ticker: str = report["ticker"]
    metric: str = report["metric"]
    period: str = report["period"]
    return EstimateRecord(
        estimate_id="SYN_EST_LATE_%s_%s_%s" % (ticker, metric, period),
        ticker=ticker,
        metric=metric,
        period=period,
        analyst_id=LATE_ANALYST_ID,
        value=float(report["reported_value"]),
        knowledge_at=report_at + timedelta(days=LATE_OFFSET_DAYS),
        source_id=estimate_source_id,
    )


def run_earnings_proof(
    seed: int = SYNTHETIC_SEED,
    inject_lookahead: bool = False,
) -> ProofResult:
    """Run the earnings reconciliation proof on a synthetic fixture.

    Args:
        seed: seed for the synthetic fixture. The same seed gives equal output.
        inject_lookahead: when True, add one post-report estimate to each
            series' expected set. The proof should then fail with
            LOOKAHEAD_RISK findings.

    Returns:
        A ProofResult. passed is True when no finding has FAIL status.
    """
    fixture_mod = component("earnings_fixture")
    bridge_mod = component("reported_vs_expected_bridge")
    register_mod = component("source_register")

    fixture = fixture_mod.make_fixture(seed=seed)
    sources = fixture["sources"]
    estimates = fixture["estimates"]
    reports = fixture["reports"]

    register = register_mod.SourceRegister()
    for src in sources:
        register.add_source(src)

    est_source_by_locator = _source_ids_by_locator(sources)
    report_source_by_ticker: Dict[str, str] = {}
    for src in sources:
        if src.locator.startswith("fixture://earnings/reports/"):
            ticker = src.locator[len("fixture://earnings/reports/"):]
            report_source_by_ticker[ticker] = src.source_id

    series_rows = _group_estimates(estimates)

    findings: List[Finding] = []
    used_source_ids: List[str] = []
    counts: Dict[str, int] = {
        "beat": 0,
        "miss": 0,
        "inline": 0,
        "no_expected": 0,
        "bridges_with_expected": 0,
        "lookahead_rows": 0,
        "basis_after_report": 0,
    }

    for report in reports:
        ticker: str = report["ticker"]
        metric: str = report["metric"]
        period: str = report["period"]
        report_at: datetime = ensure_utc(report["reported_at"])
        subject = "%s/%s/%s" % (ticker, metric, period)

        rows = list(series_rows.get((ticker, metric, period), []))
        if inject_lookahead:
            est_source = est_source_by_locator.get(
                "fixture://earnings/estimates/" + ticker, ""
            )
            rows.append(_late_estimate(report, est_source))

        used_source_ids.extend(rec.source_id for rec in rows)
        if ticker in report_source_by_ticker:
            used_source_ids.append(report_source_by_ticker[ticker])

        # 1 and 2: expected set must hold nothing known after the report time.
        # A row known exactly at the report instant is known, not look-ahead,
        # so only rows strictly later than report_at are flagged.
        for rec in rows:
            if ensure_utc(rec.knowledge_at) > report_at:
                counts["lookahead_rows"] += 1
                findings.append(Finding(
                    check_id=CHECK_LOOKAHEAD,
                    status=ValidationStatus.FAIL,
                    message="expected set holds estimate %s known %s, after report time %s"
                    % (rec.estimate_id, rec.knowledge_at.isoformat(), report_at.isoformat()),
                    subject=subject,
                ))

        # 3: bridge as of the report time.
        # The bridge's bound is exclusive, so pass one microsecond past the
        # report instant to admit rows known exactly at report_at. Rows after
        # report_at are still excluded by the bridge.
        bridge = bridge_mod.build_bridge(
            rows, ticker, metric, period, report["reported_value"],
            report_at + _ONE_MICROSECOND,
        )

        if bridge["expected"] is None:
            counts["no_expected"] += 1
            findings.append(Finding(
                check_id=CHECK_NO_EXPECTED,
                status=ValidationStatus.FAIL,
                message="no estimate was known at report time; cannot reconcile",
                subject=subject,
            ))
            continue

        counts["bridges_with_expected"] += 1

        basis = bridge["basis_as_of"]
        if basis is not None and basis > report_at:
            counts["basis_after_report"] += 1
            findings.append(Finding(
                check_id=CHECK_BASIS_AFTER_REPORT,
                status=ValidationStatus.FAIL,
                message="bridge basis %s is after report time %s"
                % (basis.isoformat(), report_at.isoformat()),
                subject=subject,
            ))

        outcome = bridge_mod.classify_surprise(bridge["surprise_pct"], SURPRISE_BAND)
        if outcome == bridge_mod.CLASS_BEAT:
            counts["beat"] += 1
        elif outcome == bridge_mod.CLASS_MISS:
            counts["miss"] += 1
        elif outcome == bridge_mod.CLASS_INLINE:
            counts["inline"] += 1
        else:
            # Expected value is zero, so percent surprise is undefined. Count it
            # as unclassifiable and fail it, so the outcome counts still
            # partition the reports and the zero case cannot pass silently.
            counts["no_expected"] += 1
            findings.append(Finding(
                check_id=CHECK_NO_EXPECTED,
                status=ValidationStatus.FAIL,
                message="expected value is zero; percent surprise is undefined",
                subject=subject,
            ))

    # Source registration: every id used must be in the register.
    source_findings = register.check_sources_used(used_source_ids)
    findings.extend(source_findings)

    # An empty report list reconciles nothing, so it must not count as a pass.
    passed = bool(reports) and all(f.status != ValidationStatus.FAIL for f in findings)
    findings.append(Finding(
        check_id=CHECK_SUMMARY,
        status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
        message="%d reports reconciled, %d look-ahead rows, %d unregistered sources"
        % (len(reports), counts["lookahead_rows"], len(source_findings)),
        subject="earnings",
    ))

    metrics: Dict[str, float] = {
        "n_reports": float(len(reports)),
        "n_estimates": float(len(estimates)),
        "n_bridges_with_expected": float(counts["bridges_with_expected"]),
        "n_lookahead_rows": float(counts["lookahead_rows"]),
        "n_basis_after_report": float(counts["basis_after_report"]),
        "n_unregistered_sources": float(len(source_findings)),
        "n_beat": float(counts["beat"]),
        "n_miss": float(counts["miss"]),
        "n_inline": float(counts["inline"]),
        "n_no_expected": float(counts["no_expected"]),
    }

    return ProofResult(
        proof_name=PROOF_NAME,
        passed=passed,
        findings=tuple(findings),
        metrics=metrics,
    )
