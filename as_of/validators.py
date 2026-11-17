"""Validator registry for the as_of package.

A validator is a named check. It takes a subject (any object) and returns a
list of Finding records from as_of.core. The registry holds validators by
name, runs them on a subject, and reduces the findings to one status.

Rules:
- Names are unique. Registering a duplicate name raises AsOfError.
- run() can be limited to named validators. An unknown name raises AsOfError.
- A check that raises an exception does not stop the run. Its exception is
  turned into a FAIL finding and the remaining checks still run.
- overall_status() returns FAIL if any finding is FAIL, else WARN if any
  finding is WARN, else PASS.

Two helper checks are included: check_no_nan (flags NaN values in a mapping)
and check_sorted_dates (flags dates that go backwards, and warns on repeats).

Topic: validators. All data handled here is synthetic. This module imports
only the standard library and as_of.core.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from as_of.core import AsOfError, Finding, ValidationStatus, require

import math


CheckFn = Callable[[Any], List[Finding]]


@dataclass(frozen=True)
class Validator:
    """A named check. check(subject) returns a list of Finding records."""

    name: str
    check: CheckFn


def _error_finding(name: str, subject: Any, exc: BaseException) -> Finding:
    """Build the FAIL finding used when a check raises."""
    return Finding(
        check_id=name,
        status=ValidationStatus.FAIL,
        message="validator raised %s: %s" % (type(exc).__name__, exc),
        subject=type(subject).__name__,
    )


class ValidatorRegistry:
    """Holds validators by unique name and runs them on subjects."""

    def __init__(self) -> None:
        self._validators: Dict[str, Validator] = {}

    def register(self, v: Validator) -> None:
        """Add a validator. A name already in use raises AsOfError."""
        require(isinstance(v, Validator), "expected a Validator, got %s" % type(v).__name__)
        require(isinstance(v.name, str) and v.name != "", "validator name must be a non-empty str")
        require(callable(v.check), "validator %r check must be callable" % v.name)
        if v.name in self._validators:
            raise AsOfError("duplicate validator name: %r" % v.name)
        self._validators[v.name] = v

    def names(self) -> List[str]:
        """Registered validator names, in registration order."""
        return list(self._validators.keys())

    def run(self, subject: Any, names: Optional[Sequence[str]] = None) -> List[Finding]:
        """Run validators on subject and return all findings.

        names=None runs every registered validator in registration order.
        Otherwise only the named validators run, in the order given. An
        unknown name raises AsOfError before any check runs.
        """
        if names is None:
            selected: List[Validator] = list(self._validators.values())
        else:
            selected = []
            for name in names:
                if name not in self._validators:
                    raise AsOfError("unknown validator name: %r" % (name,))
                selected.append(self._validators[name])

        findings: List[Finding] = []
        for v in selected:
            try:
                result = v.check(subject)
                if result is not None:
                    result = list(result)  # non-iterable returns raise here
            except Exception as exc:  # a raising check must not crash the run
                findings.append(_error_finding(v.name, subject, exc))
                continue
            if result is None:
                findings.append(
                    Finding(
                        check_id=v.name,
                        status=ValidationStatus.FAIL,
                        message="validator returned None instead of a list of findings",
                        subject=type(subject).__name__,
                    )
                )
                continue
            if not all(isinstance(f, Finding) for f in result):
                findings.append(
                    Finding(
                        check_id=v.name,
                        status=ValidationStatus.FAIL,
                        message="validator returned an item that is not a Finding",
                        subject=type(subject).__name__,
                    )
                )
                continue
            findings.extend(result)
        return findings

    def overall_status(self, findings: Sequence[Finding]) -> ValidationStatus:
        """FAIL if any finding is FAIL, else WARN if any is WARN, else PASS."""
        statuses = [f.status for f in findings]
        if ValidationStatus.FAIL in statuses:
            return ValidationStatus.FAIL
        if ValidationStatus.WARN in statuses:
            return ValidationStatus.WARN
        return ValidationStatus.PASS


def overall_status(findings: Sequence[Finding]) -> ValidationStatus:
    """Module-level form of ValidatorRegistry.overall_status."""
    return ValidatorRegistry().overall_status(findings)


def check_no_nan(values: Mapping[str, float]) -> List[Finding]:
    """Flag each key whose value is NaN, or is not a real number.

    Returns one PASS finding when every value is a number and none is NaN.
    """
    findings: List[Finding] = []
    for key, value in values.items():
        if isinstance(value, (str, bytes)):
            # float("101.25") succeeds, but a string is not a real number.
            findings.append(
                Finding(
                    check_id="no_nan",
                    status=ValidationStatus.FAIL,
                    message="value is not numeric: %r" % (value,),
                    subject=str(key),
                )
            )
            continue
        if isinstance(value, int):
            # An int is never NaN, even one too large to convert to float.
            continue
        try:
            is_nan = math.isnan(float(value))
        except (TypeError, ValueError, OverflowError):
            findings.append(
                Finding(
                    check_id="no_nan",
                    status=ValidationStatus.FAIL,
                    message="value is not numeric: %r" % (value,),
                    subject=str(key),
                )
            )
            continue
        if is_nan:
            findings.append(
                Finding(
                    check_id="no_nan",
                    status=ValidationStatus.FAIL,
                    message="value is NaN",
                    subject=str(key),
                )
            )
    if not findings:
        findings.append(
            Finding(
                check_id="no_nan",
                status=ValidationStatus.PASS,
                message="no NaN values in %d entries" % len(values),
                subject="values",
            )
        )
    return findings


def check_sorted_dates(dates: Sequence[date]) -> List[Finding]:
    """Check that dates never go backwards.

    A date that comes before its predecessor is a FAIL. A repeated date is a
    WARN. Returns one PASS finding when the sequence is strictly increasing.
    """
    findings: List[Finding] = []
    for i in range(1, len(dates)):
        prev, cur = dates[i - 1], dates[i]
        try:
            backwards = cur < prev
            repeated = (not backwards) and cur == prev
        except TypeError as exc:
            # Naive and aware datetimes, or date and datetime, cannot be ordered.
            findings.append(
                Finding(
                    check_id="sorted_dates",
                    status=ValidationStatus.FAIL,
                    message="dates at positions %d and %d cannot be compared: %s"
                    % (i - 1, i, exc),
                    subject="position %d" % i,
                )
            )
            continue
        if backwards:
            findings.append(
                Finding(
                    check_id="sorted_dates",
                    status=ValidationStatus.FAIL,
                    message="date %s at position %d is before previous date %s"
                    % (cur.isoformat(), i, prev.isoformat()),
                    subject="position %d" % i,
                )
            )
        elif repeated:
            findings.append(
                Finding(
                    check_id="sorted_dates",
                    status=ValidationStatus.WARN,
                    message="date %s repeats at position %d" % (cur.isoformat(), i),
                    subject="position %d" % i,
                )
            )
    if not findings:
        findings.append(
            Finding(
                check_id="sorted_dates",
                status=ValidationStatus.PASS,
                message="%d dates are in order" % len(dates),
                subject="dates",
            )
        )
    return findings
