"""No-look-ahead cutoff rule for macro values.

A macro value is usable at a decision time only when the vintage that carries
it was released at or before that time. A later revision of the same
observation does not count until its own release moment has passed.

value_as_of picks, for one series and one observation date, the latest
vintage whose release_at is at or before decision_at. Ties on release_at are
broken by the later vintage_date, so the result is deterministic.

cutoff_violations audits a list of values a decision actually used. Each use
whose release_at is after decision_at produces a FAIL finding. Uses that pass
the rule produce no finding, so an empty list means no violations were found.


Only as_of.core (shared types and UTC helpers) and as_of.macro_vintage_manifest
(the VintageManifest type) are imported. All data handled here is synthetic.

Public API:
    value_as_of(manifest, series_id, obs_date, decision_at) -> MacroVintage or None
    cutoff_violations(uses, decision_at) -> list of Finding
"""

from datetime import date, datetime
from typing import List, Optional, Sequence

from as_of.core import AsOfError, Finding, MacroVintage, ValidationStatus, ensure_utc
from as_of.macro_vintage_manifest import VintageManifest

CHECK_ID: str = "macro_cutoff"


def _fmt_utc(dt: datetime) -> str:
    """Format an aware UTC datetime, keeping microseconds when present.

    Dropping them would print a sub-second breach as two identical timestamps.
    """
    text = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return "%s.%06dZ" % (text, dt.microsecond)
    return text + "Z"


def value_as_of(
    manifest: VintageManifest,
    series_id: str,
    obs_date: date,
    decision_at: datetime,
) -> Optional[MacroVintage]:
    """Return the latest vintage of one observation released at or before decision_at.

    A release exactly at decision_at is allowed. Among the eligible vintages,
    the one with the largest release_at wins. A tie on release_at goes to the
    larger vintage_date. Returns None when no vintage of that observation was
    released by decision_at, including when the series or observation is
    unknown to the manifest. A naive decision_at raises AsOfError.
    """
    cutoff = ensure_utc(decision_at)
    # A string or datetime obs_date would never match and would read as "nothing released".
    if not (isinstance(obs_date, date) and not isinstance(obs_date, datetime)):
        raise AsOfError("obs_date must be a plain date, got %s" % type(obs_date).__name__)
    best: Optional[MacroVintage] = None
    best_key = None
    for vintage in manifest.entries(series_id):
        if vintage.obs_date != obs_date:
            continue
        released = ensure_utc(vintage.release_at)
        if released > cutoff:
            continue
        key = (released, vintage.vintage_date)
        if best_key is None or key > best_key:
            best = vintage
            best_key = key
    return best


def cutoff_violations(
    uses: Sequence[MacroVintage],
    decision_at: datetime,
) -> List[Finding]:
    """Return one FAIL finding for each used vintage released after decision_at.

    Uses released at or before decision_at are allowed and add no finding.
    The subject of each finding names the series, observation date and source.
    A naive decision_at raises AsOfError.
    """
    cutoff = ensure_utc(decision_at)
    findings: List[Finding] = []
    for use in uses:
        released = ensure_utc(use.release_at)
        if released <= cutoff:
            continue
        subject = "%s:%s:%s" % (use.series_id, use.obs_date.isoformat(), use.source_id)
        message = "value released at %s is after decision time %s" % (
            _fmt_utc(released),
            _fmt_utc(cutoff),
        )
        findings.append(
            Finding(
                check_id=CHECK_ID,
                status=ValidationStatus.FAIL,
                message=message,
                subject=subject,
            )
        )
    return findings
