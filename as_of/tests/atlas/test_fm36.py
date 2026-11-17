"""Failure mode fm36: synthetic value presented as real.

A fixture or synthetic value appears in output with its evidence label stripped,
so it looks like real data. The expected detection is to trace each claim back to
its source, and to block or withdraw output whose source is synthetic but whose
label is gone.

Finding: the label exists at the source level. SourceRecord.synthetic is a required
bool, and source_register rejects a non-bool value at registration. The flag also
feeds the packet hash, so flipping it changes packet_hash. Beyond that, no module
reads the flag. claim_records.validate_claim accepts a fact that cites only a
synthetic source. pm_packet_assembly and pm_packet_render drop the source records
from the rendered text, so the synthetic label does not reach the reader. The only
text label is the fixed footer in wf_pm_packet, which is not tied to any source.
The blocking tests below are strict xfails, and the gap is reported rather than faked.

Fixtures use the SYN_ prefix. The claim text is deliberately written to read like
real data, with no SYN_ prefix and no synthetic wording.
"""

from datetime import date, datetime, timezone

import pytest

from as_of.claim_records import make_claim, validate_claim
from as_of.core import AsOfError, SourceRecord, SourceType, ValidationStatus
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER, assemble_packet
from as_of.pm_packet_render import render_markdown
from as_of.source_register import SourceRegister

AS_OF = date(2026, 10, 27)
RETRIEVED = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
HASH = "a" * 64

# Planted claim: reads like a real company fact, no SYN_ prefix, no synthetic wording.
PLANTED_TEXT = "Issuer reported record quarterly margin of 31 percent"


def _source(synthetic):
    return SourceRecord(
        source_id="SYN_SRC_FM36",
        source_type=SourceType.FIXTURE,
        publisher="SYN_fixture_desk",
        locator="synthetic://SYN_fm36/01",
        retrieved_at=RETRIEVED,
        sha256=HASH,
        synthetic=synthetic,
    )


def _planted_claim():
    """A fact claim whose only source is the synthetic fixture source."""
    return make_claim(
        claim_id="SYN_CLM_FM36",
        text=PLANTED_TEXT,
        claim_kind="fact",
        source_ids=["SYN_SRC_FM36"],
        status="unverified",
        section="evidence",
    )


def _sections_with_planted_claim():
    sections = {name: {} for name in PACKET_SECTION_ORDER}
    sections["evidence"] = {
        "SYN_CLM_FM36": {"text": PLANTED_TEXT, "source_ids": ["SYN_SRC_FM36"]},
    }
    return sections


def _packet(synthetic):
    return assemble_packet(
        title="SYN_FM36_PACKET",
        as_of=AS_OF,
        sections=_sections_with_planted_claim(),
        sources=[_source(synthetic)],
        findings=[],
    )


def test_unlabeled_source_is_rejected_at_registration():
    """Detected: a source whose synthetic flag is not a bool cannot enter the register.

    The label has to be present and typed, so a source cannot be recorded without
    saying whether it is synthetic.
    """
    rec = _source(synthetic=None)
    register = SourceRegister()
    with pytest.raises(AsOfError, match="synthetic must be a bool"):
        register.add_source(rec)


def test_flipping_synthetic_flag_changes_packet_hash():
    """Detected by hash: the synthetic flag is part of the packet content, so a label change cannot pass silently."""
    labelled = _packet(synthetic=True)
    stripped = _packet(synthetic=False)
    assert labelled["packet_hash"] != stripped["packet_hash"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm36 gap: validate_claim does not read SourceRecord.synthetic. A fact citing only a "
        "synthetic source with real-looking text returns PASS, so the claim is not blocked "
        "or flagged."
    ),
)
def test_planted_claim_on_synthetic_source_is_flagged():
    """Expected control: a fact supported only by a synthetic source yields a non-PASS finding."""
    findings = validate_claim(_planted_claim())
    assert any(f.status != ValidationStatus.PASS for f in findings)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm36 gap: render_markdown drops source records, so a packet whose only source is "
        "synthetic renders with no synthetic label. The reader sees the planted claim as "
        "real data."
    ),
)
def test_rendered_packet_carries_synthetic_label_for_synthetic_source():
    """Expected control: the rendered text marks that the evidence is synthetic."""
    rendered = render_markdown(_packet(synthetic=True))
    assert "synthetic" in rendered.lower()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm36 gap: no module compares a claim's real-looking text with the synthetic flag of "
        "its sources. SourceRegister.check_sources_used checks registration only, so the "
        "claim passes with no finding."
    ),
)
def test_registered_synthetic_source_used_by_real_looking_claim_is_flagged():
    """Expected control: a register check raises a finding for a synthetic source behind a non-SYN claim."""
    register = SourceRegister()
    register.add_source(_source(synthetic=True))
    findings = register.check_sources_used(["SYN_SRC_FM36"])
    flagged = [f for f in findings if f.status != ValidationStatus.PASS]
    assert flagged, "expected a finding that the synthetic source is used by a real-looking claim"
