"""Tests for as_of.claim_sampling. All claims are synthetic and use the SYN_ prefix."""

import random
from collections import Counter

import pytest

from as_of.claim_sampling import sample_claims, sampling_log
from as_of.core import SYNTHETIC_PREFIX, AsOfError, ClaimRecord


def _claim(i, kind):
    return ClaimRecord(
        claim_id="%sCLM%04d" % (SYNTHETIC_PREFIX, i),
        text="synthetic claim %d" % i,
        claim_kind=kind,
        source_ids=("%sSRC%02d" % (SYNTHETIC_PREFIX, i % 7),),
        status="open",
        section="summary",
    )


def _population():
    # Uneven strata: a rare kind with 2 claims, a mid kind, and a large kind.
    kinds = ["guidance"] * 2 + ["estimate"] * 9 + ["price_move"] * 30
    return [_claim(i, kind) for i, kind in enumerate(kinds)]


def _ids(claims):
    return [c.claim_id for c in claims]


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_same_seed_gives_same_sample():
    pop = _population()
    first = sample_claims(pop, 10, seed=7)
    second = sample_claims(pop, 10, seed=7)
    assert _ids(first) == _ids(second)
    # Input order must not matter either.
    shuffled = list(pop)
    random.Random(3).shuffle(shuffled)
    assert _ids(sample_claims(shuffled, 10, seed=7)) == _ids(first)


def test_n_larger_than_population_raises():
    pop = _population()
    with pytest.raises(AsOfError):
        sample_claims(pop, len(pop) + 1, seed=7)


def test_sample_is_subset_of_population():
    pop = _population()
    population_ids = set(_ids(pop))
    for n in (0, 1, 2, 3, 5, 10, 25, len(pop)):
        sample = sample_claims(pop, n, seed=11)
        assert len(sample) == n
        assert set(_ids(sample)) <= population_ids
        assert len(set(_ids(sample))) == n  # no repeats


def test_every_stratum_contributes_when_n_at_least_strata():
    pop = _population()
    strata = {c.claim_kind for c in pop}
    for n in range(len(strata), len(pop) + 1):
        sample = sample_claims(pop, n, seed=5)
        kinds = {c.claim_kind for c in sample}
        assert kinds == strata, "n=%d missed strata %s" % (n, strata - kinds)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_n_zero_returns_empty_list():
    assert sample_claims(_population(), 0, seed=1) == []


def test_n_equal_to_population_returns_everything():
    pop = _population()
    assert sorted(_ids(sample_claims(pop, len(pop), seed=1))) == sorted(_ids(pop))


def test_negative_n_raises():
    with pytest.raises(AsOfError):
        sample_claims(_population(), -1, seed=1)


def test_non_int_n_raises():
    with pytest.raises(AsOfError):
        sample_claims(_population(), 2.0, seed=1)
    with pytest.raises(AsOfError):
        sample_claims(_population(), True, seed=1)


def test_duplicate_claim_ids_raise():
    pop = _population()
    pop.append(_claim(0, "guidance"))  # same claim_id as the first claim
    with pytest.raises(AsOfError):
        sample_claims(pop, 3, seed=1)


def test_unknown_stratify_field_raises():
    with pytest.raises(AsOfError):
        sample_claims(_population(), 3, seed=1, stratify_by="not_a_field")


def test_n_below_strata_count_picks_n_distinct_strata():
    pop = _population()
    sample = sample_claims(pop, 2, seed=9)
    assert len(sample) == 2
    assert len({c.claim_kind for c in sample}) == 2


def test_result_is_sorted_by_claim_id():
    sample = sample_claims(_population(), 12, seed=4)
    assert _ids(sample) == sorted(_ids(sample))


def test_empty_population_with_zero_n():
    assert sample_claims([], 0, seed=1) == []


def test_empty_population_with_positive_n_raises():
    with pytest.raises(AsOfError):
        sample_claims([], 1, seed=1)


def test_sampling_log_is_json_ready_and_consistent():
    pop = _population()
    sample = sample_claims(pop, 10, seed=2)
    log = sampling_log(sample, seed=2, population_size=len(pop))
    assert log["seed"] == 2
    assert log["population_size"] == len(pop)
    assert log["sample_size"] == 10
    assert log["sample_fraction"] == round(10 / len(pop), 6)
    assert log["claim_ids"] == sorted(_ids(sample))
    assert log["claim_kind_counts"] == dict(Counter(c.claim_kind for c in sample))
    assert len(log["sample_hash"]) == 64  # hex sha256
    # Same sample gives the same hash.
    again = sampling_log(sample_claims(pop, 10, seed=2), seed=2, population_size=len(pop))
    assert again["sample_hash"] == log["sample_hash"]
