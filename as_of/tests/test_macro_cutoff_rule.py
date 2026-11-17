"""Tests for as_of.macro_cutoff_rule. All fixtures are synthetic and use the SYN_ prefix.

Topic: macro vintage cutoff rule.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from as_of.core import AsOfError, Finding, MacroVintage, ValidationStatus
from as_of.macro_cutoff_rule import CHECK_ID, cutoff_violations, value_as_of
from as_of.macro_vintage_manifest import VintageManifest


OBS = date(2026, 1, 1)
DECISION = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)


def _vintage(
    series="SYN_GDP",
    obs=OBS,
    vint=date(2026, 2, 1),
    release=None,
    value=1.5,
    src="SYN_SRC_1",
):
    if release is None:
        release = datetime(vint.year, vint.month, vint.day, 8, 30, tzinfo=timezone.utc)
    return MacroVintage(
        series_id=series,
        obs_date=obs,
        vintage_date=vint,
        release_at=release,
        value=value,
        source_id=src,
    )


def _manifest(*rows):
    manifest = VintageManifest()
    for row in rows:
        manifest.add_vintage(row)
    return manifest


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_value_as_of_returns_earlier_vintage_when_later_one_released_after_decision():
    early = _vintage(vint=date(2026, 2, 1), value=1.5)
    late = _vintage(
        vint=date(2026, 4, 1),
        release=datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc),
        value=1.9,
    )
    manifest = _manifest(early, late)
    got = value_as_of(manifest, "SYN_GDP", OBS, DECISION)
    assert got is early
    assert got.value == 1.5


def test_used_value_released_after_decision_is_flagged_fail():
    late_use = _vintage(
        vint=date(2026, 4, 1),
        release=datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc),
        value=1.9,
    )
    findings = cutoff_violations([late_use], DECISION)
    assert len(findings) == 1
    finding = findings[0]
    assert isinstance(finding, Finding)
    assert finding.status is ValidationStatus.FAIL
    assert finding.check_id == CHECK_ID
    assert finding.subject == "SYN_GDP:2026-01-01:SYN_SRC_1"
    assert "2026-04-01T08:30:00Z" in finding.message


def test_release_exactly_at_decision_is_allowed():
    on_time = _vintage(
        vint=date(2026, 3, 15),
        release=DECISION,
        value=2.0,
    )
    manifest = _manifest(on_time)
    assert value_as_of(manifest, "SYN_GDP", OBS, DECISION) is on_time
    assert cutoff_violations([on_time], DECISION) == []


def test_value_as_of_returns_none_when_nothing_was_released_yet():
    not_yet = _vintage(
        vint=date(2026, 4, 1),
        release=datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc),
    )
    manifest = _manifest(not_yet)
    assert value_as_of(manifest, "SYN_GDP", OBS, DECISION) is None


# ---------------------------------------------------------------------------
# Edge cases for value_as_of
# ---------------------------------------------------------------------------


def test_value_as_of_one_second_after_decision_is_excluded():
    just_late = _vintage(release=DECISION + timedelta(seconds=1))
    manifest = _manifest(just_late)
    assert value_as_of(manifest, "SYN_GDP", OBS, DECISION) is None


def test_value_as_of_one_second_before_decision_is_included():
    just_early = _vintage(release=DECISION - timedelta(seconds=1))
    manifest = _manifest(just_early)
    assert value_as_of(manifest, "SYN_GDP", OBS, DECISION) is just_early


def test_value_as_of_picks_latest_eligible_vintage_not_latest_overall():
    first = _vintage(vint=date(2026, 2, 1), value=1.0)
    second = _vintage(
        vint=date(2026, 3, 1),
        release=datetime(2026, 3, 1, 8, 30, tzinfo=timezone.utc),
        value=1.2,
    )
    after = _vintage(
        vint=date(2026, 4, 1),
        release=datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc),
        value=1.4,
    )
    manifest = _manifest(first, second, after)
    assert value_as_of(manifest, "SYN_GDP", OBS, DECISION) is second


def test_value_as_of_tie_on_release_broken_by_later_vintage_date():
    same_release = datetime(2026, 3, 1, 8, 30, tzinfo=timezone.utc)
    older_vintage = _vintage(vint=date(2026, 2, 1), release=same_release, value=1.0)
    newer_vintage = _vintage(vint=date(2026, 3, 1), release=same_release, value=1.1)
    manifest = _manifest(older_vintage, newer_vintage)
    assert value_as_of(manifest, "SYN_GDP", OBS, DECISION) is newer_vintage


def test_value_as_of_ignores_other_observation_dates():
    other_obs = _vintage(obs=date(2025, 10, 1), value=9.0)
    manifest = _manifest(other_obs)
    assert value_as_of(manifest, "SYN_GDP", OBS, DECISION) is None


def test_value_as_of_unknown_series_returns_none():
    manifest = _manifest(_vintage())
    assert value_as_of(manifest, "SYN_MISSING", OBS, DECISION) is None


def test_value_as_of_empty_manifest_returns_none():
    assert value_as_of(VintageManifest(), "SYN_GDP", OBS, DECISION) is None


def test_value_as_of_naive_decision_raises():
    manifest = _manifest(_vintage())
    naive = datetime(2026, 3, 15, 12, 0)
    with pytest.raises(AsOfError):
        value_as_of(manifest, "SYN_GDP", OBS, naive)


def test_value_as_of_non_utc_decision_is_converted_before_compare():
    # 08:30 UTC release is 03:30 at UTC-5. Decision 04:00 at UTC-5 is 09:00 UTC, so it is allowed.
    release = _vintage(vint=date(2026, 3, 1), release=datetime(2026, 3, 1, 8, 30, tzinfo=timezone.utc))
    manifest = _manifest(release)
    offset = timezone(timedelta(hours=-5))
    decision_local = datetime(2026, 3, 1, 4, 0, tzinfo=offset)
    assert value_as_of(manifest, "SYN_GDP", OBS, decision_local) is release


# ---------------------------------------------------------------------------
# Edge cases for cutoff_violations
# ---------------------------------------------------------------------------


def test_cutoff_violations_empty_list_gives_no_findings():
    assert cutoff_violations([], DECISION) == []


def test_cutoff_violations_mixed_uses_only_flag_late_ones():
    ok_early = _vintage(vint=date(2026, 2, 1), value=1.0)
    ok_exact = _vintage(vint=date(2026, 3, 15), release=DECISION, value=1.1, src="SYN_SRC_2")
    late = _vintage(
        vint=date(2026, 4, 1),
        release=datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc),
        value=1.9,
        src="SYN_SRC_3",
    )
    findings = cutoff_violations([ok_early, late, ok_exact], DECISION)
    assert len(findings) == 1
    assert findings[0].subject == "SYN_GDP:2026-01-01:SYN_SRC_3"
    assert findings[0].status is ValidationStatus.FAIL


def test_cutoff_violations_one_finding_per_late_use():
    late_a = _vintage(vint=date(2026, 4, 1), release=datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc))
    late_b = _vintage(
        series="SYN_CPI",
        vint=date(2026, 4, 2),
        release=datetime(2026, 4, 2, 8, 30, tzinfo=timezone.utc),
        src="SYN_SRC_9",
    )
    findings = cutoff_violations([late_a, late_b], DECISION)
    assert len(findings) == 2
    assert all(f.status is ValidationStatus.FAIL for f in findings)


def test_cutoff_violations_naive_decision_raises():
    with pytest.raises(AsOfError):
        cutoff_violations([_vintage()], datetime(2026, 3, 15, 12, 0))
