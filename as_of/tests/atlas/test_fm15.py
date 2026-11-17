"""Failure mode fm15: margin surprise reported in percent instead of points.

A change in a margin is a difference of two ratios. It should be stated in
percentage points (for example 10% -> 12% is +2.0 points). A relative change
of the same numbers is +20%. Labeling the points figure as a percent misstates
the surprise. The detection method is to recalculate the surprise under both
unit definitions and to label the unit explicitly in the claim text. All data
is synthetic (SYN_ prefix).

Detection points checked:
  - reported_vs_expected_bridge.build_bridge returns surprise_abs (in the
    units of the input, here a fraction) and surprise_pct (a relative change).
    Both recalculations are checked below, and they agree with hand arithmetic.
  - claim_records.validate_claim is the only claim gate. It has no unit rule.

Gaps, marked xfail:
  - No module tags the unit of a claim's number, so a claim that says
    "20%" for a margin change of 2.0 points passes validate_claim.
  - field_dictionary has no margin field and no unit check tied to claim text.
  - classify_surprise applies its threshold to the relative percent. A margin
    change read as a percent therefore crosses a beat/miss band at a different
    size than the same change read in points.
"""

from datetime import datetime, timedelta, timezone

import pytest

from as_of.claim_records import make_claim, validate_claim
from as_of.core import EstimateRecord, ValidationStatus
from as_of.reported_vs_expected_bridge import build_bridge, classify_surprise

REPORT_AT = datetime(2026, 4, 30, 20, 0, 0, tzinfo=timezone.utc)
TICKER = "SYN_T01"
METRIC = "operating_margin"
PERIOD = "2026Q1"


def _margin_ledger(estimated_margins):
    """Synthetic analyst margin estimates, all known before REPORT_AT."""
    records = []
    for i, value in enumerate(estimated_margins):
        records.append(
            EstimateRecord(
                estimate_id="SYN_EST_FM15_%d" % (i + 1),
                ticker=TICKER,
                metric=METRIC,
                period=PERIOD,
                analyst_id="SYN_AN%d" % (i + 1),
                value=value,
                knowledge_at=REPORT_AT - timedelta(days=5 + i),
                source_id="SYN_SRC_EST_01",
            )
        )
    return records


def test_bridge_surprise_is_recomputed_under_both_unit_definitions():
    # Expected margin 10.0% (three analysts, all 0.10). Reported margin 12.0%.
    ledger = _margin_ledger([0.10, 0.10, 0.10])
    bridge = build_bridge(ledger, TICKER, METRIC, PERIOD, 0.12, REPORT_AT)

    # Definition A: change in percentage points = (12.0 - 10.0) = 2.0 points.
    points_hand = (0.12 - 0.10) * 100.0
    assert bridge["expected"] == pytest.approx(0.10)
    assert bridge["surprise_abs"] * 100.0 == pytest.approx(points_hand)
    assert points_hand == pytest.approx(2.0)

    # Definition B: relative change = 0.02 / 0.10 = 20 percent.
    relative_hand = 0.02 / 0.10 * 100.0
    assert bridge["surprise_pct"] * 100.0 == pytest.approx(relative_hand)
    assert relative_hand == pytest.approx(20.0)

    # The two definitions differ by the factor of expected margin. They must
    # not be interchanged in a claim without a unit label.
    assert points_hand != pytest.approx(relative_hand)


@pytest.mark.xfail(
    strict=True,
    reason="fm15 gap: claim_records has no unit rule. A margin change "
    "stated as a percent (relative) instead of percentage points passes "
    "validate_claim with a PASS finding.",
)
def test_planted_points_as_percent_claim_is_flagged_xfail():
    ledger = _margin_ledger([0.10, 0.10, 0.10])
    bridge = build_bridge(ledger, TICKER, METRIC, PERIOD, 0.12, REPORT_AT)
    relative_pct = bridge["surprise_pct"] * 100.0
    claim = make_claim(
        "CLM_FM15_02",
        "Operating margin surprise was %.1f%% versus expectations." % relative_pct,
        "estimate",
        ["SYN_SRC_EST_01"],
    )
    findings = validate_claim(claim)
    assert any(f.status == ValidationStatus.FAIL for f in findings)


@pytest.mark.xfail(
    strict=True,
    reason="fm15 gap: no field or module labels margin surprise units. "
    "field_dictionary has no margin field, and build_bridge output carries "
    "no unit key, so a caller cannot tell points from percent from the result.",
)
def test_bridge_output_labels_its_units():
    ledger = _margin_ledger([0.10, 0.10, 0.10])
    bridge = build_bridge(ledger, TICKER, METRIC, PERIOD, 0.12, REPORT_AT)
    assert "surprise_units" in bridge
    assert bridge["surprise_units"] in ("points", "percent")


@pytest.mark.xfail(
    strict=True,
    reason="fm15 gap: classify_surprise has no units argument, so a caller "
    "cannot say whether the threshold is in points or percent.",
)
def test_classification_is_unit_aware():
    ledger = _margin_ledger([0.10, 0.10, 0.10])
    bridge = build_bridge(ledger, TICKER, METRIC, PERIOD, 0.12, REPORT_AT)
    assert classify_surprise(bridge["surprise_abs"] * 100.0, threshold=1.0,
                             units="points") == "beat"
