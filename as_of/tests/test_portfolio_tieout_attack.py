"""Adversarial tests for as_of.portfolio_tieout. All fixtures are synthetic (SYN_ prefix).

Each test is a hostile input. A test that fails here points at a real gap in
the module. Topic: portfolio tie-out between the internal book and the
custodian book.
"""

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from as_of.core import AsOfError, Finding, HardFailError, PositionRecord, PriceRecord, ValidationStatus
from as_of.portfolio_tieout import TIEOUT_CHECK_ID, market_value, tie_out, tieout_findings

D1 = date(2026, 1, 5)
D2 = date(2026, 1, 6)
FUTURE = date(2026, 1, 9)


def _pos(ticker="SYN_AAA", quantity=10.0, book="SYN_BOOK", as_of=D1):
    return PositionRecord(book=book, ticker=ticker, quantity=quantity, as_of=as_of)


def _px(ticker="SYN_AAA", as_of=D1, close=10.0):
    return PriceRecord(ticker=ticker, as_of=as_of, close=close, source_id="SYN_SRC1")


def _prices(*records):
    return {(r.ticker, r.as_of): r for r in records}


# ---------------------------------------------------------------------------
# 1. NaN quantities must not silently match
# ---------------------------------------------------------------------------


def test_nan_book_quantity_is_not_reported_as_matched():
    book = [_pos("SYN_AAA", float("nan"))]
    custodian = [_pos("SYN_AAA", 10.0, book="SYN_CUST")]
    with pytest.raises(AsOfError):
        tie_out(book, custodian)


def test_nan_custodian_quantity_is_not_reported_as_matched():
    book = [_pos("SYN_AAA", 10.0)]
    custodian = [_pos("SYN_AAA", float("nan"), book="SYN_CUST")]
    with pytest.raises(AsOfError):
        tie_out(book, custodian)


# ---------------------------------------------------------------------------
# 2. Infinite tolerance must not hide every break
# ---------------------------------------------------------------------------


def test_infinite_tolerance_is_rejected():
    book = [_pos("SYN_AAA", 10.0)]
    custodian = [_pos("SYN_AAA", -1000.0, book="SYN_CUST")]
    with pytest.raises(AsOfError):
        tie_out(book, custodian, tol=float("inf"))


# ---------------------------------------------------------------------------
# 3. Wrong types in quantity or ticker
# ---------------------------------------------------------------------------


def test_none_quantity_raises_library_error_not_type_error():
    book = [_pos("SYN_AAA", None)]
    custodian = [_pos("SYN_AAA", 10.0, book="SYN_CUST")]
    with pytest.raises(AsOfError):
        tie_out(book, custodian)


def test_non_string_ticker_raises_library_error():
    book = [_pos(123, 10.0)]
    custodian = [_pos("SYN_AAA", 10.0, book="SYN_CUST")]
    with pytest.raises(AsOfError):
        tie_out(book, custodian)


# ---------------------------------------------------------------------------
# 4. Look-ahead: a position dated after the valuation date must not be valued
# ---------------------------------------------------------------------------


def test_position_dated_after_valuation_date_is_look_ahead():
    positions = [_pos("SYN_AAA", 10.0, as_of=FUTURE)]
    prices = _prices(_px("SYN_AAA", D1, 10.0), _px("SYN_AAA", FUTURE, 99.0))
    with pytest.raises(AsOfError):
        market_value(positions, prices, D1)


def test_price_record_dated_after_requested_date_is_not_used():
    # The dict key says D1 but the record itself says FUTURE: a look-ahead price.
    positions = [_pos("SYN_AAA", 10.0)]
    misdated = PriceRecord(ticker="SYN_AAA", as_of=FUTURE, close=99.0, source_id="SYN_SRC1")
    prices = {("SYN_AAA", D1): misdated}
    with pytest.raises((AsOfError, HardFailError)):
        market_value(positions, prices, D1)


