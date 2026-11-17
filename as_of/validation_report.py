"""Build and render a validation report from named check results.

This module turns a mapping of check names to lists of Finding records into a
plain dictionary report, answers whether the report passes, and renders the
report as text. The output is deterministic: check names are sorted, no
timestamp is written, and the same inputs always give the same text. A caller
that wants a timestamp must pass it in through the title or generated_for
argument.

Topic: validation report topic.

Only as_of.core is imported. All data handled here is synthetic.
"""

import re
from typing import Any, Dict, List, Mapping, Sequence

from as_of.core import Finding, ValidationStatus, require, to_plain


_STATUS_LABEL: Dict[ValidationStatus, str] = {
    ValidationStatus.PASS: "PASS",
    ValidationStatus.WARN: "WARN",
    ValidationStatus.FAIL: "FAIL",
}


# C0 and C1 controls, DEL, and the Unicode line and paragraph separators.
# str.splitlines() treats U+2028, U+2029 and U+0085 as line breaks, so they
# must be escaped too or a reviewer's line-based tools could see forged lines.
_CONTROL_RE = re.compile("[\x00-\x1f\x7f-\x9f  ]")


def _safe_text(text: Any) -> str:
    """Escape control characters so text cannot forge extra report lines."""
    return _CONTROL_RE.sub(lambda m: "\\x%02x" % ord(m.group(0)), str(text))


def _check_findings(name: str, findings: Sequence[Finding]) -> List[Finding]:
    """Validate and copy one check's findings into a list."""
    require(isinstance(name, str), "check name must be a str, got %s" % type(name).__name__)
    require(
        isinstance(findings, (list, tuple)),
        "check %r findings must be a list or tuple, got %s" % (name, type(findings).__name__),
    )
    copied: List[Finding] = []
    for finding in findings:
        require(
            isinstance(finding, Finding),
            "check %r has a non-Finding entry: %r" % (name, finding),
        )
        require(
            isinstance(finding.status, ValidationStatus),
            "check %r has a finding status that is not a ValidationStatus: %r" % (name, finding.status),
        )
        require(
            isinstance(finding.message, str) and isinstance(finding.subject, str),
            "check %r has a finding whose message and subject must be str" % name,
        )
        copied.append(finding)
    return copied


def build_report(
    title: str,
    results: Mapping[str, Sequence[Finding]],
    generated_for: str,
) -> Dict[str, Any]:
    """Build a plain-dict validation report.

    Each check is stored under its name in sorted name order. The report
    holds the overall status (FAIL if any finding failed, WARN if any finding
    warned, otherwise PASS), per-check status, and counts of findings by
    status. Empty results give a report that passes.
    """
    require(isinstance(title, str), "title must be a str")
    require(isinstance(generated_for, str), "generated_for must be a str")
    require(isinstance(results, Mapping), "results must be a mapping, got %s" % type(results).__name__)

    checks: List[Dict[str, Any]] = []
    total_counts: Dict[str, int] = {"pass": 0, "warn": 0, "fail": 0}
    overall = ValidationStatus.PASS

    names = list(results.keys())
    for name in names:
        # Validate before sorting so mixed key types raise AsOfError, not TypeError.
        require(isinstance(name, str), "check name must be a str, got %s" % type(name).__name__)
    for name in sorted(names):
        findings = _check_findings(name, results[name])
        check_status = ValidationStatus.PASS
        for finding in findings:
            total_counts[finding.status.value] += 1
            if finding.status is ValidationStatus.FAIL:
                check_status = ValidationStatus.FAIL
            elif finding.status is ValidationStatus.WARN and check_status is ValidationStatus.PASS:
                check_status = ValidationStatus.WARN
        if check_status is ValidationStatus.FAIL:
            overall = ValidationStatus.FAIL
        elif check_status is ValidationStatus.WARN and overall is ValidationStatus.PASS:
            overall = ValidationStatus.WARN
        checks.append(
            {
                "name": name,
                "status": check_status.value,
                "findings": [to_plain(f) for f in findings],
            }
        )

    return {
        "title": title,
        "generated_for": generated_for,
        "status": overall.value,
        "check_count": len(checks),
        "counts": total_counts,
        "checks": checks,
    }


def report_passes(report: Dict[str, Any]) -> bool:
    """Return True when no finding in the report has status FAIL.

    WARN findings do not make a report fail. A report built by build_report
    with no results passes. A hand-built dict whose report, check, or finding
    status is missing or unrecognised does not pass.
    """
    require(isinstance(report, dict), "report must be a dict")
    # Fail closed: a FAIL on the report or on any check counts, even when no
    # finding carries it. A missing or unrecognised status on the report, a
    # check, or a finding is not a pass.
    known = {ValidationStatus.PASS.value, ValidationStatus.WARN.value}
    if report.get("status") not in known:
        return False
    for check in report.get("checks", []):
        if check.get("status") not in known:
            return False
        for finding in check.get("findings", []):
            if finding.get("status") not in known:
                return False
    return True


def render_report_text(report: Dict[str, Any]) -> str:
    """Render the report as plain text.

    Every check name appears in the output, including checks with no
    findings. Lines are joined with newlines and the text ends with one
    newline. The same report always renders to the same text.
    """
    require(isinstance(report, dict), "report must be a dict")
    lines: List[str] = []
    lines.append("Validation report: %s" % _safe_text(report.get("title", "")))
    lines.append("Generated for: %s" % _safe_text(report.get("generated_for", "")))
    lines.append("Overall: %s" % _label_for(report.get("status", "")))
    counts = report.get("counts", {})
    lines.append(
        "Findings: pass=%d warn=%d fail=%d"
        % (counts.get("pass", 0), counts.get("warn", 0), counts.get("fail", 0))
    )
    lines.append("")
    lines.append("Checks:")
    for check in report.get("checks", []):
        lines.append(
            "- %s [%s]" % (_safe_text(check["name"]), _label_for(check.get("status", "")))
        )
        for finding in check.get("findings", []):
            lines.append(
                "    %s %s: %s"
                % (
                    _label_for(finding.get("status", "")),
                    _safe_text(finding.get("subject", "")),
                    _safe_text(finding.get("message", "")),
                )
            )
    return "\n".join(lines) + "\n"


def _label_for(status_value: str) -> str:
    """Map a status value string to its display label."""
    for status, label in _STATUS_LABEL.items():
        if status.value == status_value:
            return label
    return str(status_value).upper()
