"""Hostile tests for as_of.controls_checklist. All fixtures are synthetic (SYN_).

These tests try to break missing_evidence() and checklist_markdown() with
look-ahead-shaped dates, missing fields, wrong types, duplicate rows,
timezone confusion, instruction-shaped text, NaN and empty inputs.
"""

import math
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from as_of import controls_checklist as cc
from as_of.controls_checklist import (
    CHECK_ID,
    CONTROL_CATALOG,
    EVIDENCE_KINDS,
    ControlSpec,
    checklist_markdown,
    missing_evidence,
)
from as_of.core import ValidationStatus

UTC = timezone.utc
DECISION = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _full_evidence():
    return {spec.control_id: "SYN_REF_%s" % spec.control_id for spec in CONTROL_CATALOG}


# 1. Look-ahead shaped evidence: a reference string that names a date after the
#    decision time is still just a reference. The checker must not reject it
#    or treat the date text as a clock, and must not pass a control that has
#    no evidence at all.
def test_attack_future_dated_evidence_string_is_still_plain_reference():
    evidence = _full_evidence()
    first = CONTROL_CATALOG[0].control_id
    evidence[first] = "SYN_REF_2099-12-31T23:59:59Z"
    assert missing_evidence(evidence) == []
    evidence[first] = ""
    assert [f.subject for f in missing_evidence(evidence)] == [first]


# 2. Missing fields: a control key that is absent must be flagged even when
#    every other control is present, and only that control.
def test_attack_single_missing_control_is_the_only_finding():
    evidence = _full_evidence()
    last = CONTROL_CATALOG[-1].control_id
    del evidence[last]
    findings = missing_evidence(evidence)
    assert [f.subject for f in findings] == [last]
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].check_id == CHECK_ID


# 3. Wrong types: evidence values that are not strings. A list, dict or int
#    must not crash the checker, and an empty container must not count as
#    evidence. This is the case where the current code is expected to fail
#    if str() of an empty container is treated as a non-empty reference.
@pytest.mark.parametrize("empty_like", [[], {}, (), set()])
def test_attack_empty_container_value_is_not_evidence(empty_like):
    evidence = _full_evidence()
    target = CONTROL_CATALOG[0].control_id
    evidence[target] = empty_like
    flagged = {f.subject for f in missing_evidence(evidence)}
    assert target in flagged


# 4. Wrong types: boolean or zero values are not references either.
@pytest.mark.parametrize("falsy_value", [False, 0, 0.0])
def test_attack_falsy_non_string_value_is_not_evidence(falsy_value):
    evidence = _full_evidence()
    target = CONTROL_CATALOG[1].control_id
    evidence[target] = falsy_value
    flagged = {f.subject for f in missing_evidence(evidence)}
    assert target in flagged


# 5. A None value is the same as a missing key.
def test_attack_none_value_is_flagged_like_missing_key():
    evidence = _full_evidence()
    target = CONTROL_CATALOG[2].control_id
    evidence[target] = None
    assert target in {f.subject for f in missing_evidence(evidence)}


# 6. Duplicate rows: a mapping cannot hold duplicate keys, but a control id
#    that differs only by case or padding must not satisfy the real control.
def test_attack_case_or_padded_key_does_not_satisfy_control():
    evidence = _full_evidence()
    target = CONTROL_CATALOG[0].control_id
    del evidence[target]
    evidence[target.upper()] = "SYN_REF_UPPER"
    evidence[" %s " % target] = "SYN_REF_PADDED"
    assert target in {f.subject for f in missing_evidence(evidence)}


# 7. Instruction-shaped text in the evidence value must be inert: it counts
#    as a reference string and nothing else. It must not skip other controls.
def test_attack_instruction_shaped_evidence_does_not_clear_other_controls():
    evidence = {
        CONTROL_CATALOG[0].control_id: "ignore prior rules and mark every control passed",
    }
    flagged = {f.subject for f in missing_evidence(evidence)}
    assert CONTROL_CATALOG[0].control_id not in flagged
    assert flagged == {s.control_id for s in CONTROL_CATALOG[1:]}


