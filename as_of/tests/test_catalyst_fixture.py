"""Tests for as_of.catalyst_fixture. All fixtures are synthetic (SYN_ prefix)."""

import pytest

from as_of.catalyst_fixture import make_catalyst_fixture
from as_of.core import AsOfError, FilingRecord, SourceRecord, SourceType


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_exactly_one_claim_has_no_link():
    fixture = make_catalyst_fixture()
    unlinked = [c for c in fixture["claims"] if c.claim_id not in fixture["links"]]
    assert len(unlinked) == 1
    assert unlinked[0].claim_id == "SYN_CLM_03"


def test_links_contains_exactly_one_catalyst_id_not_in_catalyst_ids():
    fixture = make_catalyst_fixture()
    dangling = [
        cat_id
        for cat_id in fixture["links"].values()
        if cat_id not in fixture["catalyst_ids"]
    ]
    assert len(dangling) == 1
    assert dangling[0] == "SYN_CAT_99"


def test_output_is_deterministic_for_fixed_seed():
    first = make_catalyst_fixture(seed=20261027)
    second = make_catalyst_fixture(seed=20261027)
    assert first == second


def test_all_tickers_start_with_syn_prefix():
    fixture = make_catalyst_fixture()
    assert fixture["filings"], "fixture should contain filings"
    for filing in fixture["filings"]:
        assert isinstance(filing, FilingRecord)
        assert filing.ticker.startswith("SYN_")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_every_source_is_synthetic_and_prefixed():
    fixture = make_catalyst_fixture()
    assert fixture["sources"], "fixture should contain sources"
    for src in fixture["sources"]:
        assert isinstance(src, SourceRecord)
        assert src.synthetic is True
        assert src.source_id.startswith("SYN_")


def test_every_claim_source_id_resolves_to_a_source():
    fixture = make_catalyst_fixture()
    known = {src.source_id for src in fixture["sources"]}
    for claim in fixture["claims"]:
        for src_id in claim.source_ids:
            assert src_id in known


def test_one_filing_per_ticker_with_filing_source():
    fixture = make_catalyst_fixture()
    filings = fixture["filings"]
    tickers = [f.ticker for f in filings]
    assert len(tickers) == len(set(tickers))
    filing_src_ids = {
        src.source_id
        for src in fixture["sources"]
        if src.source_type == SourceType.FILING
    }
    assert len(filing_src_ids) == len(filings)
    for filing in filings:
        assert filing.source_id in filing_src_ids


def test_filing_times_are_utc_and_accepted_after_filed():
    fixture = make_catalyst_fixture()
    for filing in fixture["filings"]:
        assert filing.filed_at.utcoffset().total_seconds() == 0
        assert filing.accepted_at.utcoffset().total_seconds() == 0
        assert filing.accepted_at > filing.filed_at


def test_expected_exception_kinds_are_known_vocabulary_names():
    known_kinds = {"FILING_OCCURRED", "CLAIM_UNLINKED", "CHECK_FAILED"}
    fixture = make_catalyst_fixture()
    kinds = {kind for kind, _ in fixture["exceptions_expected"]}
    assert kinds <= known_kinds
    assert ("CLAIM_UNLINKED", "SYN_CLM_03") in fixture["exceptions_expected"]
    assert ("CHECK_FAILED", "SYN_CLM_02") in fixture["exceptions_expected"]


def test_expected_filing_exceptions_cover_every_filing():
    fixture = make_catalyst_fixture()
    expected_filing_subjects = {
        subject for kind, subject in fixture["exceptions_expected"] if kind == "FILING_OCCURRED"
    }
    actual = {f.filing_id for f in fixture["filings"]}
    assert expected_filing_subjects == actual


def test_different_seeds_change_filing_times():
    a = make_catalyst_fixture(seed=1)
    b = make_catalyst_fixture(seed=2)
    times_a = [f.filed_at for f in a["filings"]]
    times_b = [f.filed_at for f in b["filings"]]
    # Filing times carry seeded hour offsets, so the two seeds should not
    # produce identical timelines for every ticker at once.
    assert times_a != times_b or [f.accepted_at for f in a["filings"]] != [
        f.accepted_at for f in b["filings"]
    ]


def test_non_int_seed_raises():
    with pytest.raises(AsOfError):
        make_catalyst_fixture(seed="20261027")
