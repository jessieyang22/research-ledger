"""Tests for as_of.controls_checklist. All data here is synthetic."""

import re

import pytest

from as_of import controls_checklist as cc
from as_of.controls_checklist import (
    CHECK_ID,
    CONTROL_CATALOG,
    EVIDENCE_KINDS,
    OWNER_ROLES,
    ControlSpec,
    checklist_markdown,
    missing_evidence,
)
from as_of.core import ValidationStatus


def _full_evidence():
    return {spec.control_id: "synthetic-ref-%s" % spec.control_id for spec in CONTROL_CATALOG}


# Acceptance test: control_id values are unique.
def test_control_id_values_are_unique():
    ids = [spec.control_id for spec in CONTROL_CATALOG]
    assert len(ids) == len(set(ids))
    assert len(ids) > 0


def test_control_ids_are_nonempty_strings():
    for spec in CONTROL_CATALOG:
        assert isinstance(spec.control_id, str)
        assert spec.control_id.strip()


# Acceptance test: missing_evidence flags a control with no evidence key.
def test_missing_evidence_flags_control_with_no_evidence_key():
    evidence = _full_evidence()
    dropped = CONTROL_CATALOG[0].control_id
    del evidence[dropped]
    findings = missing_evidence(evidence)
    assert len(findings) == 1
    assert findings[0].subject == dropped
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].check_id == CHECK_ID


def test_missing_evidence_flags_every_control_when_empty():
    findings = missing_evidence({})
    assert len(findings) == len(CONTROL_CATALOG)
    assert {f.subject for f in findings} == {s.control_id for s in CONTROL_CATALOG}


def test_missing_evidence_flags_blank_and_whitespace_values():
    evidence = _full_evidence()
    first = CONTROL_CATALOG[0].control_id
    second = CONTROL_CATALOG[1].control_id
    evidence[first] = ""
    evidence[second] = "   "
    flagged = {f.subject for f in missing_evidence(evidence)}
    assert flagged == {first, second}


def test_missing_evidence_is_empty_when_all_controls_have_evidence():
    assert missing_evidence(_full_evidence()) == []


def test_missing_evidence_ignores_unknown_keys():
    evidence = _full_evidence()
    evidence["ctl_not_in_catalog"] = "synthetic-ref"
    assert missing_evidence(evidence) == []


# Acceptance test: no ControlSpec has evidence_kind 'settings_change'.
def test_no_control_spec_uses_settings_change_evidence():
    for spec in CONTROL_CATALOG:
        assert spec.evidence_kind != "settings_change"


def test_settings_change_is_not_a_known_evidence_kind():
    assert "settings_change" not in EVIDENCE_KINDS


def test_every_catalog_evidence_kind_is_known():
    for spec in CONTROL_CATALOG:
        assert spec.evidence_kind in EVIDENCE_KINDS


def test_every_catalog_owner_role_is_known():
    for spec in CONTROL_CATALOG:
        assert spec.owner_role in OWNER_ROLES


def test_control_spec_rejects_settings_change_kind():
    with pytest.raises(ValueError):
        ControlSpec("ctl_x", "desc", "settings_change", "analyst")


def test_control_spec_rejects_unknown_owner_role():
    with pytest.raises(ValueError):
        ControlSpec("ctl_x", "desc", "run_log", "trader")


def test_control_spec_rejects_blank_control_id():
    with pytest.raises(ValueError):
        ControlSpec("   ", "desc", "run_log", "analyst")


def test_control_spec_is_immutable():
    spec = CONTROL_CATALOG[0]
    with pytest.raises(AttributeError):
        spec.control_id = "changed"


# Acceptance test: checklist_markdown has one checkbox line per control.
CHECKBOX_RE = re.compile(r"^- \[ \] `([^`]+)` ")


def test_checklist_markdown_has_one_checkbox_line_per_control():
    lines = checklist_markdown().splitlines()
    boxes = [line for line in lines if line.startswith("- [")]
    assert len(boxes) == len(CONTROL_CATALOG)


def test_checklist_checkbox_ids_match_catalog_in_order():
    lines = checklist_markdown().splitlines()
    ids = []
    for line in lines:
        m = CHECKBOX_RE.match(line)
        if m:
            ids.append(m.group(1))
    assert ids == [spec.control_id for spec in CONTROL_CATALOG]


def test_checklist_boxes_are_unchecked():
    text = checklist_markdown()
    assert "- [x]" not in text.lower()
    assert "- [ ]" in text


def test_checklist_markdown_has_heading_and_ends_with_newline():
    text = checklist_markdown()
    assert text.startswith("# Controls checklist")
    assert text.endswith("\n")


def test_checklist_markdown_is_deterministic():
    assert checklist_markdown() == checklist_markdown()


# Catalog-level rules from the module docstring.
def test_catalog_has_unique_ids_via_internal_self_check():
    counts = cc._check_catalog()
    assert counts["controls"] == counts["unique_ids"]
