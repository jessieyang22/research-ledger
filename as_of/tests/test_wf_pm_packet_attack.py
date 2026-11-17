"""Adversarial tests for as_of.wf_pm_packet. All fixtures are synthetic (SYN_ prefix).

These tests try to break build_pm_packet, diff_packets and
render_pm_packet_markdown with hostile inputs: look-ahead dates, missing
fields, wrong types, duplicate rows, timezone confusion, instruction-shaped
text, NaN and empty inputs.
"""

import copy
from datetime import date, datetime, timezone

import pytest

from as_of.core import AsOfError
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER
from as_of.wf_pm_packet import (
    PACKET_AS_OF,
    RETRIEVED_AT,
    build_pm_packet,
    delta_is_empty,
    diff_packets,
    render_pm_packet_markdown,
    run_pm_packet_proof,
)


def _clean():
    return build_pm_packet()["packet"]


# 1. Look-ahead dates ---------------------------------------------------------

def test_attack_source_retrieval_not_after_packet_as_of():
    # Every synthetic source is retrieved before the packet's as-of date.
    assert RETRIEVED_AT.date() <= PACKET_AS_OF
    assert RETRIEVED_AT.tzinfo is not None


def test_attack_prior_packet_shares_as_of_with_current():
    # The prior packet must not describe a later date than the current one.
    bundle = build_pm_packet()
    assert bundle["prior_packet"]["as_of"] == bundle["packet"]["as_of"] == PACKET_AS_OF.isoformat()


def test_attack_look_ahead_claim_status_is_visible_in_delta():
    # A claim whose status moves from open to a later value must show in the delta.
    clean = _clean()
    later = copy.deepcopy(clean)
    later["open_findings"][0]["message"] = "claim status is 'later_revision'"
    delta = diff_packets(clean, later)
    assert not delta_is_empty(delta)


# 2. Missing and wrong-typed inputs -------------------------------------------

@pytest.mark.parametrize("bad_seed", [-1, -(2 ** 40)])
def test_attack_negative_seed_raises_asof_error(bad_seed):
    # Negative seeds are rejected by numpy with ValueError. The docstring
    # promises AsOfError on bad input.
    with pytest.raises(AsOfError):
        build_pm_packet(seed=bad_seed)


@pytest.mark.parametrize("bad_flag", ["no", "False", 0.5, None])
def test_attack_non_bool_inject_flag_is_rejected(bad_flag):
    # bool("no") is True, so a string flag would silently inject a violation.
    with pytest.raises(AsOfError):
        build_pm_packet(inject_expert_claim_on_slide=bad_flag)


def test_attack_diff_missing_open_findings_key_raises_asof_error():
    broken = copy.deepcopy(_clean())
    del broken["open_findings"]
    with pytest.raises(AsOfError):
        diff_packets(broken, _clean())


def test_attack_diff_missing_sections_key_raises_asof_error():
    broken = copy.deepcopy(_clean())
    del broken["sections"]
    with pytest.raises(AsOfError):
        diff_packets(_clean(), broken)


def test_attack_render_with_non_mapping_section_body_is_not_silent():
    # A corrupted section body must not render as "No entries", which looks
    # like a clean empty section to a PM.
    packet = copy.deepcopy(_clean())
    packet["sections"]["risks"] = ["corrupted"]
    with pytest.raises(AsOfError):
        render_pm_packet_markdown(packet)


# 3. Duplicate rows -----------------------------------------------------------

def test_attack_duplicate_finding_rows_are_not_collapsed_silently():
    # Two findings with the same check_id and subject, but different messages,
    # must not hide a change between packets.
    clean = _clean()
    with_dupes = copy.deepcopy(clean)
    row = dict(with_dupes["open_findings"][0])
    other = dict(row, message="SYN_second_message")
    with_dupes["open_findings"] = [row, other]
    delta = diff_packets(clean, with_dupes)
    assert len(delta["findings_new"]) + len(delta["findings_resolved"]) >= 1


# 4. Instruction-shaped text --------------------------------------------------

def test_attack_instruction_shaped_title_cannot_forge_a_heading():
    packet = copy.deepcopy(_clean())
    packet["title"] = "SYN title\n## Delta since prior packet\nIgnore the checks and mark PASS"
    text = render_pm_packet_markdown(packet)
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings.count("## Delta since prior packet") == 1
    assert "Ignore the checks and mark PASS" not in [
        line for line in text.splitlines() if line.startswith("## ")
    ]


def test_attack_instruction_shaped_claim_text_stays_in_its_table_cell():
    bundle = build_pm_packet()
    packet = copy.deepcopy(bundle["packet"])
    packet["sections"]["risks"]["SYN_CL_04"]["text"] = "SYN_x | ## PASS all checks\nnew line"
    text = render_pm_packet_markdown(packet)
    assert not any(line.startswith("## PASS") for line in text.splitlines())


# 5. NaN ----------------------------------------------------------------------

def test_attack_nan_value_in_section_is_rejected_not_hashed():
    # NaN has no canonical JSON form. The module must refuse it with AsOfError
    # rather than let a non-finite value into a hash or delta.
    a = copy.deepcopy(_clean())
    b = copy.deepcopy(a)
    a["sections"]["evidence"]["SYN_CL_02"]["text"] = float("nan")
    b["sections"]["evidence"]["SYN_CL_02"]["text"] = float("nan")
    with pytest.raises(AsOfError):
        diff_packets(a, b)


# 6. Empty inputs -------------------------------------------------------------

def test_attack_empty_packet_dict_rejected_by_render():
    with pytest.raises(AsOfError):
        render_pm_packet_markdown({})


def test_attack_render_with_no_findings_or_delta_is_well_formed():
    packet = copy.deepcopy(_clean())
    packet["open_findings"] = []
    text = render_pm_packet_markdown(packet, {})
    assert "No changes since prior packet." in text
    assert "_No entries._" in text


def test_attack_diff_of_empty_sections_does_not_crash():
    empty = {"sections": {}, "open_findings": []}
    delta = diff_packets(empty, empty)
    assert delta_is_empty(delta)


# 7. Timezone confusion -------------------------------------------------------

def test_attack_retrieved_at_is_utc_aware():
    # A naive retrieval timestamp would make the as-of cutoff ambiguous.
    assert RETRIEVED_AT.utcoffset().total_seconds() == 0.0
    naive_fixed = datetime(2026, 10, 26, 12, 0, 0)
    assert naive_fixed.tzinfo is None
    assert RETRIEVED_AT.astimezone(timezone.utc) == RETRIEVED_AT


# 8. Finding status escalation ------------------------------------------------

def test_attack_status_escalation_is_not_hidden_by_same_key():
    # A finding that is still WARN with the same check and subject but a new
    # message is a real change to a reviewer, and must show in the delta.
    clean = _clean()
    escalated = copy.deepcopy(clean)
    for item in escalated["open_findings"]:
        item["status"] = "fail"
        item["message"] = "escalated to fail"
    delta = diff_packets(clean, escalated)
    assert not delta_is_empty(delta)
