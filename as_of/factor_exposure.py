"""Factor exposure reproduction by ordinary least squares.

This module re-estimates linear factor exposures (betas) for a panel of asset
returns and compares the recomputed values with exposures that were reported
elsewhere, for example by a vendor or an internal risk file.

The workflow follows the as-of research-state idea of reproducing a number
from its inputs before trusting it. All data handled here must be synthetic.

Conventions:
    * asset_returns is a T x N array (rows are periods, columns are assets).
    * factor_returns is a T x K array with the same row count.
    * Estimation uses numpy.linalg.lstsq on the design matrix [1, F] when an
      intercept is requested, or F alone otherwise.
    * r2 is 1 - SSR / SST per asset. SST is centred on the asset mean when an
      intercept is used. It is NaN when SST is zero.
    * resid_vol is the residual standard deviation with the degrees of freedom
      correction sqrt(SSR / (T - p)), where p is the number of estimated
      coefficients per asset. Values are per period, not annualised.

Only numpy and as_of.core are used. There is no network access and no order
or trading logic.
"""

from typing import Dict, List

import numpy as np

from as_of.core import AsOfError, Finding, ValidationStatus, require


_CHECK_ID_RECON = "factor_exposure.reproduce"
_CHECK_ID_COMPARE = "factor_exposure.compare"

# Nonzero inputs smaller than this in magnitude could underflow when squared
# (residuals and sums of squares are squared), which would silently turn
# resid_vol into 0 and r2 into NaN. Real return series are far above this.
_MIN_NONZERO_MAGNITUDE = 1e-100


def _as_2d_float(name: str, arr: np.ndarray) -> np.ndarray:
    """Return arr as a 2D float64 array or raise AsOfError."""
    require(isinstance(arr, np.ndarray), "%s must be a numpy array" % name)
    require(arr.ndim == 2, "%s must be 2-dimensional, got ndim=%d" % (name, arr.ndim))
    require(
        arr.dtype.kind in ("i", "u", "f"),
        "%s must hold real integer or float values, got dtype %s" % (name, arr.dtype),
    )
    out = np.asarray(arr, dtype=np.float64)
    require(np.all(np.isfinite(out)), "%s contains NaN or infinite values" % name)
    nonzero = np.abs(out[out != 0.0])
    require(
        nonzero.size == 0 or float(nonzero.min()) >= _MIN_NONZERO_MAGNITUDE,
        "%s has nonzero values below %g in magnitude; squared sums would underflow"
        % (name, _MIN_NONZERO_MAGNITUDE),
    )
    return out


def reproduce_exposures(
    asset_returns: np.ndarray,
    factor_returns: np.ndarray,
    add_intercept: bool = True,
) -> Dict[str, np.ndarray]:
    """Estimate factor betas for each asset by ordinary least squares.

    Args:
        asset_returns: T x N array of asset returns.
        factor_returns: T x K array of factor returns. T must match
            asset_returns.
        add_intercept: when True, a constant column is added to the design.

    Returns:
        A dict with these keys:
            betas: N x K array of factor exposures.
            intercept: length N array. Zeros when add_intercept is False.
            r2: length N array of coefficients of determination.
            resid_vol: length N array of residual standard deviations.

    Raises:
        AsOfError: on bad shapes, mismatched row counts, non-finite inputs,
            a rank-deficient design, or too few rows for the parameter count.
    """
    y = _as_2d_float("asset_returns", asset_returns)
    f = _as_2d_float("factor_returns", factor_returns)

    T, N = y.shape
    T_f, K = f.shape
    require(
        T == T_f,
        "row count mismatch: asset_returns has %d rows, factor_returns has %d"
        % (T, T_f),
    )
    require(N >= 1, "asset_returns must have at least one asset column")
    require(K >= 1, "factor_returns must have at least one factor column")
    require(isinstance(add_intercept, bool), "add_intercept must be a bool")

    p = K + (1 if add_intercept else 0)
    require(T > p, "need more rows (%d) than parameters (%d)" % (T, p))

    if add_intercept:
        design = np.column_stack([np.ones(T), f])
    else:
        design = f

    require(
        np.linalg.matrix_rank(design) == p,
        "design matrix is rank deficient; factor returns may be collinear",
    )

    coef, _, _, _ = np.linalg.lstsq(design, y, rcond=None)  # p x N
    fitted = design @ coef
    resid = y - fitted
    require(
        np.all(np.isfinite(coef)) and np.all(np.isfinite(resid)),
        "estimation produced non-finite values; input magnitudes are too large",
    )

    if add_intercept:
        intercept = coef[0].copy()
        betas = coef[1:].T.copy()
    else:
        intercept = np.zeros(N, dtype=np.float64)
        betas = coef.T.copy()

    ssr = np.sum(resid ** 2, axis=0)
    if add_intercept:
        centred = y - y.mean(axis=0, keepdims=True)
        sst = np.sum(centred ** 2, axis=0)
    else:
        sst = np.sum(y ** 2, axis=0)

    # Centring a constant series leaves floating-point residue in sst, so
    # treat sst as zero relative to the asset's raw scale rather than exactly 0.
    scale = np.sum(y ** 2, axis=0)
    sst_is_zero = sst <= np.finfo(np.float64).eps * 100.0 * scale
    with np.errstate(divide="ignore", invalid="ignore"):
        r2 = np.where(
            ~sst_is_zero,
            1.0 - ssr / np.where(~sst_is_zero, sst, 1.0),
            np.nan,
        )

    resid_vol = np.sqrt(ssr / float(T - p))
    require(
        bool(np.all(np.isfinite(resid_vol))),
        "resid_vol overflowed; input magnitudes are too large",
    )

    return {
        "betas": betas,
        "intercept": intercept,
        "r2": np.asarray(r2, dtype=np.float64),
        "resid_vol": resid_vol,
    }


