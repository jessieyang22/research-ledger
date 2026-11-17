"""Tests for as_of.field_dictionary. All fixtures are synthetic and use the SYN_ prefix."""

from datetime import date, datetime, timezone

import pytest

from as_of.core import AsOfError, ClockName, Finding, FieldSpec, ValidationStatus
from as_of import field_dictionary
from as_of.field_dictionary import (
    FIELD_DICTIONARY,
    build_field_dictionary,
    lookup_field,
    validate_fields,
)


def _utc(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _by_check(findings, check_id):
    return [f for f in findings if f.check_id == check_id]


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_every_field_clock_is_a_clock_name():
    for name, spec in FIELD_DICTIONARY.items():
        assert isinstance(spec.clock, ClockName), name
        assert spec.name == name


def test_lookup_unknown_field_raises_as_of_error():
    with pytest.raises(AsOfError):
        lookup_field("no_such_field")


def test_validate_fields_fails_for_absent_required_field():
    record = {"ticker": "SYN_AAA"}
    findings = validate_fields(record, ["ticker", "source_id"])
    absent = [
        f for f in findings
        if f.check_id == "field.present" and f.subject == "source_id"
    ]
    assert len(absent) == 1
    assert absent[0].status == ValidationStatus.FAIL


def test_every_field_has_non_empty_unit():
    for name, spec in FIELD_DICTIONARY.items():
        assert isinstance(spec.unit, str), name
        assert spec.unit.strip() != "", name


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_field_spec_is_frozen_dataclass():
    spec = lookup_field("ticker")
    assert isinstance(spec, FieldSpec)
    with pytest.raises(Exception):
        spec.unit = "changed"


def test_lookup_known_field_returns_matching_spec():
    spec = lookup_field("price_close")
    assert spec.name == "price_close"
    assert spec.dtype == "float"
    assert spec.clock == ClockName.EVENT
    assert spec.nullable is False


def test_lookup_empty_string_raises_as_of_error():
    with pytest.raises(AsOfError):
        lookup_field("")


def test_build_field_dictionary_returns_fresh_copy():
    first = build_field_dictionary()
    second = build_field_dictionary()
    assert first is not second
    assert set(first) == set(second) == set(FIELD_DICTIONARY)
    first.pop("ticker")
    assert "ticker" in FIELD_DICTIONARY
    assert "ticker" in build_field_dictionary()


def test_every_dtype_is_a_known_name():
    known = set(field_dictionary._KNOWN_DTYPES)
    for name, spec in FIELD_DICTIONARY.items():
        assert spec.dtype in known, name


def test_validate_fields_passes_clean_record():
    record = {
        "ticker": "SYN_AAA",
        "source_id": "SYN_SRC_1",
        "ingest_at": _utc(2026, 10, 1, 12),
    }
    findings = validate_fields(record, ["ticker", "source_id", "ingest_at"])
    assert findings, "expected at least one finding"
    assert all(f.status == ValidationStatus.PASS for f in findings)


def test_validate_fields_fails_on_null_non_nullable():
    record = {"ticker": None}
    findings = validate_fields(record, ["ticker"])
    nulls = _by_check(findings, "field.null")
    assert len(nulls) == 1
    assert nulls[0].status == ValidationStatus.FAIL


def test_validate_fields_passes_null_nullable():
    record = {"exception_resolved_at": None}
    findings = validate_fields(record, ["exception_resolved_at"])
    nulls = _by_check(findings, "field.null")
    assert len(nulls) == 1
    assert nulls[0].status == ValidationStatus.PASS


def test_validate_fields_fails_on_wrong_dtype():
    record = {"price_close": "12.5"}
    findings = validate_fields(record, ["price_close"])
    dtype_checks = _by_check(findings, "field.dtype")
    assert len(dtype_checks) == 1
    assert dtype_checks[0].status == ValidationStatus.FAIL


def test_validate_fields_rejects_bool_as_float():
    record = {"price_close": True}
    findings = validate_fields(record, ["price_close"])
    assert _by_check(findings, "field.dtype")[0].status == ValidationStatus.FAIL


def test_validate_fields_rejects_naive_datetime():
    record = {"ingest_at": datetime(2026, 10, 1, 12)}
    findings = validate_fields(record, ["ingest_at"])
    dtype_checks = _by_check(findings, "field.dtype")
    assert dtype_checks[0].status == ValidationStatus.FAIL
    assert "naive" in dtype_checks[0].message


def test_validate_fields_rejects_datetime_for_date_field():
    record = {"price_as_of": _utc(2026, 10, 1)}
    findings = validate_fields(record, ["price_as_of"])
    assert _by_check(findings, "field.dtype")[0].status == ValidationStatus.FAIL


def test_validate_fields_accepts_plain_date_for_date_field():
    record = {"price_as_of": date(2026, 10, 1)}
    findings = validate_fields(record, ["price_as_of"])
    assert _by_check(findings, "field.dtype")[0].status == ValidationStatus.PASS


def test_validate_fields_flags_required_field_missing_from_dictionary():
    findings = validate_fields({}, ["no_such_field"])
    unknown = _by_check(findings, "field.unknown")
    assert len(unknown) == 1
    assert unknown[0].status == ValidationStatus.FAIL


def test_validate_fields_warns_on_extra_unknown_field():
    record = {"ticker": "SYN_AAA", "mystery_col": 1}
    findings = validate_fields(record, ["ticker"])
    unknown = _by_check(findings, "field.unknown")
    assert len(unknown) == 1
    assert unknown[0].status == ValidationStatus.WARN
    assert unknown[0].subject == "mystery_col"


def test_validate_fields_reports_every_problem_at_once():
    record = {"ticker": None, "price_close": "bad", "ingest_at": datetime(2026, 1, 1)}
    findings = validate_fields(record, ["ticker", "price_close", "source_id", "ingest_at"])
    fails = [f for f in findings if f.status == ValidationStatus.FAIL]
    subjects = {f.subject for f in fails}
    assert {"ticker", "price_close", "source_id", "ingest_at"} <= subjects


def test_validate_fields_returns_finding_objects():
    findings = validate_fields({"ticker": "SYN_AAA"}, ["ticker"])
    assert all(isinstance(f, Finding) for f in findings)


def test_validate_fields_extra_known_field_is_dtype_checked_only():
    # source_id is in the dictionary but not required: it gets a dtype check
    # (PASS here), and no presence or null check.
    record = {"ticker": "SYN_AAA", "source_id": "SYN_SRC_1"}
    findings = validate_fields(record, ["ticker"])
    extra = [f for f in findings if f.subject == "source_id"]
    assert extra and all(f.check_id == "field.dtype" for f in extra)
    assert all(f.status == ValidationStatus.PASS for f in extra)


def test_validate_fields_extra_none_value_is_not_dtype_checked():
    # A None value for a known, non-required field is skipped entirely.
    record = {"ticker": "SYN_AAA", "source_id": None}
    findings = validate_fields(record, ["ticker"])
    assert not [f for f in findings if f.subject == "source_id"]
