"""Canonical field dictionary for the as_of package.

Each field has one FieldSpec that records its unit, its dtype, the clock that
governs when the value was known (one of core.ClockName), and whether it may
be null. validate_fields() checks a record against these definitions and
returns core.Finding objects, one per check, so a caller can see every
problem at once instead of stopping at the first.

Topic: field dictionary.

Dtype names used in FieldSpec.dtype are: "str", "int", "float", "bool",
"date" and "datetime". Datetimes must be timezone-aware. Naive datetimes FAIL. Aware datetimes with
any offset PASS, because core.ensure_utc converts them to UTC; the check does
not require the offset to be zero. Only synthetic data is expected to flow
through these definitions.
"""

import math
import numbers
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Dict, List, Sequence

import numpy as np

from as_of.core import AsOfError, ClockName, Finding, FieldSpec, ValidationStatus

__all__ = [
    "FieldSpec",
    "FIELD_DICTIONARY",
    "build_field_dictionary",
    "lookup_field",
    "validate_fields",
]

_KNOWN_DTYPES = ("str", "int", "float", "bool", "date", "datetime")


def _spec(name: str, unit: str, dtype: str, clock: ClockName, nullable: bool) -> FieldSpec:
    """Build one FieldSpec, checking the dtype name against the known set."""
    if dtype not in _KNOWN_DTYPES:
        raise AsOfError("unknown dtype %r for field %r" % (dtype, name))
    return FieldSpec(name=name, unit=unit, dtype=dtype, clock=clock, nullable=nullable)


def build_field_dictionary() -> Dict[str, FieldSpec]:
    """Return a fresh mapping from field name to FieldSpec.

    Every spec has a non-empty unit and a ClockName clock. The mapping is
    rebuilt on each call so callers can change their copy without touching
    the module constant.
    """
    specs = [
        _spec("ticker", "exchange symbol", "str", ClockName.INGEST, False),
        _spec("source_id", "identifier", "str", ClockName.INGEST, False),
        _spec("ingest_at", "UTC timestamp", "datetime", ClockName.INGEST, False),
        _spec("price_as_of", "calendar date", "date", ClockName.EVENT, False),
        _spec("price_close", "USD per share", "float", ClockName.EVENT, False),
        _spec("position_quantity", "shares", "float", ClockName.EVENT, False),
        _spec("filed_at", "UTC timestamp", "datetime", ClockName.EVENT, False),
        _spec("accepted_at", "UTC timestamp", "datetime", ClockName.RELEASE, False),
        _spec("estimate_value", "USD per share", "float", ClockName.KNOWLEDGE, False),
        _spec("estimate_knowledge_at", "UTC timestamp", "datetime", ClockName.KNOWLEDGE, False),
        _spec("macro_obs_date", "calendar date", "date", ClockName.EVENT, False),
        _spec("macro_value", "series units as published", "float", ClockName.RELEASE, False),
        _spec("macro_release_at", "UTC timestamp", "datetime", ClockName.RELEASE, False),
        _spec("exception_severity", "enum: info, warn, block", "str", ClockName.KNOWLEDGE, False),
        _spec("exception_resolved_at", "UTC timestamp", "datetime", ClockName.KNOWLEDGE, True),
        _spec("claim_status", "enum: draft, supported, retired", "str", ClockName.REPORT, False),
        _spec("report_generated_at", "UTC timestamp", "datetime", ClockName.REPORT, False),
        _spec("change_evidence_ref", "identifier", "str", ClockName.REPORT, True),
    ]
    return {spec.name: spec for spec in specs}


FIELD_DICTIONARY: Dict[str, FieldSpec] = build_field_dictionary()


def lookup_field(name: str) -> FieldSpec:
    """Return the FieldSpec for name. Raise AsOfError if the name is unknown."""
    try:
        return FIELD_DICTIONARY[name]
    except (KeyError, TypeError):
        raise AsOfError("unknown field: %r" % (name,))


def _is_null(value: Any) -> bool:
    """True for None and for float NaN, so a missing float counts as null."""
    if value is None:
        return True
    return (isinstance(value, numbers.Real) and not isinstance(value, numbers.Integral)
            and math.isnan(value))


