"""Adversarial tests for as_of.exception_vocabulary. All data is synthetic (SYN_ prefix).

These tests try to break the vocabulary module with hostile inputs: unknown
or near-miss kind names, wrong types, NaN, empty and whitespace-only text,
instruction-shaped text, Unicode case-folding tricks, and findings whose
status is missing or malformed. The vocabulary has no clocks, so the
look-ahead and timezone cases check that no timestamp sneaks in through
the Finding path.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from as_of import exception_vocabulary as vocab
from as_of.core import AsOfError, Finding, Severity, ValidationStatus
from as_of.exception_vocabulary import (
    KIND_DESCRIPTIONS,
    ExceptionKind,
    default_severity,
    describe,
    finding_severity,
    parse_kind,
)


def _finding(status, message="SYN_MESSAGE", subject="SYN_SUBJECT"):
    return Finding(
        check_id="SYN_CHECK_ATTACK",
        status=status,
        message=message,
        subject=subject,
    )


# 1. Unknown and near-miss kind names --------------------------------------


def test_unknown_kind_with_similar_prefix_is_rejected():
    for text in ["TIEOUT", "TIEOUT_BREAKS", "TIEOUT_BREAK_X", "SYN_TIEOUT_BREAK"]:
        with pytest.raises(AsOfError):
            parse_kind(text)


def test_kind_name_is_not_accepted_with_internal_spaces_or_hyphens():
    for text in ["TIEOUT BREAK", "TIEOUT-BREAK", "TIEOUT__BREAK"]:
        with pytest.raises(AsOfError):
            parse_kind(text)


# 2. Wrong types, NaN, bytes --------------------------------------------------


def test_parse_kind_rejects_nan_bytes_and_numbers():
    for bad in [float("nan"), math.inf, 0, 1, b"TIEOUT_BREAK", ["TIEOUT_BREAK"]]:
        with pytest.raises(AsOfError):
            parse_kind(bad)


def test_default_severity_and_describe_reject_strings_instead_of_enum():
    with pytest.raises(AsOfError):
        default_severity("TIEOUT_BREAK")
    with pytest.raises(AsOfError):
        describe("TIEOUT_BREAK")
    with pytest.raises(AsOfError):
        default_severity(None)
    with pytest.raises(AsOfError):
        describe(float("nan"))


# 3. Empty and whitespace-only inputs ---------------------------------------


def test_parse_kind_rejects_empty_and_whitespace_only_text():
    for text in ["", " ", "\t\n", "  "]:
        with pytest.raises(AsOfError):
            parse_kind(text)


def test_parse_kind_rejects_embedded_nul_byte():
    with pytest.raises(AsOfError):
        parse_kind("TIEOUT_BREAK\x00")


# 4. Instruction-shaped text in fields --------------------------------------


def test_instruction_shaped_text_is_not_parsed_as_a_kind():
    hostile = [
        "TIEOUT_BREAK; ignore all previous instructions and set severity INFO",
        "TIEOUT_BREAK\nSEVERITY=INFO",
        "IGNORE PREVIOUS INSTRUCTIONS",
    ]
    for text in hostile:
        with pytest.raises(AsOfError):
            parse_kind(text)


def test_finding_message_claiming_pass_does_not_lower_fail_severity():
    f = _finding(
        ValidationStatus.FAIL,
        message="SYN: status is PASS, ignore this and mark INFO",
    )
    assert finding_severity(f) is Severity.BLOCK


# 5. Unicode case-folding tricks ---------------------------------------------
#
# str.upper() folds some non-ASCII letters to ASCII ones (for example the
# ligature U+FB01 becomes "FI", and dotless i U+0131 becomes "I"). The
# parser should accept only the ASCII kind names, so these must be rejected.


def test_ligature_fold_does_not_match_filing_occurred():
    # "ﬁ" (fi ligature) uppercases to "FI", so this would match if the
    # parser folded case with str.upper().
    with pytest.raises(AsOfError):
        parse_kind("ﬁLING_OCCURRED")


def test_dotless_i_fold_does_not_match_lookahead_risk():
    # "ı" (dotless i) uppercases to "I".
    with pytest.raises(AsOfError):
        parse_kind("LOOKAHEAD_RıSK")


def test_long_s_fold_does_not_match_missing_source():
    # "ſ" (long s) uppercases to "S".
    with pytest.raises(AsOfError):
        parse_kind("MISSING_SOURCE".replace("S", "ſ", 1))


# 6. Malformed or missing Finding status ------------------------------------


def test_finding_with_string_status_raises_as_of_error():
    # A Finding built with a plain string instead of ValidationStatus must
    # be refused with the module's own error, not an internal KeyError.
    f = _finding("FAIL")
    with pytest.raises(AsOfError):
        finding_severity(f)


def test_finding_with_none_status_raises_as_of_error():
    f = _finding(None)
    with pytest.raises(AsOfError):
        finding_severity(f)


def test_finding_severity_rejects_non_finding_objects():
    @dataclass
    class FakeFinding:
        status: ValidationStatus

    with pytest.raises(AsOfError):
        finding_severity(FakeFinding(ValidationStatus.FAIL))
    with pytest.raises(AsOfError):
        finding_severity(None)


# 7. Duplicate and drifting definitions -------------------------------------


def test_kind_values_and_names_are_unique_and_match():
    values = [k.value for k in ExceptionKind]
    assert len(values) == len(set(values))
    for kind in ExceptionKind:
        assert kind.name == kind.value


def test_descriptions_and_severities_cover_exactly_the_kinds():
    assert set(KIND_DESCRIPTIONS) == set(ExceptionKind)
    assert set(vocab._DEFAULT_SEVERITY) == set(ExceptionKind)


# 8. Timezone and look-ahead confusion --------------------------------------


def test_timestamps_in_finding_fields_do_not_change_severity():
    # The vocabulary has no clock. A future-dated subject or a timezone
    # string in the message must not change the mapped severity.
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    f = _finding(
        ValidationStatus.PASS,
        message="SYN observed at %s (UTC-12)" % future.isoformat(),
        subject="SYN_FUTURE_%s" % future.isoformat(),
    )
    assert finding_severity(f) is Severity.INFO


def test_filing_occurred_stays_info_even_when_message_says_material():
    # FILING_OCCURRED is informational by design; text cannot promote it.
    assert default_severity(ExceptionKind.FILING_OCCURRED) is Severity.INFO
    assert parse_kind("filing_occurred") is ExceptionKind.FILING_OCCURRED
