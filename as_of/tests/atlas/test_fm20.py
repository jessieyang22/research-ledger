"""Failure mode fm20: percent and decimal mixed.

Some series are published in percent (2.5 means 2.5 percent) and others in
decimals (0.025 means 2.5 percent). If the units are never normalized, a
comparison between the two is off by a factor of 100. The detection method
named in the failure mode note is to inspect raw and normalized series side by
side, and to require an explicit derived unit field on every series. No
network calls are made and no file is written.

What the existing modules do with units:
- field_dictionary.FieldSpec carries a free-text unit string (for example
  "series units as published" for macro_value). validate_fields checks dtype,
  nullability and clock names, but it never reads the unit string. A record
  that carries a conflicting unit key only gets a WARN for an unknown field.
- macro_vintage_manifest.VintageManifest.add_vintage accepts any finite real
  value. A percent value and a decimal value for the same series are both
  stored without comment.
- reported_vs_expected_bridge.build_bridge computes surprise_abs and
  surprise_pct from raw floats. Nothing checks that reported and expected are
  on the same scale.
- macro_fixture builds both SYN_GDP and SYN_CPI on one published scale, so the
  shipped fixture does not plant this failure. That is a control, not a
  detection.

Gaps, marked xfail (strict): no module normalizes units, no FieldSpec has a
derived or normalized unit field, and no check compares the scale of two
series. The xfail tests state the expected detection and the gap.

Only synthetic data is used.
"""

from dataclasses import fields
from datetime import date, datetime, timezone

import pytest

from as_of import field_dictionary, reported_vs_expected_bridge
from as_of.core import AsOfError, ClockName, EstimateRecord, MacroVintage, ValidationStatus
from as_of.field_dictionary import FIELD_DICTIONARY, validate_fields
from as_of.macro_fixture import make_macro_fixture
from as_of.macro_vintage_manifest import VintageManifest

SERIES = "SYN_RATE"
OBS = date(2026, 3, 1)
RELEASE = datetime(2026, 4, 15, tzinfo=timezone.utc)
TICKER = "SYN_T01"
METRIC = "SYN_EPS"
PERIOD = "SYN_Q1"


def _vintage(value, day=RELEASE.date()):
    return MacroVintage(
        series_id=SERIES,
        obs_date=OBS,
        vintage_date=day,
        release_at=datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
        value=value,
        source_id="SYN_SRC_RATE",
    )


def _oracle_scale_mismatch(values_by_series):
    """Test-side oracle, not a module: flag series whose magnitudes differ by ~100x.

    This shows the planted failure is detectable from raw and normalized values
    side by side. It is not a claim that any module performs this check.
    """
    flagged = []
    for name, values in values_by_series.items():
        mags = [abs(v) for v in values if v not in (0, None)]
        if not mags:
            continue
        for other, other_values in values_by_series.items():
            if other == name:
                continue
            other_mags = [abs(v) for v in other_values if v not in (0, None)]
            if not other_mags:
                continue
            ratio = (sum(mags) / len(mags)) / (sum(other_mags) / len(other_mags))
            if ratio >= 50 or ratio <= 1 / 50:
                flagged.append((name, other))
    return flagged


# ---------------------------------------------------------------------------
# Control tests: the existing modules behave as their docstrings describe.
# ---------------------------------------------------------------------------


def test_control_every_field_spec_has_a_nonempty_unit_string():
    # The dictionary records a unit for each field. This is the only unit
    # information in the package.
    for name, spec in FIELD_DICTIONARY.items():
        assert isinstance(spec.unit, str) and spec.unit.strip() != "", name


def test_control_macro_fixture_publishes_both_series_on_one_scale():
    # The shipped fixture has no planted scale mix. Both series sit within the
    # same order of magnitude, so the oracle finds nothing to flag.
    rows = make_macro_fixture()
    by_series = {}
    for row in rows:
        by_series.setdefault(row.series_id, []).append(row.value)
    assert set(by_series) == {"SYN_GDP", "SYN_CPI"}
    assert _oracle_scale_mismatch(by_series) == []