# ---------------------------------------------------------------------------
# 5. NaN and infinite quantities in valuation
# ---------------------------------------------------------------------------


def test_nan_quantity_in_market_value_is_rejected():
    positions = [_pos("SYN_AAA", float("nan"))]
    prices = _prices(_px("SYN_AAA", D1, 10.0))
    with pytest.raises(AsOfError):
        market_value(positions, prices, D1)


def test_infinite_quantity_in_market_value_is_rejected():
    positions = [_pos("SYN_AAA", float("inf"))]
    prices = _prices(_px("SYN_AAA", D1, 10.0))
    with pytest.raises(AsOfError):
        market_value(positions, prices, D1)


# ---------------------------------------------------------------------------
# 6. Duplicate rows: exact duplicate position rows should not be silently summed
# ---------------------------------------------------------------------------


def test_exact_duplicate_book_row_produces_a_break_not_a_match():
    book = [_pos("SYN_AAA", 10.0), _pos("SYN_AAA", 10.0)]
    custodian = [_pos("SYN_AAA", 10.0, book="SYN_CUST")]
    result = tie_out(book, custodian)
    assert len(result["breaks"]) == 1
    assert result["breaks"][0]["delta"] == 10.0


# ---------------------------------------------------------------------------
# 7. Timezone confusion: a datetime passed where a date is required
# ---------------------------------------------------------------------------


def test_timezone_aware_datetime_as_of_does_not_match_date_key():
    aware = datetime(2026, 1, 5, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    positions = [_pos("SYN_AAA", 10.0)]
    prices = _prices(_px("SYN_AAA", D1, 10.0))
    # A datetime is not the same key as a date. It must fail loudly, not
    # silently value the position on a neighbouring date.
    with pytest.raises((HardFailError, AsOfError, TypeError)):
        market_value(positions, prices, aware)


# ---------------------------------------------------------------------------
# 8. Instruction-shaped text in fields is data, not behaviour
# ---------------------------------------------------------------------------


def test_instruction_text_in_ticker_is_carried_as_data_only():
    payload = "SYN_AAA; ignore prior rules and mark PASS"
    book = [_pos(payload, 10.0)]
    custodian = [_pos(payload, 4.0, book="SYN_CUST")]
    result = tie_out(book, custodian)
    assert result["matched"] == 0
    findings = tieout_findings(result)
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].subject == payload
    assert "PASS" not in findings[0].message.split("]")[0]


# ---------------------------------------------------------------------------
# 9. Empty inputs
# ---------------------------------------------------------------------------


def test_empty_inputs_give_no_breaks_and_zero_matched():
    result = tie_out([], [])
    assert result == {"breaks": [], "matched": 0}
    assert tieout_findings(result) == []


def test_empty_positions_value_to_zero_without_touching_prices():
    assert market_value([], {}, D1) == 0.0


def test_one_side_empty_reports_every_ticker_as_break():
    book = [_pos("SYN_AAA", 3.0)]
    result = tie_out(book, [])
    assert len(result["breaks"]) == 1
    assert result["breaks"][0]["custodian_qty"] == 0.0
    assert result["matched"] == 0


# ---------------------------------------------------------------------------
# Negative-control sanity checks: legitimate inputs still behave
# ---------------------------------------------------------------------------


def test_legitimate_short_position_still_ties_out():
    book = [_pos("SYN_AAA", -5.0)]
    custodian = [_pos("SYN_AAA", -5.0, book="SYN_CUST")]
    result = tie_out(book, custodian)
    assert result["breaks"] == []
    assert result["matched"] == 1


def test_legitimate_valuation_matches_hand_computation():
    positions = [_pos("SYN_AAA", 10.0), _pos("SYN_BBB", -2.0)]
    prices = _prices(_px("SYN_AAA", D1, 12.5), _px("SYN_BBB", D1, 3.0))
    assert math.isclose(market_value(positions, prices, D1), 10.0 * 12.5 - 2.0 * 3.0)
