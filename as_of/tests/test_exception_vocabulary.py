"""Tests for as_of.exception_vocabulary. All fixtures are synthetic (SYN_ prefix)."""

import pytest

from as_of.core import AsOfError, Finding, Severity, ValidationStatus
from as_of.exception_vocabulary import (
    KIND_DESCRIPTIONS,
    ExceptionKind,
    default_severity,
    describe,
    finding_severity,
    parse_kind,
)


def _finding(status):
    return Finding(
        check_id="SYN_CHECK_1",
        status=status,
        message="synthetic message",
        subject="SYN_SUBJECT",
    )


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_every_exception_kind_has_non_empty_description():
    for kind in ExceptionKind:
        assert kind in KIND_DESCRIPTIONS
        assert isinstance(KIND_DESCRIPTIONS[kind], str)
        assert KIND_DESCRIPTIONS[kind].strip() != ""
        assert describe(kind) == KIND_DESCRIPTIONS[kind]


def test_parse_kind_tieout_break_works():
    assert parse_kind("tieout_break") is ExceptionKind.TIEOUT_BREAK


def test_parse_kind_unknown_raises_as_of_error():
    with pytest.raises(AsOfError):
        parse_kind("nope")


def test_filing_occurred_default_severity_is_info():
    assert default_severity(ExceptionKind.FILING_OCCURRED) is Severity.INFO


def test_finding_severity_maps_fail_to_block():
    assert finding_severity(_finding(ValidationStatus.FAIL)) is Severity.BLOCK


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_every_kind_has_a_default_severity():
    for kind in ExceptionKind:
        assert isinstance(default_severity(kind), Severity)


def test_parse_kind_round_trips_every_value():
    for kind in ExceptionKind:
        assert parse_kind(kind.value) is kind


def test_parse_kind_ignores_case_and_surrounding_spaces():
    assert parse_kind("  Tieout_Break \n") is ExceptionKind.TIEOUT_BREAK
    assert parse_kind("filing_occurred") is ExceptionKind.FILING_OCCURRED


def test_parse_kind_rejects_non_string():
    with pytest.raises(AsOfError):
        parse_kind(None)
    with pytest.raises(AsOfError):
        parse_kind(ExceptionKind.TIEOUT_BREAK)


def test_parse_kind_rejects_empty_string():
    with pytest.raises(AsOfError):
        parse_kind("")


def test_describe_and_default_severity_reject_non_kind():
    with pytest.raises(AsOfError):
        describe("TIEOUT_BREAK")
    with pytest.raises(AsOfError):
        default_severity("TIEOUT_BREAK")


def test_finding_severity_maps_all_statuses():
    assert finding_severity(_finding(ValidationStatus.WARN)) is Severity.WARN
    assert finding_severity(_finding(ValidationStatus.PASS)) is Severity.INFO


def test_finding_severity_rejects_non_finding():
    with pytest.raises(AsOfError):
        finding_severity(ValidationStatus.FAIL)
    with pytest.raises(AsOfError):
        finding_severity(None)


def test_filing_occurred_description_says_significance_is_not_judged():
    text = describe(ExceptionKind.FILING_OCCURRED).lower()
    assert "does not say whether" in text
