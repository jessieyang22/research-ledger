"""Failure mode fm19: factor row after cutoff is included.

The availability date of a factor row is ignored, so a row that was not yet
known at the decision time enters the factor-exposure calculation. Detection
counts eligible rows by their availability timestamp against the cutoff,
excludes the late rows, and reruns the dependent calculation. All data is
synthetic (SYN_ prefix).

Planted failure: a synthetic factor-return panel of 36 daily rows. The last
three rows are "late": their release_at is before the decision time, but their
ingest_at (when the row entered our store) is after it. release_at alone would
make them look usable, so the test also checks the ingest-first rule. The late
rows carry a large factor shock, so including them visibly moves the betas.

Detection points checked:
  - availability_cutoff.cutoff_report and filter_usable count and drop the
    late rows. The release fallback is not used because ingest_at is present.
  - Rerunning factor_exposure.reproduce_exposures on the eligible rows gives the
    betas computed from the clean rows. Rerunning it on all rows does not.

Gap, marked xfail:
  - factor_exposure.reproduce_exposures takes bare numpy arrays with no clocks
    or decision time, and no workflow applies availability_cutoff before
    estimation. Nothing blocks a late row from entering an exposure run.
"""

import inspect
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from as_of import availability_cutoff
from as_of.availability_cutoff import cutoff_report, filter_usable
from as_of.core import ClockSet
from as_of.factor_exposure import reproduce_exposures

N_ROWS = 36
N_LATE = 3
N_FACTORS = 2
BASE_DAY = datetime(2026, 1, 1, tzinfo=timezone.utc)
DECISION_AT = BASE_DAY + timedelta(days=N_ROWS - N_LATE)  # first late row's day
TRUE_BETAS = np.array([[1.2, -0.4], [0.8, 0.5]])  # 2 assets x 2 factors
TRUE_INTERCEPT = np.array([0.0002, -0.0001])


def _factor_panel():
    """Return (ids, clocks, factors, asset_returns) for the synthetic panel.

    Rows 0..N_ROWS-N_LATE-1 are known before DECISION_AT. The last N_LATE rows
    are released before DECISION_AT but ingested two days after it.
    """
    rng = np.random.RandomState(20260101)
    factors = rng.normal(0.0, 0.01, size=(N_ROWS, N_FACTORS))
    late_start = N_ROWS - N_LATE
    factors[late_start:, 0] += 0.05  # planted shock in the late rows
    noise = rng.normal(0.0, 0.0005, size=(N_ROWS, 2))
    asset_returns = factors @ TRUE_BETAS.T + TRUE_INTERCEPT + noise

    ids = []
    clocks = []
    for i in range(N_ROWS):
        day = BASE_DAY + timedelta(days=i)
        ids.append("SYN_FACTOR_ROW_%02d" % i)
        if i < late_start:
            clocks.append(
                ClockSet(
                    event_at=day,
                    release_at=day + timedelta(hours=6),
                    ingest_at=day + timedelta(hours=8),
                )
            )
        else:
            clocks.append(
                ClockSet(
                    event_at=day,
                    release_at=DECISION_AT - timedelta(hours=12),
                    ingest_at=DECISION_AT + timedelta(days=2),
                )
            )
    return ids, clocks, factors, asset_returns


def _eligible_mask(clocks):
    return np.array([availability_cutoff.usable_at(cs, DECISION_AT) for cs in clocks])


def test_late_factor_rows_are_counted_and_dropped_by_ingest_clock():
    ids, clocks, _factors, _returns = _factor_panel()
    records = list(zip(ids, clocks))

    report = cutoff_report(records, DECISION_AT)
    assert report["usable"] == N_ROWS - N_LATE
    assert report["unusable"] == N_LATE
    assert report["no_clock"] == 0
    # Ingest time is set on every row, so release fallback must not be used.
    assert report["fallback_to_release"] == 0
    assert report["usable"] + report["unusable"] + report["no_clock"] == N_ROWS

    kept = filter_usable(records, DECISION_AT)
    assert kept == ids[: N_ROWS - N_LATE]
    for late_id in ids[N_ROWS - N_LATE :]:
        assert late_id not in kept


def test_late_rows_pass_a_release_only_check_but_fail_the_ingest_rule():
    # The trap: release_at is before the decision time, so a release-only
    # filter would keep these rows. The ingest-first rule must drop them.
    _ids, clocks, _factors, _returns = _factor_panel()
    late = clocks[N_ROWS - N_LATE :]
    for cs in late:
        assert cs.release_at <= DECISION_AT
        assert cs.ingest_at > DECISION_AT
        assert availability_cutoff.usable_at(cs, DECISION_AT) is False


def test_rerunning_exposures_on_eligible_rows_matches_clean_estimate():
    ids, clocks, factors, returns = _factor_panel()
    mask = _eligible_mask(clocks)
    assert int(mask.sum()) == N_ROWS - N_LATE

    clean = reproduce_exposures(returns[mask], factors[mask], add_intercept=True)
    # Clean estimate uses only the rows that were known at the cutoff.
    assert clean["betas"].shape == (2, N_FACTORS)
    assert np.allclose(clean["betas"], TRUE_BETAS, atol=0.05)


def test_including_late_rows_changes_the_betas_so_the_plant_matters():
    ids, clocks, factors, returns = _factor_panel()
    mask = _eligible_mask(clocks)

    clean = reproduce_exposures(returns[mask], factors[mask], add_intercept=True)
    contaminated = reproduce_exposures(returns, factors, add_intercept=True)

    shift = np.max(np.abs(contaminated["betas"] - clean["betas"]))
    # The late rows are consistent with the true model, so OLS absorbs most
    # of the shock. The shift is small but well above float noise.
    assert shift > 1e-4, "planted late rows must move the betas measurably"


def test_detection_recovers_clean_betas_from_contaminated_run():
    ids, clocks, factors, returns = _factor_panel()
    records = list(zip(ids, clocks))
    kept_ids = set(filter_usable(records, DECISION_AT))
    keep = np.array([rid in kept_ids for rid in ids])

    clean = reproduce_exposures(returns[keep], factors[keep], add_intercept=True)
    direct = reproduce_exposures(
        returns[: N_ROWS - N_LATE], factors[: N_ROWS - N_LATE], add_intercept=True
    )
    assert np.allclose(clean["betas"], direct["betas"], rtol=0, atol=1e-12)


@pytest.mark.xfail(
    strict=True,
    reason="fm19 gap: factor_exposure.reproduce_exposures takes bare arrays with "
    "no clocks or decision time, and no workflow applies availability_cutoff "
    "before estimation, so a late factor row enters the exposure run silently.",
)
def test_exposure_entry_point_is_gated_by_availability():
    params = inspect.signature(reproduce_exposures).parameters
    assert "decision_at" in params or "clocks" in params
