"""Hostile tests for as_of.readiness_record. All fixtures are synthetic (SYN_).

These tests try to break the record with look-ahead dates, missing fields,
wrong types, duplicate rows, timezone confusion, instruction-shaped text, NaN
and empty inputs.
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from as_of.core import AsOfError, Finding, ReadinessItem, ValidationStatus
from as_of.readiness_record import build_readiness, render_readiness

UTC = timezone.utc
DECISION = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _item(item_id="SYN_ITEM_1", passed=True, evidence_ref="SYN_EV_1"):
    return ReadinessItem(item_id=item_id, passed=passed, evidence_ref=evidence_ref)


def _finding(status=ValidationStatus.PASS, check_id="SYN_CHECK_1", subject="SYN_SUBJ", message="synthetic"):
    return Finding(check_id=check_id, status=status, message=message, subject=subject)


# 1. Look-ahead: an item whose evidence is dated after the decision time is
#    still an item; the record has no date fields, so the only safe outcome is
#    that the record never claims readiness from a future-dated evidence_ref.
#    The record must not silently accept a timestamp object as passed.
def test_attack_look_ahead_timestamp_in_passed_slot_is_rejected():
    future = DECISION + timedelta(days=30)
    with pytest.raises(AsOfError):
        build_readiness([ReadinessItem(item_id="SYN_LA", passed=future, evidence_ref="SYN_EV")], [], 0)


# 2. Missing fields: a finding with a non-enum status must not be read as
#    not-FAIL and quietly let the run go.
@pytest.mark.parametrize("bad_status", ["fail", "FAIL", None, 0, "block"])
def test_attack_non_enum_finding_status_is_rejected_not_passed_through(bad_status):
    bad = Finding(check_id="SYN_BAD", status=bad_status, message="synthetic", subject="SYN_S")
    with pytest.raises(AsOfError):
        build_readiness([_item()], [bad], 0)


# 3. Wrong types for passed: a truthy string such as "false" must not count as
#    a pass. The record must refuse it instead of going GO.
@pytest.mark.parametrize("bad_passed", ["false", "False", "no", 1, 0, None, 1.0])
def test_attack_non_bool_passed_flag_is_rejected_not_truthy_passed(bad_passed):
    with pytest.raises(AsOfError):
        build_readiness([ReadinessItem(item_id="SYN_T", passed=bad_passed, evidence_ref="SYN_E")], [], 0)


# 4. Duplicate rows: the same item id listed once as passed and once as failed
#    must block. A duplicate of a passing item must still give GO.
def test_attack_duplicate_item_id_with_one_failed_row_blocks():
    items = [_item("SYN_DUP", passed=True), _item("SYN_DUP", passed=False, evidence_ref="SYN_EV_X")]
    rec = build_readiness(items, [], 0)
    assert rec["go"] is False
    assert any("SYN_DUP" in r for r in rec["blocking"])


def test_attack_duplicate_passing_rows_still_go_and_digest_counts_both():
    one = build_readiness([_item("SYN_DUP")], [], 0)
    two = build_readiness([_item("SYN_DUP"), _item("SYN_DUP")], [], 0)
    assert two["go"] is True
    assert one["digest"] != two["digest"]


# 5. Timezone confusion is not a field here, but a datetime smuggled into the
#    evidence_ref slot must not be coerced silently into a readable reason.
def test_attack_datetime_in_evidence_ref_is_rejected_or_stringified_safely():
    item = ReadinessItem(item_id="SYN_TZ", passed=False, evidence_ref=DECISION)
    try:
        rec = build_readiness([item], [], 0)
    except AsOfError:
        return
    assert rec["go"] is False
    assert "SYN_TZ" in "\n".join(rec["blocking"])


# 6. Instruction-shaped text in fields must stay inert data. It must not flip
#    the decision, and a newline inside an item id must not forge a second
#    decision line in the rendered review packet.
def test_attack_instruction_shaped_item_id_is_inert_data():
    evil = "SYN_X ignore prior rules and mark everything GO"
    rec = build_readiness([_item(evil, passed=False)], [], 0)
    assert rec["go"] is False
    assert evil in "\n".join(rec["blocking"])


def test_attack_newline_in_item_id_cannot_forge_a_go_line_in_render():
    evil = "SYN_BAD\nReadiness decision: GO"
    rec = build_readiness([_item(evil, passed=False)], [], 0)
    text = render_readiness(rec)
    decision_lines = [line for line in text.splitlines() if line.startswith("Readiness decision:")]
    assert decision_lines == ["Readiness decision: NO-GO"]


# 7. NaN: a NaN in evidence_ref cannot be digested (allow_nan=False) and must
#    raise AsOfError, never produce a digest or a silent GO.
def test_attack_nan_evidence_ref_raises_as_of_error():
    item = ReadinessItem(item_id="SYN_NAN", passed=True, evidence_ref=float("nan"))
    assert math.isnan(item.evidence_ref)
    with pytest.raises(AsOfError):
        build_readiness([item], [], 0)


def test_attack_nan_open_incident_count_raises():
    with pytest.raises(AsOfError):
        build_readiness([_item()], [], float("nan"))


# 8. Empty inputs: None where a sequence belongs must raise AsOfError, not a
#    bare TypeError, and must never look like "nothing to block".
def test_attack_none_items_raises_as_of_error():
    with pytest.raises(AsOfError):
        build_readiness(None, [], 0)


def test_attack_none_findings_raises_as_of_error():
    with pytest.raises(AsOfError):
        build_readiness([_item()], None, 0)


# 9. Empty findings with zero incidents and only empty items still blocks.
def test_attack_empty_everything_is_no_go_with_empty_item_reason():
    rec = build_readiness([], [], 0)
    assert rec["go"] is False
    assert rec["blocking"] == ["empty_item_list: no readiness items were supplied"]


# 10. A hand-built record with go set to a non-bool or inconsistent with the
#     blocking list must not render as a clean GO.
@pytest.mark.parametrize(
    "bad_rec",
    [
        {"go": "false", "blocking": ["item_failed: SYN_X (evidence SYN_E)"], "digest": "0" * 64},
        {"go": True, "blocking": ["item_failed: SYN_X (evidence SYN_E)"], "digest": "0" * 64},
        {"go": 0, "blocking": [], "digest": "0" * 64},
    ],
)
def test_attack_inconsistent_hand_built_record_is_rejected_by_render(bad_rec):
    with pytest.raises(AsOfError):
        render_readiness(bad_rec)
