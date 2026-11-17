"""Tests for as_of.wf_pm_packet. All data is synthetic (SYN_ prefix).

Topic: PM review packet.
"""

import copy

import pytest

from as_of.core import SYNTHETIC_SEED, AsOfError, ProofResult, ValidationStatus
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER
from as_of.wf_pm_packet import (
    EXPERT_CLAIM_ID,
    PROOF_NAME,
    SAMPLE_SIZE,
    build_pm_packet,
    delta_is_empty,
    diff_packets,
    render_pm_packet_markdown,
    run_pm_packet_proof,
)


def _fail_checks(result: ProofResult):
    return [f.check_id for f in result.findings if f.status is ValidationStatus.FAIL]


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_default_run_passes():
    result = run_pm_packet_proof()
    assert isinstance(result, ProofResult)
    assert result.proof_name == PROOF_NAME
    assert result.passed is True
    assert _fail_checks(result) == []
    assert result.metrics["fail_findings"] == 0.0
    assert result.metrics["findings_new"] == 0.0
    assert result.metrics["findings_resolved"] == 0.0


def test_inject_expert_claim_on_slide_gives_passed_false():
    result = run_pm_packet_proof(inject_expert_claim_on_slide=True)
    assert result.passed is False
    assert "expert_input_on_slide" in _fail_checks(result)
    assert result.metrics["fail_findings"] >= 1.0


def test_delta_between_identical_packets_is_empty():
    a = build_pm_packet()
    b = build_pm_packet()
    delta = diff_packets(a["packet"], b["packet"])
    assert delta_is_empty(delta)
    assert diff_packets(a["packet"], a["packet"]) == {
        "added_sections": [],
        "removed_sections": [],
        "changed_sections": [],
        "changed_fields": {},
        "findings_new": [],
        "findings_resolved": [],
    }


def test_rendered_text_contains_packet_hash():
    bundle = build_pm_packet()
    packet_hash = bundle["packet"]["packet_hash"]
    assert packet_hash in bundle["markdown"]
    # Also present when rendered directly, with and without a delta.
    assert packet_hash in render_pm_packet_markdown(bundle["packet"])
    assert packet_hash in render_pm_packet_markdown(bundle["packet"], bundle["delta"])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_default_build_is_deterministic():
    a = build_pm_packet(SYNTHETIC_SEED)
    b = build_pm_packet(SYNTHETIC_SEED)
    assert a["packet"]["packet_hash"] == b["packet"]["packet_hash"]
    assert a["markdown"] == b["markdown"]
    assert a["passed"] is True


def test_packet_sections_follow_fixed_order():
    bundle = build_pm_packet()
    assert set(bundle["packet"]["sections"].keys()) == set(PACKET_SECTION_ORDER)
    headings = [line for line in bundle["markdown"].splitlines() if line.startswith("## ")]
    positions = [headings.index("## " + name) for name in PACKET_SECTION_ORDER]
    assert positions == sorted(positions)


def test_injected_expert_claim_sits_in_thesis_and_is_reported():
    bundle = build_pm_packet(inject_expert_claim_on_slide=True)
    assert EXPERT_CLAIM_ID in bundle["packet"]["sections"]["thesis"]
    assert EXPERT_CLAIM_ID not in bundle["packet"]["sections"]["open_items"]
    assert bundle["passed"] is False


def test_injected_delta_reports_changed_sections_against_prior():
    bundle = build_pm_packet(inject_expert_claim_on_slide=True)
    delta = bundle["delta"]
    assert not delta_is_empty(delta)
    assert "thesis" in delta["changed_sections"]
    assert "open_items" in delta["changed_sections"]
    assert "thesis" in delta["changed_fields"]
    assert EXPERT_CLAIM_ID in delta["changed_fields"]["thesis"]


def test_swapping_delta_arguments_swaps_directions():
    clean = build_pm_packet()["packet"]
    injected = build_pm_packet(inject_expert_claim_on_slide=True)["packet"]
    forward = diff_packets(clean, injected)
    backward = diff_packets(injected, clean)
    assert forward["changed_sections"] == backward["changed_sections"]
    assert forward["findings_new"] == backward["findings_resolved"]
    assert forward["findings_resolved"] == backward["findings_new"]


def test_render_without_delta_says_no_changes():
    packet = build_pm_packet()["packet"]
    text = render_pm_packet_markdown(packet, None)
    assert "No changes since prior packet." in text
    text_empty = render_pm_packet_markdown(packet, diff_packets(packet, packet))
    assert "No changes since prior packet." in text_empty


def test_render_is_deterministic():
    bundle = build_pm_packet()
    first = render_pm_packet_markdown(bundle["packet"], bundle["delta"])
    second = render_pm_packet_markdown(bundle["packet"], bundle["delta"])
    assert first == second


def test_render_escapes_pipes_in_table_cells():
    packet = copy.deepcopy(build_pm_packet()["packet"])
    packet["open_findings"] = [
        {"check_id": "x", "status": "warn", "subject": "SYN_a|b", "message": "line\nbreak"}
    ]
    text = render_pm_packet_markdown(packet)
    assert "SYN_a\\|b" in text
    assert "line break" in text


def test_render_rejects_packet_missing_hash():
    packet = copy.deepcopy(build_pm_packet()["packet"])
    del packet["packet_hash"]
    with pytest.raises(AsOfError):
        render_pm_packet_markdown(packet)


def test_diff_rejects_non_mapping_inputs():
    packet = build_pm_packet()["packet"]
    with pytest.raises(AsOfError):
        diff_packets(None, packet)
    with pytest.raises(AsOfError):
        diff_packets(packet, "not a packet")


def test_build_rejects_bad_seed():
    with pytest.raises(AsOfError):
        build_pm_packet(seed=True)
    with pytest.raises(AsOfError):
        build_pm_packet(seed="1")


def test_sample_size_matches_metric():
    result = run_pm_packet_proof()
    assert result.metrics["claims_sampled"] == float(SAMPLE_SIZE)
    assert result.metrics["claims_total"] == 8.0
    assert result.metrics["rendered_chars"] > 0.0
