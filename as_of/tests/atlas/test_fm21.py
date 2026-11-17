"""Failure mode fm21: beta differs across tools.

Two tools report different betas for the same asset because the denominator,
the missing-row handling or the sample cutoff differs. The detection procedure
is to compare the exact sample pairs and formulas each tool used, and to align
them before a result is accepted. All data is synthetic (SYN_ prefix) and
seeded, and no network is used.

What the repo has today:
  - factor_exposure.reproduce_exposures re-estimates betas by OLS. It raises
    AsOfError on a row-count mismatch between asset and factor returns and on
    any NaN or infinite value. So a silently shortened or padded sample cannot
    pass through this path.
  - factor_exposure.reproduce_exposures takes add_intercept as an explicit
    argument. A tool that fits without an intercept therefore gives a
    different beta, and this is visible when the reproduction is compared.
  - factor_exposure.compare_reported compares a reported exposure with a
    recomputed one and returns FAIL when the gap exceeds tol. It detects that
    two betas differ. It does not say why.
  - No module records the sample window, the intercept convention or the
    denominator that each tool used, so no module can align two tools' sample
    pairs. The diagnosis half of fm21 is therefore a gap, marked xfail below.

Planted case: a single factor and a single asset with a nonzero mean. The
"reference tool" fits with an intercept on all rows. The "other tool" fits
without an intercept on the same rows and reports that beta. The two betas
differ, and compare_reported must FAIL on them.
"""

import numpy as np
import pytest

from as_of.core import AsOfError, ValidationStatus
from as_of.factor_exposure import compare_reported, reproduce_exposures

SEED = 21
T = 120
TOL = 1e-6


def _planted_returns():
    rng = np.random.default_rng(SEED)
    factor = rng.normal(0.0, 0.01, size=(T, 1))
    # A nonzero mean in the asset makes the intercept matter for the beta.
    asset = 0.002 + 1.3 * factor[:, 0] + rng.normal(0.0, 0.004, size=T)
    return asset.reshape(T, 1), factor


def _ref_beta():
    asset, factor = _planted_returns()
    out = reproduce_exposures(asset, factor, add_intercept=True)
    return float(out["betas"][0, 0])


def _other_tool_beta():
    # The other tool used no intercept on the same rows.
    asset, factor = _planted_returns()
    out = reproduce_exposures(asset, factor, add_intercept=False)
    return float(out["betas"][0, 0])


def test_fm21_intercept_convention_gap_is_flagged_by_compare_reported():
    ref = _ref_beta()
    other = _other_tool_beta()
    assert abs(ref - other) > TOL, "planted convention must move the beta"
    findings = compare_reported(
        {"SYN_A": other}, {"SYN_A": ref}, tol=TOL
    )
    assert len(findings) == 1
    assert findings[0].status is ValidationStatus.FAIL
    assert findings[0].subject == "SYN_A"


def test_fm21_matching_tools_pass_compare_reported():
    ref = _ref_beta()
    findings = compare_reported({"SYN_A": ref}, {"SYN_A": ref}, tol=TOL)
    assert [f.status for f in findings] == [ValidationStatus.PASS]


def test_fm21_shortened_sample_is_blocked_not_silently_aligned():
    # A tool that cut the sample to a shorter window must not be silently
    # compared on a different row set. The row-count check must raise.
    asset, factor = _planted_returns()
    with pytest.raises(AsOfError) as excinfo:
        reproduce_exposures(asset[:-5], factor, add_intercept=True)
    assert "row count mismatch" in str(excinfo.value)


def test_fm21_missing_row_is_blocked_not_dropped():
    # A missing observation must stop the estimate, not be dropped, because
    # dropping one row silently changes the sample and the denominator.
    asset, factor = _planted_returns()
    asset = asset.copy()
    asset[37, 0] = np.nan
    with pytest.raises(AsOfError) as excinfo:
        reproduce_exposures(asset, factor, add_intercept=True)
    assert "NaN" in str(excinfo.value)


def test_fm21_sample_pair_alignment_is_recorded_and_checked():
    # The full fm21 check needs each tool's sample pairs and formula, then an
    # alignment step that refuses to accept a beta whose sample differs. No
    # module in the as_of package does this today, so the gap is reported.
    pytest.xfail(
        "fm21 gap: no module records the sample window, intercept convention or "
        "denominator used by each tool, so two tools' sample pairs cannot be "
        "aligned before a beta is accepted."
    )
