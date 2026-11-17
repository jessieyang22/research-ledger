"""Tests for as_of.readiness_record. All fixtures are synthetic (SYN_ prefix)."""

import pytest

from as_of.core import AsOfError, Finding, ReadinessItem, ValidationStatus
from as_of.readiness_record import build_readiness, render_readiness


def _item(item_id="SYN_ITEM_1", passed=True, evidence_ref="SYN_EV_1"):
    return ReadinessItem(item_id=item_id, passed=passed, evidence_ref=evidence_ref)


def _finding(status=ValidationStatus.PASS, check_id="SYN_CHECK_1", subject="SYN_SUBJ", message="synthetic"):
    return Finding(check_id=check_id, status=status, message=message, subject=subject)


# --- acceptance tests -------------------------------------------------------


def test_empty_item_list_gives_go_false():
    rec = build_readiness([], [], 0)
    assert rec["go"] is False
    assert any(r.startswith("empty_item_list") for r in rec["blocking"])


def test_one_failed_item_appears_in_blocking_and_sets_go_false():
    items = [_item("SYN_ITEM_OK"), _item("SYN_ITEM_BAD", passed=False, evidence_ref="SYN_EV_BAD")]
    rec = build_readiness(items, [], 0)
    assert rec["go"] is False
    joined = "\n".join(rec["blocking"])
    assert "SYN_ITEM_BAD" in joined
    assert "SYN_EV_BAD" in joined
    assert "SYN_ITEM_OK" not in joined


def test_fail_finding_sets_go_false():
    rec = build_readiness([_item()], [_finding(status=ValidationStatus.FAIL)], 0)
    assert rec["go"] is False
    assert any(r.startswith("finding_failed") for r in rec["blocking"])


def test_open_incident_count_sets_go_false_and_is_named_in_blocking():
    rec = build_readiness([_item()], [], 2)
    assert rec["go"] is False
    assert any("open_incidents" in r and "2" in r for r in rec["blocking"])


# --- edge cases -------------------------------------------------------------


def test_all_pass_gives_go_true_and_no_blocking():
    findings = [_finding(status=ValidationStatus.PASS), _finding(status=ValidationStatus.PASS, check_id="SYN_C2")]
    rec = build_readiness([_item("A"), _item("B")], findings, 0)
    assert rec["go"] is True
    assert rec["blocking"] == []


def test_warn_finding_does_not_block():
    rec = build_readiness([_item()], [_finding(status=ValidationStatus.WARN)], 0)
    assert rec["go"] is True
    assert rec["blocking"] == []


def test_zero_open_incidents_does_not_block():
    rec = build_readiness([_item()], [], 0)
    assert rec["go"] is True


def test_multiple_reasons_all_listed_in_fixed_order():
    items = [_item("SYN_I", passed=False)]
    findings = [_finding(status=ValidationStatus.FAIL, check_id="SYN_C")]
    rec = build_readiness(items, findings, 1)
    assert rec["go"] is False
    assert len(rec["blocking"]) == 3
    assert rec["blocking"][0].startswith("item_failed")
    assert rec["blocking"][1].startswith("finding_failed")
    assert rec["blocking"][2].startswith("open_incidents")


def test_digest_is_stable_for_same_inputs():
    a = build_readiness([_item()], [_finding()], 0)
    b = build_readiness([_item()], [_finding()], 0)
    assert a["digest"] == b["digest"]
    assert len(a["digest"]) == 64


def test_digest_changes_when_inputs_change():
    base = build_readiness([_item()], [], 0)
    other_items = build_readiness([_item(passed=False)], [], 0)
    other_incidents = build_readiness([_item()], [], 1)
    assert base["digest"] != other_items["digest"]
    assert base["digest"] != other_incidents["digest"]


def test_input_order_of_items_is_accepted_as_sequence():
    rec = build_readiness((_item("A"), _item("B")), (), 0)
    assert rec["go"] is True


def test_bool_open_incident_count_rejected():
    with pytest.raises(AsOfError):
        build_readiness([_item()], [], True)


def test_non_int_open_incident_count_rejected():
    with pytest.raises(AsOfError):
        build_readiness([_item()], [], 1.0)


def test_negative_open_incident_count_rejected():
    with pytest.raises(AsOfError):
        build_readiness([_item()], [], -1)


def test_non_readiness_item_rejected():
    with pytest.raises(AsOfError):
        build_readiness(["SYN_NOT_AN_ITEM"], [], 0)


def test_non_finding_rejected():
    with pytest.raises(AsOfError):
        build_readiness([_item()], ["SYN_NOT_A_FINDING"], 0)


def test_render_go_record():
    rec = build_readiness([_item()], [], 0)
    text = render_readiness(rec)
    assert text.startswith("Readiness decision: GO\n")
    assert "Blocking reasons: none" in text
    assert rec["digest"] in text


def test_render_no_go_lists_reasons():
    rec = build_readiness([], [], 3)
    text = render_readiness(rec)
    assert text.startswith("Readiness decision: NO-GO\n")
    assert "  - empty_item_list" in text
    assert "  - open_incidents" in text


def test_render_missing_key_raises():
    with pytest.raises(AsOfError):
        render_readiness({"go": True, "blocking": []})


def test_render_non_dict_raises():
    with pytest.raises(AsOfError):
        render_readiness(["not", "a", "dict"])
