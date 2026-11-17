"""Tests for as_of.factor_exposure. All data is synthetic and seeded."""

import numpy as np
import pytest

from as_of.core import AsOfError, ValidationStatus
from as_of.factor_exposure import compare_reported, reproduce_exposures


def _make_panel(T=200, K=2, N=3, seed=7, noise=0.0):
    rng = np.random.default_rng(seed)
    F = rng.standard_normal((T, K))
    true_betas = rng.uniform(-1.5, 1.5, size=(N, K))
    true_alpha = rng.uniform(-0.2, 0.2, size=N)
    eps = noise * rng.standard_normal((T, N))
    Y = true_alpha[None, :] + F @ true_betas.T + eps
    return Y, F, true_betas, true_alpha


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------

def test_noise_free_data_recovers_true_betas_within_1e8():
    Y, F, true_betas, true_alpha = _make_panel(noise=0.0)
    out = reproduce_exposures(Y, F, add_intercept=True)
    assert np.max(np.abs(out["betas"] - true_betas)) <= 1e-8
    assert np.max(np.abs(out["intercept"] - true_alpha)) <= 1e-8


def test_r2_equals_one_for_noise_free_data():
    Y, F, _, _ = _make_panel(noise=0.0)
    out = reproduce_exposures(Y, F, add_intercept=True)
    assert np.allclose(out["r2"], 1.0, atol=1e-10)


def test_mismatched_row_counts_raise_asof_error():
    Y, F, _, _ = _make_panel(T=100)
    with pytest.raises(AsOfError, match="row count mismatch"):
        reproduce_exposures(Y, F[:90], add_intercept=True)


def test_compare_reported_flags_difference_larger_than_tol():
    findings = compare_reported({"SYN_A": 1.0}, {"SYN_A": 1.5}, tol=0.1)
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].subject == "SYN_A"


def test_compare_reported_passes_difference_within_tol():
    findings = compare_reported({"SYN_A": 1.0}, {"SYN_A": 1.05}, tol=0.1)
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.PASS


# ---------------------------------------------------------------------------
# Edge cases: reproduce_exposures
# ---------------------------------------------------------------------------

def test_no_intercept_recovers_betas_and_zero_intercept():
    rng = np.random.default_rng(11)
    F = rng.standard_normal((150, 2))
    B = np.array([[0.7, -0.3], [1.1, 0.4]])
    Y = F @ B.T
    out = reproduce_exposures(Y, F, add_intercept=False)
    assert np.max(np.abs(out["betas"] - B)) <= 1e-8
    assert np.all(out["intercept"] == 0.0)
    assert np.allclose(out["r2"], 1.0, atol=1e-10)


def test_output_shapes():
    Y, F, _, _ = _make_panel(T=120, K=3, N=4, noise=0.1)
    out = reproduce_exposures(Y, F)
    assert out["betas"].shape == (4, 3)
    assert out["intercept"].shape == (4,)
    assert out["r2"].shape == (4,)
    assert out["resid_vol"].shape == (4,)


def test_resid_vol_near_zero_for_noise_free_data():
    Y, F, _, _ = _make_panel(noise=0.0)
    out = reproduce_exposures(Y, F)
    assert np.all(out["resid_vol"] < 1e-8)


def test_resid_vol_uses_dof_correction():
    Y, F, _, _ = _make_panel(T=60, K=2, N=2, noise=0.5, seed=3)
    out = reproduce_exposures(Y, F, add_intercept=True)
    T, p = 60, 3
    design = np.column_stack([np.ones(T), F])
    coef = np.linalg.lstsq(design, Y, rcond=None)[0]
    resid = Y - design @ coef
    expected = np.sqrt(np.sum(resid ** 2, axis=0) / float(T - p))
    assert np.allclose(out["resid_vol"], expected, rtol=1e-10)


def test_r2_is_nan_for_constant_asset():
    Y, F, _, _ = _make_panel(noise=0.2)
    Y[:, 0] = 0.05
    out = reproduce_exposures(Y, F, add_intercept=True)
    assert np.isnan(out["r2"][0])
    assert np.isfinite(out["r2"][1])


