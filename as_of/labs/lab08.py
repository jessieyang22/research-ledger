"""Lab 08: tie a synthetic portfolio snapshot and its factor exposure (synthetic data only).

What this lab does, in order:

1. Writes a synthetic snapshot under as_of/labs/results/lab08_inputs/:
   positions.csv (four stable security IDs, SYN_SEC001 to SYN_SEC004), prices.csv
   (a prior-day row and an as-of row for each security) and factor_rows.csv
   (seven factor rows with release and ingest times, in mixed units).
   Two factor rows were ingested after the decision time, and one of them has an
   earlier return date than every eligible row, so the lab tests the ingest rule
   and not only the return date.
2. Values every position through as_of.price_hard_fail.require_price, matched by
   security ID. A missing, blank, NaN or non-positive price stops the run with
   HardFailError. Nothing is dropped, filled or treated as zero. Signed shares
   times price give each market value. Positive values are summed for long,
   negative values for short, absolute values for gross and signed values for net.
3. Keeps only the factor rows that as_of.availability_cutoff says were ingested
   by the decision time. Percent values are divided by 100 and decimal values are
   used as they are. The unit of each value is read from its own column.
4. Computes beta as the sample covariance divided by the sample variance, both with
   n - 1, over the same eligible rows. It cross-checks the slope with
   as_of.factor_exposure.reproduce_exposures (OLS with an intercept).
5. Runs a verifier. It reads the CSV files with the standard csv module
   only. It recomputes long, short, gross, net, beta and row count, and it reports
   every security whose price is missing from the file. It does not import any
   as_of module.
6. Checks the live totals against hand values: market values 5,000, 6,000,
   -3,000 and -2,000, long 11,000, short -5,000, gross 16,000, net 6,000, five
   eligible factor rows, and beta 0.5. It also checks the eligible return dates
   against the hand list, checks the input files against SHA-256 values pinned in
   the script, and checks the factor metadata against the expected constants.
7. Planted failure A: writes a disposable price file under
   as_of/labs/results/lab08_disposable/missing_price/ with the as-of price for
   SYN_SEC004 removed. The prior-day row stays, so a forward-fill would hide the
   gap. The calculation must raise HardFailError naming SYN_SEC004, and the
   verifier must report exactly that name as missing.
8. Planted failure B: writes a disposable positions file under
   as_of/labs/results/lab08_disposable/sign_flip/ with the short SYN_SEC003 flipped
   from -100 to +100 shares. Net must move by 6,000 (from 6,000 to 12,000), gross
   must stay at 16,000, and the verifier must agree.
9. Checks that the factor rule matters: beta over all seven rows must differ from
   the eligible-row beta by more than the tolerance.
10. Writes as_of/labs/results/lab08.json with a PASS or FAIL for each check, the
    factor metadata (definition, source, vintage, retrieval time, observation
    counts, tolerance), input hashes and the limits.

Limits, stated in the JSON as well. A PASS shows that the frozen synthetic export
ties to its own inputs and that the verifier and the modules agree. It does not
show that any position, price or factor value is correct, complete or entitled.
For live use, the totals must be reproduced in the authoritative workbook or
risk system, which owns identifiers, corporate actions, FX, stale prices and data
rights. This sidecar explains a frozen export. It does not replace the live
control owner. Public factor data from a research library does not establish a
live entitlement or a production risk calculation. All values here are USD
synthetic values with no FX.

Topic: portfolio snapshot tie-out and factor exposure.

Python 3.9 syntax only. Only as_of.core is imported statically. Every other
as_of piece is loaded with core.component inside a function body. No network, no
subprocess, no orders, no git.
"""

import csv
import json
import math
import os
import sys
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

LAB_DIR: str = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT: str = os.path.dirname(os.path.dirname(LAB_DIR))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from as_of.core import AsOfError, PositionRecord, PriceRecord, component, parse_ts, require  # noqa: E402


LAB_ID: str = "lab08"
TITLE: str = "Tie a portfolio snapshot and factor exposure"
RESULTS_DIR: str = os.path.join(LAB_DIR, "results")
INPUT_DIR: str = os.path.join(RESULTS_DIR, "lab08_inputs")
DISPOSABLE_DIR: str = os.path.join(RESULTS_DIR, "lab08_disposable")
RESULTS_PATH: str = os.path.join(RESULTS_DIR, "lab08.json")

