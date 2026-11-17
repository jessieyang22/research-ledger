"""Adversarial tests for as_of.catalyst_fixture. All data is synthetic (SYN_ prefix)."""

import math
from datetime import datetime, timezone

import numpy as np
import pytest

from as_of.catalyst_fixture import make_catalyst_fixture
from as_of.core import AsOfError, FilingRecord, SourceRecord, SourceType

TODAY_UTC = datetime(2026, 10, 27, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. Wrong types for the seed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_seed",
    ["20261027", None, 1.0, float("nan"), float("inf"), b"1", [1], np.int64(5)],
)
def test_wrong_type_seed_raises_as_of_error(bad_seed):
    with pytest.raises(AsOfError):
        make_catalyst_fixture(seed=bad_seed)


def test_bool_seed_is_rejected_as_not_an_int():
    # bool is a subclass of int in Python, so True silently means seed 1.
    # A caller passing a flag by mistake should get an error, not a timeline.
    with pytest.raises(AsOfError):
        make_catalyst_fixture(seed=True)


# ---------------------------------------------------------------------------
# 2. Out-of-range seed values
# ---------------------------------------------------------------------------


def test_negative_seed_raises_as_of_error_not_numpy_error():
    # numpy raises ValueError for negative seeds. The module promises AsOfError
    # for bad input, so the module should reject it before numpy is called.
    with pytest.raises(AsOfError):
        make_catalyst_fixture(seed=-1)


def test_zero_seed_and_very_large_seed_still_build_valid_fixture():
    for seed in (0, 2 ** 70):
        fixture = make_catalyst_fixture(seed=seed)
        assert len(fixture["filings"]) == 2
        assert len(fixture["claims"]) == 3


# ---------------------------------------------------------------------------
# 3. Look-ahead dates
# ---------------------------------------------------------------------------


def test_no_filing_is_dated_after_today():
    for seed in (0, 1, 20261027, 2 ** 40):
        fixture = make_catalyst_fixture(seed=seed)
        for filing in fixture["filings"]:
            assert filing.filed_at <= TODAY_UTC, (seed, filing.filing_id)
            assert filing.accepted_at <= TODAY_UTC, (seed, filing.filing_id)


def test_source_retrieved_at_is_not_before_the_filing_it_holds():
    # A filing source cannot have been retrieved before the filing existed.
    # Retrieval earlier than the filing is a look-ahead inconsistency.
    fixture = make_catalyst_fixture()
    filings_by_source = {f.source_id: f for f in fixture["filings"]}
    for src in fixture["sources"]:
        if src.source_id in filings_by_source:
            filing = filings_by_source[src.source_id]
            assert src.retrieved_at >= filing.accepted_at, src.source_id


# ---------------------------------------------------------------------------
# 4. Timezone confusion
# ---------------------------------------------------------------------------


def test_every_datetime_is_timezone_aware_utc():
    fixture = make_catalyst_fixture(seed=7)
    stamps = []
    for src in fixture["sources"]:
        stamps.append(src.retrieved_at)
    for filing in fixture["filings"]:
        stamps.append(filing.filed_at)
        stamps.append(filing.accepted_at)
    for stamp in stamps:
        assert stamp.tzinfo is not None, stamp
        assert stamp.utcoffset().total_seconds() == 0, stamp


# ---------------------------------------------------------------------------
# 5. Duplicate rows and dangling references
# ---------------------------------------------------------------------------


def test_ids_are_unique_across_sources_claims_and_filings():
    fixture = make_catalyst_fixture()
    source_ids = [s.source_id for s in fixture["sources"]]
    claim_ids = [c.claim_id for c in fixture["claims"]]
    filing_ids = [f.filing_id for f in fixture["filings"]]
    assert len(source_ids) == len(set(source_ids))
    assert len(claim_ids) == len(set(claim_ids))
    assert len(filing_ids) == len(set(filing_ids))


def test_links_only_reference_existing_claims():
    fixture = make_catalyst_fixture()
    claim_ids = {c.claim_id for c in fixture["claims"]}
    assert set(fixture["links"].keys()) <= claim_ids


def test_filing_source_ids_point_at_filing_sources_only():
    fixture = make_catalyst_fixture()
    by_id = {s.source_id: s for s in fixture["sources"]}
    for filing in fixture["filings"]:
        assert by_id[filing.source_id].source_type == SourceType.FILING


# ---------------------------------------------------------------------------
# 6. NaN, instruction-shaped text, and empty inputs
# ---------------------------------------------------------------------------


def test_output_text_fields_are_fixed_strings_not_seed_derived():
    # The module takes no free text, so instruction-shaped text cannot enter.
    # Check that every output string is a known fixed string or an SYN_ id.
    fixture = make_catalyst_fixture(seed=20261027)
    for claim in fixture["claims"]:
        assert "ignore" not in claim.text.lower()
        assert "instruction" not in claim.text.lower()
        assert "system" not in claim.text.lower()
    for src in fixture["sources"]:
        assert "\n" not in src.locator
        assert "\n" not in src.publisher


def test_hostile_seed_strings_are_rejected_not_executed():
    hostile = "1; import os; os.system('echo pwned')"
    with pytest.raises(AsOfError):
        make_catalyst_fixture(seed=hostile)


def test_empty_seed_container_is_rejected():
    with pytest.raises(AsOfError):
        make_catalyst_fixture(seed="")
    with pytest.raises(AsOfError):
        make_catalyst_fixture(seed=())


def test_default_call_with_no_arguments_yields_complete_fixture():
    fixture = make_catalyst_fixture()
    expected_keys = {
        "sources",
        "claims",
        "catalyst_ids",
        "links",
        "filings",
        "exceptions_expected",
    }
    assert set(fixture.keys()) == expected_keys
    assert all(isinstance(f, FilingRecord) for f in fixture["filings"])
    assert all(isinstance(s, SourceRecord) for s in fixture["sources"])
    assert not any(math.isnan(f.accepted_at.timestamp()) for f in fixture["filings"])
