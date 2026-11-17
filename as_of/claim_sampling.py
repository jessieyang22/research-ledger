"""Deterministic stratified sampling of claims for human review.

A claim sample is the subset of claims that a human reviewer checks by hand.
The sample has to be reproducible: the same population, seed and n always
give the same claims, so a reviewer, an auditor and a later rerun all see
one set of claims. This module keeps that property and keeps the sample
spread across strata (for example, one claim kind per stratum) so that a
rare kind of claim is not missed.

Behaviour:

- sample_claims() sorts the population by claim_id first, so the input order
  does not change the result. It groups claims by the value of one
  ClaimRecord field (stratify_by, default 'claim_kind').
- When n is at least the number of strata, every stratum contributes at
  least one claim. The remaining slots are split across strata in proportion
  to how many spare claims each stratum has, with largest-remainder rounding
  and a per-stratum cap at the stratum size. Ties go to the stratum with the
  smaller key.
- When n is smaller than the number of strata, n strata are picked at random
  and one claim is taken from each.
- Within a stratum, claims are picked with a permutation drawn from
  make_rng(seed). Strata are visited in sorted key order, so the draws are
  reproducible.
- n larger than the population, a negative n, duplicate claim ids or an
  unknown stratify_by field raise AsOfError.
- sampling_log() returns a JSON-ready record of the sample: seed, population
  size, sample size, claim ids, a stable hash of the id list and the counts
  by claim_kind.

Topic: claim sampling. The exact procedure is not reproduced here. This is an
original design that follows the idea of stratified review.

Only core.py is imported from the as_of package. The data is synthetic and
the module does no I/O.
"""

import dataclasses
from collections import Counter
from typing import Any, Dict, List, Sequence, Tuple

from as_of.core import (
    SYNTHETIC_SEED,
    AsOfError,
    ClaimRecord,
    make_rng,
    require,
    stable_hash,
)


def _claim_field_names() -> Tuple[str, ...]:
    return tuple(f.name for f in dataclasses.fields(ClaimRecord))


def _stratum_label(value: Any) -> str:
    """Collision-free label for a stratum value.

    Plain str(value) merges distinct values such as 1 and "1" into one stratum.
    Pairing the type name with repr() keeps those apart. Values with the same
    type and repr share a stratum, so every NaN float lands in one "float:'nan'"
    stratum even though NaN != NaN. That is a deliberate grouping choice, not
    an identity test.
    """
    return "%s:%s" % (type(value).__name__, repr(value))


def _allocate(sizes: Dict[str, int], n: int) -> Dict[str, int]:
    """Split n slots over strata with at least one slot each when n >= strata.

    sizes maps stratum key to stratum size. The keys are visited in sorted
    order so that the result depends only on the sizes and n.
    """
    keys = sorted(sizes)
    k = len(keys)
    alloc = {key: 0 for key in keys}
    if n < k:
        return alloc
    for key in keys:
        alloc[key] = 1
    remaining = n - k
    while remaining > 0:
        spare = {key: sizes[key] - alloc[key] for key in keys}
        eligible = [key for key in keys if spare[key] > 0]
        total_spare = sum(spare[key] for key in eligible)
        if total_spare <= 0:
            # Guard against a non-terminating loop if sizes and n disagree.
            raise AsOfError("cannot allocate %d more slots: no spare claims" % remaining)
        # total_spare >= remaining because the population has at least n claims.
        shares = {key: remaining * spare[key] / total_spare for key in eligible}
        given = 0
        for key in eligible:
            add = min(int(shares[key]), spare[key])
            alloc[key] += add
            given += add
        remaining -= given
        if remaining <= 0:
            break
        # Largest remainder: one extra slot each to the biggest fractions.
        order = sorted(
            [key for key in eligible if alloc[key] < sizes[key]],
            key=lambda key: (-(shares[key] - int(shares[key])), key),
        )
        for key in order:
            if remaining <= 0:
                break
            alloc[key] += 1
            remaining -= 1
    return alloc


def sample_claims(
    claims: Sequence[ClaimRecord],
    n: int,
    seed: int = SYNTHETIC_SEED,
    stratify_by: str = "claim_kind",
) -> List[ClaimRecord]:
    """Return n claims chosen deterministically and spread across strata.

    The result is sorted by claim_id. The same claims, n, seed and
    stratify_by always give the same sample. Raises AsOfError when n is
    negative, when n is larger than the population, when claim ids repeat,
    or when stratify_by is not a ClaimRecord field.
    """
    require(isinstance(n, int) and not isinstance(n, bool), "n must be an int")
    require(n >= 0, "n must be non-negative, got %d" % n)
    require(
        stratify_by in _claim_field_names(),
        "stratify_by %r is not a ClaimRecord field" % (stratify_by,),
    )
    population = sorted(claims, key=lambda c: c.claim_id)
    ids = [c.claim_id for c in population]
    require(len(set(ids)) == len(ids), "duplicate claim_id in population")
    if n > len(population):
        raise AsOfError(
            "sample size %d exceeds population size %d" % (n, len(population))
        )
    if n == 0:
        return []

    strata: Dict[str, List[ClaimRecord]] = {}
    for claim in population:
        label = _stratum_label(getattr(claim, stratify_by))
        strata.setdefault(label, []).append(claim)
    # Labels are strings that include the type, so mixed-type keys never merge.
    key_order = sorted(strata)
    sizes = {key: len(strata[key]) for key in key_order}

    rng = make_rng(seed)
    if n < len(key_order):
        # Too few slots for a guarantee: pick n strata at random.
        chosen_idx = rng.permutation(len(key_order))[:n]
        alloc = {key_order[i]: 1 for i in chosen_idx}
        alloc = {key: alloc.get(key, 0) for key in sizes}
    else:
        alloc = _allocate(sizes, n)

    chosen: List[ClaimRecord] = []
    for key in sorted(sizes):
        take = alloc[key]
        if take == 0:
            continue
        members = strata[key]
        order = rng.permutation(len(members))
        chosen.extend(members[i] for i in order[:take])
    return sorted(chosen, key=lambda c: c.claim_id)


def sampling_log(
    sample: Sequence[ClaimRecord],
    seed: int,
    population_size: int,
) -> Dict[str, Any]:
    """Return a JSON-ready record of how a sample was drawn.

    The record holds the seed, the population size, the sample size and
    fraction, the sorted claim ids, a stable hash of those ids and the number
    of sampled claims per claim_kind. The claim_kind counts are reported
    whatever stratify_by was used, since sample_claims() does not return it.
    A sample that repeats a claim_id raises AsOfError.
    """
    require(population_size >= 0, "population_size must be non-negative")
    require(len(sample) <= population_size, "sample is larger than the population")
    claim_ids = sorted(c.claim_id for c in sample)
    require(len(set(claim_ids)) == len(claim_ids), "sample contains a duplicate claim_id")
    # claim_kind is documented as a string; str() keeps the counts sortable
    # even if a caller passes other types.
    kind_counts = Counter(str(c.claim_kind) for c in sample)
    fraction = (len(sample) / population_size) if population_size else 0.0
    return {
        "seed": int(seed),
        "population_size": int(population_size),
        "sample_size": len(sample),
        "sample_fraction": round(fraction, 6),
        "claim_ids": claim_ids,
        "sample_hash": stable_hash(claim_ids),
        "claim_kind_counts": {k: kind_counts[k] for k in sorted(kind_counts)},
    }
