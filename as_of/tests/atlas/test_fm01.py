"""Failure mode fm01: document used without confirmed rights.

A document is used in the project although its license or rights class is
unknown. A successful download is treated as permission to use it. The
expected control is that a record with unknown rights is flagged and blocked
until a reviewer records a decision.

Fixtures use the SYN_ prefix. The planted document is a synthetic source
record with no rights decision attached.

Finding: as_of.core.SourceRecord has no rights or license field, and
as_of.source_register checks only that a source is registered. Nothing in the
package flags or blocks an unknown-rights document. The blocking test is
therefore marked xfail (strict) and the gap is reported, not faked.
"""

import dataclasses
from datetime import datetime, timezone

import pytest

from as_of.core import SourceRecord, SourceType
from as_of.source_register import SourceRegister

PLANTED_ID = "SYN_FM01_DOC"
GOOD_SHA = "cd" * 32


def _planted_document() -> SourceRecord:
    """A synthetic document whose rights class is unknown: no decision exists."""
    return SourceRecord(
        source_id=PLANTED_ID,
        source_type=SourceType.FIXTURE,
        publisher="SYN_PUBLISHER",
        locator="SYN_LOCATOR/unlicensed_doc",
        retrieved_at=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
        sha256=GOOD_SHA,
        synthetic=True,
    )


def test_source_record_has_no_rights_field():
    """Documents the current design: no rights or license field is recorded."""
    names = [f.name for f in dataclasses.fields(SourceRecord)]
    assert not any("right" in n or "licen" in n for n in names)


def test_planted_unknown_rights_document_is_currently_accepted():
    """Documents the live failure: a planted doc with no rights decision is used cleanly."""
    reg = SourceRegister()
    reg.add_source(_planted_document())
    # Registration alone is treated as sufficient; no rights finding is produced.
    assert reg.has_source(PLANTED_ID)
    assert reg.check_sources_used([PLANTED_ID]) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm01 gap: no module records or checks document rights/license. "
        "SourceRecord has no rights field and source_register only checks "
        "registration, so an unknown-rights document is not flagged or blocked."
    ),
)
def test_unknown_rights_document_is_flagged_and_blocked():
    """Expected control: using a planted unknown-rights document yields a FAIL finding."""
    reg = SourceRegister()
    reg.add_source(_planted_document())
    findings = reg.check_sources_used([PLANTED_ID])
    rights_fails = [
        f for f in findings
        if "right" in f.check_id.lower() or "licen" in f.check_id.lower()
    ]
    assert rights_fails, "no rights finding raised for unknown-rights document"
