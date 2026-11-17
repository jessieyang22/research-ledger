"""Ordering checks for the five as-of clocks.

The as_of design tracks five clocks for every record: event, release,
ingest, knowledge and report (see core.CLOCK_NAMES). This module checks
that a ClockSet respects a fixed set of ordering rules.

Rules implemented here:

    event     <= release
    release   <= ingest
    release   <= knowledge
    knowledge <= report

Topic: five clocks.

Behaviour:
    * A rule whose two clocks are both present and in the right order
      produces no finding.
    * A rule whose two clocks are both present and out of order produces a
      FAIL finding.
    * A rule where either clock is None produces a WARN finding. A missing
      clock never produces a FAIL.

All data handled here is synthetic. Only as_of.core is imported.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from as_of.core import AsOfError, ClockSet, Finding, ValidationStatus, ensure_utc


# (check_id, earlier clock, later clock). Clock names match core.CLOCK_NAMES.
ORDER_RULES: Tuple[Tuple[str, str, str], ...] = (
    ("clock.event_after_release", "event", "release"),
    ("clock.ingest_before_release", "release", "ingest"),
    ("clock.knowledge_before_release", "release", "knowledge"),
    ("clock.report_before_knowledge", "knowledge", "report"),
)


def _clock_value(cs: ClockSet, name: str) -> Optional[datetime]:
    """Return the datetime stored for clock name, or None when it is unset."""
    value: Optional[datetime] = getattr(cs, name + "_at")
    if value is None:
        return None
    try:
        return ensure_utc(value)
    except OverflowError as exc:
        # An offset can push a near-minimum datetime out of range on conversion.
        raise AsOfError("%s clock cannot be converted to UTC: %s" % (name, exc))


def check_clock_order(cs: ClockSet) -> List[Finding]:
    """Check every rule in ORDER_RULES against cs.

    Returns a list of Finding objects in rule order. An empty list means
    every rule had both clocks present and in order.
    """
    if not isinstance(cs, ClockSet):
        raise AsOfError("expected ClockSet, got %s" % type(cs).__name__)
    findings: List[Finding] = []
    values: Dict[str, Optional[datetime]] = {}
    for name in ("event", "release", "ingest", "knowledge", "report"):
        values[name] = _clock_value(cs, name)

    for check_id, earlier, later in ORDER_RULES:
        subject = "clock:%s<=%s" % (earlier, later)
        early_value = values[earlier]
        late_value = values[later]

        if early_value is None or late_value is None:
            missing = [n for n, v in ((earlier, early_value), (later, late_value)) if v is None]
            findings.append(
                Finding(
                    check_id=check_id,
                    status=ValidationStatus.WARN,
                    message="clock(s) not set, rule not checked: %s" % ", ".join(missing),
                    subject=subject,
                )
            )
            continue

        if early_value > late_value:
            findings.append(
                Finding(
                    check_id=check_id,
                    status=ValidationStatus.FAIL,
                    message="%s clock is after %s clock" % (earlier, later),
                    subject=subject,
                )
            )

    return findings