TOL: float = 1e-9
BETA_SENSITIVITY_MIN: float = 1e-6
DECISION_TEXT: str = "2026-03-31T23:59:59Z"
AS_OF_TEXT: str = "2026-03-31"
PRIOR_TEXT: str = "2026-03-30"
BOOK_LABEL: str = "SYN_BOOK"
PRICE_SOURCE: str = "SYN_LAB08_PX"
FACTOR_ID: str = "SYN_FACTOR_MKT"
FACTOR_DEFINITION: str = "Synthetic market factor: one-day simple return, reported in percent"
FACTOR_SOURCE: str = "SYN_LAB08_SRC"
FACTOR_VINTAGE: str = "SYN_VINTAGE_V1"
RETRIEVED_AT: str = "2026-04-09T00:00:00Z"
MISSING_ID: str = "SYN_SEC004"
FLIP_ID: str = "SYN_SEC003"

POSITIONS_FIELDS: Tuple[str, ...] = ("book", "security_id", "quantity", "as_of")
PRICES_FIELDS: Tuple[str, ...] = ("security_id", "as_of", "close", "source_id")
FACTOR_FIELDS: Tuple[str, ...] = (
    "return_date",
    "factor_id",
    "factor_definition",
    "factor_return",
    "factor_unit",
    "portfolio_return",
    "portfolio_unit",
    "release_at",
    "ingest_at",
    "source_id",
    "vintage",
    "retrieved_at",
)

# Hand-set synthetic book: (security_id, quantity, as-of close, prior-day close).
SECURITIES: Tuple[Tuple[str, int, float, float], ...] = (
    ("SYN_SEC001", 100, 50.0, 49.0),
    ("SYN_SEC002", 200, 30.0, 29.5),
    ("SYN_SEC003", -100, 30.0, 31.0),
    ("SYN_SEC004", -50, 40.0, 41.0),
)

# Hand recalculation, written before any code runs. Market values by name are
# 100 x 50, 200 x 30, -100 x 30 and -50 x 40.
HAND_MARKET_VALUES: Dict[str, float] = {
    "SYN_SEC001": 5000.0,
    "SYN_SEC002": 6000.0,
    "SYN_SEC003": -3000.0,
    "SYN_SEC004": -2000.0,
}
HAND_TOTALS: Dict[str, float] = {
    "long": 11000.0,
    "short": -5000.0,
    "gross": 16000.0,
    "net": 6000.0,
    "beta": 0.5,
}
HAND_ROW_COUNT: int = 5
HAND_FLIP_TOTALS: Dict[str, float] = {"long": 14000.0, "short": -2000.0, "gross": 16000.0, "net": 12000.0}
HAND_ELIGIBLE_FACTOR_DEC: Tuple[float, ...] = (0.01, -0.02, 0.03, 0.0, -0.01)
HAND_ELIGIBLE_PORT_DEC: Tuple[float, ...] = (0.005, -0.01, 0.015, 0.0, -0.005)
HAND_EXCLUDED_DATES: Tuple[str, ...] = ("2026-03-02", "2026-03-10")
HAND_ELIGIBLE_DATES: Tuple[str, ...] = ("2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06", "2026-03-09")
# Pinned SHA-256 of the frozen input files, computed once from the fixed content
# above. The writer rewrites these files on every run, so a hash check against a
# pinned value is the only thing that shows the inputs were not changed.
EXPECTED_INPUT_SHA256: Dict[str, str] = {
    "factors": "4f64afd498de81d7c5554b2f70f8029f8f38ce08d882d1a6ef43d320d5c11982",
    "positions": "4ba2c06b9507b4876083a0e7b0977569b91f660058f6e8adb079e5e4ff278591",
    "prices": "300aa80461e1a030b9fa440d5c3208cda723c2f62697e979452412b92feabf45",
}

