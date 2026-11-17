"""Tests for as_of.pm_packet_assembly. All fixtures are synthetic (SYN_ prefix)."""

from datetime import date, datetime, timezone

import pytest

from as_of.core import AsOfError, Finding, SourceRecord, SourceType, ValidationStatus
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER, assemble_packet


def _sections(tag="base"):
    return {
        name: {"label": "SYN_%s_%s" % (name, tag)} for name in PACKET_SECTION_ORDER
    }


def _source(source_id="SYN_S1"):
    return SourceRecord(
        source_id=source_id,
        source_type=SourceType.FILING,
        publisher="SYN_PUBLISHER",
        locator="SYN_LOCATOR/%s" % source_id,
        retrieved_at=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
        sha256="0" * 64,
        synthetic=True,
    )


def _finding(check_id, status, subject="SYN_SUBJECT"):
    return Finding(
        check_id=check_id,
        status=status,
        message="SYN_MESSAGE_%s" % check_id,
        subject=subject,
    )


def _build(sections=None, sources=None, findings=None, title="SYN_PACKET", as_of=date(2026, 1, 5)):
    return assemble_packet(
        title=title,
        as_of=as_of,
        sections=_sections() if sections is None else sections,
        sources=[_source()] if sources is None else sources,
        findings=[] if findings is None else findings,
    )


# ---------------------------------------------------------------------------
# Required and unknown sections
# ---------------------------------------------------------------------------


def test_missing_required_section_raises_asof_error():
    sections = _sections()
    del sections["controls"]
    with pytest.raises(AsOfError):
        _build(sections=sections)


@pytest.mark.parametrize("missing", PACKET_SECTION_ORDER)
def test_each_required_section_is_enforced(missing):
    sections = _sections()
    del sections[missing]
    with pytest.raises(AsOfError):
        _build(sections=sections)


def test_unknown_section_raises_asof_error():
    sections = _sections()
    sections["appendix_extra"] = {"label": "SYN_EXTRA"}
    with pytest.raises(AsOfError):
        _build(sections=sections)


def test_section_body_must_be_mapping():
    sections = _sections()
    sections["thesis"] = ["SYN_NOT_A_MAPPING"]
    with pytest.raises(AsOfError):
        _build(sections=sections)


def test_sections_argument_must_be_mapping():
    with pytest.raises(AsOfError):
        _build(sections=[("thesis", {})])


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_sections_emitted_in_packet_order_regardless_of_input_order():
    base = _sections()
    reversed_input = {name: base[name] for name in reversed(PACKET_SECTION_ORDER)}
    packet = _build(sections=reversed_input)
    assert tuple(packet["sections"].keys()) == PACKET_SECTION_ORDER


def test_shuffled_input_gives_same_section_order_and_bodies():
    base = _sections()
    order = ("tieout", "thesis", "open_items", "evidence", "exceptions", "risks", "controls")
    shuffled = {name: base[name] for name in order}
    packet = _build(sections=shuffled)
    assert tuple(packet["sections"].keys()) == PACKET_SECTION_ORDER
    for name in PACKET_SECTION_ORDER:
        assert packet["sections"][name] == base[name]


# ---------------------------------------------------------------------------
# Open findings
# ---------------------------------------------------------------------------


def test_open_findings_contains_warn_and_fail_but_not_pass():
    findings = [
        _finding("CHK_PASS", ValidationStatus.PASS),
        _finding("CHK_WARN", ValidationStatus.WARN),
        _finding("CHK_FAIL", ValidationStatus.FAIL),
        _finding("CHK_PASS_2", ValidationStatus.PASS),
    ]
    packet = _build(findings=findings)
    check_ids = [item["check_id"] for item in packet["open_findings"]]
    assert "CHK_WARN" in check_ids
    assert "CHK_FAIL" in check_ids
    assert "CHK_PASS" not in check_ids
    assert "CHK_PASS_2" not in check_ids
    assert len(packet["open_findings"]) == 2