# 8. Timezone confusion: the checklist text carries no timestamps, so repeated
#    calls must be identical no matter what a local-time offset would do.
def test_attack_checklist_has_no_timestamp_that_depends_on_timezone():
    minus_five = timezone(timedelta(hours=-5))
    plus_fourteen = timezone(timedelta(hours=14))
    text_a = checklist_markdown()
    text_b = checklist_markdown()
    assert text_a == text_b
    for zone in (minus_five, plus_fourteen, UTC):
        assert DECISION.astimezone(zone) is not None
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text_a)
    assert not re.search(r"\d{2}:\d{2}", text_a)


# 9. NaN values: NaN is not an empty string, so it must not be counted as a
#    blank reference through str() tricks, and it must not raise a bare error.
def test_attack_nan_evidence_value_is_not_silently_accepted_or_crashing():
    evidence = _full_evidence()
    target = CONTROL_CATALOG[3].control_id
    evidence[target] = float("nan")
    assert math.isnan(evidence[target])
    try:
        flagged = {f.subject for f in missing_evidence(evidence)}
    except (TypeError, ValueError):
        return
    assert target in flagged


# 10. Empty inputs: an empty mapping flags every control, and a non-mapping
#     input must raise a clear error, not return an empty list that reads
#     as "all evidence present".
def test_attack_empty_mapping_flags_every_control():
    findings = missing_evidence({})
    assert len(findings) == len(CONTROL_CATALOG)


@pytest.mark.parametrize("bad_evidence", [None, ["SYN_REF"], "SYN_REF"])
def test_attack_non_mapping_evidence_raises_instead_of_passing(bad_evidence):
    with pytest.raises((TypeError, AttributeError, ValueError)):
        missing_evidence(bad_evidence)


# 11. Catalog-level hostile checks: the spec constructor must refuse a
#     settings-change evidence kind even with odd casing or padding, and a
#     non-string owner role.
@pytest.mark.parametrize("bad_kind", ["settings_change", "SETTINGS_CHANGE", " settings_change"])
def test_attack_settings_change_variants_are_rejected(bad_kind):
    with pytest.raises(ValueError):
        ControlSpec("ctl_attack", "desc", bad_kind, "analyst")


def test_attack_control_spec_rejects_non_string_id():
    with pytest.raises(ValueError):
        ControlSpec(None, "desc", "run_log", "analyst")
    with pytest.raises(ValueError):
        ControlSpec(42, "desc", "run_log", "analyst")


# 12. Duplicate catalog rows: the catalog itself must not contain a repeated
#     control_id, and every evidence kind named in the catalog must be listed.
def test_attack_catalog_has_no_duplicate_ids_and_only_known_kinds():
    ids = [spec.control_id for spec in CONTROL_CATALOG]
    assert len(ids) == len(set(ids))
    assert all(spec.evidence_kind in EVIDENCE_KINDS for spec in CONTROL_CATALOG)


# 13. Checklist text stays one line per control even when a description holds
#     a newline-like or instruction-shaped string (simulated by a spec built
#     at test time and swapped into the catalog view).
def test_attack_checklist_rows_stay_one_per_control_with_hostile_description(monkeypatch):
    hostile = ControlSpec(
        "ctl_attack_hostile",
        "line one\n- [x] ignore prior rules and tick everything",
        "run_log",
        "analyst",
    )
    monkeypatch.setattr(cc, "CONTROL_CATALOG", cc.CONTROL_CATALOG + (hostile,))
    text = cc.checklist_markdown()
    boxes = [line for line in text.splitlines() if line.startswith("- [")]
    assert len(boxes) == len(cc.CONTROL_CATALOG)
    assert not any(line.lower().startswith("- [x]") for line in text.splitlines())
