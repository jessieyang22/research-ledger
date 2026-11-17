"""Failure mode fm18: short sign disappears.

Absolute values are taken before aggregation, so short positions appear as
long and the net totals come out wrong. The detection method named in the
failure mode note is to recompute signed values and net totals from the
inputs and compare them with the reported figures. No network calls are made
and no file is written.

What the existing modules do with signs:
- portfolio_tieout._sum_by_ticker sums signed quantities. Long and short lots
  for one ticker net against each other, so a correct signed book ties out.
- portfolio_tieout.tie_out compares signed net quantities. If one side has
  lost the sign of a short, the delta is about twice the short size and the
  ticker is reported as a break. This is a real detection path for the
  sign-loss symptom, and the tests below plant it.
- portfolio_tieout.market_value multiplies signed quantity by close, so a
  short contributes a negative value.
- factor_exposure uses np.abs only for a magnitude floor check and for
  comparing reproduced betas with reported ones. It does not aggregate
  positions, so it is not a place where this failure is planted.

Gap, marked xfail (strict): no module compares a reported net total with a
signed net recomputed from the inputs. tie_out compares two books with each
other, and market_value returns a total with nothing to compare it against.
The gap test states that.

Only the signed-value and tie-out paths are exercised here.
"""

from datetime import date

import pytest

from as_of import portfolio_tieout
from as_of.core import PositionRecord, PriceRecord, ValidationStatus
from as_of.portfolio_tieout import market_value, tie_out, tieout_findings

AS_OF = date(2026, 6, 30)
TICKER = "SYN_S01"
OTHER = "SYN_S02"


def _pos(book, ticker, quantity, as_of=AS_OF):
    return PositionRecord(book=book, ticker=ticker, quantity=quantity, as_of=as_of)


def _price(ticker, close, as_of=AS_OF):
    return PriceRecord(ticker=ticker, as_of=as_of, close=close, source_id="SYN_SRC1")


def _abs_before_sum(positions):
    """Planted failure: take absolute values per lot, then aggregate.

    This is the wrong step. It stands in for an upstream stage that drops the
    short sign before the totals are formed.
    """
    return [
        PositionRecord(book=p.book, ticker=p.ticker, quantity=abs(p.quantity), as_of=p.as_of)
        for p in positions
    ]


def _signed_net(positions):
    """Oracle: signed net quantity per ticker, recomputed from the inputs."""
    totals = {}
    for p in positions:
        totals[p.ticker] = totals.get(p.ticker, 0.0) + float(p.quantity)
    return totals


# ---------------------------------------------------------------------------
# Control tests: a correct signed book behaves as expected.
# ---------------------------------------------------------------------------


def test_control_long_and_short_lots_net_to_signed_total():
    book = [_pos("INT", TICKER, 100.0), _pos("INT", TICKER, -40.0)]
    custodian = [_pos("CUST", TICKER, 60.0)]
    result = tie_out(book, custodian)
    assert result["breaks"] == []
    assert result["matched"] == 1
    assert _signed_net(book)[TICKER] == pytest.approx(60.0)


def test_control_short_only_position_ties_out_with_negative_quantity():
    book = [_pos("INT", TICKER, -250.0)]
    custodian = [_pos("CUST", TICKER, -250.0)]
    result = tie_out(book, custodian)
    assert result["breaks"] == []


def test_control_market_value_counts_short_as_negative():
    positions = [_pos("INT", TICKER, 100.0), _pos("INT", TICKER, -40.0)]
    prices = {(TICKER, AS_OF): _price(TICKER, 10.0)}
    assert market_value(positions, prices, AS_OF) == pytest.approx(600.0)


# ---------------------------------------------------------------------------
# Planted failure: the short sign is lost before aggregation.
# ---------------------------------------------------------------------------


def test_planted_abs_before_sum_is_detected_as_tieout_break():
    # Correct book: a short of 40 sitting against a long of 100.
    # Custodian holds the true signed net of 60.
    book_true = [_pos("INT", TICKER, 100.0), _pos("INT", TICKER, -40.0)]
    custodian = [_pos("CUST", TICKER, 60.0)]

    # Planted: the book side has its short sign dropped before summing,
    # so the book total becomes 140 instead of 60.
    book_planted = _abs_before_sum(book_true)
    result = tie_out(book_planted, custodian)

    assert len(result["breaks"]) == 1
    brk = result["breaks"][0]
    assert brk["ticker"] == TICKER
    assert brk["book_qty"] == pytest.approx(140.0)
    assert brk["delta"] == pytest.approx(80.0)

    findings = tieout_findings(result)
    assert len(findings) == 1
    assert findings[0].check_id == portfolio_tieout.TIEOUT_CHECK_ID
    assert findings[0].status == ValidationStatus.FAIL


def test_planted_dropped_short_sign_on_custodian_side_is_detected():
    # A custodian file that stores a short as a positive number. Book holds
    # the correct short of -250. The delta is -500, so the break is visible.
    book = [_pos("INT", TICKER, -250.0)]
    custodian_planted = _abs_before_sum([_pos("CUST", TICKER, -250.0)])
    result = tie_out(book, custodian_planted)

    assert len(result["breaks"]) == 1
    brk = result["breaks"][0]
    assert brk["book_qty"] == pytest.approx(-250.0)
    assert brk["custodian_qty"] == pytest.approx(250.0)
    assert brk["delta"] == pytest.approx(-500.0)


def test_planted_sign_loss_changes_market_value_and_is_visible_against_oracle():
    positions = [_pos("INT", TICKER, 100.0), _pos("INT", TICKER, -40.0)]
    prices = {(TICKER, AS_OF): _price(TICKER, 10.0)}

    correct_total = market_value(positions, prices, AS_OF)
    planted_total = market_value(_abs_before_sum(positions), prices, AS_OF)

    # The oracle is the signed net recomputed from the inputs.
    oracle_net = _signed_net(positions)[TICKER] * 10.0
    assert correct_total == pytest.approx(oracle_net)
    assert planted_total != pytest.approx(oracle_net)
    assert planted_total == pytest.approx(1400.0)


def test_planted_sign_loss_on_mixed_tickers_only_breaks_the_affected_ticker():
    book_true = [
        _pos("INT", TICKER, 100.0),
        _pos("INT", TICKER, -40.0),
        _pos("INT", OTHER, 75.0),
    ]
    custodian = [_pos("CUST", TICKER, 60.0), _pos("CUST", OTHER, 75.0)]
    book_planted = _abs_before_sum(book_true)
    result = tie_out(book_planted, custodian)

    broken = [b["ticker"] for b in result["breaks"]]
    assert broken == [TICKER]
    assert result["matched"] == 1


# ---------------------------------------------------------------------------
# Gap: no module compares a reported net total with a recomputed signed net.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm18 gap: no module checks a reported net total against a signed net "
        "recomputed from positions. tie_out compares two books, and "
        "market_value returns a total without a reported figure to compare."
    ),
)
def test_gap_reported_net_total_is_checked_against_signed_recomputation():
    # A check that accepts a reported net and flags a mismatch with the
    # signed recomputation. It does not exist in the current modules.
    net_check = getattr(portfolio_tieout, "check_net_total", None)
    assert net_check is not None
    positions = [_pos("INT", TICKER, 100.0), _pos("INT", TICKER, -40.0)]
    findings = net_check(positions, reported_net={TICKER: 140.0})
    assert any(f.status == ValidationStatus.FAIL for f in findings)