def test_open_findings_empty_when_all_pass():
    findings = [_finding("CHK_A", ValidationStatus.PASS)]
    assert _build(findings=findings)["open_findings"] == []


def test_open_findings_keeps_input_order():
    findings = [
        _finding("CHK_FAIL_1", ValidationStatus.FAIL),
        _finding("CHK_PASS", ValidationStatus.PASS),
        _finding("CHK_WARN_1", ValidationStatus.WARN),
        _finding("CHK_FAIL_2", ValidationStatus.FAIL),
    ]
    packet = _build(findings=findings)
    check_ids = [item["check_id"] for item in packet["open_findings"]]
    assert check_ids == ["CHK_FAIL_1", "CHK_WARN_1", "CHK_FAIL_2"]


def test_open_findings_are_plain_dicts_with_string_status():
    packet = _build(findings=[_finding("CHK_WARN", ValidationStatus.WARN)])
    item = packet["open_findings"][0]
    assert isinstance(item, dict)
    assert item["status"] == "warn"


def test_non_finding_input_raises_asof_error():
    with pytest.raises(AsOfError):
        _build(findings=[{"check_id": "CHK_FAKE", "status": "fail"}])


# ---------------------------------------------------------------------------
# packet_hash
# ---------------------------------------------------------------------------


def test_packet_hash_equal_for_equal_inputs():
    first = _build(findings=[_finding("CHK_WARN", ValidationStatus.WARN)])
    second = _build(findings=[_finding("CHK_WARN", ValidationStatus.WARN)])
    assert first["packet_hash"] == second["packet_hash"]


def test_packet_hash_is_hex_sha256():
    digest = _build()["packet_hash"]
    assert isinstance(digest, str)
    assert len(digest) == 64
    int(digest, 16)


def test_packet_hash_ignores_section_input_key_order():
    base = _sections()
    reversed_input = {name: base[name] for name in reversed(PACKET_SECTION_ORDER)}
    assert _build(sections=base)["packet_hash"] == _build(sections=reversed_input)["packet_hash"]


def test_packet_hash_changes_when_section_content_changes():
    assert _build(sections=_sections("a"))["packet_hash"] != _build(sections=_sections("b"))["packet_hash"]


def test_packet_hash_changes_when_title_changes():
    assert _build(title="SYN_ONE")["packet_hash"] != _build(title="SYN_TWO")["packet_hash"]


def test_packet_hash_changes_when_as_of_changes():
    assert _build(as_of=date(2026, 1, 5))["packet_hash"] != _build(as_of=date(2026, 1, 6))["packet_hash"]


def test_packet_hash_changes_when_sources_change():
    assert _build(sources=[_source("SYN_S1")])["packet_hash"] != _build(sources=[_source("SYN_S2")])["packet_hash"]


# ---------------------------------------------------------------------------
# Other input validation and output shape
# ---------------------------------------------------------------------------


def test_output_keys_and_as_of_string():
    packet = _build(as_of=date(2026, 1, 5))
    assert set(packet.keys()) == {"title", "as_of", "sections", "open_findings", "packet_hash"}
    assert packet["as_of"] == "2026-01-05"


def test_datetime_as_of_is_rejected():
    with pytest.raises(AsOfError):
        _build(as_of=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc))


@pytest.mark.parametrize("bad_title", ["", "   ", None, 42])
def test_empty_or_non_string_title_is_rejected(bad_title):
    with pytest.raises(AsOfError):
        _build(title=bad_title)


def test_non_source_record_is_rejected():
    with pytest.raises(AsOfError):
        _build(sources=[{"source_id": "SYN_FAKE"}])


def test_empty_sources_and_findings_are_allowed():
    packet = _build(sources=[], findings=[])
    assert packet["open_findings"] == []
    assert len(packet["packet_hash"]) == 64
