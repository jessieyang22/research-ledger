"""Tests for as_of.source_register. All fixtures are synthetic (SYN_ prefix)."""

from datetime import datetime, timezone

import pytest

from as_of.core import AsOfError, Finding, SourceRecord, SourceType, ValidationStatus
from as_of.source_register import UNREGISTERED_CHECK_ID, SourceRegister


def _rec(source_id, source_type=SourceType.FILING):
    return SourceRecord(
        source_id=source_id,
        source_type=source_type,
        publisher="SYN_PUBLISHER",
        locator="SYN_LOCATOR/%s" % source_id,
        retrieved_at=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
        sha256="0" * 64,
        synthetic=True,
    )


def test_add_and_get_roundtrip():
    reg = SourceRegister()
    rec = _rec("SYN_S1")
    reg.add_source(rec)
    assert reg.get_source("SYN_S1") is rec
    assert reg.has_source("SYN_S1")


def test_duplicate_source_id_raises_asof_error():
    reg = SourceRegister()
    reg.add_source(_rec("SYN_S1"))
    with pytest.raises(AsOfError):
        reg.add_source(_rec("SYN_S1", SourceType.PRICE))


def test_duplicate_does_not_overwrite_original():
    reg = SourceRegister()
    original = _rec("SYN_S1")
    reg.add_source(original)
    with pytest.raises(AsOfError):
        reg.add_source(_rec("SYN_S1", SourceType.PRICE))
    assert reg.get_source("SYN_S1") is original


def test_get_missing_source_raises_asof_error():
    reg = SourceRegister()
    with pytest.raises(AsOfError):
        reg.get_source("SYN_MISSING")


def test_has_source_false_for_missing():
    reg = SourceRegister()
    assert not reg.has_source("SYN_MISSING")


def test_add_source_rejects_non_record():
    reg = SourceRegister()
    with pytest.raises(AsOfError):
        reg.add_source({"source_id": "SYN_S1"})


def test_check_sources_used_flags_exactly_unregistered_ids():
    reg = SourceRegister()
    reg.add_source(_rec("SYN_A"))
    reg.add_source(_rec("SYN_B"))
    findings = reg.check_sources_used(["SYN_A", "SYN_X", "SYN_B", "SYN_Y"])
    assert [f.subject for f in findings] == ["SYN_X", "SYN_Y"]
    for f in findings:
        assert isinstance(f, Finding)
        assert f.check_id == UNREGISTERED_CHECK_ID
        assert f.status == ValidationStatus.FAIL


def test_check_sources_used_all_registered_gives_no_findings():
    reg = SourceRegister()
    reg.add_source(_rec("SYN_A"))
    assert reg.check_sources_used(["SYN_A", "SYN_A"]) == []


def test_check_sources_used_empty_input_gives_no_findings():
    reg = SourceRegister()
    assert reg.check_sources_used([]) == []


def test_check_sources_used_repeated_unregistered_id_reported_once():
    reg = SourceRegister()
    findings = reg.check_sources_used(["SYN_X", "SYN_X", "SYN_X"])
    assert len(findings) == 1
    assert findings[0].subject == "SYN_X"


def test_check_sources_used_follows_first_seen_order():
    reg = SourceRegister()
    findings = reg.check_sources_used(["SYN_Z", "SYN_A", "SYN_Z", "SYN_M"])
    assert [f.subject for f in findings] == ["SYN_Z", "SYN_A", "SYN_M"]


def test_check_sources_used_does_not_mutate_register():
    reg = SourceRegister()
    reg.check_sources_used(["SYN_X"])
    assert not reg.has_source("SYN_X")


def test_to_manifest_is_sorted_by_source_id():
    reg = SourceRegister()
    for sid in ["SYN_C", "SYN_A", "SYN_B"]:
        reg.add_source(_rec(sid))
    manifest = reg.to_manifest()
    assert [entry["source_id"] for entry in manifest] == ["SYN_A", "SYN_B", "SYN_C"]


def test_to_manifest_entries_are_plain_dicts():
    reg = SourceRegister()
    reg.add_source(_rec("SYN_A", SourceType.ESTIMATE))
    (entry,) = reg.to_manifest()
    assert isinstance(entry, dict)
    assert entry["source_type"] == "estimate"
    assert isinstance(entry["retrieved_at"], str)
    assert entry["retrieved_at"].startswith("2026-01-05T12:00:00")
    assert entry["synthetic"] is True


def test_to_manifest_empty_register():
    assert SourceRegister().to_manifest() == []