def _dtype_ok(value: Any, dtype: str) -> bool:
    """Return True when value matches the dictionary dtype name."""
    if dtype == "str":
        return isinstance(value, str)
    if dtype == "bool":
        # np.bool_ is what pandas and numpy yield; core.to_plain treats it as a bool.
        return isinstance(value, (bool, np.bool_))
    if dtype == "int":
        return isinstance(value, numbers.Integral) and not isinstance(value, bool)
    if dtype == "float":
        return isinstance(value, numbers.Real) and not isinstance(value, bool)
    if dtype == "datetime":
        return isinstance(value, datetime)
    if dtype == "date":
        return isinstance(value, date) and not isinstance(value, datetime)
    return False


def _finding(check_id: str, status: ValidationStatus, message: str, subject: str) -> Finding:
    """Shorthand for a Finding with a fixed check id prefix."""
    return Finding(check_id=check_id, status=status, message=message, subject=subject)


def validate_fields(record: Dict[str, Any], required: Sequence[str]) -> List[Finding]:
    """Check record against the dictionary and return one Finding per check.

    For each name in required:
      - absent from record            -> FAIL (field.present)
      - None and not nullable          -> FAIL (field.null)
      - None and nullable              -> PASS (field.null)
      - wrong dtype                    -> FAIL (field.dtype)
      - naive datetime                 -> FAIL (field.dtype)
      - not in the dictionary          -> FAIL (field.unknown)

    Fields present in record but not required are checked for dtype only when
    they are in the dictionary. Unknown extra fields get a WARN (field.unknown).
    """
    if not isinstance(record, Mapping):
        raise AsOfError("record must be a mapping, got %s" % type(record).__name__)
    if isinstance(required, (str, bytes)):
        raise AsOfError("required must be a sequence of field names, not a single string")
    findings: List[Finding] = []

    for name in required:
        # Non-str entries (for example lists) are not dictionary names. Check
        # the type first so a bad entry becomes a Finding, not a raw TypeError.
        if not isinstance(name, str) or name not in FIELD_DICTIONARY:
            findings.append(_finding("field.unknown", ValidationStatus.FAIL,
                                     "required field is not in the dictionary", str(name)))
            continue
        spec = FIELD_DICTIONARY[name]
        if name not in record:
            findings.append(_finding("field.present", ValidationStatus.FAIL,
                                     "required field is absent", name))
            continue
        value = record[name]
        if _is_null(value):
            if spec.nullable:
                findings.append(_finding("field.null", ValidationStatus.PASS,
                                         "nullable field is null", name))
            else:
                findings.append(_finding("field.null", ValidationStatus.FAIL,
                                         "non-nullable field is null", name))
            continue
        findings.extend(_check_value(name, spec, value))

    for name in sorted(record, key=str):
        if name in required:
            continue
        if name not in FIELD_DICTIONARY:
            findings.append(_finding("field.unknown", ValidationStatus.WARN,
                                     "record field is not in the dictionary", str(name)))
            continue
        value = record[name]
        if not _is_null(value):
            findings.extend(_check_value(name, FIELD_DICTIONARY[name], value))

    return findings


def _check_value(name: str, spec: FieldSpec, value: Any) -> List[Finding]:
    """Dtype and timezone checks for one non-null value."""
    if not _dtype_ok(value, spec.dtype):
        return [_finding("field.dtype", ValidationStatus.FAIL,
                         "expected dtype %s, got %s" % (spec.dtype, type(value).__name__),
                         name)]
    if spec.dtype == "datetime" and (value.tzinfo is None or value.utcoffset() is None):
        return [_finding("field.dtype", ValidationStatus.FAIL,
                         "naive datetime is not allowed", name)]
    if (spec.dtype == "float" and not isinstance(value, numbers.Integral)
            and not math.isfinite(value)):
        return [_finding("field.dtype", ValidationStatus.FAIL,
                         "non-finite float is not allowed", name)]
    return [_finding("field.dtype", ValidationStatus.PASS, "value matches dtype", name)]