# Factor rows: (return_date, factor_return, factor_unit, portfolio_return,
# portfolio_unit, release_at, ingest_at). The portfolio return is exactly half of
# the factor on eligible rows, so the true beta is 0.5. The two excluded rows
# carry values that would move beta if they were used.
FACTOR_ROWS: Tuple[Tuple[str, str, str, str, str, str, str], ...] = (
    ("2026-03-02", "5.0", "percent", "0.09", "decimal", "2026-04-02T18:00:00Z", "2026-04-03T09:00:00Z"),
    ("2026-03-03", "1.0", "percent", "0.005", "decimal", "2026-03-03T22:00:00Z", "2026-03-04T09:00:00Z"),
    ("2026-03-04", "-2.0", "percent", "-0.01", "decimal", "2026-03-04T22:00:00Z", "2026-03-05T09:00:00Z"),
    ("2026-03-05", "3.0", "percent", "0.015", "decimal", "2026-03-05T22:00:00Z", "2026-03-06T09:00:00Z"),
    ("2026-03-06", "0.0", "percent", "0.0", "decimal", "2026-03-06T22:00:00Z", "2026-03-09T09:00:00Z"),
    ("2026-03-09", "-1.0", "percent", "-0.005", "decimal", "2026-03-09T22:00:00Z", "2026-03-10T09:00:00Z"),
    ("2026-03-10", "2.0", "percent", "0.07", "decimal", "2026-03-10T22:00:00Z", "2026-04-08T09:00:00Z"),
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _check(check_id: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {"check_id": check_id, "passed": bool(passed), "detail": detail}


def _close(a: Optional[float], b: float, tol: float = TOL) -> bool:
    return a is not None and math.isfinite(a) and abs(a - b) <= tol


def _write_csv(path: str, fields: Sequence[str], rows: Sequence[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_csv(path: str, fields: Sequence[str]) -> List[Dict[str, str]]:
    with open(path, "r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        require(
            reader.fieldnames is not None and tuple(reader.fieldnames) == tuple(fields),
            "unexpected columns in %s: %r" % (path, reader.fieldnames),
        )
        return [dict(row) for row in reader]


def to_decimal(value: float, unit: str) -> float:
    """Normalize one return to decimal. Percent is divided by 100; decimal is kept."""
    if unit == "percent":
        return value / 100.0
    if unit == "decimal":
        return value
    raise AsOfError("unknown return unit %r; refusing to guess" % (unit,))


def sample_beta(factor: Sequence[float], portfolio: Sequence[float]) -> float:
    """Beta as sample covariance divided by sample variance, both with n - 1."""
    n = len(factor)
    require(n == len(portfolio) and n >= 2, "beta needs at least two aligned rows")
    mean_f = sum(factor) / n
    mean_p = sum(portfolio) / n
    cov = sum((f - mean_f) * (p - mean_p) for f, p in zip(factor, portfolio)) / (n - 1)
    var = sum((f - mean_f) ** 2 for f in factor) / (n - 1)
    require(var > 0.0, "factor variance is zero; beta is undefined")
    return cov / var


def beta_crosscheck(factor: Sequence[float], portfolio: Sequence[float]) -> float:
    """Slope from as_of.factor_exposure OLS with an intercept, for comparison."""
    import numpy as np

    factor_exposure = component("factor_exposure")
    out = factor_exposure.reproduce_exposures(
        np.array(portfolio, dtype=np.float64).reshape(-1, 1),
        np.array(factor, dtype=np.float64).reshape(-1, 1),
        add_intercept=True,
    )
    return float(out["betas"][0, 0])


# ---------------------------------------------------------------------------
# Input files
# ---------------------------------------------------------------------------
def write_inputs(directory: str) -> Dict[str, str]:
    """Write the live synthetic snapshot. The content is fixed, so the hashes are stable."""
    positions_path = os.path.join(directory, "positions.csv")
    prices_path = os.path.join(directory, "prices.csv")
    factors_path = os.path.join(directory, "factor_rows.csv")

    position_rows = [
        {"book": BOOK_LABEL, "security_id": sid, "quantity": str(qty), "as_of": AS_OF_TEXT}
        for sid, qty, _close, _prior in SECURITIES
    ]
    price_rows: List[Dict[str, str]] = []
    for sid, _qty, close, prior in SECURITIES:
        price_rows.append({"security_id": sid, "as_of": PRIOR_TEXT, "close": str(prior), "source_id": PRICE_SOURCE})
        price_rows.append({"security_id": sid, "as_of": AS_OF_TEXT, "close": str(close), "source_id": PRICE_SOURCE})
    factor_rows = [
        {
            "return_date": ret_date,
            "factor_id": FACTOR_ID,
            "factor_definition": FACTOR_DEFINITION,
            "factor_return": f_val,
            "factor_unit": f_unit,
            "portfolio_return": p_val,
            "portfolio_unit": p_unit,
            "release_at": release,
            "ingest_at": ingest,
            "source_id": FACTOR_SOURCE,
            "vintage": FACTOR_VINTAGE,
            "retrieved_at": RETRIEVED_AT,
        }
        for ret_date, f_val, f_unit, p_val, p_unit, release, ingest in FACTOR_ROWS
    ]
    _write_csv(positions_path, POSITIONS_FIELDS, position_rows)
    _write_csv(prices_path, PRICES_FIELDS, price_rows)
    _write_csv(factors_path, FACTOR_FIELDS, factor_rows)
    return {"positions": positions_path, "prices": prices_path, "factors": factors_path}


def write_disposable(directory: str, drop_price_for: Optional[str] = None,
                     flip_sign_for: Optional[str] = None) -> Dict[str, str]:
    """Copy the live inputs into a disposable folder with one planted change.

    drop_price_for removes only the as-of price row, so the prior-day row stays
    and a forward-fill could hide the gap. flip_sign_for negates that name's
    share count. The live files are never changed.
    """
    live = write_inputs(INPUT_DIR)
    positions = _read_csv(live["positions"], POSITIONS_FIELDS)
    prices = _read_csv(live["prices"], PRICES_FIELDS)
    factors = _read_csv(live["factors"], FACTOR_FIELDS)
    if drop_price_for is not None:
        before = len(prices)
        prices = [r for r in prices if not (r["security_id"] == drop_price_for and r["as_of"] == AS_OF_TEXT)]
        require(len(prices) == before - 1, "planted price removal did not remove exactly one row")
    if flip_sign_for is not None:
        flipped = 0
        for row in positions:
            if row["security_id"] == flip_sign_for:
                row["quantity"] = str(-float(row["quantity"]))
                flipped += 1
        require(flipped == 1, "planted sign flip did not match exactly one position")
    out = {
        "positions": os.path.join(directory, "positions.csv"),
        "prices": os.path.join(directory, "prices.csv"),
        "factors": os.path.join(directory, "factor_rows.csv"),
    }
    _write_csv(out["positions"], POSITIONS_FIELDS, positions)
    _write_csv(out["prices"], PRICES_FIELDS, prices)
    _write_csv(out["factors"], FACTOR_FIELDS, factors)
    return out


# ---------------------------------------------------------------------------
# Live calculation (uses the as_of modules)
# ---------------------------------------------------------------------------
def load_positions(path: str) -> List[Any]:
    """Load positions as PositionRecord. The ticker field holds the stable security ID."""
    records: List[Any] = []
    seen = set()
    for row in _read_csv(path, POSITIONS_FIELDS):
        require(row["book"] == BOOK_LABEL, "unexpected book label %r" % (row["book"],))
        sid = row["security_id"]
        require(sid not in seen, "duplicate position for %s" % sid)
        seen.add(sid)
        require(row["quantity"].strip() != "", "blank quantity for %s; not treated as zero" % sid)
        records.append(
            PositionRecord(
                book=row["book"],
                ticker=sid,
                quantity=float(row["quantity"]),
                as_of=date.fromisoformat(row["as_of"]),
            )
        )
    return records


def load_prices(path: str) -> Dict[Tuple[str, date], Any]:
    """Load prices keyed by (security ID, date). A blank close is kept as None, not zero."""
    prices: Dict[Tuple[str, date], Any] = {}
    for row in _read_csv(path, PRICES_FIELDS):
        key = (row["security_id"], date.fromisoformat(row["as_of"]))
        require(key not in prices, "duplicate price row for %s on %s" % key)
        close_text = row["close"].strip()
        close = None if close_text == "" else float(close_text)
        prices[key] = PriceRecord(ticker=row["security_id"], as_of=key[1], close=close, source_id=row["source_id"])
    return prices


def value_positions(positions: Sequence[Any], prices: Dict[Tuple[str, date], Any]) -> Dict[str, Any]:
    """Value every position with require_price. Any missing price stops the run."""
    price_rules = component("price_hard_fail")
    per_name: List[Dict[str, Any]] = []
    for position in positions:
        record = price_rules.require_price(prices, position.ticker, position.as_of)
        per_name.append(
            {
                "security_id": position.ticker,
                "quantity": position.quantity,
                "close": float(record.close),
                "market_value": position.quantity * float(record.close),
            }
        )
    values = [row["market_value"] for row in per_name]
    return {
        "per_name": per_name,
        "long": sum(v for v in values if v > 0.0),
        "short": sum(v for v in values if v < 0.0),
        "gross": sum(abs(v) for v in values),
        "net": sum(values),
    }


def load_factor_rows(path: str) -> List[Dict[str, Any]]:
    """Load factor rows with their clocks parsed as aware UTC datetimes."""
    rows: List[Dict[str, Any]] = []
    for row in _read_csv(path, FACTOR_FIELDS):
        rows.append(
            {
                "return_date": row["return_date"],
                "factor_id": row["factor_id"],
                "factor_definition": row["factor_definition"],
                "factor_return": float(row["factor_return"]),
                "factor_unit": row["factor_unit"],
                "portfolio_return": float(row["portfolio_return"]),
                "portfolio_unit": row["portfolio_unit"],
                "release_at": parse_ts(row["release_at"]),
                "ingest_at": parse_ts(row["ingest_at"]),
                "source_id": row["source_id"],
                "vintage": row["vintage"],
                "retrieved_at": row["retrieved_at"],
            }
        )
    return rows


def run_calculation(paths: Dict[str, str], decision_text: str = DECISION_TEXT) -> Dict[str, Any]:
    """Run the live calculation. Raises HardFailError when a position has no valid price."""
    availability = component("availability_cutoff")
    core_clockset = component("core").ClockSet
    decision_at = parse_ts(decision_text)

    positions = load_positions(paths["positions"])
    prices = load_prices(paths["prices"])
    totals = value_positions(positions, prices)

    factor_rows = load_factor_rows(paths["factors"])
    metadata_fields = ("factor_id", "factor_definition", "source_id", "vintage", "retrieved_at")
    for field in metadata_fields:
        require(len(set(r[field] for r in factor_rows)) == 1, "factor metadata %s differs across rows" % field)

    eligible: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for row in factor_rows:
        clocks = core_clockset(release_at=row["release_at"], ingest_at=row["ingest_at"])
        if availability.usable_at(clocks, decision_at):
            eligible.append(row)
        else:
            excluded.append(row)

    factor_dec = [to_decimal(r["factor_return"], r["factor_unit"]) for r in eligible]
    port_dec = [to_decimal(r["portfolio_return"], r["portfolio_unit"]) for r in eligible]
    beta = sample_beta(factor_dec, port_dec)

    all_factor_dec = [to_decimal(r["factor_return"], r["factor_unit"]) for r in factor_rows]
    all_port_dec = [to_decimal(r["portfolio_return"], r["portfolio_unit"]) for r in factor_rows]

    first = factor_rows[0]
    return {
        "long": totals["long"],
        "short": totals["short"],
        "gross": totals["gross"],
        "net": totals["net"],
        "per_name": totals["per_name"],
        "beta": beta,
        "beta_crosscheck": beta_crosscheck(factor_dec, port_dec),
        "beta_all_rows": sample_beta(all_factor_dec, all_port_dec),
        "row_count": len(eligible),
        "row_count_total": len(factor_rows),
        "eligible_factor_dec": factor_dec,
        "eligible_dates": [r["return_date"] for r in eligible],
        "excluded_dates": [r["return_date"] for r in excluded],
        "factor_metadata": {
            "factor_id": first["factor_id"],
            "definition": first["factor_definition"],
            "source_id": first["source_id"],
            "vintage": first["vintage"],
            "retrieved_at": first["retrieved_at"],
        },
    }


# ---------------------------------------------------------------------------
# Lab 8 verifier (csv module only; imports no as_of module)
# ---------------------------------------------------------------------------
def _verifier_decimal(value: float, unit: str) -> float:
    if unit == "percent":
        return value / 100.0
    if unit == "decimal":
        return value
    raise ValueError("unknown unit %r" % (unit,))


def verify_lab8(paths: Dict[str, str], decision_text: str = DECISION_TEXT) -> Dict[str, Any]:
    """Recompute the snapshot totals and beta from the CSV files alone.

    Every position must have a finite, positive as-of close on its exact
    security ID and date. A position without one is reported in missing_prices,
    and no totals are returned. A blank close is missing, not zero.
    """
    positions = _read_csv(paths["positions"], POSITIONS_FIELDS)
    price_rows = _read_csv(paths["prices"], PRICES_FIELDS)
    closes: Dict[Tuple[str, str], str] = {(r["security_id"], r["as_of"]): r["close"] for r in price_rows}

    missing: List[str] = []
    market_values: Dict[str, float] = {}
    for pos in positions:
        sid = pos["security_id"]
        text = closes.get((sid, pos["as_of"]), "")
        try:
            close = float(text) if text.strip() != "" else float("nan")
        except ValueError:
            close = float("nan")
        if not (math.isfinite(close) and close > 0.0):
            missing.append(sid)
            continue
        market_values[sid] = float(pos["quantity"]) * close

    result: Dict[str, Any] = {
        "missing_prices": sorted(missing),
        "long": None,
        "short": None,
        "gross": None,
        "net": None,
        "beta": None,
        "row_count": None,
        "eligible_dates": None,
        "market_values": market_values,
    }
    if missing:
        return result

    values = list(market_values.values())
    result["long"] = sum(v for v in values if v > 0.0)
    result["short"] = sum(v for v in values if v < 0.0)
    result["gross"] = sum(abs(v) for v in values)
    result["net"] = sum(values)

    factor_rows = _read_csv(paths["factors"], FACTOR_FIELDS)
    # Parse both clocks rather than comparing strings, so a format change fails loudly.
    decision_dt = datetime.strptime(decision_text, "%Y-%m-%dT%H:%M:%SZ")
    eligible = [
        r for r in factor_rows
        if datetime.strptime(r["ingest_at"], "%Y-%m-%dT%H:%M:%SZ") <= decision_dt
    ]
    result["eligible_dates"] = [r["return_date"] for r in eligible]
    x = [_verifier_decimal(float(r["factor_return"]), r["factor_unit"]) for r in eligible]
    y = [_verifier_decimal(float(r["portfolio_return"]), r["portfolio_unit"]) for r in eligible]
    n = len(x)
    if n >= 2:
        mx = sum(x) / n
        my = sum(y) / n
        cov = sum((a - mx) * (b - my) for a, b in zip(x, y)) / (n - 1)
        var = sum((a - mx) ** 2 for a in x) / (n - 1)
        result["beta"] = cov / var if var > 0.0 else None
    result["row_count"] = n
    return result


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def build_checks(live: Dict[str, Any], verifier_live: Dict[str, Any], missing_run: Dict[str, Any],
                 verifier_missing: Dict[str, Any], flip_run: Dict[str, Any],
                 verifier_flip: Dict[str, Any], input_hashes: Dict[str, str]) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []

    hash_ok = set(input_hashes) == set(EXPECTED_INPUT_SHA256) and all(
        input_hashes[k] == EXPECTED_INPUT_SHA256[k] for k in EXPECTED_INPUT_SHA256
    )
    checks.append(_check(
        "frozen_input_files_match_pinned_sha256",
        hash_ok,
        "; ".join("%s=%s" % (k, input_hashes.get(k)) for k in sorted(EXPECTED_INPUT_SHA256)),
    ))

    checks.append(_check(
        "eligible_dates_match_hand_and_verifier",
        tuple(live["eligible_dates"]) == HAND_ELIGIBLE_DATES
        and tuple(verifier_live["eligible_dates"] or ()) == HAND_ELIGIBLE_DATES,
        "live=%s verifier=%s hand=%s" % (
            ",".join(live["eligible_dates"]),
            ",".join(verifier_live["eligible_dates"] or []),
            ",".join(HAND_ELIGIBLE_DATES),
        ),
    ))

    mv_by_name = {row["security_id"]: row["market_value"] for row in live["per_name"]}
    mv_ok = set(mv_by_name) == set(HAND_MARKET_VALUES) and all(
        _close(mv_by_name[k], HAND_MARKET_VALUES[k]) for k in HAND_MARKET_VALUES
    )
    checks.append(_check(
        "live_market_values_match_hand_recalc",
        mv_ok,
        "; ".join("%s=%s" % (k, mv_by_name.get(k)) for k in sorted(HAND_MARKET_VALUES)),
    ))

    totals_ok = all(_close(live[k], HAND_TOTALS[k]) for k in ("long", "short", "gross", "net"))
    checks.append(_check(
        "live_long_short_gross_net_match_hand",
        totals_ok,
        "long=%s short=%s gross=%s net=%s (hand: 11000, -5000, 16000, 6000)"
        % (live["long"], live["short"], live["gross"], live["net"]),
    ))

    checks.append(_check(
        "live_every_position_priced_none_dropped",
        len(live["per_name"]) == len(SECURITIES),
        "valued=%d positions=%d" % (len(live["per_name"]), len(SECURITIES)),
    ))

    checks.append(_check(
        "factor_rows_excluded_by_ingest_cutoff",
        live["row_count"] == HAND_ROW_COUNT
        and live["excluded_dates"] == list(HAND_EXCLUDED_DATES),
        "eligible=%d excluded_dates=%s (the early-return-date row ingested 2026-04-03 is excluded)"
        % (live["row_count"], ",".join(live["excluded_dates"])),
    ))

    units_ok = len(live["eligible_factor_dec"]) == len(HAND_ELIGIBLE_FACTOR_DEC) and all(
        _close(a, b) for a, b in zip(live["eligible_factor_dec"], HAND_ELIGIBLE_FACTOR_DEC)
    )
    checks.append(_check(
        "units_normalized_percent_to_decimal",
        units_ok,
        "eligible factor values in decimal: %s" % ", ".join("%g" % v for v in live["eligible_factor_dec"]),
    ))

    beta_ok = _close(live["beta"], HAND_TOTALS["beta"]) and _close(live["beta_crosscheck"], live["beta"], 1e-9)
    checks.append(_check(
        "beta_cov_over_var_matches_hand_and_ols",
        beta_ok,
        "beta=%.12f ols_cross_check=%.12f hand=0.5 tol=%g" % (live["beta"], live["beta_crosscheck"], TOL),
    ))

    meta = live["factor_metadata"]
    meta_ok = (
        meta["factor_id"] == FACTOR_ID
        and meta["definition"] == FACTOR_DEFINITION
        and meta["source_id"] == FACTOR_SOURCE
        and meta["vintage"] == FACTOR_VINTAGE
        and meta["retrieved_at"] == RETRIEVED_AT
    )
    checks.append(_check(
        "factor_definition_source_vintage_retrieval_preserved",
        meta_ok,
        "definition=%r source=%s vintage=%s retrieved_at=%s"
        % (meta["definition"], meta["source_id"], meta["vintage"], meta["retrieved_at"]),
    ))

    verifier_ok = (
        verifier_live["missing_prices"] == []
        and _close(verifier_live["long"], HAND_TOTALS["long"])
        and _close(verifier_live["short"], HAND_TOTALS["short"])
        and _close(verifier_live["gross"], HAND_TOTALS["gross"])
        and _close(verifier_live["net"], HAND_TOTALS["net"])
        and _close(verifier_live["beta"], HAND_TOTALS["beta"], 1e-9)
        and verifier_live["row_count"] == HAND_ROW_COUNT
        and _close(verifier_live["gross"], live["gross"])
        and _close(verifier_live["net"], live["net"])
        and _close(verifier_live["beta"], live["beta"], 1e-9)
        and verifier_live["row_count"] == live["row_count"]
    )
    checks.append(_check(
        "lab8_verifier_reproduces_gross_net_long_short_beta_rows",
        verifier_ok,
        "verifier long=%s short=%s gross=%s net=%s beta=%s rows=%s"
        % (verifier_live["long"], verifier_live["short"], verifier_live["gross"], verifier_live["net"],
           verifier_live["beta"], verifier_live["row_count"]),
    ))

    checks.append(_check(
        "planted_missing_price_verifier_reports_name",
        verifier_missing["missing_prices"] == [MISSING_ID] and verifier_missing["gross"] is None,
        "verifier missing_prices=%s totals_returned=%s"
        % (verifier_missing["missing_prices"], verifier_missing["gross"] is not None),
    ))

    checks.append(_check(
        "planted_missing_price_calculation_fails_hard",
        missing_run["raised"] and missing_run["error_type"] == "HardFailError" and MISSING_ID in missing_run["message"],
        "raised=%s type=%s message=%r (no three-name total returned)"
        % (missing_run["raised"], missing_run["error_type"], missing_run["message"]),
    ))

    net_delta = flip_run["net"] - live["net"]
    flip_ok = (
        _close(flip_run["net"], HAND_FLIP_TOTALS["net"])
        and _close(net_delta, 6000.0)
        and _close(flip_run["gross"], HAND_TOTALS["gross"])
        and _close(flip_run["long"], HAND_FLIP_TOTALS["long"])
        and _close(flip_run["short"], HAND_FLIP_TOTALS["short"])
        and verifier_flip["missing_prices"] == []
        and _close(verifier_flip["net"], HAND_FLIP_TOTALS["net"])
        and _close(verifier_flip["gross"], HAND_TOTALS["gross"])
    )
    checks.append(_check(
        "planted_short_sign_flip_changes_net_not_gross",
        flip_ok,
        "%s flipped: net %s -> %s (delta %s); gross %s -> %s; verifier net=%s gross=%s"
        % (FLIP_ID, live["net"], flip_run["net"], net_delta, live["gross"], flip_run["gross"],
           verifier_flip["net"], verifier_flip["gross"]),
    ))

    sensitivity = abs(live["beta_all_rows"] - live["beta"])
    checks.append(_check(
        "factor_cutoff_changes_beta_on_this_fixture",
        sensitivity > BETA_SENSITIVITY_MIN,
        "beta eligible=%.12f beta all %d rows=%.12f difference=%.6g"
        % (live["beta"], live["row_count_total"], live["beta_all_rows"], sensitivity),
    ))
    return checks


def run_lab() -> Dict[str, Any]:
    """Run the whole lab and return the results dict. Writes only under as_of/labs/results."""
    content_hash = component("content_hash")
    live_paths = write_inputs(INPUT_DIR)
    input_hashes = {name: content_hash.sha256_file(path) for name, path in sorted(live_paths.items())}

    live = run_calculation(live_paths)
    verifier_live = verify_lab8(live_paths)

    missing_paths = write_disposable(os.path.join(DISPOSABLE_DIR, "missing_price"), drop_price_for=MISSING_ID)
    try:
        run_calculation(missing_paths)
        missing_run = {"raised": False, "error_type": "none", "message": "no error; totals were returned"}
    except AsOfError as exc:
        missing_run = {"raised": True, "error_type": type(exc).__name__, "message": str(exc)}
    verifier_missing = verify_lab8(missing_paths)

    flip_paths = write_disposable(os.path.join(DISPOSABLE_DIR, "sign_flip"), flip_sign_for=FLIP_ID)
    flip_run = run_calculation(flip_paths)
    verifier_flip = verify_lab8(flip_paths)

    checks = build_checks(live, verifier_live, missing_run, verifier_missing, flip_run, verifier_flip,
                          input_hashes)
    passed = all(c["passed"] for c in checks)

    return {
        "lab_id": LAB_ID,
        "title": TITLE,
        "synthetic_only": True,
        "network_calls": False,
        "passed": passed,
        "decision_at": DECISION_TEXT,
        "as_of_date": AS_OF_TEXT,
        "tolerance": TOL,
        "checks": checks,
        "live_totals": {
            "long": live["long"],
            "short": live["short"],
            "gross": live["gross"],
            "net": live["net"],
            "beta": live["beta"],
            "row_count": live["row_count"],
        },
        "verifier_totals": {
            "long": verifier_live["long"],
            "short": verifier_live["short"],
            "gross": verifier_live["gross"],
            "net": verifier_live["net"],
            "beta": verifier_live["beta"],
            "row_count": verifier_live["row_count"],
            "missing_prices": verifier_live["missing_prices"],
        },
        "per_name": live["per_name"],
        "factor_metadata": dict(
            live["factor_metadata"],
            observation_count_total=live["row_count_total"],
            observation_count_eligible=live["row_count"],
            excluded_dates=live["excluded_dates"],
            unit_normalization="percent divided by 100; decimal used as is; unit read per row",
            tolerance=TOL,
            decision_at=DECISION_TEXT,
        ),
        "planted_failures": [
            {
                "name": "missing_price_disposable",
                "file": os.path.relpath(missing_paths["prices"], LAB_DIR),
                "removed_row": "%s on %s" % (MISSING_ID, AS_OF_TEXT),
                "calculation": missing_run,
                "verifier_missing_prices": verifier_missing["missing_prices"],
            },
            {
                "name": "short_sign_flip_disposable",
                "file": os.path.relpath(flip_paths["positions"], LAB_DIR),
                "flipped": FLIP_ID,
                "net_before": live["net"],
                "net_after": flip_run["net"],
                "gross_before": live["gross"],
                "gross_after": flip_run["gross"],
            },
        ],
        "input_sha256": input_hashes,
        "limits": [
            "Synthetic only: four SYN_SEC security IDs, one synthetic factor, USD values, no FX, no corporate actions, no stale-price rules.",
            "A PASS shows that the frozen export ties to its own inputs and that the verifier and the modules agree. It does not show that any position, price or factor value is correct, complete or entitled.",
            "For live use, reproduce the totals in the authoritative workbook or risk system, which owns identifiers, corporate actions, FX, stale prices and data rights. This sidecar explains a frozen export and does not replace the live control owner.",
            "Public factor data from a research library does not establish a live entitlement or a production risk calculation.",
            "Beta is a historical sample slope over five synthetic rows. It is not a forecast and not a risk limit.",
        ],
    }


def main() -> int:
    result = run_lab()
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=False)
        handle.write("\n")
    for check in result["checks"]:
        print("%s %s" % ("PASS" if check["passed"] else "FAIL", check["check_id"]))
    print("overall: %s" % ("PASS" if result["passed"] else "FAIL"))
    print("wrote %s" % RESULTS_PATH)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
