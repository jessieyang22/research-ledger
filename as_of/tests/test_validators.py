"""Tests for as_of.validators. All fixtures are synthetic (SYN_ prefix)."""

from datetime import date

import pytest

from as_of.core import AsOfError, Finding, ValidationStatus
from as_of.validators import (
    Validator,
    ValidatorRegistry,
    check_no_nan,
    check_sorted_dates,
    overall_status,
)


def _pass(name, subject_label="SYN_OK"):
    def check(subject):
        return [
            Finding(
                check_id=name,
                status=ValidationStatus.PASS,
                message="ok for %s" % subject_label,
                subject=subject_label,
            )
        ]

    return Validator(name=name, check=check)


def _fail(name):
    def check(subject):
        return [
            Finding(
                check_id=name,
                status=ValidationStatus.FAIL,
                message="synthetic failure",
                subject="SYN_BAD",
            )
        ]

    return Validator(name=name, check=check)


def _warn(name):
    def check(subject):
        return [
            Finding(
                check_id=name,
                status=ValidationStatus.WARN,
                message="synthetic warning",
                subject="SYN_WARN",
            )
        ]

    return Validator(name=name, check=check)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registering_duplicate_name_raises_asof_error():
    reg = ValidatorRegistry()
    reg.register(_pass("SYN_dup"))
    with pytest.raises(AsOfError, match="duplicate validator name"):
        reg.register(_fail("SYN_dup"))
    # The original registration is kept and the registry is unchanged.
    assert reg.names() == ["SYN_dup"]


def test_register_rejects_non_validator():
    reg = ValidatorRegistry()
    with pytest.raises(AsOfError):
        reg.register("SYN_not_a_validator")


def test_register_rejects_empty_name():
    reg = ValidatorRegistry()
    with pytest.raises(AsOfError):
        reg.register(Validator(name="", check=lambda s: []))


def test_register_rejects_non_callable_check():
    reg = ValidatorRegistry()
    with pytest.raises(AsOfError):
        reg.register(Validator(name="SYN_nocall", check=None))


def test_names_keep_registration_order():
    reg = ValidatorRegistry()
    for name in ["SYN_c", "SYN_a", "SYN_b"]:
        reg.register(_pass(name))
    assert reg.names() == ["SYN_c", "SYN_a", "SYN_b"]


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def test_run_with_names_runs_only_those_validators():
    calls = []

    def make(name):
        def check(subject):
            calls.append(name)
            return [
                Finding(
                    check_id=name,
                    status=ValidationStatus.PASS,
                    message="ran",
                    subject="SYN",
                )
            ]

        return Validator(name=name, check=check)

    reg = ValidatorRegistry()
    for name in ["SYN_one", "SYN_two", "SYN_three"]:
        reg.register(make(name))

    findings = reg.run({"SYN": 1}, names=["SYN_three", "SYN_one"])

    assert calls == ["SYN_three", "SYN_one"]
    assert [f.check_id for f in findings] == ["SYN_three", "SYN_one"]


def test_run_with_empty_names_runs_nothing():
    calls = []
    reg = ValidatorRegistry()
    reg.register(Validator(name="SYN_x", check=lambda s: calls.append(s) or []))
    assert reg.run("SYN", names=[]) == []
    assert calls == []


def test_run_with_none_runs_all_in_registration_order():
    calls = []
    reg = ValidatorRegistry()
    for name in ["SYN_p", "SYN_q"]:
        reg.register(
            Validator(name=name, check=lambda s, n=name: calls.append(n) or [])
        )
    reg.run("SYN")
    assert calls == ["SYN_p", "SYN_q"]


def test_run_with_unknown_name_raises_before_any_check_runs():
    calls = []
    reg = ValidatorRegistry()
    reg.register(Validator(name="SYN_known", check=lambda s: calls.append(s) or []))
    with pytest.raises(AsOfError, match="unknown validator name"):
        reg.run("SYN", names=["SYN_known", "SYN_missing"])
    assert calls == []


def test_validator_that_raises_becomes_fail_finding_and_run_continues():
    def boom(subject):
        raise ValueError("synthetic boom")

    reg = ValidatorRegistry()
    reg.register(Validator(name="SYN_boom", check=boom))
    reg.register(_pass("SYN_after"))

    findings = reg.run("SYN_subject")

    assert len(findings) == 2
    bad = findings[0]
    assert bad.check_id == "SYN_boom"
    assert bad.status == ValidationStatus.FAIL
    assert "ValueError" in bad.message
    assert "synthetic boom" in bad.message
    assert bad.subject == "str"
    # The validator after the raising one still ran.
    assert findings[1].check_id == "SYN_after"
    assert findings[1].status == ValidationStatus.PASS


