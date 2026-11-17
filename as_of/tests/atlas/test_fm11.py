"""Failure mode fm11: hashes match but the source is wrong.

A bad initial capture is hashed faithfully, so the digest passes while the
content is wrong, and the wrong value then propagates downstream. A digest
only shows byte identity. The detection method is to tie captured values to
an authoritative source or to an independent recapture, and to quarantine the
capture when the two disagree. All fixtures are synthetic (SYN_ prefix); no
network, no real data.

Detection points checked:
  - portfolio_tieout.tie_out compares the internal book with the custodian
    book, which is an independent recapture of the same quantities. A bad
    book capture shows up as a break, even though its hash is stable.
  - portfolio_tieout.tieout_findings turns each break into a FAIL finding.
  - readiness_record.build_readiness blocks go when such a FAIL finding exists.
  - content_hash.hash_records gives the same digest for the bad capture on
    every re-hash, which shows the digest alone cannot catch fm11.

Gaps, marked xfail:
  - Prices: price_hard_fail only rejects missing, NaN and non-positive closes.
    A wrong but positive close passes both require_price and check_price_panel,
    and no module recaptures prices independently.
  - Quarantine: no module moves a disagreeing capture into a quarantine state.
    The only action available is a blocking readiness record.
"""

import pytest

from as_of.content_hash import hash_records
from as_of.core import PositionRecord, PriceRecord, ReadinessItem, ValidationStatus
from as_of.portfolio_fixture import BOOK_LABEL, CUSTODIAN_LABEL, make_portfolio_fixture
from as_of.portfolio_tieout import TIEOUT_CHECK_ID, tie_out, tieout_findings
from as_of.price_hard_fail import check_price_panel
from as_of.readiness_record import build_readiness

_TYPO_SIZE = 37.0  # synthetic bad capture: a digit-level error on one quantity


def _good_fixture():
    return make_portfolio_fixture(n_days=60)


def _custodian_matching_book(fx):
    # Independent recapture: custodian quantities equal the internal truth.
    return [
        PositionRecord(book=CUSTODIAN_LABEL, ticker=c.ticker, quantity=fx["positions_book"][i].quantity, as_of=c.as_of)
        for i, c in enumerate(fx["positions_custodian"])
    ]


def _planted_book(fx, ticker_index=0, shift=_TYPO_SIZE):
    # The initial capture of the internal book is wrong on one ticker.
    # The record is well formed, so it passes every schema check.
    book = []
    for i, p in enumerate(fx["positions_book"]):
        qty = p.quantity + (shift if i == ticker_index else 0.0)
        book.append(PositionRecord(book=BOOK_LABEL, ticker=p.ticker, quantity=qty, as_of=p.as_of))
    return book


def test_planted_bad_book_capture_is_detected_by_custodian_tieout():
    fx = _good_fixture()
    # The fixture's own custodian break is replaced, so the only break is planted.
    clean_custodian = _custodian_matching_book(fx)
    bad_book = _planted_book(fx, ticker_index=0)
    result = tie_out(bad_book, clean_custodian, tol=0.0)
    assert len(result["breaks"]) == 1
    assert result["breaks"][0]["ticker"] == fx["positions_book"][0].ticker
    assert result["breaks"][0]["delta"] == pytest.approx(_TYPO_SIZE)


def test_bad_capture_passes_digest_check_on_every_rehash():
    # The hash of the bad capture is stable and reproducible, so a digest
    # check alone reports no problem. This is the fm11 failure itself.
    fx = _good_fixture()
    bad_book = _planted_book(fx, ticker_index=0)
    first = hash_records(bad_book)
    second = hash_records(list(bad_book))
    assert first == second
    # The digest differs from the good capture, so the hash is not wrong.
    # It just faithfully records the wrong content.
    assert first != hash_records(fx["positions_book"])


def test_break_from_bad_capture_becomes_fail_finding_and_blocks_readiness():
    fx = _good_fixture()
    clean_custodian = _custodian_matching_book(fx)
    bad_book = _planted_book(fx, ticker_index=0)
    findings = tieout_findings(tie_out(bad_book, clean_custodian, tol=0.0))
    assert len(findings) == 1
    assert findings[0].check_id == TIEOUT_CHECK_ID
    assert findings[0].status == ValidationStatus.FAIL

    rec = build_readiness(
        [ReadinessItem(item_id="tieout", passed=True, evidence_ref="SYN_TIEOUT")],
        findings,
        0,
    )
    assert rec["go"] is False
    assert any("tieout.break" in reason for reason in rec["blocking"])


def test_control_matching_capture_passes_tieout_and_readiness():
    # Control: when the internal capture agrees with the custodian recapture,
    # there is no break and readiness is not blocked by the tie-out.
    fx = _good_fixture()
    agreeing_custodian = _custodian_matching_book(fx)
    result = tie_out(fx["positions_book"], agreeing_custodian, tol=0.0)
    assert result["breaks"] == []
    findings = tieout_findings(result)
    assert findings == []
    rec = build_readiness(
        [ReadinessItem(item_id="tieout", passed=True, evidence_ref="SYN_TIEOUT")],
        findings,
        0,
    )
    assert rec["go"] is True


def test_planted_bad_price_capture_is_not_detected_by_price_checks():
    # A wrong but positive close is a plausible capture error (for example a
    # mis-keyed digit). price_hard_fail only rejects missing, NaN and
    # non-positive closes, so this planted value passes.
    fx = _good_fixture()
    tickers = sorted({p.ticker for p in fx["prices"]})
    dates = sorted({p.as_of for p in fx["prices"]})
    prices = list(fx["prices"])
    victim = prices[5]
    prices[5] = PriceRecord(
        ticker=victim.ticker,
        as_of=victim.as_of,
        close=round(victim.close * 1.37, 4),  # wrong, positive, plausible-looking
        source_id=victim.source_id,
    )
    # Baseline: findings on the untouched panel (the fixture's own gap only).
    baseline = check_price_panel(fx["prices"], tickers, dates)
    findings = check_price_panel(prices, tickers, dates)
    victim_flagged = len(findings) != len(baseline)
    if not victim_flagged:
        pytest.xfail(
            "GAP fm11: a wrong but positive close passes check_price_panel and "
            "require_price. No module recaptures prices independently, so a bad "
            "price capture is hashed and propagates. Needs an independent price "
            "recapture and a quarantine rule."
        )
    assert victim_flagged


def test_bad_capture_is_quarantined_not_only_blocked():
    # The detection step calls for quarantining a disagreeing capture. No
    # module holds a quarantine state, so this cannot pass yet.
    pytest.xfail(
        "GAP fm11: no quarantine state exists for captured source values. "
        "readiness_record blocks the run, but the bad capture is not isolated "
        "from downstream use, and no module records it as quarantined."
    )
