"""Failure mode fm16: drivers do not sum to the revision.

A revision to a consensus number should be explained by named drivers (for
example, one analyst's change, an analyst entering or leaving the panel). The
drivers must add up to the revision. Any residual that is left over means the
explanation is missing or wrong. The detection method is to sum the drivers
on their own, compare that sum with the revision, and return the bridge to
the analyst when the residual is not zero. All data is synthetic (SYN_
prefix).

What the repo has today:
  - estimate_revisions.consensus_series gives the consensus on each date.
  - estimate_revisions.revision_breadth counts analysts up, down or unchanged.
    It skips analysts with no earlier estimate, so an entrant is not a revision.
  - reported_vs_expected_bridge.build_bridge has one driver,
    surprise_abs = reported - expected. That identity holds by construction,
    and it is not a revision bridge.

No module takes a list of named revision drivers, sums them, and reports a
residual against the consensus change. The planted case below therefore shows
a residual that the repo computes but never flags. The xfail test marks that
gap.

Planted case: analysts A and B both estimate, consensus is 11.0 at the window
start S. A revises from 10.0 to 11.0 at T1, B holds at 12.0, and a new analyst
C enters at 9.0 at T2. The consensus moves from 11.0 at S to 32/3 (about
10.667) at T2, a change of -1/3. The
revision-only driver (A's change divided by the new panel size of 3) is +1/3.
The residual is -2/3, and it comes from the entrant and the panel-size change.
"""

from datetime import datetime, timedelta, timezone

import pytest

import as_of.estimate_revisions as estimate_revisions
from as_of.core import EstimateRecord
from as_of.estimate_revisions import consensus_series, revision_breadth

T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
S = T0 + timedelta(days=5)   # window start, before A revises
T1 = T0 + timedelta(days=10)  # A revises to 11.0
T2 = T0 + timedelta(days=20)  # C enters at 9.0
TICKER = "SYN_T16"
METRIC = "eps"
PERIOD = "2026Q2"


def _rec(i, analyst, value, knowledge_at):
    return EstimateRecord(
        estimate_id="SYN_EST_FM16_%d" % i,
        ticker=TICKER,
        metric=METRIC,
        period=PERIOD,
        analyst_id=analyst,
        value=value,
        knowledge_at=knowledge_at,
        source_id="SYN_SRC_EST_16",
    )


def _planted_ledger():
    return [
        _rec(1, "SYN_AN_A", 10.0, T0),
        _rec(2, "SYN_AN_B", 12.0, T0),
        _rec(3, "SYN_AN_A", 11.0, T1),  # A revises up by 1.0
        _rec(4, "SYN_AN_C", 9.0, T2),   # C enters the panel at T2
    ]


def test_building_blocks_give_the_hand_values_for_the_planted_case():
    ledger = _planted_ledger()
    s_value, t2_value = consensus_series(ledger, TICKER, METRIC, PERIOD, [S, T2])
    assert s_value == pytest.approx(11.0)
    assert t2_value == pytest.approx(32.0 / 3.0)

    # Breadth over (S, T2]: A moved from 10.0 to 11.0, so it is one up. B
    # published nothing new. C is an entrant with no estimate at S, so it is
    # skipped and is not counted as a revision.
    counts = revision_breadth(ledger, TICKER, METRIC, PERIOD, S, T2)
    assert counts == {"up": 1, "down": 0, "unchanged": 0}


def test_planted_residual_is_present_in_the_numbers_the_repo_computes():
    ledger = _planted_ledger()
    s_value, t2_value = consensus_series(ledger, TICKER, METRIC, PERIOD, [S, T2])
    revision = t2_value - s_value
    assert revision == pytest.approx(-1.0 / 3.0)

    # Naive revision-only driver: A's change, divided by the panel size at T2.
    revision_driver = (11.0 - 10.0) / 3.0
    assert revision_driver == pytest.approx(1.0 / 3.0)

    residual = revision - revision_driver
    assert residual == pytest.approx(-2.0 / 3.0)
    assert residual != pytest.approx(0.0)


@pytest.mark.xfail(
    strict=True,
    reason="fm16 gap: no module decomposes a consensus revision into named "
    "drivers, sums them, or reports a residual. estimate_revisions exposes "
    "consensus_series and revision_breadth only, and "
    "reported_vs_expected_bridge has a single surprise driver. The planted "
    "residual of -2/3 is therefore never flagged or returned as a bridge.",
)
def test_revision_bridge_drivers_sum_to_revision_with_zero_residual():
    ledger = _planted_ledger()
    assert hasattr(estimate_revisions, "driver_bridge"), (
        "no driver-level revision bridge exists in estimate_revisions"
    )
    bridge = estimate_revisions.driver_bridge(ledger, TICKER, METRIC, PERIOD, S, T2)
    driver_sum = sum(item["amount"] for item in bridge["drivers"])
    assert driver_sum == pytest.approx(bridge["revision"])
    assert bridge["residual"] == pytest.approx(0.0)
