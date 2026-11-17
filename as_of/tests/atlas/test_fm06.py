"""Failure mode fm06: provider export lacks retrieval time.

A provider export with no capture timestamp leaves the as-of status of its
values unknown. The guidance is to require retrieved_at and a precision note
in the export schema, and to reject or quarantine rows that lack them. All
fixtures are synthetic (SYN_ prefix); no network or real data.

Detection points checked:
  - source_register.SourceRegister.add_source rejects a source with no
    retrieval time (core.ensure_utc raises AsOfError on None).
  - source_register rejects a naive retrieval time.
  - source_register.check_sources_used flags an export source that was never
    registered.
  - availability_cutoff.usable_at would still treat a row with only a
    release time as usable, with no capture time. This is a gap, marked xfail.
  - No module models a precision note. This is a gap, marked xfail.
"""

from datetime import datetime, timezone

import pytest

from as_of.availability_cutoff import usable_at
from as_of.core import AsOfError, ClockSet, SourceRecord, SourceType, ValidationStatus
from as_of.source_register import UNREGISTERED_CHECK_ID, SourceRegister

UTC = timezone.utc
DECISION = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
SHA = "a" * 64


def _export_source(retrieved_at, source_id="SYN_EXPORT_1"):
    return SourceRecord(
        source_id=source_id,
        source_type=SourceType.PRICE,
        publisher="SYN_PROVIDER",
        locator="synthetic://provider/export_2026_05.csv",
        retrieved_at=retrieved_at,
        sha256=SHA,
        synthetic=True,
    )


def test_export_source_with_no_retrieval_time_is_rejected():
    reg = SourceRegister()
    with pytest.raises(AsOfError):
        reg.add_source(_export_source(None))
    assert not reg.has_source("SYN_EXPORT_1")


def test_export_source_with_naive_retrieval_time_is_rejected():
    reg = SourceRegister()
    naive = datetime(2026, 5, 31, 22, 0, 0)  # no tzinfo
    with pytest.raises(AsOfError):
        reg.add_source(_export_source(naive))
    assert not reg.has_source("SYN_EXPORT_1")


def test_output_citing_unregistered_export_is_flagged():
    # The export was never registered, so an output that cites it must FAIL.
    reg = SourceRegister()
    findings = reg.check_sources_used(["SYN_EXPORT_1"])
    assert len(findings) == 1
    assert findings[0].check_id == UNREGISTERED_CHECK_ID
    assert findings[0].status == ValidationStatus.FAIL


def test_control_export_with_retrieval_time_registers_and_passes():
    # Control: the same export with a retrieval time is accepted, so the
    # rejections above come from the missing stamp and not from the fixture.
    reg = SourceRegister()
    reg.add_source(_export_source(datetime(2026, 5, 31, 22, 0, 0, tzinfo=UTC)))
    assert reg.has_source("SYN_EXPORT_1")
    assert reg.check_sources_used(["SYN_EXPORT_1"]) == []


def test_row_with_only_release_time_is_not_treated_as_known_as_of_capture():
    # A row from an export with no capture clock: only release_at is set.
    # The failure mode says its as-of status cannot be established, so it
    # should not be usable. availability_cutoff currently falls back to
    # release_at and says it is usable.
    cs = ClockSet(release_at=datetime(2026, 5, 30, tzinfo=UTC))
    if usable_at(cs, DECISION):
        pytest.xfail(
            "GAP fm06: availability_cutoff.usable_at falls back to release_at and "
            "accepts a row with no capture (retrieved_at) clock. No module "
            "quarantines such rows. Needs a capture clock or a rule that blocks "
            "release-only rows from provider exports."
        )
    assert usable_at(cs, DECISION) is False


def test_precision_note_is_required_on_export_schema():
    # The schema calls for a precision note next to retrieved_at. No module
    # defines or checks a precision field, so this cannot pass yet.
    pytest.xfail(
        "GAP fm06: no module models a precision note on provider exports. "
        "SourceRecord has no precision field and field_dictionary has none. "
        "Nothing rejects an export that lacks one."
    )
