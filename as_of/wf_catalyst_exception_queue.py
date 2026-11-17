"""Proof 3: catalyst exception queue.

This module runs the catalyst checks end to end on the synthetic catalyst
fixture and opens the results in an exception queue:

    1. Register the fixture sources in a SourceRegister.
    2. Run claim-link validation (catalyst links and source registration).
    3. Ingest the fixture filings into a FilingMonitor and read them back.
    4. Map each finding and each observed filing to an ExceptionKind, take its
       default severity from the vocabulary, and open it in a fresh
       ExceptionQueue.
    5. Compare the open (kind, subject_id) pairs with the fixture's
       exceptions_expected list.

Public API:
    run_catalyst_proof(seed, inject_unlinked) -> ProofResult

ProofResult layout (the tests read this, so it is fixed here):
    * proof_name is "catalyst_exception_queue".
    * findings holds exactly one Finding per open exception, in this order:
      first the fixture's expected order, then any extra items. Each Finding
      has check_id set to the kind name, subject set to the subject_id,
      status FAIL for BLOCK, WARN for WARN and PASS for INFO, and a message
      that starts with the severity name. No summary findings are added.
    * metrics (all floats):
        queue_size              open exceptions in the queue
        expected_count          entries in exceptions_expected
        matched                 1.0 when open (kind, subject) pairs equal the
                                expected list as a multiset, else 0.0
        filing_occurred_count   FILING_OCCURRED items in the queue
        filing_occurred_non_info  FILING_OCCURRED items whose severity is not INFO
    * passed is True only when matched is 1.0 and filing_occurred_non_info is 0.

Design notes:
    * No module-level state. Each call builds a new register, monitor and
      queue, so two calls with the same seed give the same queue size.
    * Queue timestamps are fixed. Filing exceptions use the filing's
      accepted_at. Claim exceptions use CLAIM_OPENED_AT. The current clock is
      never read.
    * Severity comes from exception_vocabulary.default_severity. The
      vocabulary is the canonical source of severities for queue records.
    * With inject_unlinked=True an extra claim with no link is added. The
      expected list is not changed, so the run no longer matches and passed
      is False.

Imports: only as_of.core is imported at module load. The other as_of modules
(catalyst_fixture, source_register, catalyst_claim_links, filing_monitor,
exception_queue, exception_vocabulary) are reached inside function bodies
through component(), which is the package convention described in core.py.
No depends_on list was supplied with this task.

It uses synthetic data only and makes no network calls and no I/O.
"""

from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Tuple

from as_of.core import (
    SYNTHETIC_PREFIX,
    SYNTHETIC_SEED,
    ClaimRecord,
    Finding,
    ProofResult,
    Severity,
    SourceType,
    ValidationStatus,
    component,
    parse_ts,
    require,
)

PROOF_NAME: str = "catalyst_exception_queue"
EXTRA_CLAIM_ID: str = SYNTHETIC_PREFIX + "CLM_04"
CLAIM_OPENED_AT: datetime = parse_ts("2026-10-27T00:00:00Z")
FILING_WINDOW_START: datetime = parse_ts("2026-01-01T00:00:00Z")
# The window ends at the as-of point. A filing accepted later would be
# information the review could not have seen (look-ahead).
FILING_WINDOW_END: datetime = CLAIM_OPENED_AT

_STATUS_FOR_SEVERITY: Dict[Severity, ValidationStatus] = {
    Severity.BLOCK: ValidationStatus.FAIL,
    Severity.WARN: ValidationStatus.WARN,
    Severity.INFO: ValidationStatus.PASS,
}


def _kind_for_check(check_id: str, vocab: Any, links_mod: Any, src_mod: Any) -> Any:
    """Map a validation check_id to an ExceptionKind.

    CLAIM_UNLINKED maps to its own kind. SRC_UNREGISTERED maps to
    MISSING_SOURCE. Every other check, including CLAIM_DANGLING_LINK, maps to
    CHECK_FAILED, which the vocabulary reserves for failing checks that fit no
    more specific kind.
    """
    kinds = vocab.ExceptionKind
    if check_id == links_mod.UNLINKED_CHECK_ID:
        return kinds.CLAIM_UNLINKED
    if check_id == src_mod.UNREGISTERED_CHECK_ID:
        return kinds.MISSING_SOURCE
    return kinds.CHECK_FAILED


