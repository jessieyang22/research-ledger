"""Tests for as_of.portfolio_tieout. All fixtures are synthetic (SYN_ prefix)."""

from datetime import date

import pytest

from as_of.core import AsOfError, Finding, HardFailError, PositionRecord, PriceRecord, ValidationStatus
from as_of.portfolio_tieout import TIEOUT_CHECK_ID, market_value, tie_out, tieout_findings

D1 = date(2026, 1, 5)
D2 = date(2026, 1, 6)


def _pos(ticker="SYN_AAA", quantity=10.0, book="SYN_BOOK", as_of=D1):
    return PositionRecord(book=book, ticker=ticker, quantity=quantity, as_of=as_of)


def _px(ticker="SYN_AAA", as_of=D1, close=10.0):
    return PriceRecord(ticker=ticker, as_of=as_of, close=close, source_id="SYN_SRC1")


def _prices(*records):
    return {(r.ticker, r.as_of): r for r in records}


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_identical_books_give_zero_breaks():
    book = [_pos("SYN_AAA", 10.0), _pos("SYN_BBB", -4.5)]
    custodian = [_pos("SYN_AAA", 10.0, book="SYN_CUST"), _pos("SYN_BBB", -4.5, book="SYN_CUST")]
    result = tie_out(book, custodian)
    assert result["breaks"] == []
    assert result["matched"] == 2
    assert tieout_findings(result) == []


def test_one_quantity_mismatch_gives_exactly_one_break_with_right_delta():
    book = [_pos("SYN_AAA", 10.0), _pos("SYN_BBB", 7.0)]
    custodian = [_pos("SYN_AAA", 10.0), _pos("SYN_BBB", 5.0)]
    result = tie_out(book, custodian)
    assert len(result["breaks"]) == 1
    brk = result["breaks"][0]
    assert brk["ticker"] == "SYN_BBB"
    assert brk["book_qty"] == 7.0
    assert brk["custodian_qty"] == 5.0
    assert brk["delta"] == 2.0  # book minus custodian
    assert result["matched"] == 1


def test_market_value_on_missing_price_raises_hard_fail():
    positions = [_pos("SYN_AAA", 10.0), _pos("SYN_BBB", 3.0)]
    prices = _prices(_px("SYN_AAA", D1, 10.0))  # no SYN_BBB price
    with pytest.raises(HardFailError) as excinfo:
        market_value(positions, prices, D1)
    assert "SYN_BBB" in str(excinfo.value)
    assert "not forward-filled" in str(excinfo.value)


def test_delta_within_tol_is_not_a_break():
    book = [_pos("SYN_AAA", 10.25)]
    custodian = [_pos("SYN_AAA", 10.0)]
    result = tie_out(book, custodian, tol=0.25)  # delta equals tol
    assert result["breaks"] == []
    assert result["matched"] == 1


def test_delta_just_above_tol_is_a_break():
    book = [_pos("SYN_AAA", 10.5)]
    custodian = [_pos("SYN_AAA", 10.0)]
    result = tie_out(book, custodian, tol=0.25)
    assert len(result["breaks"]) == 1
    assert result["breaks"][0]["delta"] == 0.5


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_ticker_only_on_book_side_is_a_break_against_zero():
    result = tie_out([_pos("SYN_AAA", 3.0)], [])
    assert result["breaks"] == [
        {"ticker": "SYN_AAA", "book_qty": 3.0, "custodian_qty": 0.0, "delta": 3.0}
    ]


def test_ticker_only_on_custodian_side_is_a_break_against_zero():
    result = tie_out([], [_pos("SYN_AAA", 3.0)])
    assert len(result["breaks"]) == 1
    assert result["breaks"][0]["delta"] == -3.0


def test_repeated_tickers_are_summed_before_comparison():
    book = [_pos("SYN_AAA", 4.0), _pos("SYN_AAA", 6.0)]
    custodian = [_pos("SYN_AAA", 10.0)]
    result = tie_out(book, custodian)
    assert result["breaks"] == []
    assert result["matched"] == 1


def test_negative_delta_is_reported_as_book_minus_custodian():
    result = tie_out([_pos("SYN_AAA", 2.0)], [_pos("SYN_AAA", 5.0)])
    assert result["breaks"][0]["delta"] == -3.0


def test_breaks_are_sorted_by_ticker():
    book = [_pos("SYN_CCC", 1.0), _pos("SYN_AAA", 1.0), _pos("SYN_BBB", 1.0)]
    result = tie_out(book, [])
    assert [b["ticker"] for b in result["breaks"]] == ["SYN_AAA", "SYN_BBB", "SYN_CCC"]


def test_empty_inputs_give_no_breaks():
    assert tie_out([], []) == {"breaks": [], "matched": 0}


def test_negative_tol_is_rejected():
    with pytest.raises(AsOfError):
        tie_out([], [], tol=-1.0)


def test_nan_tol_is_rejected():
    with pytest.raises(AsOfError):
        tie_out([], [], tol=float("nan"))


def test_boolean_tol_is_rejected():
    with pytest.raises(AsOfError):
        tie_out([], [], tol=True)


def test_tieout_findings_one_fail_per_break_with_check_id():
    result = tie_out([_pos("SYN_AAA", 7.0), _pos("SYN_BBB", 1.0)], [_pos("SYN_AAA", 5.0)])
    findings = tieout_findings(result)
    assert len(findings) == 2
    for f in findings:
        assert isinstance(f, Finding)
        assert f.check_id == TIEOUT_CHECK_ID
        assert f.status == ValidationStatus.FAIL
    assert [f.subject for f in findings] == ["SYN_AAA", "SYN_BBB"]
    assert "delta=2.0" in findings[0].message


# ---------------------------------------------------------------------------
# market_value
# ---------------------------------------------------------------------------


def test_market_value_sums_quantity_times_close():
    positions = [_pos("SYN_AAA", 10.0), _pos("SYN_BBB", -2.0)]
    prices = _prices(_px("SYN_AAA", D1, 10.0), _px("SYN_BBB", D1, 50.0))
    assert market_value(positions, prices, D1) == pytest.approx(10.0 * 10.0 - 2.0 * 50.0)


def test_market_value_uses_only_the_requested_date():
    positions = [_pos("SYN_AAA", 10.0)]
    prices = _prices(_px("SYN_AAA", D1, 10.0), _px("SYN_AAA", D2, 12.0))
    assert market_value(positions, prices, D2) == pytest.approx(120.0)


def test_market_value_does_not_forward_fill_from_earlier_date():
    positions = [_pos("SYN_AAA", 10.0)]
    prices = _prices(_px("SYN_AAA", D1, 10.0))
    with pytest.raises(HardFailError):
        market_value(positions, prices, D2)


def test_market_value_nan_price_raises_hard_fail():
    positions = [_pos("SYN_AAA", 10.0)]
    prices = _prices(_px("SYN_AAA", D1, float("nan")))
    with pytest.raises(HardFailError):
        market_value(positions, prices, D1)


def test_market_value_of_no_positions_is_zero():
    assert market_value([], {}, D1) == 0.0
