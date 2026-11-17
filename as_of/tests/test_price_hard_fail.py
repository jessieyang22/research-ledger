"""Tests for as_of.price_hard_fail. All fixtures are synthetic (SYN_ prefix)."""

from datetime import date

import pytest

from as_of.core import Finding, HardFailError, PriceRecord, ValidationStatus
from as_of.price_hard_fail import PRICE_CHECK_ID, check_price_panel, require_price

D1 = date(2026, 1, 5)
D2 = date(2026, 1, 6)
D3 = date(2026, 1, 7)


def _rec(ticker="SYN_AAA", as_of=D1, close=10.0, source_id="SYN_SRC1"):
    return PriceRecord(ticker=ticker, as_of=as_of, close=close, source_id=source_id)


def _prices(*records):
    return {(r.ticker, r.as_of): r for r in records}


# ---------------------------------------------------------------------------
# Acceptance: require_price
# ---------------------------------------------------------------------------


def test_missing_price_raises_hard_fail_and_is_not_forward_filled():
    # An earlier close exists on D1. Asking for D2 must not reuse it.
    prices = _prices(_rec(as_of=D1, close=10.0))
    with pytest.raises(HardFailError) as excinfo:
        require_price(prices, "SYN_AAA", D2)
    assert "not forward-filled" in str(excinfo.value)
    assert "SYN_AAA" in str(excinfo.value)


def test_missing_ticker_raises_hard_fail():
    prices = _prices(_rec(ticker="SYN_AAA", as_of=D1))
    with pytest.raises(HardFailError):
        require_price(prices, "SYN_BBB", D1)


def test_empty_price_map_raises_hard_fail():
    with pytest.raises(HardFailError):
        require_price({}, "SYN_AAA", D1)


def test_nan_close_raises_hard_fail():
    prices = _prices(_rec(close=float("nan")))
    with pytest.raises(HardFailError) as excinfo:
        require_price(prices, "SYN_AAA", D1)
    assert "NaN" in str(excinfo.value)


def test_zero_close_raises_hard_fail():
    prices = _prices(_rec(close=0.0))
    with pytest.raises(HardFailError):
        require_price(prices, "SYN_AAA", D1)


def test_negative_close_raises_hard_fail():
    prices = _prices(_rec(close=-1.5))
    with pytest.raises(HardFailError):
        require_price(prices, "SYN_AAA", D1)


def test_infinite_close_raises_hard_fail():
    prices = _prices(_rec(close=float("inf")))
    with pytest.raises(HardFailError) as excinfo:
        require_price(prices, "SYN_AAA", D1)
    assert "infinite" in str(excinfo.value)


def test_non_numeric_close_raises_hard_fail():
    prices = _prices(_rec(close="not-a-number"))
    with pytest.raises(HardFailError):
        require_price(prices, "SYN_AAA", D1)


def test_none_close_raises_hard_fail():
    prices = _prices(_rec(close=None))
    with pytest.raises(HardFailError):
        require_price(prices, "SYN_AAA", D1)


def test_valid_price_is_returned_unchanged():
    rec = _rec(close=12.25)
    prices = _prices(rec)
    assert require_price(prices, "SYN_AAA", D1) is rec


def test_tiny_positive_close_is_valid():
    rec = _rec(close=1e-9)
    assert require_price(_prices(rec), "SYN_AAA", D1) is rec


# ---------------------------------------------------------------------------
# Acceptance: check_price_panel
# ---------------------------------------------------------------------------


def test_complete_valid_panel_returns_empty_list():
    tickers = ["SYN_AAA", "SYN_BBB"]
    dates = [D1, D2]
    records = [
        _rec("SYN_AAA", D1, 10.0),
        _rec("SYN_AAA", D2, 10.5),
        _rec("SYN_BBB", D1, 20.0),
        _rec("SYN_BBB", D2, 19.5),
    ]
    assert check_price_panel(records, tickers, dates) == []


def test_panel_returns_one_finding_per_gap():
    tickers = ["SYN_AAA", "SYN_BBB"]
    dates = [D1, D2, D3]
    # Gaps: AAA@D2, BBB@D1, BBB@D3. Four cells are present and valid.
    records = [
        _rec("SYN_AAA", D1, 10.0),
        _rec("SYN_AAA", D3, 10.2),
        _rec("SYN_BBB", D2, 20.0),
    ]
    findings = check_price_panel(records, tickers, dates)
    assert len(findings) == 3
    subjects = [f.subject for f in findings]
    assert subjects == [
        "SYN_AAA@2026-01-06",
        "SYN_BBB@2026-01-05",
        "SYN_BBB@2026-01-07",
    ]
    for f in findings:
        assert isinstance(f, Finding)
        assert f.check_id == PRICE_CHECK_ID
        assert f.status is ValidationStatus.FAIL
        assert "block" in f.message
        assert "not forward-filled" in f.message


def test_gap_is_not_forward_filled_in_panel_check():
    # D1 is valid, D2 is missing. Only D2 may be reported.
    records = [_rec("SYN_AAA", D1, 10.0)]
    findings = check_price_panel(records, ["SYN_AAA"], [D1, D2])
    assert [f.subject for f in findings] == ["SYN_AAA@2026-01-06"]


def test_panel_reports_nan_zero_and_negative_closes():
    records = [
        _rec("SYN_AAA", D1, float("nan")),
        _rec("SYN_AAA", D2, 0.0),
        _rec("SYN_AAA", D3, -2.0),
    ]
    findings = check_price_panel(records, ["SYN_AAA"], [D1, D2, D3])
    assert len(findings) == 3
    assert all(f.status is ValidationStatus.FAIL for f in findings)
    assert "NaN" in findings[0].message
    assert "non-positive" in findings[1].message
    assert "non-positive" in findings[2].message


def test_panel_one_finding_per_bad_cell_even_with_several_problems():
    # Two bad records in one cell give one finding that names both reasons.
    records = [
        _rec("SYN_AAA", D1, float("nan")),
        _rec("SYN_AAA", D1, -1.0),
    ]
    findings = check_price_panel(records, ["SYN_AAA"], [D1])
    assert len(findings) == 1
    assert "NaN" in findings[0].message
    assert "non-positive" in findings[0].message


def test_panel_duplicate_cell_is_invalid_if_any_record_is_invalid():
    records = [
        _rec("SYN_AAA", D1, 10.0),
        _rec("SYN_AAA", D1, 0.0),
    ]
    findings = check_price_panel(records, ["SYN_AAA"], [D1])
    assert len(findings) == 1
    assert findings[0].subject == "SYN_AAA@2026-01-05"


def test_panel_empty_inputs_return_empty_list():
    assert check_price_panel([], [], []) == []
    assert check_price_panel([], [], [D1]) == []


def test_panel_with_no_records_reports_every_cell():
    findings = check_price_panel([], ["SYN_AAA", "SYN_BBB"], [D1])
    assert len(findings) == 2
    assert all(f.status is ValidationStatus.FAIL for f in findings)


def test_panel_ignores_records_outside_requested_grid():
    # An extra ticker or date that is not in the grid is not reported.
    records = [
        _rec("SYN_AAA", D1, 10.0),
        _rec("SYN_ZZZ", D1, float("nan")),
        _rec("SYN_AAA", date(2030, 1, 1), float("nan")),
    ]
    assert check_price_panel(records, ["SYN_AAA"], [D1]) == []