def run_catalyst_proof(
    seed: int = SYNTHETIC_SEED,
    inject_unlinked: bool = False,
) -> ProofResult:
    """Run Proof 3 on the synthetic catalyst fixture.

    Args:
        seed: Seed passed to the synthetic catalyst fixture.
        inject_unlinked: When True, add one extra claim that has no catalyst
            link. The run then fails the comparison with the expected list.

    Returns:
        A ProofResult. See the module docstring for its layout.
    """
    require(isinstance(seed, int) and not isinstance(seed, bool), "seed must be an int")
    require(isinstance(inject_unlinked, bool), "inject_unlinked must be a bool")

    fixture_mod = component("catalyst_fixture")
    register_mod = component("source_register")
    links_mod = component("catalyst_claim_links")
    filing_mod = component("filing_monitor")
    queue_mod = component("exception_queue")
    vocab = component("exception_vocabulary")

    fx: Dict[str, Any] = fixture_mod.make_catalyst_fixture(seed)
    expected_pairs: List[Tuple[str, str]] = [
        (str(kind), str(subject)) for kind, subject in fx["exceptions_expected"]
    ]

    # 1. Source register holds every fixture source.
    register = register_mod.SourceRegister()
    for src in fx["sources"]:
        register.add_source(src)

    # 2. Claim-link validation.
    claims: List[ClaimRecord] = list(fx["claims"])
    links: Dict[str, str] = dict(fx["links"])
    if inject_unlinked:
        catalyst_sources = [s for s in fx["sources"] if s.source_type == SourceType.CATALYST]
        require(catalyst_sources, "fixture has no catalyst source to cite for the injected claim")
        catalyst_source_id = catalyst_sources[0].source_id
        claims.append(
            ClaimRecord(
                claim_id=EXTRA_CLAIM_ID,
                text="Synthetic injected claim with no catalyst link.",
                claim_kind="risk",
                source_ids=(catalyst_source_id,),
                status="draft",
                section="risks",
            )
        )
    link_findings: List[Any] = links_mod.validate_links(
        claims, links, fx["catalyst_ids"], register
    )

    # 3. Filing monitor: ingest the fixture filings and read them back.
    monitor = filing_mod.FilingMonitor(register)
    for filing in fx["filings"]:
        monitor.ingest_filing(filing)
    observed: List[Any] = []
    for ticker in sorted({f.ticker for f in fx["filings"]}):
        observed.extend(monitor.occurrences(ticker, FILING_WINDOW_START, FILING_WINDOW_END))

    # 4. Open exceptions in a fresh queue.
    queue = queue_mod.ExceptionQueue()
    # The queue keeps one record per (kind, subject, opened_at). Several link
    # findings can share that key (for example two unregistered sources on one
    # claim). Merge their messages so that no note is silently dropped.
    grouped: Dict[Tuple[str, str], List[str]] = {}
    for finding in link_findings:
        kind = _kind_for_check(finding.check_id, vocab, links_mod, register_mod)
        notes = grouped.setdefault((kind.value, str(finding.subject)), [])
        if finding.message not in notes:
            notes.append(finding.message)
    for (kind_name, subject), notes in grouped.items():
        kind = vocab.ExceptionKind(kind_name)
        queue.open(
            kind.value,
            subject,
            CLAIM_OPENED_AT,
            note="; ".join(notes),
            severity=vocab.default_severity(kind),
        )
    for rec in observed:
        kind = vocab.ExceptionKind.FILING_OCCURRED
        queue.open(
            kind.value,
            rec.filing_id,
            rec.accepted_at,
            note="filing %s (%s) accepted" % (rec.filing_id, rec.form_type),
            severity=vocab.default_severity(kind),
        )

    # 5. Compare open items with the expected list.
    open_records = queue.open_items()
    actual_pairs: List[Tuple[str, str]] = [(r.kind, r.subject_id) for r in open_records]
    matched = Counter(actual_pairs) == Counter(expected_pairs)

    # Order findings: expected order first, then extras in insertion order.
    first_index: Dict[Tuple[str, str], int] = {}
    for idx, pair in enumerate(expected_pairs):
        first_index.setdefault(pair, idx)
    fallback = len(expected_pairs)
    ordered = sorted(
        enumerate(open_records),
        key=lambda item: (first_index.get((item[1].kind, item[1].subject_id), fallback), item[0]),
    )

    findings: List[Finding] = []
    for _, rec in ordered:
        findings.append(
            Finding(
                check_id=rec.kind,
                status=_STATUS_FOR_SEVERITY[rec.severity],
                message="%s: %s" % (rec.severity.name, rec.note),
                subject=rec.subject_id,
            )
        )

    filing_items = [r for r in open_records if r.kind == vocab.ExceptionKind.FILING_OCCURRED.value]
    filing_non_info = [r for r in filing_items if r.severity != Severity.INFO]

    metrics: Dict[str, float] = {
        "queue_size": float(len(open_records)),
        "expected_count": float(len(expected_pairs)),
        "matched": 1.0 if matched else 0.0,
        "filing_occurred_count": float(len(filing_items)),
        "filing_occurred_non_info": float(len(filing_non_info)),
    }
    passed = bool(matched and not filing_non_info)

    return ProofResult(
        proof_name=PROOF_NAME,
        passed=passed,
        findings=tuple(findings),
        metrics=metrics,
    )
