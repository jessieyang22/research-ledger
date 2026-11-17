"""Failure mode fm04: a filing fact differs from its CSV row.

Failure mode fm04 "Filing fact differs from CSV": an extracted value uses the
wrong context, period, unit, or amendment, so it does not match the full
filing. The detection rule is to reconcile each CSV value against the full
filing for period, unit and amendment flag, then invalidate dependent rows on
a mismatch.

Everything here is synthetic (SYN_ ids, invented numbers). No real filer is
named and no network access is used.

What the existing modules do with this failure:
    * field_dictionary.validate_fields checks dtype and nullability only. It
      has no period, unit or amendment rule, so a wrong-period row passes.
    * source_register checks that a source id is registered and that its hash
      has the right shape. It does not read a filing and compare values.
    * filing_monitor records filing occurrences (form type and dates). It
      explicitly does not carry filing values.
    * content_hash hashes whole files. It can show that a file changed, but it
      cannot say which extracted value disagrees with the filing.

So no existing module detects fm04 at the value level. The first test below
documents that gap as a passing fact. The second is a strict xfail that states
the missing detector and would start failing (XPASS) once one exists.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from as_of.core import ValidationStatus
from as_of.field_dictionary import validate_fields


def _planted_filing() -> Dict[str, Any]:
    """The full filing, as a synthetic reference."""
    return {
        "filing_id": "SYN_FIL_FM04_01",
        "ticker": "SYN_T01",
        "form_type": "10-Q",
        "period_end": "2026-06-30",
        "unit": "USD thousands",
        "amendment": False,
        "context": "consolidated",
        "revenue": 12345,
    }


def _planted_csv_row() -> Dict[str, Any]:
    """A CSV row extracted from the filing with planted mistakes.

    The row carries the prior quarter's period, the wrong unit, and an
    amendment flag that the filing does not have. The value 12345 is the
    filing's figure, so a value-only comparison would look clean.
    """
    return {
        "ticker": "SYN_T01",
        "source_id": "SYN_SRC_FM04_01",
        "ingest_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "period_end": "2026-03-31",
        "unit": "USD",
        "amendment": True,
        "revenue": 12345,
    }


def _mismatches(row: Dict[str, Any], filing: Dict[str, Any]) -> List[str]:
    """Return the fields where the row disagrees with the full filing."""
    out = []
    for field in ("period_end", "unit", "amendment"):
        if row[field] != filing[field]:
            out.append(field)
    return out


def test_fm04_planted_mismatch_is_real_in_fixture():
    """Sanity check: the planted row really disagrees with the filing."""
    assert _mismatches(_planted_csv_row(), _planted_filing()) == [
        "period_end",
        "unit",
        "amendment",
    ]


def test_fm04_existing_field_validation_misses_planted_mismatch():
    """Gap record: validate_fields passes the row with no FAIL finding.

    The row's period, unit and amendment are wrong, but the field dictionary
    has no rule for any of them. This asserts the current behavior so the
    gap stays visible. It is not a sign that the check is correct.
    """
    row = _planted_csv_row()
    findings = validate_fields(row, ["ticker", "source_id", "ingest_at"])
    fails = [f for f in findings if f.status == ValidationStatus.FAIL]
    mismatched = set(_mismatches(row, _planted_filing()))
    assert [f for f in fails if f.subject in mismatched] == []
    assert fails == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm04 gap: no as_of module reconciles extracted CSV values against the "
        "full filing for period, unit or amendment. validate_fields only checks "
        "dtype and nullability. Add a filing-reconciliation check that returns a "
        "FAIL finding for each mismatch to close this."
    ),
)
def test_fm04_detector_flags_period_unit_amendment_mismatch():
    """Target behavior: a detector returns FAIL for the planted mismatch.

    Written against validate_fields because it is the only existing
    validator that takes a record. It has no filing argument and does not
    compare values, so the FAIL assertion below cannot hold today.
    """
    row = _planted_csv_row()
    filing = _planted_filing()
    expected_mismatch = _mismatches(row, filing)
    assert expected_mismatch, "fixture must plant at least one mismatch"
    findings = validate_fields(row, ["ticker", "source_id", "ingest_at"])
    flagged = {
        f.subject
        for f in findings
        if f.status == ValidationStatus.FAIL and f.subject in expected_mismatch
    }
    assert flagged == set(expected_mismatch)