def test_control_oracle_flags_a_planted_percent_decimal_mix():
    # Sanity check on the test-side oracle itself. A decimal series next to a
    # percent series should be flagged, so a passing test below is meaningful.
    flagged = _oracle_scale_mismatch({"PCT": [2.5, 2.6], "DEC": [0.025, 0.026]})
    assert ("PCT", "DEC") in flagged or ("DEC", "PCT") in flagged


def test_control_manifest_keeps_same_scale_revisions():
    # A revision on one scale is stored as a separate vintage, as designed.
    m = VintageManifest()
    m.add_vintage(_vintage(2.5))
    m.add_vintage(_vintage(2.6, day=date(2026, 5, 15)))
    assert [v.value for v in m.entries(SERIES)] == [2.5, 2.6]


# ---------------------------------------------------------------------------
# Planted failure: a percent value and a decimal value for the same series.
# Expected: the manifest blocks the second row. Actual: it accepts both.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="gap: VintageManifest.add_vintage has no unit check, so a decimal "
           "revision (0.026) next to a percent original (2.5) is stored silently",
)
def test_planted_percent_then_decimal_vintage_is_blocked_by_manifest():
    m = VintageManifest()
    m.add_vintage(_vintage(2.5))
    try:
        m.add_vintage(_vintage(0.026, day=date(2026, 5, 15)))
    except AsOfError:
        blocked = True
    else:
        blocked = False
    assert blocked, "manifest accepted a decimal value on a percent series"


# ---------------------------------------------------------------------------
# Planted failure: reported in decimal, expected in percent (or the reverse).
# Expected: the bridge flags the scale mismatch. Actual: surprise_pct is
# computed silently and is about 100 times too large in magnitude.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="gap: build_bridge takes raw floats and has no unit argument, so a "
           "decimal reported value against a percent estimate is not flagged",
)
def test_planted_bridge_scale_mismatch_is_flagged():
    # build_bridge takes a plain list of records (as the existing bridge tests do).
    ledger = [EstimateRecord(
        estimate_id="SYN_E1",
        ticker=TICKER,
        metric=METRIC,
        period=PERIOD,
        analyst_id="SYN_A1",
        value=5.0,  # percent-scale estimate
        knowledge_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        source_id="SYN_SRC_EST",
    )]
    try:
        out = reported_vs_expected_bridge.build_bridge(
            ledger, TICKER, METRIC, PERIOD,
            reported_value=0.05,  # same quantity, decimal-scale
            reported_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
        )
    except AsOfError:
        flagged = True
    else:
        flagged = "unit" in out or "scale_flag" in out
    assert flagged, "bridge returned a surprise without any scale flag"


# ---------------------------------------------------------------------------
# Planted failure: a record that declares decimal units but carries a
# percent-scale value. Expected: validate_fields fails the record. Actual: a
# conflicting unit key is only a WARN, and the value passes dtype checks.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="gap: validate_fields ignores the unit string and has no derived unit "
           "field, so a record that says decimal with a percent value passes",
)
def test_planted_record_unit_conflict_fails_validation():
    record = {
        "macro_value": 2.5,
        "macro_release_at": RELEASE,
        "unit": "decimal",
    }
    findings = validate_fields(record, ["macro_value", "macro_release_at"])
    statuses = [f.status for f in findings]
    assert ValidationStatus.FAIL in statuses, "unit conflict was not failed"


# ---------------------------------------------------------------------------
# Gap test: the dictionary has no derived or normalized unit field.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="gap: FieldSpec has only a free-text unit; no derived or normalized "
           "unit field exists, so the 'explicit derived unit field' rule cannot be met",
)
def test_gap_field_spec_has_an_explicit_derived_unit_field():
    names = {f.name for f in fields(field_dictionary.FieldSpec)}
    assert names & {"derived_unit", "normalized_unit", "scale"}, sorted(names)