def test_rank_deficient_factors_raise():
    rng = np.random.default_rng(5)
    f1 = rng.standard_normal(80)
    F = np.column_stack([f1, 2.0 * f1])
    Y = rng.standard_normal((80, 2))
    with pytest.raises(AsOfError, match="rank deficient"):
        reproduce_exposures(Y, F, add_intercept=True)


def test_too_few_rows_for_parameter_count_raises():
    rng = np.random.default_rng(9)
    F = rng.standard_normal((3, 2))
    Y = rng.standard_normal((3, 2))
    with pytest.raises(AsOfError, match="need more rows"):
        reproduce_exposures(Y, F, add_intercept=True)


def test_non_finite_values_raise():
    Y, F, _, _ = _make_panel(noise=0.1)
    Y[5, 1] = np.nan
    with pytest.raises(AsOfError, match="NaN or infinite"):
        reproduce_exposures(Y, F)


def test_infinite_factor_values_raise():
    Y, F, _, _ = _make_panel(noise=0.1)
    F[2, 0] = np.inf
    with pytest.raises(AsOfError, match="NaN or infinite"):
        reproduce_exposures(Y, F)


def test_non_2d_input_raises():
    Y, F, _, _ = _make_panel(noise=0.1)
    with pytest.raises(AsOfError, match="2-dimensional"):
        reproduce_exposures(Y[:, 0], F)


def test_non_array_input_raises():
    Y, F, _, _ = _make_panel(noise=0.1)
    with pytest.raises(AsOfError, match="numpy array"):
        reproduce_exposures(Y.tolist(), F)


def test_zero_factor_columns_raise():
    Y = np.zeros((10, 2))
    F = np.zeros((10, 0))
    with pytest.raises(AsOfError):
        reproduce_exposures(Y, F)


def test_non_bool_intercept_flag_raises():
    Y, F, _, _ = _make_panel(noise=0.1)
    with pytest.raises(AsOfError, match="add_intercept must be a bool"):
        reproduce_exposures(Y, F, add_intercept=1)


# ---------------------------------------------------------------------------
# Edge cases: compare_reported
# ---------------------------------------------------------------------------

def test_compare_reported_difference_exactly_at_tol_passes():
    findings = compare_reported({"SYN_A": 1.0}, {"SYN_A": 1.25}, tol=0.25)
    assert findings[0].status == ValidationStatus.PASS


def test_compare_reported_nan_difference_fails():
    findings = compare_reported({"SYN_A": float("nan")}, {"SYN_A": 1.0}, tol=0.1)
    assert findings[0].status == ValidationStatus.FAIL


def test_compare_reported_key_only_in_one_side_warns():
    findings = compare_reported(
        {"SYN_A": 1.0, "SYN_B": 2.0},
        {"SYN_A": 1.0, "SYN_C": 3.0},
        tol=0.1,
    )
    by_subject = {f.subject: f for f in findings}
    assert by_subject["SYN_B"].status == ValidationStatus.WARN
    assert by_subject["SYN_C"].status == ValidationStatus.WARN
    assert by_subject["SYN_A"].status == ValidationStatus.PASS


def test_compare_reported_findings_sorted_by_key():
    findings = compare_reported(
        {"SYN_C": 1.0, "SYN_A": 1.0, "SYN_B": 1.0},
        {"SYN_C": 1.0, "SYN_A": 1.0, "SYN_B": 1.0},
        tol=0.0,
    )
    assert [f.subject for f in findings] == ["SYN_A", "SYN_B", "SYN_C"]


def test_compare_reported_negative_tol_raises():
    with pytest.raises(AsOfError, match="tol"):
        compare_reported({"SYN_A": 1.0}, {"SYN_A": 1.0}, tol=-0.1)


def test_compare_reported_non_finite_tol_raises():
    with pytest.raises(AsOfError, match="tol"):
        compare_reported({"SYN_A": 1.0}, {"SYN_A": 1.0}, tol=float("inf"))


def test_compare_reported_empty_inputs_return_no_findings():
    assert compare_reported({}, {}, tol=0.1) == []
