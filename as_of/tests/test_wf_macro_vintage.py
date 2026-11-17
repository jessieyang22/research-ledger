"""Tests for as_of.wf_macro_vintage. All data is synthetic (SYN_ prefix).

Topic: macro vintage and as-of value selection.
"""

import pytest

from as_of.core import SYNTHETIC_SEED, ProofResult, ValidationStatus
from as_of.wf_macro_vintage import (
    OBS_COUNT,
    PROOF_NAME,
    REVISION_EVERY,
    run_macro_proof,
)


def _fail_checks(result: ProofResult):
    return [f.check_id for f in result.findings if f.status is ValidationStatus.FAIL]


def _manifest_hash_from_findings(result: ProofResult) -> str:
    for f in result.findings:
        if f.check_id == "macro_vintage_manifest":
            for part in f.message.split():
                if part.startswith("manifest_hash="):
                    return part.split("=", 1)[1]
    raise AssertionError("manifest_hash finding not found")


def _state_digest_from_findings(result: ProofResult) -> str:
    for f in result.findings:
        if f.check_id == "macro_vintage_manifest":
            for part in f.message.split():
                if part.startswith("state_digest="):
                    return part.split("=", 1)[1]
    raise AssertionError("state_digest finding not found")


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_default_run_passes():
    result = run_macro_proof()
    assert isinstance(result, ProofResult)
    assert result.proof_name == PROOF_NAME
    assert result.passed is True
    assert _fail_checks(result) == []
    assert result.metrics["violation_count"] == 0.0
    assert result.metrics["inject_lookahead"] == 0.0


def test_inject_lookahead_true_gives_passed_false():
    result = run_macro_proof(inject_lookahead=True)
    assert result.passed is False
    assert "macro_vintage_cutoff" in _fail_checks(result)
    assert result.metrics["inject_lookahead"] == 1.0


def test_manifest_hash_is_equal_across_two_runs():
    first = run_macro_proof()
    second = run_macro_proof()
    h1 = _manifest_hash_from_findings(first)
    h2 = _manifest_hash_from_findings(second)
    assert h1 == h2
    assert len(h1) == 64
    int(h1, 16)
    assert _state_digest_from_findings(first) == _state_digest_from_findings(second)


def test_metrics_include_the_vintage_count():
    result = run_macro_proof()
    assert "vintage_count" in result.metrics
    revisions = sum(1 for idx in range(OBS_COUNT) if idx % REVISION_EVERY == 0)
    assert result.metrics["vintage_count"] == float(OBS_COUNT + revisions)
    assert result.metrics["vintage_count"] == 9.0
    assert result.metrics["observation_count"] == float(OBS_COUNT)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_default_run_uses_seed_default():
    explicit = run_macro_proof(seed=SYNTHETIC_SEED)
    implicit = run_macro_proof()
    assert _manifest_hash_from_findings(explicit) == _manifest_hash_from_findings(implicit)


def test_different_seed_changes_manifest_hash():
    a = run_macro_proof(seed=SYNTHETIC_SEED)
    b = run_macro_proof(seed=SYNTHETIC_SEED + 1)
    assert _manifest_hash_from_findings(a) != _manifest_hash_from_findings(b)


def test_different_seed_still_passes_by_default():
    for seed in (1, 7, 42):
        assert run_macro_proof(seed=seed).passed is True


def test_lookahead_violations_one_per_revised_observation():
    result = run_macro_proof(inject_lookahead=True)
    revised = result.metrics["revised_observation_count"]
    assert result.metrics["violation_count"] == revised
    cutoff_fails = [
        f for f in result.findings
        if f.check_id == "macro_vintage_cutoff" and f.status is ValidationStatus.FAIL
    ]
    assert len(cutoff_fails) == int(revised)
    for f in cutoff_fails:
        assert "is after decision time" in f.message


def test_lookahead_also_reports_pick_mismatch():
    result = run_macro_proof(inject_lookahead=True)
    assert "macro_vintage_pick" in _fail_checks(result)


def test_default_run_has_no_coverage_or_order_failures():
    result = run_macro_proof()
    checks = _fail_checks(result)
    assert "macro_vintage_coverage" not in checks
    assert "macro_vintage_order" not in checks


def test_revised_observation_count_matches_revision_rule():
    result = run_macro_proof()
    expected = sum(1 for idx in range(OBS_COUNT) if idx % REVISION_EVERY == 0)
    assert result.metrics["revised_observation_count"] == float(expected)


def test_decision_count_is_one_per_vintage():
    result = run_macro_proof()
    assert result.metrics["decision_count"] == result.metrics["vintage_count"]


def test_inject_lookahead_does_not_change_manifest_hash():
    # The planted fault changes the pick, not the vintage set, so the manifest hash is unchanged.
    clean = run_macro_proof(inject_lookahead=False)
    planted = run_macro_proof(inject_lookahead=True)
    assert _manifest_hash_from_findings(clean) == _manifest_hash_from_findings(planted)


def test_findings_are_a_tuple_and_metrics_are_floats():
    result = run_macro_proof()
    assert isinstance(result.findings, tuple)
    assert all(isinstance(v, float) for v in result.metrics.values())


