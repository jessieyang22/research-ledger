"""Failure mode fm14: revenue bridge uses the wrong quarter.

A period-mapping error places a reported figure in the wrong quarter, so the
bridge compares the wrong periods. The detection method named in the failure
mode note is to compare each row's period against the expected fiscal calendar
and to rerun the earnings mapping after a fix. No network calls are made and
no file is written.

Calendar used as the oracle: the repo has no fiscal calendar and no
effective_period field. The only calendar in the code is the one in
earnings_fixture, where period "YYYYQn" closes in calendar month 3n and each
report lands MIN_REPORT_LAG_DAYS to MAX_REPORT_LAG_DAYS after the 28th of that
month. The control tests below use that calendar as the oracle and say so.
Nothing here is verified against a real company's fiscal year.

Findings from the existing modules:
- earnings_fixture.make_fixture labels periods from the quarter index and
  stamps report times from the same index, so a clean fixture is self-consistent.
- reported_vs_expected_bridge.build_bridge matches estimates by exact period
  string. It never compares a report's period with its reported_at. A report
  labelled with the wrong quarter therefore gets the expected value of that
  wrong quarter with no error.
- wf_earnings_reconciliation.run_earnings_proof flags look-ahead rows, basis
  after report, missing expected values and unregistered sources. It does not
  check report period against report time, duplicate report keys, or missing
  periods. A backward mislabel (a later-quarter actual labelled as an earlier
  quarter) creates no look-ahead row, so the proof passes.
- A forward mislabel is caught only incidentally: the estimates for the later
  quarter are known after the report time, so they are flagged as look-ahead.

Gap, marked xfail (strict): no module checks period against report time or
against an expected fiscal calendar. The xfail tests state that gap.
"""

from datetime import datetime, timedelta, timezone

import pytest

from as_of.core import ValidationStatus
from as_of import earnings_fixture
from as_of.earnings_fixture import MAX_REPORT_LAG_DAYS, MIN_REPORT_LAG_DAYS, make_fixture
from as_of.reported_vs_expected_bridge import build_bridge
from as_of.wf_earnings_reconciliation import CHECK_LOOKAHEAD, run_earnings_proof

SEED = 14
TICKER = "SYN_T01"
METRIC = "revenue"
TRUE_PERIOD = "2025Q2"
WRONG_PERIOD = "2025Q1"


def _window_for_period(period):
    """Return the (earliest, latest) report instant for a period label.

    Uses the fixture's own calendar: quarter end month, 28th, then the lag range.
    """
    year = int(period[:4])
    quarter = int(period[-1])
    month = quarter * 3
    base = datetime(year, month, 28, 20, 0, 0, tzinfo=timezone.utc)
    return (
        base + timedelta(days=MIN_REPORT_LAG_DAYS),
        base + timedelta(days=MAX_REPORT_LAG_DAYS),
    )


def _clean_fixture():
    return make_fixture(seed=SEED, n_tickers=2, n_quarters=4)


def _planted_fixture():
    """Clean fixture with one revenue report for TRUE_PERIOD relabelled WRONG_PERIOD.

    The reported value and reported_at are left as they were, so the row now
    claims the earlier quarter while holding the later quarter's actual.
    """
    fx = _clean_fixture()
    reports = []
    planted = False
    for rep in fx["reports"]:
        if (
            not planted
            and rep["ticker"] == TICKER
            and rep["metric"] == METRIC
            and rep["period"] == TRUE_PERIOD
        ):
            reports.append(dict(rep, period=WRONG_PERIOD))
            planted = True
        else:
            reports.append(rep)
    assert planted, "fixture lacks the planted revenue report"
    fx["reports"] = reports
    return fx


def _patch_fixture(monkeypatch, fx):
    monkeypatch.setattr(earnings_fixture, "make_fixture", lambda **kwargs: fx)


def test_control_clean_fixture_report_times_match_their_period_labels():
    """Control: on a clean fixture every report falls in its own quarter window."""
    fx = _clean_fixture()
    for rep in fx["reports"]:
        lo, hi = _window_for_period(rep["period"])
        assert lo <= rep["reported_at"] <= hi, rep


def test_control_clean_fixture_earnings_proof_passes():
    """Control: the untouched fixture reconciles with no FAIL finding."""
    result = run_earnings_proof(seed=SEED)
    assert result.passed is True
    assert all(f.status != ValidationStatus.FAIL for f in result.findings)


def test_wrong_quarter_bridge_silently_uses_the_wrong_quarter_estimates():
    """Documents the live failure: the bridge answers for the label it is given.

    The planted report holds the TRUE_PERIOD actual but is labelled WRONG_PERIOD.
    build_bridge returns an expected value from WRONG_PERIOD estimates with no
    warning, because it never compares the label with reported_at.
    """
    fx = _clean_fixture()
    est = [
        e for e in fx["estimates"]
        if e.ticker == TICKER and e.metric == METRIC and e.period == WRONG_PERIOD
    ]
    rep = next(
        r for r in fx["reports"]
        if r["ticker"] == TICKER and r["metric"] == METRIC and r["period"] == TRUE_PERIOD
    )
    bridge = build_bridge(est, TICKER, METRIC, WRONG_PERIOD, rep["reported_value"], rep["reported_at"])
    assert bridge["expected"] is not None
    assert bridge["basis_as_of"] is not None
    # No field in the bridge output records that the period and report time disagree.
    assert set(bridge.keys()) == {
        "expected", "reported", "surprise_abs", "surprise_pct", "basis_as_of"
    }


def test_forward_mislabel_is_caught_only_as_lookahead(monkeypatch):
    """Partial catch: a later quarter's estimates leak in and show as look-ahead.

    Relabel the TRUE_PERIOD=2025Q1 actual as 2025Q2. The 2025Q2 estimates are
    stamped after the Q1 report time, so the proof flags them, but under the
    look-ahead check, not a period check.
    """
    fx = _clean_fixture()
    reports = []
    planted = False
    for rep in fx["reports"]:
        if (
            not planted
            and rep["ticker"] == TICKER
            and rep["metric"] == METRIC
            and rep["period"] == "2025Q1"
        ):
            reports.append(dict(rep, period="2025Q2"))
            planted = True
        else:
            reports.append(rep)
    fx["reports"] = reports
    _patch_fixture(monkeypatch, fx)
    result = run_earnings_proof(seed=SEED)
    assert result.passed is False
    assert any(f.check_id == CHECK_LOOKAHEAD for f in result.findings)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm14 gap: a backward period mislabel (a 2025Q2 actual labelled 2025Q1) "
        "passes run_earnings_proof. No module compares a report's period with "
        "its reported_at or with an expected fiscal calendar, and no check flags "
        "a duplicate or missing (ticker, metric, period) key. The proof stays green."
    ),
)
def test_backward_mislabel_blocks_the_earnings_proof(monkeypatch):
    """Expected control: a wrong-quarter report must make the proof fail."""
    _patch_fixture(monkeypatch, _planted_fixture())
    result = run_earnings_proof(seed=SEED)
    assert result.passed is False
    fails = [f for f in result.findings if f.status == ValidationStatus.FAIL]
    assert fails, "no FAIL finding raised for a report whose period disagrees with its report time"
