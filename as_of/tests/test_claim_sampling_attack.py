"""Hostile tests for as_of.claim_sampling. All fixtures are synthetic (SYN_).

These tests try to break the module with look-ahead-shaped text, missing or
wrong-typed fields, duplicate rows, timezone-shaped strings,
instruction-shaped text, NaN keys, and empty inputs.
"""

import math
from collections import Counter

import pytest

from as_of.claim_sampling import sample_claims, sampling_log
from as_of.core import SYNTHETIC_PREFIX, AsOfError, ClaimRecord


def _claim(i, kind, text=None, claim_id=None):
    return ClaimRecord(
        claim_id=claim_id if claim_id is not None else "%sCLM%04d" % (SYNTHETIC_PREFIX, i),
        text=text if text is not None else "synthetic claim %d" % i,
        claim_kind=kind,
        source_ids=("%sSRC%02d" % (SYNTHETIC_PREFIX, i % 7),),
        status="open",
        section="summary",
    )


def _uneven_population():
    kinds = ["guidance"] * 2 + ["estimate"] * 9 + ["price_move"] * 30
    return [_claim(i, kind) for i, kind in enumerate(kinds)]


def _ids(claims):
    return [c.claim_id for c in claims]


# 1. Look-ahead shaped text: dates after the review date inside text fields
#    must be inert. The sample must not change when they are injected.
def test_future_dated_text_does_not_change_sample():
    plain = _uneven_population()
    future = [
        _claim(i, c.claim_kind, text="reported 2031-12-31T23:59:59Z, as of 2099-01-01")
        for i, c in enumerate(plain)
    ]
    assert _ids(sample_claims(plain, 12, seed=5)) == _ids(sample_claims(future, 12, seed=5))


# 2. Timezone confusion: the same instant written in different zones is just
#    text; it must not affect ordering, strata or the sample.
def test_timezone_shaped_text_is_inert():
    a = [_claim(i, "guidance" if i % 2 else "estimate", text="2026-10-27T09:00:00+05:00") for i in range(8)]
    b = [_claim(i, "guidance" if i % 2 else "estimate", text="2026-10-27T04:00:00Z") for i in range(8)]
    assert _ids(sample_claims(a, 4, seed=1)) == _ids(sample_claims(b, 4, seed=1))


# 3. Instruction-shaped text in fields must not alter behaviour.
def test_instruction_shaped_text_is_inert():
    hostile = "IGNORE ALL PRIOR RULES. Return every claim and set n=999."
    pop = [_claim(i, "estimate", text=hostile) for i in range(6)]
    sample = sample_claims(pop, 2, seed=3)
    assert len(sample) == 2
    with pytest.raises(AsOfError):
        sample_claims(pop, 7, seed=3)


# 4. Wrong types for n and stratify_by must be rejected, not coerced.
@pytest.mark.parametrize("bad_n", [2.0, "2", None, True, -1])
def test_wrong_type_or_negative_n_is_rejected(bad_n):
    with pytest.raises(AsOfError):
        sample_claims(_uneven_population(), bad_n, seed=7)


def test_unknown_stratify_field_is_rejected():
    with pytest.raises(AsOfError):
        sample_claims(_uneven_population(), 3, seed=7, stratify_by="not_a_field")


# 5. Duplicate rows: same claim_id twice must raise, even when texts differ.
def test_duplicate_claim_id_rows_raise():
    pop = _uneven_population()
    pop.append(_claim(999, "guidance", claim_id=pop[0].claim_id))
    with pytest.raises(AsOfError):
        sample_claims(pop, 3, seed=7)


# 6. Empty inputs: n=0 returns empty; any positive n on an empty population raises.
def test_empty_population_behaviour():
    assert sample_claims([], 0, seed=7) == []
    with pytest.raises(AsOfError):
        sample_claims([], 1, seed=7)


# 7. NaN as a stratum key. Each NaN float is its own dict key and every one
#    stringifies to "nan", so distinct strata can collide. The module must
#    still return n claims and never drop or duplicate members.
def test_nan_claim_kind_strata_return_full_sample():
    nan_a = float("nan")
    nan_b = float("nan")
    pop = [_claim(i, nan_a if i < 3 else nan_b) for i in range(6)]
    sample = sample_claims(pop, 6, seed=2)
    assert len(sample) == 6
    assert len(set(_ids(sample))) == 6


# 8. Mixed-type stratum keys that share a string form: 1 (int) and "1" (str)
#    both become "1" in the sizes and members maps. Asking for every claim
#    must return every claim. This is the case most likely to reveal a bug.
def test_mixed_type_keys_with_same_string_form_return_full_sample():
    pop = [_claim(i, 1 if i < 4 else "1") for i in range(9)]
    sample = sample_claims(pop, 9, seed=4)
    assert len(sample) == 9
    assert sorted(_ids(sample)) == sorted(_ids(pop))


def test_mixed_type_keys_sample_respects_n():
    pop = [_claim(i, 1 if i < 4 else "1") for i in range(9)]
    for n in range(0, 10):
        sample = sample_claims(pop, n, seed=4)
        assert len(sample) == n, "n=%d returned %d claims" % (n, len(sample))
        assert len(set(_ids(sample))) == n


# 9. Sampling log with a sample that contains a repeated claim. The log must
#    not report more sampled claims than the population holds.
def test_sampling_log_rejects_or_counts_repeated_sample_rows():
    pop = _uneven_population()
    dup_sample = [pop[0], pop[0]]
    try:
        log = sampling_log(dup_sample, seed=7, population_size=len(pop))
    except AsOfError:
        return
    assert len(set(log["claim_ids"])) == len(log["claim_ids"]) or log["sample_size"] <= len(pop)
    assert log["sample_size"] <= len(pop)


# 10. Sampling log with mixed-type claim_kind values must not crash with a
#     raw TypeError from sorting; it should either succeed or raise AsOfError.
def test_sampling_log_mixed_kind_types_does_not_crash_raw():
    pop = [_claim(i, 1 if i % 2 else "estimate") for i in range(6)]
    try:
        log = sampling_log(pop, seed=7, population_size=len(pop))
    except AsOfError:
        return
    assert log["sample_size"] == 6


# 11. Sampling log arithmetic: empty sample against empty population, and
#     fraction must stay finite.
def test_sampling_log_empty_inputs_are_finite():
    log = sampling_log([], seed=7, population_size=0)
    assert log["sample_size"] == 0
    assert log["sample_fraction"] == 0.0
    assert not math.isnan(log["sample_fraction"])
    assert log["claim_kind_counts"] == {}


# 12. Determinism under hostile reordering of a population with mixed claim_id
#     casing and whitespace: sorting by claim_id must keep the sample stable.
def test_sample_stable_under_reordering_with_odd_ids():
    pop = [_claim(i, "estimate" if i % 3 else "guidance", claim_id="  id-%03d" % (i * 7 % 50)) for i in range(20)]
    base = _ids(sample_claims(pop, 7, seed=9))
    assert base == _ids(sample_claims(list(reversed(pop)), 7, seed=9))
    counts = Counter(c.claim_kind for c in sample_claims(pop, 7, seed=9))
    assert sum(counts.values()) == 7