def compare_reported(
    reported: Dict[str, float],
    recomputed: Dict[str, float],
    tol: float,
) -> List[Finding]:
    """Compare reported exposures with recomputed exposures.

    Each key present in both dicts gets one Finding. The status is PASS when
    the absolute difference is at most tol and FAIL otherwise. A non-finite
    difference is a FAIL. A key present in only one dict gets a WARN finding.

    Args:
        reported: exposure values taken from the reported source.
        recomputed: exposure values from reproduce_exposures or similar.
        tol: non-negative absolute tolerance.

    Returns:
        Findings sorted by key.

    Raises:
        AsOfError: when tol is negative or not finite.
    """
    require(isinstance(reported, dict), "reported must be a dict")
    require(isinstance(recomputed, dict), "recomputed must be a dict")
    require(
        isinstance(tol, (int, float, np.integer, np.floating))
        and not isinstance(tol, (bool, np.bool_))
        and np.isfinite(float(tol))
        and float(tol) >= 0.0,
        "tol must be a finite non-negative number, got %r" % (tol,),
    )
    tol_f = float(tol)

    def _as_value(source: str, key, value) -> float:
        require(
            isinstance(value, (int, float, np.integer, np.floating))
            and not isinstance(value, (bool, np.bool_)),
            "%s value for %s must be a real number, got %r" % (source, str(key), value),
        )
        return float(value)

    findings: List[Finding] = []
    for key in sorted(set(reported) | set(recomputed), key=str):
        if key not in recomputed:
            findings.append(
                Finding(
                    check_id=_CHECK_ID_COMPARE,
                    status=ValidationStatus.WARN,
                    message="reported exposure has no recomputed counterpart",
                    subject=str(key),
                )
            )
            continue
        if key not in reported:
            findings.append(
                Finding(
                    check_id=_CHECK_ID_COMPARE,
                    status=ValidationStatus.WARN,
                    message="recomputed exposure has no reported counterpart",
                    subject=str(key),
                )
            )
            continue

        rep = _as_value("reported", key, reported[key])
        rec = _as_value("recomputed", key, recomputed[key])
        diff = abs(rep - rec)
        if not np.isfinite(diff):
            findings.append(
                Finding(
                    check_id=_CHECK_ID_COMPARE,
                    status=ValidationStatus.FAIL,
                    message="non-finite value: reported=%r recomputed=%r" % (rep, rec),
                    subject=str(key),
                )
            )
        elif diff > tol_f:
            findings.append(
                Finding(
                    check_id=_CHECK_ID_COMPARE,
                    status=ValidationStatus.FAIL,
                    message="difference %.6g exceeds tol %.6g (reported=%.6g recomputed=%.6g)"
                    % (diff, tol_f, rep, rec),
                    subject=str(key),
                )
            )
        else:
            findings.append(
                Finding(
                    check_id=_CHECK_ID_COMPARE,
                    status=ValidationStatus.PASS,
                    message="difference %.6g within tol %.6g" % (diff, tol_f),
                    subject=str(key),
                )
            )
    return findings
