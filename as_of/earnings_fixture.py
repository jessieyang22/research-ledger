"""Synthetic earnings fixture for the as_of earnings proof.

Builds estimate records, reported figures and source records for a small set
of invented tickers. Every value is drawn from one numpy generator seeded by
the caller, so two calls with the same arguments return equal output. The
module does no I/O and no network access, and it names no real company.

Conventions:
    * Tickers are SYN_T01, SYN_T02, and so on.
    * Every source has source_type FIXTURE and synthetic=True.
    * Each source's sha256 is the hash of the canonical JSON of the rows it
      supplies, so a manifest can re-hash the rows and detect a change.
    * Each reported figure has analyst estimates whose knowledge_at falls
      strictly before its reported_at.

The design is an original implementation of the idea that a fixture
should carry its own as-of timestamps.
"""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from as_of.core import (
    SYNTHETIC_PREFIX,
    SYNTHETIC_SEED,
    EstimateRecord,
    SourceRecord,
    SourceType,
    make_rng,
    require,
    stable_hash,
)

METRICS: Tuple[str, ...] = ("eps", "revenue")
N_ANALYSTS: int = 3
# Reports land this many days after the 28th of the quarter-end month. The
# generator and the retrieval bound both read these constants, so they cannot
# drift apart.
MIN_REPORT_LAG_DAYS: int = 25
MAX_REPORT_LAG_DAYS: int = 39


def _period_label(index: int) -> str:
    """Return a label such as '2025Q1' for a zero-based quarter index."""
    return "%dQ%d" % (2025 + index // 4, index % 4 + 1)


def _quarter_end_month(index: int) -> int:
    """Return the calendar month that closes the quarter at index."""
    return (index % 4 + 1) * 3


def _quarter_report_base(index: int) -> datetime:
    """Return the 28th of the quarter-end month, before any report lag."""
    return datetime(
        2025 + index // 4, _quarter_end_month(index), 28, 20, 0, 0, tzinfo=timezone.utc
    )


def _latest_report_bound(n_quarters: int) -> datetime:
    """Return a UTC instant no earlier than any report date for n_quarters.

    Report lag is at most MAX_REPORT_LAG_DAYS after the 28th of the
    quarter-end month, so one extra day after that date is a safe bound.
    """
    last = n_quarters - 1
    return _quarter_report_base(last) + timedelta(days=MAX_REPORT_LAG_DAYS + 1)


def make_fixture(
    seed: int = SYNTHETIC_SEED,
    n_tickers: int = 3,
    n_quarters: int = 4,
) -> Dict[str, Any]:
    """Build a deterministic synthetic earnings fixture.

    Returns a dict with three keys:
        sources: List[SourceRecord], one estimate source and one report
            source per ticker. sha256 hashes the rows that source supplies.
        estimates: List[EstimateRecord], one row per ticker, metric,
            quarter and analyst.
        reports: List[Dict] with keys ticker, metric, period,
            reported_value and reported_at (aware UTC datetime).
    """
    require(isinstance(seed, int) and not isinstance(seed, bool) and seed >= 0,
            "seed must be a non-negative int")
    require(isinstance(n_tickers, int) and not isinstance(n_tickers, bool) and n_tickers >= 1,
            "n_tickers must be a positive int")
    require(isinstance(n_quarters, int) and not isinstance(n_quarters, bool) and n_quarters >= 1,
            "n_quarters must be a positive int")

    rng = make_rng(seed)
    sources: List[SourceRecord] = []
    estimates: List[EstimateRecord] = []
    reports: List[Dict[str, Any]] = []
    # A source cannot be retrieved before the data it holds exists, so the
    # retrieval stamp is set after the last possible report date.
    retrieved_at = _latest_report_bound(n_quarters)

    for t_idx in range(n_tickers):
        ticker = "%sT%02d" % (SYNTHETIC_PREFIX, t_idx + 1)
        est_src_id = "SYN_SRC_EST_%02d" % (t_idx + 1)
        rep_src_id = "SYN_SRC_REP_%02d" % (t_idx + 1)

        base_level = {
            "eps": float(rng.uniform(0.5, 3.0)),
            "revenue": float(rng.uniform(100.0, 900.0)),
        }
        ticker_estimates: List[EstimateRecord] = []
        ticker_reports: List[Dict[str, Any]] = []

        for q_idx in range(n_quarters):
            period = _period_label(q_idx)
            lag_days = MIN_REPORT_LAG_DAYS + int(
                rng.integers(0, MAX_REPORT_LAG_DAYS - MIN_REPORT_LAG_DAYS + 1)
            )
            report_at = _quarter_report_base(q_idx) + timedelta(days=lag_days)

            for metric in METRICS:
                consensus = base_level[metric] * (1.0 + 0.03 * q_idx)
                actual = consensus * (1.0 + float(rng.normal(0.0, 0.04)))

                for a_idx in range(N_ANALYSTS):
                    analyst_value = consensus * (1.0 + float(rng.normal(0.0, 0.03)))
                    offset = 3 + 4 * a_idx + int(rng.integers(0, 3))
                    ticker_estimates.append(
                        EstimateRecord(
                            estimate_id="SYN_EST_%02d_%s_%s_AN%d"
                            % (t_idx + 1, metric, period, a_idx + 1),
                            ticker=ticker,
                            metric=metric,
                            period=period,
                            analyst_id="SYN_AN%d" % (a_idx + 1),
                            value=round(analyst_value, 4),
                            knowledge_at=report_at - timedelta(days=offset),
                            source_id=est_src_id,
                        )
                    )

                ticker_reports.append(
                    {
                        "ticker": ticker,
                        "metric": metric,
                        "period": period,
                        "reported_value": round(actual, 4),
                        "reported_at": report_at,
                    }
                )

        # Hash the rows each source supplies, so the sha256 field pins content.
        est_rows = [asdict(est) for est in ticker_estimates]
        sources.append(
            SourceRecord(
                source_id=est_src_id,
                source_type=SourceType.FIXTURE,
                publisher="synthetic-estimates",
                locator="fixture://earnings/estimates/" + ticker,
                retrieved_at=retrieved_at,
                sha256=stable_hash(est_rows),
                synthetic=True,
            )
        )
        sources.append(
            SourceRecord(
                source_id=rep_src_id,
                source_type=SourceType.FIXTURE,
                publisher="synthetic-reports",
                locator="fixture://earnings/reports/" + ticker,
                retrieved_at=retrieved_at,
                sha256=stable_hash(ticker_reports),
                synthetic=True,
            )
        )
        estimates.extend(ticker_estimates)
        reports.extend(ticker_reports)

    return {"sources": sources, "estimates": estimates, "reports": reports}
