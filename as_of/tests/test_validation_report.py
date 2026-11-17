"""Tests for as_of.validation_report. All fixtures are synthetic (SYN_ prefix)."""

import pytest

from as_of.core import AsOfError, Finding, ValidationStatus
from as_of.validation_report import build_report, render_report_text, report_passes


def _f(check_id, status, subject="SYN_SUBJ", message="synthetic message"):
    return Finding(check_id=check_id, status=status, message=message, subject=subject)


def _build(results, title="SYN report", generated_for="SYN reviewer"):
    return build_report(title, results, generated_for)


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_report_passes_is_false_when_any_finding_is_fail():
    results = {
        "SYN_CHECK_A": [_f("SYN_CHECK_A", ValidationStatus.PASS)],
        "SYN_CHECK_B": [
            _f("SYN_CHECK_B", ValidationStatus.WARN),
            _f("SYN_CHECK_B", ValidationStatus.FAIL, subject="SYN_ROW_2"),
        ],
    }
    report = _build(results)
    assert report["status"] == ValidationStatus.FAIL.value
    assert report_passes(report) is False


def test_empty_results_pass():
    report = _build({})
    assert report["check_count"] == 0
    assert report["status"] == ValidationStatus.PASS.value
    assert report_passes(report) is True


def test_render_report_text_lists_every_check_name():
    results = {
        "SYN_ZETA": [_f("SYN_ZETA", ValidationStatus.PASS)],
        "SYN_ALPHA": [_f("SYN_ALPHA", ValidationStatus.FAIL)],
        "SYN_EMPTY": [],
    }
    text = render_report_text(_build(results))
    for name in results:
        assert name in text


def test_same_inputs_give_identical_text():
    def make():
        return {
            "SYN_B": [_f("SYN_B", ValidationStatus.WARN, subject="SYN_X")],
            "SYN_A": [_f("SYN_A", ValidationStatus.PASS, subject="SYN_Y")],
        }

    first = render_report_text(_build(make(), title="SYN t", generated_for="SYN g"))
    second = render_report_text(_build(make(), title="SYN t", generated_for="SYN g"))
    assert first == second


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_warn_only_report_still_passes():
    report = _build({"SYN_W": [_f("SYN_W", ValidationStatus.WARN)]})
    assert report["status"] == ValidationStatus.WARN.value
    assert report_passes(report) is True


def test_check_with_no_findings_is_pass_and_rendered():
    report = _build({"SYN_NONE": []})
    assert report["checks"][0]["status"] == ValidationStatus.PASS.value
    assert report["checks"][0]["findings"] == []
    assert "SYN_NONE [PASS]" in render_report_text(report)


def test_checks_are_stored_in_sorted_name_order():
    results = {
        "SYN_C": [],
        "SYN_A": [],
        "SYN_B": [],
    }
    report = _build(results)
    assert [c["name"] for c in report["checks"]] == ["SYN_A", "SYN_B", "SYN_C"]


def test_counts_tally_each_status():
    results = {
        "SYN_1": [
            _f("SYN_1", ValidationStatus.PASS),
            _f("SYN_1", ValidationStatus.WARN),
        ],
        "SYN_2": [
            _f("SYN_2", ValidationStatus.FAIL),
            _f("SYN_2", ValidationStatus.FAIL),
        ],
    }
    report = _build(results)
    assert report["counts"] == {"pass": 1, "warn": 1, "fail": 2}
    assert report["check_count"] == 2


def test_render_marks_failing_finding_and_overall_fail():
    report = _build({"SYN_F": [_f("SYN_F", ValidationStatus.FAIL, subject="SYN_ROW", message="SYN bad")]})
    text = render_report_text(report)
    assert "Overall: FAIL" in text
    assert "FAIL SYN_ROW: SYN bad" in text
    assert text.endswith("\n")


def test_report_passes_rejects_non_dict():
    with pytest.raises(AsOfError):
        report_passes(["not", "a", "dict"])


def test_render_rejects_non_dict():
    with pytest.raises(AsOfError):
        render_report_text("not a dict")


def test_build_rejects_non_finding_entry():
    with pytest.raises(AsOfError):
        _build({"SYN_BAD": ["not a finding"]})


def test_build_rejects_non_str_check_name():
    with pytest.raises(AsOfError):
        _build({123: []})
