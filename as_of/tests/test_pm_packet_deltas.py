"""Tests for as_of.pm_packet_deltas. All fixtures are synthetic (SYN_ prefix)."""

import pytest

from as_of.core import Finding, ValidationStatus
from as_of.pm_packet_deltas import DELTA_KEYS, diff_packets, render_delta_lines


def _packet(**overrides):
    base = {
        "sections": {
            "SYN_EXPOSURE": {"gross": 1.0, "net": 0.2},
            "SYN_TIEOUT": {"status": "SYN_OK"},
            "SYN_NOTES": "SYN_NOTE_BASE",
        },
        "findings": [],
    }
    base.update(overrides)
    return base


def _finding(check_id, subject="SYN_SUBJECT", message="SYN_MESSAGE"):
    return {"check_id": check_id, "subject": subject, "message": message}


def test_identical_packets_give_empty_delta():
    prev = _packet(findings=[_finding("SYN_C1")])
    curr = _packet(findings=[_finding("SYN_C1")])
    delta = diff_packets(prev, curr)
    assert set(delta.keys()) == set(DELTA_KEYS)
    assert delta["added_sections"] == []
    assert delta["removed_sections"] == []
    assert delta["changed_sections"] == []
    assert delta["changed_fields"] == {}
    assert delta["findings_new"] == []
    assert delta["findings_resolved"] == []
    assert render_delta_lines(delta) == ["No changes since prior packet."]


def test_changed_section_appears_in_changed_sections():
    prev = _packet()
    curr = _packet()
    curr["sections"]["SYN_TIEOUT"] = {"status": "SYN_FAIL"}
    delta = diff_packets(prev, curr)
    assert delta["changed_sections"] == ["SYN_TIEOUT"]
    assert delta["changed_fields"]["SYN_TIEOUT"] == ["status"]
    assert delta["added_sections"] == []
    assert delta["removed_sections"] == []


def test_changed_dict_section_lists_only_differing_fields():
    prev = _packet()
    curr = _packet()
    curr["sections"]["SYN_EXPOSURE"] = {"gross": 1.0, "net": 0.5, "beta": 0.1}
    delta = diff_packets(prev, curr)
    assert delta["changed_fields"]["SYN_EXPOSURE"] == ["beta", "net"]


def test_changed_non_dict_section_uses_whole_section_marker():
    prev = _packet()
    curr = _packet()
    curr["sections"]["SYN_NOTES"] = "SYN_NOTE_EDITED"
    delta = diff_packets(prev, curr)
    assert delta["changed_sections"] == ["SYN_NOTES"]
    assert delta["changed_fields"]["SYN_NOTES"] == ["*"]
    lines = render_delta_lines(delta)
    assert "  - SYN_NOTES" in lines


def test_finding_present_only_in_curr_appears_in_findings_new():
    prev = _packet(findings=[_finding("SYN_C1")])
    curr = _packet(findings=[_finding("SYN_C1"), _finding("SYN_C2")])
    delta = diff_packets(prev, curr)
    assert len(delta["findings_new"]) == 1
    assert delta["findings_new"][0]["check_id"] == "SYN_C2"
    assert delta["findings_resolved"] == []


def test_finding_present_only_in_prev_appears_in_findings_resolved():
    prev = _packet(findings=[_finding("SYN_C1"), _finding("SYN_C2")])
    curr = _packet(findings=[_finding("SYN_C1")])
    delta = diff_packets(prev, curr)
    assert delta["findings_new"] == []
    assert len(delta["findings_resolved"]) == 1
    assert delta["findings_resolved"][0]["check_id"] == "SYN_C2"


def test_finding_identity_is_check_id_and_subject():
    prev = _packet(findings=[_finding("SYN_C1", subject="SYN_A", message="SYN_OLD")])
    curr = _packet(findings=[_finding("SYN_C1", subject="SYN_A", message="SYN_NEW")])
    delta = diff_packets(prev, curr)
    assert delta["findings_new"] == []
    assert delta["findings_resolved"] == []


