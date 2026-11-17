"""Failure mode fm34: packet says PASS but a branch failed.

A failure is summarized away when the packet is compressed, so the reader sees
PASS. The expected detection is to compare the packet with the underlying JSON
results, and to replace it with a failure-only packet that lists every failed
branch.

What the existing modules do with a planted branch failure:
  * as_of.wf_pm_packet keeps a FAIL branch visible: its open_findings carry the
    FAIL, the rendered Markdown shows it, and the proof result is passed=False.
    The CLI verdict (cli._proof_passed) also reads the FAIL.
  * as_of.pm_packet_assembly keeps WARN and FAIL findings it is given, so a
    FAIL that reaches assembly is not dropped by the packet itself.
  * as_of.validation_report.build_report and report_passes detect a FAIL in
    the per-branch results.

The gap: nothing cross-checks the packet against the per-branch results. If a
caller passes a compressed findings list (the FAIL is left out), assemble_packet
accepts it and returns a packet with no FAIL in open_findings. No module
compares the two, and no module produces a failure-only packet. The blocking
test is therefore a strict xfail, and the gap is reported rather than faked.

Fixtures use the SYN_ prefix.
"""

import pytest

from as_of import wf_pm_packet
from as_of.core import AsOfError, Finding, ValidationStatus
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER, assemble_packet
from as_of.pm_packet_render import render_markdown
from as_of.validation_report import build_report, report_passes


def _planted_branch_results():
    """Per-branch JSON-style results: one branch FAILs, the others PASS.

    The planted failure is an expert-input claim placed on a slide section,
    which the packet proof must catch.
    """
    return {
        "claim_sourced": [
            Finding("claim_sourced", ValidationStatus.PASS, "all claims sourced", "SYN_CL_01"),
        ],
        "expert_input_on_slide": [
            Finding(
                "expert_input_on_slide",
                ValidationStatus.FAIL,
                "expert input appears in slide section 'thesis'",
                "SYN_CL_08",
            ),
        ],
        "sample_spot_check": [
            Finding("sample_spot_check", ValidationStatus.PASS, "sampled 3 claims, all sourced", "controls"),
        ],
    }


def _compressed_findings(results):
    """A summarizer that keeps only PASS findings, as a compressed packet would."""
    kept = []
    for items in results.values():
        for item in items:
            if item.status is ValidationStatus.PASS:
                kept.append(item)
    return kept


def test_planted_branch_fail_is_kept_by_proof_packet():
    """Detected: the packet proof keeps the planted FAIL in open_findings and fails the proof."""
    result = wf_pm_packet.build_pm_packet(inject_expert_claim_on_slide=True)
    assert result["passed"] is False
    fails = [f for f in result["packet"]["open_findings"] if f["status"] == "fail"]
    assert [f["check_id"] for f in fails] == ["expert_input_on_slide"]


def test_clean_proof_packet_passes_with_no_fail_finding():
    """Control: without the planted failure the proof passes and no FAIL is listed."""
    result = wf_pm_packet.build_pm_packet(inject_expert_claim_on_slide=False)
    assert result["passed"] is True
    assert all(f["status"] != "fail" for f in result["packet"]["open_findings"])


def test_rendered_markdown_shows_the_planted_fail():
    """Detected: the rendered packet text names the failed check, so a reader does not see a clean packet."""
    result = wf_pm_packet.build_pm_packet(inject_expert_claim_on_slide=True)
    assert "expert_input_on_slide" in result["markdown"]
    assert "| fail |" in result["markdown"]


def test_assembly_keeps_a_fail_it_is_given():
    """Detected: assemble_packet does not drop a FAIL finding that it receives."""
    sections = {name: {"SYN_ITEM": {"text": "synthetic"}} for name in PACKET_SECTION_ORDER}
    packet = assemble_packet(
        title="SYN_FM34_PACKET",
        as_of=wf_pm_packet.PACKET_AS_OF,
        sections=sections,
        sources=[],
        findings=_planted_branch_results()["expert_input_on_slide"],
    )
    assert [f["status"] for f in packet["open_findings"]] == ["fail"]


def test_branch_results_report_fails_closed_on_the_planted_fail():
    """Detected: the per-branch JSON results report a FAIL and report_passes refuses them."""
    report = build_report("SYN_FM34_BRANCHES", _planted_branch_results(), "SYN_FM34")
    assert report["status"] == "fail"
    assert report_passes(report) is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm34 gap: no module compares a PM packet with its per-branch results. A compressed "
        "findings list that drops a branch FAIL is accepted by assemble_packet and produces a "
        "packet with no FAIL in open_findings. No failure-only packet exists. Expected control: "
        "assembly (or a cross-check) blocks a packet whose findings omit a FAIL present in the "
        "branch results."
    ),
)
def test_compressed_packet_that_drops_a_branch_fail_is_blocked():
    """Expected control: a packet built from PASS-only findings must not be accepted when a branch FAILed."""
    results = _planted_branch_results()
    sections = {name: {"SYN_ITEM": {"text": "synthetic"}} for name in PACKET_SECTION_ORDER}
    with pytest.raises(AsOfError):
        assemble_packet(
            title="SYN_FM34_PACKET",
            as_of=wf_pm_packet.PACKET_AS_OF,
            sections=sections,
            sources=[],
            findings=_compressed_findings(results),
        )