def test_raising_validator_with_key_error_is_fail():
    def bad(subject):
        return subject["SYN_missing_key"]

    reg = ValidatorRegistry()
    reg.register(Validator(name="SYN_keyerr", check=bad))
    findings = reg.run({})
    assert findings[0].status == ValidationStatus.FAIL
    assert "KeyError" in findings[0].message


def test_check_returning_none_becomes_fail_and_run_continues():
    reg = ValidatorRegistry()
    reg.register(Validator(name="SYN_none", check=lambda s: None))
    reg.register(_pass("SYN_next"))
    findings = reg.run("SYN")
    assert findings[0].check_id == "SYN_none"
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[1].check_id == "SYN_next"


def test_run_on_empty_registry_returns_no_findings():
    reg = ValidatorRegistry()
    assert reg.run("SYN") == []
    assert reg.overall_status([]) == ValidationStatus.PASS


# ---------------------------------------------------------------------------
# Overall status
# ---------------------------------------------------------------------------


def test_overall_status_is_fail_when_any_finding_is_fail():
    reg = ValidatorRegistry()
    reg.register(_pass("SYN_a"))
    reg.register(_fail("SYN_b"))
    reg.register(_warn("SYN_c"))
    findings = reg.run("SYN")
    assert reg.overall_status(findings) == ValidationStatus.FAIL


def test_overall_status_fail_wins_even_when_listed_last():
    findings = [
        Finding("SYN_1", ValidationStatus.PASS, "ok", "SYN"),
        Finding("SYN_2", ValidationStatus.WARN, "hmm", "SYN"),
        Finding("SYN_3", ValidationStatus.FAIL, "bad", "SYN"),
    ]
    assert overall_status(findings) == ValidationStatus.FAIL
    assert ValidatorRegistry().overall_status(findings) == ValidationStatus.FAIL


def test_overall_status_is_warn_when_worst_is_warn():
    findings = [
        Finding("SYN_1", ValidationStatus.PASS, "ok", "SYN"),
        Finding("SYN_2", ValidationStatus.WARN, "hmm", "SYN"),
    ]
    assert overall_status(findings) == ValidationStatus.WARN


def test_overall_status_is_pass_when_all_pass():
    findings = [Finding("SYN_1", ValidationStatus.PASS, "ok", "SYN")]
    assert overall_status(findings) == ValidationStatus.PASS


def test_overall_status_of_no_findings_is_pass():
    assert overall_status([]) == ValidationStatus.PASS


# ---------------------------------------------------------------------------
# check_no_nan
# ---------------------------------------------------------------------------


def test_check_no_nan_passes_on_clean_values():
    findings = check_no_nan({"SYN_a": 1.0, "SYN_b": 0.0, "SYN_c": -2})
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.PASS


def test_check_no_nan_flags_nan_with_key():
    findings = check_no_nan({"SYN_ok": 1.0, "SYN_nan": float("nan")})
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].subject == "SYN_nan"


def test_check_no_nan_flags_non_numeric_value():
    findings = check_no_nan({"SYN_text": "not a number"})
    assert findings[0].status == ValidationStatus.FAIL
    assert "not numeric" in findings[0].message


def test_check_no_nan_on_empty_mapping_passes():
    findings = check_no_nan({})
    assert findings[0].status == ValidationStatus.PASS


# ---------------------------------------------------------------------------
# check_sorted_dates
# ---------------------------------------------------------------------------


def test_check_sorted_dates_passes_when_strictly_increasing():
    findings = check_sorted_dates([date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)])
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.PASS


def test_check_sorted_dates_fails_on_backwards_date():
    findings = check_sorted_dates([date(2026, 1, 5), date(2026, 1, 2)])
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].subject == "position 1"


def test_check_sorted_dates_warns_on_repeat():
    findings = check_sorted_dates([date(2026, 1, 5), date(2026, 1, 5)])
    assert findings[0].status == ValidationStatus.WARN


def test_check_sorted_dates_empty_and_single_pass():
    assert check_sorted_dates([])[0].status == ValidationStatus.PASS
    assert check_sorted_dates([date(2026, 1, 5)])[0].status == ValidationStatus.PASS