def test_finding_dataclass_records_are_accepted():
    f = Finding(
        check_id="SYN_C9",
        status=ValidationStatus.PASS,
        message="SYN_MSG",
        subject="SYN_SUBJ",
    )
    delta = diff_packets(_packet(), _packet(findings=[f]))
    assert len(delta["findings_new"]) == 1
    assert delta["findings_new"][0]["check_id"] == "SYN_C9"
    assert delta["findings_new"][0]["subject"] == "SYN_SUBJ"


def test_findings_without_check_id_use_whole_item_hash():
    item = {"note": "SYN_FREEFORM"}
    delta_same = diff_packets(_packet(findings=[item]), _packet(findings=[dict(item)]))
    assert delta_same["findings_new"] == []
    assert delta_same["findings_resolved"] == []
    delta_diff = diff_packets(_packet(findings=[item]), _packet(findings=[{"note": "SYN_OTHER"}]))
    assert len(delta_diff["findings_new"]) == 1
    assert len(delta_diff["findings_resolved"]) == 1


def test_added_and_removed_sections():
    prev = _packet()
    curr = _packet()
    del curr["sections"]["SYN_NOTES"]
    curr["sections"]["SYN_NEW"] = {"x": 1}
    delta = diff_packets(prev, curr)
    assert delta["added_sections"] == ["SYN_NEW"]
    assert delta["removed_sections"] == ["SYN_NOTES"]
    assert delta["changed_sections"] == []


def test_swapping_prev_and_curr_swaps_added_and_removed():
    prev = _packet()
    curr = _packet()
    del curr["sections"]["SYN_NOTES"]
    curr["sections"]["SYN_NEW"] = {"x": 1}
    forward = diff_packets(prev, curr)
    backward = diff_packets(curr, prev)
    assert backward["added_sections"] == forward["removed_sections"]
    assert backward["removed_sections"] == forward["added_sections"]
    assert backward["added_sections"] == ["SYN_NOTES"]
    assert backward["removed_sections"] == ["SYN_NEW"]


def test_swapping_prev_and_curr_swaps_findings():
    prev = _packet(findings=[_finding("SYN_C1")])
    curr = _packet(findings=[_finding("SYN_C2")])
    forward = diff_packets(prev, curr)
    backward = diff_packets(curr, prev)
    assert forward["findings_new"] == backward["findings_resolved"]
    assert forward["findings_resolved"] == backward["findings_new"]


def test_packet_without_sections_key_treats_top_level_keys_as_sections():
    prev = {"SYN_A": {"v": 1}, "SYN_B": {"v": 2}, "findings": []}
    curr = {"SYN_A": {"v": 1}, "SYN_B": {"v": 3}, "findings": []}
    delta = diff_packets(prev, curr)
    assert delta["changed_sections"] == ["SYN_B"]
    assert delta["changed_fields"]["SYN_B"] == ["v"]
    assert delta["added_sections"] == []
    assert delta["removed_sections"] == []


def test_missing_findings_key_is_treated_as_empty():
    prev = {"sections": {"SYN_A": 1}}
    curr = {"sections": {"SYN_A": 1}, "findings": [_finding("SYN_C1")]}
    delta = diff_packets(prev, curr)
    assert len(delta["findings_new"]) == 1
    assert delta["findings_resolved"] == []


def test_render_lists_all_categories():
    prev = _packet(findings=[_finding("SYN_OLD")])
    curr = _packet(findings=[_finding("SYN_NEW")])
    del curr["sections"]["SYN_NOTES"]
    curr["sections"]["SYN_ADDED"] = {"x": 1}
    curr["sections"]["SYN_EXPOSURE"] = {"gross": 2.0, "net": 0.2}
    lines = render_delta_lines(diff_packets(prev, curr))
    text = "\n".join(lines)
    assert "Added sections (1):" in text
    assert "Removed sections (1):" in text
    assert "Changed sections (1):" in text
    assert "SYN_EXPOSURE: gross" in text
    assert "New findings (1):" in text
    assert "Resolved findings (1):" in text


def test_non_dict_packet_is_rejected():
    with pytest.raises(Exception):
        diff_packets(["SYN_NOT_A_DICT"], _packet())
    with pytest.raises(Exception):
        diff_packets(_packet(), None)
