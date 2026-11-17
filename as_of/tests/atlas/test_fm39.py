"""Failure mode fm39: packet sent through an unapproved channel.

A packet that holds confidential or licensed data is distributed through a
channel that was never approved. The detection named in the catalog idea is to
inspect the audit and channel record for every distribution, and to stop the
distribution and follow the incident process when an unapproved channel was
used.

Fixtures use the SYN_ prefix. Nothing here sends a packet anywhere, opens a
channel, or touches the real home folder.

What the repo has today:
  - secrets_scanner.scan_text flags credential-shaped strings in packet text.
    That catches a leaked key, not a confidential or licensed body of text.
  - pm_packet_assembly.assemble_packet returns a packet_hash over the packet
    content. A changed section gives a different hash, so a copy that was
    altered after approval can be told apart from the approved one. The hash
    says nothing about where a copy was sent.
  - incident_records.open_incident opens an incident, and readiness_record
    blocks go while an incident is open. The incident path is manual: nothing
    opens an incident on its own when a distribution happens.
  - jsonl_store is an append-only log, which can hold a distribution log. No
    module writes one, and no module reads one to compare against an approved
    channel list.

What the repo does not have:
  - No channel record, no approved-channel list, no distribution audit event,
    and no confidentiality or license marking on a packet. The blocking
    checks are marked xfail (strict) and the gap is reported, not faked.
"""

import dataclasses
from datetime import date, datetime, timezone

import pytest

from as_of import pm_packet_assembly, readiness_record, secrets_scanner
from as_of.core import Finding, ReadinessItem, Severity, ValidationStatus
from as_of.incident_records import open_incident
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER, assemble_packet
from as_of.readiness_record import build_readiness

SYN_AS_OF = date(2026, 10, 5)
SYN_TITLE = "SYN_FM39_packet"
SYN_CONFIDENTIAL_TEXT = "SYN CONFIDENTIAL: licensed vendor table, do not forward."
SYN_APPROVED_CHANNEL = "SYN_channel_pm_portal"
SYN_UNAPPROVED_CHANNEL = "SYN_channel_personal_mail"
SYN_CHANNEL_CHECK = "distribution.unapproved_channel"


def _sections(body_text):
    """A full section map with one planted body text in the first section."""
    sections = {name: {"note": "SYN_%s" % name} for name in PACKET_SECTION_ORDER}
    first = PACKET_SECTION_ORDER[0]
    sections[first] = {"note": body_text}
    return sections


def _packet(body_text):
    return assemble_packet(SYN_TITLE, SYN_AS_OF, _sections(body_text), [], [])


def _fails(findings):
    return [f for f in findings if f.status == ValidationStatus.FAIL]


def test_planted_credential_in_packet_text_is_flagged():
    """Detected (partial): a credential-shaped string in the packet text is a FAIL.

    The key shape is built at runtime so the source file itself holds no
    credential-shaped literal.
    """
    planted_key = "AK" + "IA" + "SYN0FM39EXAMPLE1"
    body = "SYN planted line with a key: " + planted_key
    findings = secrets_scanner.scan_text(body, name="SYN_packet_body")
    assert _fails(findings), "scanner did not flag the planted key shape"
    assert all(planted_key not in f.message for f in findings), "scanner echoed the secret"


def test_altered_packet_copy_has_a_different_hash_from_the_approved_one():
    """Detected (partial): a packet changed after approval no longer matches the approved hash.

    This is a tamper check. It does not show which channel carried the copy.
    """
    approved = _packet(SYN_CONFIDENTIAL_TEXT)
    altered = _packet(SYN_CONFIDENTIAL_TEXT + " SYN extra line added before sending.")
    assert approved["packet_hash"] != altered["packet_hash"]
    # Same content gives the same hash, so a faithful copy still matches.
    assert _packet(SYN_CONFIDENTIAL_TEXT)["packet_hash"] == approved["packet_hash"]


def test_open_incident_for_unapproved_channel_blocks_readiness():
    """Detected when raised: an open incident blocks go, even when every item passes.

    The incident has to be opened by a person or a process. Nothing in the
    package opens it on a distribution event, so this covers the block path
    only.
    """
    incident = open_incident(
        "SYN_FM39_INC_1",
        "SYN packet found on an unapproved channel",
        Severity.BLOCK,
        SYN_AS_OF,
    )
    assert incident.status == "open"
    items = [ReadinessItem(item_id="SYN_item_packet_ok", passed=True, evidence_ref="SYN_ref_1")]
    rec = build_readiness(items, [], open_incident_count=1)
    assert rec["go"] is False


def test_fail_finding_from_a_channel_check_blocks_readiness():
    """Block path: a FAIL finding for an unapproved channel blocks go.

    The finding is built by hand here. No module produces this check_id yet.
    The test shows the readiness gate would honour such a finding once one exists.
    """
    finding = Finding(
        check_id=SYN_CHANNEL_CHECK,
        status=ValidationStatus.FAIL,
        message="SYN packet sent to a channel not on the approved list",
        subject=SYN_UNAPPROVED_CHANNEL,
    )
    items = [ReadinessItem(item_id="SYN_item_packet_ok", passed=True, evidence_ref="SYN_ref_1")]
    rec = build_readiness(items, [finding], open_incident_count=0)
    assert rec["go"] is False
    assert any(SYN_CHANNEL_CHECK in reason for reason in rec["blocking"])


def test_no_channel_or_confidentiality_concept_exists_in_the_package():
    """Documents the gap: no packet, source or finding carries a channel or confidentiality field."""
    from as_of.core import SourceRecord

    names = set()
    for cls in (SourceRecord, Finding):
        names.update(f.name for f in dataclasses.fields(cls))
    banned = ("channel", "distribut", "confiden", "licen", "rights")
    assert not any(any(b in n for b in banned) for n in names)
    assert not hasattr(pm_packet_assembly, "channel")
    assert not hasattr(readiness_record, "channel")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm39 gap: no module records a distribution channel, keeps an approved "
        "channel list, or marks a packet as confidential or licensed. Nothing flags "
        "a packet sent to a channel that was never approved, so the check named "
        "here does not exist yet."
    ),
)
def test_packet_sent_through_unapproved_channel_is_blocked():
    """Expected control: a confidential packet sent to an unapproved channel yields a FAIL.

    The check is looked up by name. It does not exist in the package, so the
    lookup fails and the test is reported as an expected failure.
    """
    packet = _packet(SYN_CONFIDENTIAL_TEXT)
    distribution_log = [
        {
            "packet_hash": packet["packet_hash"],
            "channel": SYN_UNAPPROVED_CHANNEL,
            "at": datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc).isoformat(),
        }
    ]
    approved_channels = {SYN_APPROVED_CHANNEL}
    check = pm_packet_assembly.check_distribution  # does not exist yet
    findings = check(packet, distribution_log, approved_channels)
    assert any(
        f.status == ValidationStatus.FAIL and f.check_id == SYN_CHANNEL_CHECK for f in findings
    ), "no unapproved-channel FAIL raised for a confidential packet"
