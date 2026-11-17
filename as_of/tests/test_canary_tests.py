"""Tests for as_of.canary_tests. All text is synthetic (SYN_ prefix or plain test strings)."""

import pytest

from as_of import canary_tests
from as_of.canary_tests import (
    CANARY_PHRASES,
    CHECK_PRESENT,
    CHECK_STEER,
    plant_canary,
    run_canary,
    scan_for_canaries,
)
from as_of.core import AsOfError, ValidationStatus


BASE = "SYN_control_a: verdict FAIL; SYN_tieout: difference 0.00"


def ignoring_pipeline(text):
    """Ignores its input entirely."""
    return {"verdict": "FAIL", "checks": 3}


def copying_pipeline(text):
    """Copies a PASS verdict out of its input when one is present."""
    return {"verdict": "PASS" if "PASS" in text else "FAIL"}


def length_pipeline(text):
    """Output depends on the input text, so a planted phrase changes it."""
    return {"chars": len(text)}


# Acceptance tests


def test_pipeline_that_ignores_input_passes_run_canary():
    findings = run_canary(ignoring_pipeline, BASE)
    assert len(findings) == 1
    assert findings[0].check_id == CHECK_STEER
    assert findings[0].status == ValidationStatus.PASS


def test_pipeline_that_copies_pass_from_input_is_flagged_fail():
    findings = run_canary(copying_pipeline, BASE)
    assert len(findings) == 1
    assert findings[0].check_id == CHECK_STEER
    assert findings[0].status == ValidationStatus.FAIL


def test_scan_for_canaries_finds_planted_phrase():
    planted = plant_canary(BASE, 0)
    findings = scan_for_canaries(planted)
    assert len(findings) == 1
    assert findings[0].check_id == CHECK_PRESENT
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].subject == CANARY_PHRASES[0]


def test_plant_canary_output_contains_phrase_and_original_text():
    planted = plant_canary(BASE, 0)
    assert BASE in planted
    assert CANARY_PHRASES[0] in planted
    assert planted.startswith(BASE)


# Edge cases: plant_canary


@pytest.mark.parametrize("index", range(len(CANARY_PHRASES)))
def test_plant_canary_every_index_contains_its_phrase(index):
    planted = plant_canary(BASE, index)
    assert CANARY_PHRASES[index] in planted
    assert BASE in planted


def test_plant_canary_default_index_is_zero():
    assert plant_canary(BASE) == plant_canary(BASE, 0)


def test_plant_canary_puts_phrase_on_its_own_line():
    planted = plant_canary(BASE, 1)
    assert planted.split("\n")[-1] == CANARY_PHRASES[1]


@pytest.mark.parametrize("bad_index", [-1, len(CANARY_PHRASES), 99])
def test_plant_canary_rejects_out_of_range_index(bad_index):
    with pytest.raises(AsOfError):
        plant_canary(BASE, bad_index)


def test_plant_canary_rejects_bool_index():
    with pytest.raises(AsOfError):
        plant_canary(BASE, True)


def test_plant_canary_rejects_non_str_text():
    with pytest.raises(AsOfError):
        plant_canary(123, 0)


def test_plant_canary_on_empty_text_contains_only_phrase_and_separator():
    planted = plant_canary("", 0)
    assert planted.strip() == CANARY_PHRASES[0]


# Edge cases: scan_for_canaries


def test_scan_clean_text_returns_no_findings():
    assert scan_for_canaries(BASE) == []


def test_scan_is_case_insensitive():
    shouted = plant_canary(BASE, 0).upper()
    findings = scan_for_canaries(shouted)
    assert len(findings) == 1
    assert findings[0].subject == CANARY_PHRASES[0]


def test_scan_reports_one_finding_per_phrase_present():
    text = plant_canary(plant_canary(BASE, 0), 2)
    subjects = sorted(f.subject for f in scan_for_canaries(text))
    assert subjects == sorted([CANARY_PHRASES[0], CANARY_PHRASES[2]])


def test_scan_empty_string_returns_no_findings():
    assert scan_for_canaries("") == []


def test_scan_rejects_non_str():
    with pytest.raises(AsOfError):
        scan_for_canaries(None)


# Edge cases: run_canary


def test_run_canary_returns_single_finding_list():
    findings = run_canary(length_pipeline, BASE)
    assert isinstance(findings, list)
    assert len(findings) == 1


def test_length_dependent_pipeline_is_flagged_fail():
    findings = run_canary(length_pipeline, BASE)
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].check_id == CHECK_STEER


def test_pipeline_that_raises_on_planted_text_is_flagged_fail():
    def raising_pipeline(text):
        if CANARY_PHRASES[0] in text:
            raise ValueError("boom")
        return {"verdict": "FAIL"}

    findings = run_canary(raising_pipeline, BASE)
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].check_id == CHECK_STEER
    assert "ValueError" in findings[0].message


def test_run_canary_rejects_non_callable_pipeline():
    with pytest.raises(AsOfError):
        run_canary("not callable", BASE)


def test_run_canary_rejects_non_str_base_text():
    with pytest.raises(AsOfError):
        run_canary(ignoring_pipeline, None)


def test_run_canary_on_empty_base_text_with_ignoring_pipeline_passes():
    findings = run_canary(ignoring_pipeline, "")
    assert findings[0].status == ValidationStatus.PASS


def test_module_phrases_are_distinct_and_nonempty():
    assert len(set(CANARY_PHRASES)) == len(CANARY_PHRASES)
    assert all(p.strip() for p in CANARY_PHRASES)
    assert canary_tests.CHECK_PRESENT != canary_tests.CHECK_STEER
