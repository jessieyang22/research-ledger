"""Tests for as_of.wf_catalyst_exception_queue. All data is synthetic (SYN_ prefix).

Topic: catalyst exception queue.
"""

from collections import Counter

import pytest

from as_of.catalyst_fixture import make_catalyst_fixture
from as_of.core import SYNTHETIC_SEED, AsOfError, ProofResult, Severity, ValidationStatus
from as_of.wf_catalyst_exception_queue import (
    EXTRA_CLAIM_ID,
    PROOF_NAME,
    run_catalyst_proof,
)


def _pairs(result: ProofResult):
    return [(f.check_id, f.subject) for f in result.findings]


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_default_run_open_kinds_and_subjects_equal_expected():
    result = run_catalyst_proof()
    assert isinstance(result, ProofResult)
    assert result.proof_name == PROOF_NAME
    fx = make_catalyst_fixture(SYNTHETIC_SEED)
    expected = [(str(k), str(s)) for k, s in fx["exceptions_expected"]]
    assert Counter(_pairs(result)) == Counter(expected)
    assert result.metrics["matched"] == 1.0
    assert result.metrics["expected_count"] == float(len(expected))
    assert result.metrics["queue_size"] == float(len(expected))
    assert result.passed is True


def test_default_run_findings_follow_expected_order():
    result = run_catalyst_proof()
    fx = make_catalyst_fixture(SYNTHETIC_SEED)
    expected = [(str(k), str(s)) for k, s in fx["exceptions_expected"]]
    assert _pairs(result) == expected


def test_filing_occurred_items_are_info():
    result = run_catalyst_proof()
    filing = [f for f in result.findings if f.check_id == "FILING_OCCURRED"]
    assert len(filing) == 2
    assert result.metrics["filing_occurred_count"] == 2.0
    assert result.metrics["filing_occurred_non_info"] == 0.0
    for f in filing:
        assert f.status is ValidationStatus.PASS
        assert f.message.startswith("INFO")


def test_running_proof_twice_gives_same_queue_size():
    first = run_catalyst_proof()
    second = run_catalyst_proof()
    assert first.metrics["queue_size"] == second.metrics["queue_size"]
    assert first.metrics == second.metrics
    assert _pairs(first) == _pairs(second)


def test_inject_unlinked_gives_passed_false():
    result = run_catalyst_proof(inject_unlinked=True)
    assert result.passed is False
    assert result.metrics["matched"] == 0.0
    assert result.metrics["queue_size"] == result.metrics["expected_count"] + 1.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_inject_unlinked_adds_one_extra_claim_finding_at_end():
    base = run_catalyst_proof()
    injected = run_catalyst_proof(inject_unlinked=True)
    assert len(injected.findings) == len(base.findings) + 1
    # Expected-order findings come first; the extra one is last.
    assert _pairs(injected)[:-1] == _pairs(base)
    kind, subject = _pairs(injected)[-1]
    assert kind == "CLAIM_UNLINKED"
    assert subject == EXTRA_CLAIM_ID


def test_inject_unlinked_does_not_leak_into_later_default_run():
    run_catalyst_proof(inject_unlinked=True)
    result = run_catalyst_proof()
    assert result.passed is True
    assert result.metrics["matched"] == 1.0


def test_findings_metadata_matches_queue_records():
    result = run_catalyst_proof()
    assert len(result.findings) == int(result.metrics["queue_size"])
    for f in result.findings:
        assert f.check_id
        assert f.subject
        assert ":" in f.message
    # Severity name prefix maps to the status: INFO -> PASS, WARN -> WARN.
    for f in result.findings:
        prefix = f.message.split(":", 1)[0]
        if prefix == Severity.INFO.name:
            assert f.status is ValidationStatus.PASS
        elif prefix == Severity.WARN.name:
            assert f.status is ValidationStatus.WARN
        else:
            assert prefix == Severity.BLOCK.name
            assert f.status is ValidationStatus.FAIL


def test_default_run_has_no_fail_findings():
    result = run_catalyst_proof()
    assert all(f.status is not ValidationStatus.FAIL for f in result.findings)


def test_metrics_are_floats():
    result = run_catalyst_proof()
    assert set(result.metrics) == {
        "queue_size",
        "expected_count",
        "matched",
        "filing_occurred_count",
        "filing_occurred_non_info",
    }
    for value in result.metrics.values():
        assert isinstance(value, float)


def test_default_seed_matches_explicit_seed():
    a = run_catalyst_proof()
    b = run_catalyst_proof(seed=SYNTHETIC_SEED)
    assert _pairs(a) == _pairs(b)
    assert a.passed == b.passed


def test_other_seed_still_runs_and_matches():
    result = run_catalyst_proof(seed=SYNTHETIC_SEED + 1)
    assert isinstance(result, ProofResult)
    assert result.metrics["matched"] == 1.0
    assert result.passed is True


def test_filing_occurred_count_matches_fixture_filings():
    fx = make_catalyst_fixture(SYNTHETIC_SEED)
    n_filings = sum(1 for k, _ in fx["exceptions_expected"] if k == "FILING_OCCURRED")
    result = run_catalyst_proof()
    assert result.metrics["filing_occurred_count"] == float(n_filings)


def test_non_int_seed_raises():
    with pytest.raises(AsOfError):
        run_catalyst_proof(seed="1")


def test_bool_seed_raises():
    with pytest.raises(AsOfError):
        run_catalyst_proof(seed=True)


def test_non_bool_inject_flag_raises():
    with pytest.raises(AsOfError):
        run_catalyst_proof(inject_unlinked=1)
