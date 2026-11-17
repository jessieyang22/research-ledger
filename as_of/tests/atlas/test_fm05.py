"""Failure mode fm05: macro history begins after cutoff.

A macro series has no observation released by the as-of cutoff, yet the
analysis uses it as if it were known then. The expected control is that the
pipeline counts such observations, and either flags a use that happened after
its release or requires an explicit unavailable-at-cutoff status instead of
silently using them.

Fixtures use the SYN_ prefix and are planted in memory.

What the package does today:
  * macro_cutoff_rule.value_as_of returns None when no vintage was released by
    the decision time. The primitive does not invent a value.
  * macro_cutoff_rule.cutoff_violations flags any recorded use whose release is
    after the decision time as FAIL. Detection needs the use to be recorded.
  * wf_macro_vintage emits a FAIL macro_vintage_coverage finding when a
    decision has no available vintage. The default fixture never reaches that
    branch, so the test plants the condition by shifting one release.

What is missing: nothing counts observations that are unavailable at the
cutoff, and nothing returns an explicit unavailable-at-cutoff status. A caller
that gets None from value_as_of can still fall back to a later value without
any record. The explicit-status requirement is therefore a strict xfail below.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from as_of.core import Finding, MacroVintage, ValidationStatus
from as_of.macro_cutoff_rule import CHECK_ID, cutoff_violations, value_as_of
from as_of.macro_vintage_manifest import VintageManifest
from as_of import wf_macro_vintage

SERIES = "SYN_FM05_CPI"
SOURCE = "SYN_SRC_FM05"
DECISION = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
OBS_EARLY = date(2026, 1, 1)
OBS_LATE_ONLY = date(2026, 2, 1)


def _vintage(obs, vint, release, value):
    return MacroVintage(
        series_id=SERIES,
        obs_date=obs,
        vintage_date=vint,
        release_at=release,
        value=value,
        source_id=SOURCE,
    )


def _planted_manifest():
    """One observation released before the cutoff, and one whose only release is after it."""
    manifest = VintageManifest()
    manifest.add_vintage(
        _vintage(
            OBS_EARLY,
            date(2026, 2, 1),
            datetime(2026, 2, 1, 8, 30, tzinfo=timezone.utc),
            2.1,
        )
    )
    manifest.add_vintage(
        _vintage(
            OBS_LATE_ONLY,
            date(2026, 4, 1),
            datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc),
            2.4,
        )
    )
    return manifest


def test_late_only_observation_has_no_value_at_cutoff():
    """The rule returns None for an observation whose history starts after the cutoff."""
    manifest = _planted_manifest()
    assert value_as_of(manifest, SERIES, OBS_LATE_ONLY, DECISION) is None
    # The control observation released before the cutoff is still available.
    assert value_as_of(manifest, SERIES, OBS_EARLY, DECISION) is not None


def test_use_of_late_only_observation_is_flagged_fail():
    """If the late value is recorded as used, the cutoff audit flags it as FAIL."""
    manifest = _planted_manifest()
    late_vintage = manifest.entries(SERIES)[-1]
    assert late_vintage.obs_date == OBS_LATE_ONLY
    findings = cutoff_violations([late_vintage], DECISION)
    assert len(findings) == 1
    assert isinstance(findings[0], Finding)
    assert findings[0].status is ValidationStatus.FAIL
    assert findings[0].check_id == CHECK_ID
    assert findings[0].subject == "%s:%s:%s" % (SERIES, OBS_LATE_ONLY.isoformat(), SOURCE)


def test_proof_blocks_decision_with_no_vintage_at_cutoff(monkeypatch):
    """Planted: the first release of the first observation lands after its decision time.

    The decision for that observation then has no available vintage, so the
    proof must fail with a coverage finding instead of passing.
    """
    original = wf_macro_vintage._build_vintages

    def _late_first_release(seed):
        rows, plan = original(seed)
        first_obs = wf_macro_vintage._add_months(wf_macro_vintage.OBS_START, 0)
        first_day = first_obs + timedelta(days=wf_macro_vintage.RELEASE_LAG_DAYS)
        shifted = []
        for row in rows:
            if row.obs_date == first_obs and row.vintage_date == first_day:
                row = MacroVintage(
                    series_id=row.series_id,
                    obs_date=row.obs_date,
                    vintage_date=row.vintage_date,
                    # Decision time in the proof is 12:00 UTC on first_day.
                    release_at=datetime(
                        first_day.year, first_day.month, first_day.day, 13, 0,
                        tzinfo=timezone.utc,
                    ),
                    value=row.value,
                    source_id=row.source_id,
                )
            shifted.append(row)
        return shifted, plan

    monkeypatch.setattr(wf_macro_vintage, "_build_vintages", _late_first_release)
    result = wf_macro_vintage.run_macro_proof(seed=wf_macro_vintage.SYNTHETIC_SEED)
    assert result.passed is False
    coverage = [
        f for f in result.findings
        if f.check_id == "macro_vintage_coverage" and f.status is ValidationStatus.FAIL
    ]
    assert coverage, "expected a coverage FAIL for the unavailable observation"
    assert any(first_obs_subject(f) for f in coverage)


def first_obs_subject(finding):
    """True when a coverage finding names the first synthetic observation."""
    return finding.subject.endswith(wf_macro_vintage.OBS_START.isoformat())


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Gap: no module counts observations unavailable at the cutoff or returns "
        "an explicit unavailable-at-cutoff status. macro_cutoff_rule returns None "
        "silently and only flags uses that were recorded. Reported, not faked."
    ),
)
def test_unavailable_at_cutoff_status_is_explicit():
    """Required behaviour: an explicit unavailable-at-cutoff count or status exists."""
    import as_of.macro_cutoff_rule as rule

    assert hasattr(rule, "unavailable_at_cutoff"), (
        "no unavailable_at_cutoff helper exists in as_of.macro_cutoff_rule"
    )
    manifest = _planted_manifest()
    status = rule.unavailable_at_cutoff(manifest, SERIES, OBS_LATE_ONLY, DECISION)
    assert status == "unavailable_at_cutoff"
