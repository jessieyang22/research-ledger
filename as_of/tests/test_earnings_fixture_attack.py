"""Adversarial tests for as_of.earnings_fixture. All data is synthetic (SYN_ prefix).

These tests probe look-ahead leakage, provenance dates, bad inputs, duplicate
rows, timezone handling, injected text and non-finite values.
"""

import math
from datetime import timezone

import pytest

from as_of.core import AsOfError, EstimateRecord, SourceRecord
from as_of.earnings_fixture import METRICS, N_ANALYSTS, make_fixture


# ---------------------------------------------------------------------------
# Look-ahead and provenance
# ---------------------------------------------------------------------------


def test_every_estimate_is_strictly_before_its_report_for_long_histories():
    # Hostile: a long history crosses the year boundary several times.
    fixture = make_fixture(n_tickers=3, n_quarters=12)
    reports = {
        (r["ticker"], r["metric"], r["period"]): r["reported_at"]
        for r in fixture["reports"]
    }
    assert reports, "fixture should contain reports"
    for est in fixture["estimates"]:
        key = (est.ticker, est.metric, est.period)
        assert key in reports, key
        assert est.knowledge_at < reports[key], est.estimate_id


def test_source_retrieved_at_is_not_earlier_than_the_data_it_holds():
    # A source cannot have been retrieved before the reports and estimates it
    # supplies existed. Each source's retrieved_at must be no earlier than the
    # latest timestamp in its own rows.
    fixture = make_fixture(n_tickers=2, n_quarters=8)
    latest_by_source = {}
    for est in fixture["estimates"]:
        latest_by_source[est.source_id] = max(
            latest_by_source.get(est.source_id, est.knowledge_at), est.knowledge_at
        )
    for src in fixture["sources"]:
        if src.source_id in latest_by_source:
            assert src.retrieved_at >= latest_by_source[src.source_id], src.source_id


# ---------------------------------------------------------------------------
# Hostile and wrong-typed arguments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [True, False])
def test_bool_n_tickers_is_rejected(bad):
    # bool is a subclass of int in Python, so True would silently mean one ticker.
    with pytest.raises(AsOfError):
        make_fixture(n_tickers=bad)


@pytest.mark.parametrize("bad_seed", [-1, 1.5, "20261027", None])
def test_bad_seed_raises_as_of_error(bad_seed):
    with pytest.raises(AsOfError):
        make_fixture(seed=bad_seed)


def test_huge_seed_is_still_deterministic():
    a = make_fixture(seed=2 ** 40)
    b = make_fixture(seed=2 ** 40)
    assert a == b


# ---------------------------------------------------------------------------
# Duplicate rows and identity
# ---------------------------------------------------------------------------


def test_estimate_ids_are_unique_even_past_99_tickers():
    fixture = make_fixture(n_tickers=101, n_quarters=1)
    ids = [est.estimate_id for est in fixture["estimates"]]
    assert len(ids) == len(set(ids))


def test_no_duplicate_analyst_rows_per_report():
    fixture = make_fixture(n_tickers=2, n_quarters=4)
    keys = [
        (est.ticker, est.metric, est.period, est.analyst_id)
        for est in fixture["estimates"]
    ]
    assert len(keys) == len(set(keys))
    assert len(keys) == 2 * 4 * len(METRICS) * N_ANALYSTS


def test_no_duplicate_reports_or_sources():
    fixture = make_fixture(n_tickers=3, n_quarters=4)
    report_keys = [(r["ticker"], r["metric"], r["period"]) for r in fixture["reports"]]
    assert len(report_keys) == len(set(report_keys))
    source_ids = [src.source_id for src in fixture["sources"]]
    assert len(source_ids) == len(set(source_ids))


# ---------------------------------------------------------------------------
# NaN, non-finite values and empty inputs
# ---------------------------------------------------------------------------


def test_all_values_are_finite():
    fixture = make_fixture(n_tickers=3, n_quarters=8)
    for est in fixture["estimates"]:
        assert math.isfinite(est.value), est.estimate_id
    for rep in fixture["reports"]:
        assert math.isfinite(rep["reported_value"]), rep["ticker"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_nan_or_inf_counts_are_rejected(bad):
    with pytest.raises(AsOfError):
        make_fixture(n_tickers=bad)
    with pytest.raises(AsOfError):
        make_fixture(n_quarters=bad)


def test_zero_length_inputs_are_rejected():
    with pytest.raises(AsOfError):
        make_fixture(n_tickers=0, n_quarters=0)


# ---------------------------------------------------------------------------
# Timezone handling
# ---------------------------------------------------------------------------


def test_all_timestamps_are_aware_utc():
    fixture = make_fixture(n_tickers=2, n_quarters=6)
    for est in fixture["estimates"]:
        assert isinstance(est, EstimateRecord)
        assert est.knowledge_at.tzinfo is not None
        assert est.knowledge_at.utcoffset() == timezone.utc.utcoffset(None)
    for rep in fixture["reports"]:
        assert rep["reported_at"].tzinfo is not None
        assert rep["reported_at"].utcoffset() == timezone.utc.utcoffset(None)
    for src in fixture["sources"]:
        assert isinstance(src, SourceRecord)
        assert src.retrieved_at.utcoffset() == timezone.utc.utcoffset(None)


# ---------------------------------------------------------------------------
# Instruction-shaped text
# ---------------------------------------------------------------------------


def test_no_free_text_field_carries_instruction_shaped_content():
    # The fixture takes no free text, so every string it emits must come from
    # a fixed template. Anything that reads as an instruction is a bug.
    fixture = make_fixture(n_tickers=2, n_quarters=2)
    suspicious = ("ignore", "instruction", "system", "assistant", "execute", "buy", "sell")
    strings = []
    for src in fixture["sources"]:
        strings.extend([src.source_id, src.publisher, src.locator, src.sha256])
    for est in fixture["estimates"]:
        strings.extend([est.estimate_id, est.ticker, est.metric, est.period, est.analyst_id])
    for text in strings:
        lowered = text.lower()
        for word in suspicious:
            assert word not in lowered, text
