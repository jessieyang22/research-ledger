"""Adversarial tests for as_of.macro_fixture. All data is synthetic (SYN_ prefix).

These tests try hostile inputs and invariant checks against make_macro_fixture.
Topic: synthetic fixtures and vintage discipline.
"""

import math
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

from as_of.core import AsOfError, MacroVintage
from as_of.macro_fixture import _SERIES_SPECS, make_macro_fixture

SYN_ID = re.compile(r"^SYN_[A-Z]+(_[A-Z]+)*$")


# Hostile seed values


@pytest.mark.parametrize("bad_seed", [None, True, False, 1.5, "abc", [1], b"1"])
def test_non_integer_or_bool_seed_is_rejected_with_as_of_error(bad_seed):
    with pytest.raises(AsOfError):
        make_macro_fixture(bad_seed)


@pytest.mark.parametrize("bad_seed", [-1, -(2 ** 40)])
def test_negative_seed_is_rejected_with_as_of_error(bad_seed):
    with pytest.raises(AsOfError):
        make_macro_fixture(bad_seed)


def test_extra_positional_arguments_are_rejected():
    with pytest.raises(TypeError):
        make_macro_fixture(1, 2)


# Look-ahead and timing


def test_no_release_before_observation_across_many_seeds():
    for seed in range(40):
        for r in make_macro_fixture(seed):
            assert r.release_at.date() >= r.obs_date, (seed, r)
            assert r.vintage_date > r.obs_date, (seed, r)


def test_every_release_strictly_after_observation_month_start():
    for r in make_macro_fixture(7):
        obs_midnight = datetime(r.obs_date.year, r.obs_date.month, r.obs_date.day,
                                tzinfo=timezone.utc)
        assert r.release_at > obs_midnight, r


def test_revision_releases_strictly_after_first_release_for_same_obs():
    rows = make_macro_fixture(11)
    grouped = {}
    for r in rows:
        grouped.setdefault((r.series_id, r.obs_date), []).append(r)
    for key, vintages in grouped.items():
        ordered = sorted(vintages, key=lambda v: v.release_at)
        for earlier, later in zip(ordered, ordered[1:]):
            assert earlier.release_at < later.release_at, key


# Duplicate rows


def test_no_duplicate_series_obs_vintage_keys_across_seeds():
    for seed in range(20):
        keys = [(r.series_id, r.obs_date, r.vintage_date) for r in make_macro_fixture(seed)]
        dupes = [k for k, n in Counter(keys).items() if n > 1]
        assert dupes == [], (seed, dupes)


def test_row_count_is_fixed_regardless_of_seed():
    counts = {len(make_macro_fixture(seed)) for seed in range(15)}
    assert len(counts) == 1


# Instruction-shaped text and string fields


def test_string_fields_are_strict_synthetic_identifiers():
    for r in make_macro_fixture(3):
        assert SYN_ID.match(r.series_id), r.series_id
        assert r.source_id.startswith("SYN_SRC_"), r.source_id
        assert SYN_ID.match(r.source_id), r.source_id
        assert all(ch.isascii() and (ch.isalnum() or ch == "_") for ch in r.source_id)


def test_only_declared_series_appear():
    declared = {spec[0] for spec in _SERIES_SPECS}
    seen = {r.series_id for r in make_macro_fixture(5)}
    assert seen == declared


# Timezone confusion


def test_all_release_datetimes_are_aware_utc_and_match_vintage_date():
    for r in make_macro_fixture(9):
        assert isinstance(r.release_at, datetime)
        assert r.release_at.utcoffset() == timedelta(0), r
        assert r.release_at.date() == r.vintage_date, r
        assert (r.release_at.hour, r.release_at.minute, r.release_at.second) == (0, 0, 0)


# NaN and bad numeric values


def test_values_are_finite_and_near_series_base_across_seeds():
    base_by_series = {spec[0]: spec[1] for spec in _SERIES_SPECS}
    for seed in range(25):
        for r in make_macro_fixture(seed):
            assert isinstance(r.value, float)
            assert math.isfinite(r.value), r
            assert abs(r.value - base_by_series[r.series_id]) < 2.0, r


# Output isolation


def test_returned_list_is_a_fresh_copy_each_call():
    first = make_macro_fixture(4)
    first.clear()
    second = make_macro_fixture(4)
    assert len(second) > 0
    assert all(isinstance(r, MacroVintage) for r in second)
