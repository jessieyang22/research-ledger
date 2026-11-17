"""Failure mode fm32: packet has one missing branch.

Partial input or a retrieval failure leaves one branch out of the PM packet, and
nothing in the packet shows it. The expected detection is to compare the required
input manifest with what was actually processed, and to produce a failure-only
packet when a branch is missing.

Finding: as_of.pm_packet_assembly does reject a section KEY that is absent, so a
structurally missing section is detected. It does not detect a section that is
present but empty, and it has no input manifest to compare against. In
as_of.wf_pm_packet, claims are routed by their section name and any claim whose
section is not in PACKET_SECTION_ORDER is dropped without a finding, and an empty
branch yields an empty section that still passes. claim_records does not check the
section name either. No module produces a failure-only packet. The blocking tests
below are strict xfails, and the gap is reported rather than faked.

Fixtures use the SYN_ prefix.
"""

import dataclasses

import pytest

from as_of import wf_pm_packet
from as_of.core import AsOfError
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER, assemble_packet


def _full_sections():
    """One non-empty body per required section, all synthetic."""
    return {name: {"SYN_ITEM": {"text": "synthetic %s" % name}} for name in PACKET_SECTION_ORDER}


def test_missing_section_key_is_rejected_by_assembly():
    """Detected: a section key that is absent makes assembly raise, so the branch cannot vanish silently."""
    sections = _full_sections()
    del sections["risks"]
    with pytest.raises(AsOfError, match="missing required packet section"):
        assemble_packet(
            title="SYN_FM32_PACKET",
            as_of=wf_pm_packet.PACKET_AS_OF,
            sections=sections,
            sources=[],
            findings=[],
        )


def test_empty_section_body_is_accepted_silently_by_assembly():
    """Documents the live behavior: an empty branch passes assembly with no finding."""
    sections = _full_sections()
    sections["risks"] = {}
    packet = assemble_packet(
        title="SYN_FM32_PACKET",
        as_of=wf_pm_packet.PACKET_AS_OF,
        sections=sections,
        sources=[],
        findings=[],
    )
    assert packet["sections"]["risks"] == {}
    assert packet["open_findings"] == []


def test_build_packet_has_no_input_manifest_to_compare():
    """Documents the design: build_pm_packet takes only seed and an expert-claim flag, no required-branch list."""
    import inspect

    params = list(inspect.signature(wf_pm_packet.build_pm_packet).parameters)
    assert params == ["seed", "inject_expert_claim_on_slide"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm32 gap: when the risks branch of the packet loses all its claims, build_pm_packet "
        "emits an empty risks section, passes, and reports no finding. No module compares "
        "a required branch list with the processed branches or emits a failure-only packet."
    ),
)
def test_dropped_branch_is_flagged_and_blocks_packet(monkeypatch):
    """Expected control: a branch that lost its input yields a FAIL and passed is False."""
    original = wf_pm_packet._build_claims

    def _risks_branch_lost(seed, inject):
        claims, sampled = original(seed, inject)
        return [c for c in claims if c.section != "risks"], sampled

    monkeypatch.setattr(wf_pm_packet, "_build_claims", _risks_branch_lost)
    bundle = wf_pm_packet.build_pm_packet()
    assert bundle["passed"] is False
    assert any(f.status.name == "FAIL" for f in bundle["findings"])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm32 gap: a claim routed to a section name outside PACKET_SECTION_ORDER is silently "
        "dropped by build_pm_packet. claim_records does not validate the section name, so "
        "no finding is raised and the packet still passes."
    ),
)
def test_misrouted_claim_branch_is_flagged(monkeypatch):
    """Expected control: a claim whose section is not a packet section yields a FAIL."""
    original = wf_pm_packet._build_claims

    def _misrouted(seed, inject):
        claims, sampled = original(seed, inject)
        claims = [
            dataclasses.replace(c, section="risk") if c.section == "risks" else c
            for c in claims
        ]
        return claims, sampled

    monkeypatch.setattr(wf_pm_packet, "_build_claims", _misrouted)
    bundle = wf_pm_packet.build_pm_packet()
    assert bundle["passed"] is False
