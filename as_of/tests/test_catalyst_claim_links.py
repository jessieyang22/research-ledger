"""Tests for as_of.catalyst_claim_links. All fixtures are synthetic (SYN_ prefix)."""

from datetime import datetime, timezone

from as_of.catalyst_claim_links import (
    DANGLING_LINK_CHECK_ID,
    UNLINKED_CHECK_ID,
    validate_links,
)
from as_of.core import ClaimRecord, Finding, SourceRecord, SourceType, ValidationStatus
from as_of.source_register import UNREGISTERED_CHECK_ID, SourceRegister


def _src(source_id):
    return SourceRecord(
        source_id=source_id,
        source_type=SourceType.FILING,
        publisher="SYN_PUBLISHER",
        locator="SYN_LOCATOR/%s" % source_id,
        retrieved_at=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
        sha256="0" * 64,
        synthetic=True,
    )


def _register(*ids):
    reg = SourceRegister()
    for sid in ids:
        reg.add_source(_src(sid))
    return reg


def _claim(claim_id, source_ids=("SYN_S1",)):
    return ClaimRecord(
        claim_id=claim_id,
        text="SYN_TEXT for %s" % claim_id,
        claim_kind="SYN_KIND",
        source_ids=tuple(source_ids),
        status="draft",
        section="SYN_SECTION",
    )


def test_claim_with_no_link_is_fail_finding():
    claims = [_claim("SYN_C1")]
    findings = validate_links(claims, {}, {"SYN_CAT1"}, _register("SYN_S1"))
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, Finding)
    assert f.check_id == UNLINKED_CHECK_ID
    assert f.status == ValidationStatus.FAIL
    assert f.subject == "SYN_C1"


def test_link_to_catalyst_not_in_catalyst_ids_is_fail_finding():
    claims = [_claim("SYN_C1")]
    links = {"SYN_C1": "SYN_CAT_MISSING"}
    findings = validate_links(claims, links, {"SYN_CAT1"}, _register("SYN_S1"))
    assert len(findings) == 1
    f = findings[0]
    assert f.check_id == DANGLING_LINK_CHECK_ID
    assert f.status == ValidationStatus.FAIL
    assert f.subject == "SYN_C1"
    assert "SYN_CAT_MISSING" in f.message


def test_claim_citing_unregistered_source_is_fail_finding():
    claims = [_claim("SYN_C1", source_ids=("SYN_S1", "SYN_UNREG"))]
    links = {"SYN_C1": "SYN_CAT1"}
    findings = validate_links(claims, links, {"SYN_CAT1"}, _register("SYN_S1"))
    assert len(findings) == 1
    f = findings[0]
    assert f.check_id == UNREGISTERED_CHECK_ID
    assert f.status == ValidationStatus.FAIL
    assert f.subject == "SYN_C1"
    assert "SYN_UNREG" in f.message


def test_fully_linked_and_registered_returns_empty_list():
    claims = [
        _claim("SYN_C1", source_ids=("SYN_S1",)),
        _claim("SYN_C2", source_ids=("SYN_S1", "SYN_S2")),
    ]
    links = {"SYN_C1": "SYN_CAT1", "SYN_C2": "SYN_CAT2"}
    findings = validate_links(
        claims, links, {"SYN_CAT1", "SYN_CAT2"}, _register("SYN_S1", "SYN_S2")
    )
    assert findings == []


def test_empty_inputs_return_empty_list():
    assert validate_links([], {}, set(), SourceRegister()) == []


def test_claim_with_no_sources_and_valid_link_is_clean():
    claims = [_claim("SYN_C1", source_ids=())]
    findings = validate_links(claims, {"SYN_C1": "SYN_CAT1"}, {"SYN_CAT1"}, SourceRegister())
    assert findings == []


def test_link_naming_unknown_claim_is_fail_finding():
    claims = [_claim("SYN_C1")]
    links = {"SYN_C1": "SYN_CAT1", "SYN_GHOST": "SYN_CAT1"}
    findings = validate_links(claims, links, {"SYN_CAT1"}, _register("SYN_S1"))
    assert len(findings) == 1
    f = findings[0]
    assert f.check_id == DANGLING_LINK_CHECK_ID
    assert f.status == ValidationStatus.FAIL
    assert f.subject == "SYN_GHOST"


def test_findings_follow_claim_order_then_sorted_dangling_links():
    claims = [_claim("SYN_B"), _claim("SYN_A")]
    links = {"SYN_Z_GHOST": "SYN_CAT1", "SYN_A": "SYN_CAT1", "SYN_B": "SYN_CAT_BAD"}
    findings = validate_links(claims, links, {"SYN_CAT1"}, _register("SYN_S1"))
    assert [(f.check_id, f.subject) for f in findings] == [
        (DANGLING_LINK_CHECK_ID, "SYN_B"),
        (DANGLING_LINK_CHECK_ID, "SYN_Z_GHOST"),
    ]


def test_unlinked_and_unregistered_both_reported_for_same_claim():
    claims = [_claim("SYN_C1", source_ids=("SYN_UNREG",))]
    findings = validate_links(claims, {}, {"SYN_CAT1"}, SourceRegister())
    check_ids = [f.check_id for f in findings]
    assert check_ids == [UNLINKED_CHECK_ID, UNREGISTERED_CHECK_ID]
    assert all(f.status == ValidationStatus.FAIL for f in findings)
    assert all(f.subject == "SYN_C1" for f in findings)
