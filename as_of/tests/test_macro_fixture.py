"""Tests for as_of.macro_fixture (synthetic macro vintages only)."""

import math
from collections import defaultdict
from datetime import date, datetime, timezone

import pytest

from as_of.core import SYNTHETIC_PREFIX, SYNTHETIC_SEED, MacroVintage
from as_of.macro_fixture import make_macro_fixture


@pytest.fixture(scope="module")
def rows():
    return make_macro_fixture()


def _as_date(value):
    """release_at is an aware datetime; compare on the calendar date."""
    if isinstance(value, datetime):
        return value.date()
    return value


def test_returns_macro_vintage_records(rows):
    assert rows, "fixture should not be empty"
    assert all(isinstance(r, MacroVintage) for r in rows)


def test_expected_row_count_and_series(rows):
    # 2 series x 12 monthly obs; every third obs (idx 0, 3, 6, 9) has a revision.
    assert len(rows) == 2 * (12 + 4)
    assert {r.series_id for r in rows} == {"SYN_GDP", "SYN_CPI"}


def test_at_least_one_obs_has_two_vintages_with_different_values(rows):
    by_key = defaultdict(list)
    for r in rows:
        by_key[(r.series_id, r.obs_date)].append(r)

    multi = {k: v for k, v in by_key.items() if len(v) >= 2}
    assert multi, "expected at least one (series, obs_date) with multiple vintages"

    differing = [
        k for k, v in multi.items()
        if len({round(x.value, 6) for x in v}) >= 2
    ]
    assert differing, "expected at least one pair of vintages with different values"

    # Every revised pair must also carry distinct vintage dates.
    for k in differing:
        dates = [x.vintage_date for x in by_key[k]]
        assert len(set(dates)) == len(dates)


def test_every_release_at_is_on_or_after_obs_date(rows):
    for r in rows:
        assert isinstance(r.release_at, datetime)
        assert r.release_at.tzinfo is not None, "release_at must be timezone-aware"
        assert _as_date(r.release_at) >= r.obs_date, (
            "release before observation date: %s %s" % (r.series_id, r.obs_date)
        )


def test_vintage_date_matches_release_at_and_follows_obs_date(rows):
    for r in rows:
        assert r.vintage_date >= r.obs_date
        assert _as_date(r.release_at) == r.vintage_date


def test_first_release_precedes_revision_for_same_obs(rows):
    by_key = defaultdict(list)
    for r in rows:
        by_key[(r.series_id, r.obs_date)].append(r)
    for key, vintages in by_key.items():
        vintages = sorted(vintages, key=lambda v: v.vintage_date)
        for earlier, later in zip(vintages, vintages[1:]):
            assert earlier.release_at < later.release_at, key


def test_all_series_ids_start_with_syn_prefix(rows):
    assert SYNTHETIC_PREFIX == "SYN_"
    for r in rows:
        assert r.series_id.startswith("SYN_"), r.series_id


def test_source_ids_are_synthetic(rows):
    for r in rows:
        assert r.source_id.startswith("SYN_SRC_")


def test_values_are_finite_floats(rows):
    for r in rows:
        assert isinstance(r.value, float)
        assert math.isfinite(r.value)


def test_obs_dates_are_first_of_month_starting_2025(rows):
    obs = sorted({r.obs_date for r in rows})
    assert obs[0] == date(2025, 1, 1)
    assert len(obs) == 12
    for d in obs:
        assert d.day == 1


def test_output_is_sorted_by_series_obs_vintage(rows):
    keys = [(r.series_id, r.obs_date, r.vintage_date) for r in rows]
    assert keys == sorted(keys)


def test_output_is_deterministic_for_fixed_seed():
    first = make_macro_fixture(SYNTHETIC_SEED)
    second = make_macro_fixture(SYNTHETIC_SEED)
    assert first == second
    # Default seed is the same as passing it explicitly.
    assert make_macro_fixture() == first


def test_different_seeds_change_values():
    a = make_macro_fixture(1)
    b = make_macro_fixture(2)
    assert [r.value for r in a] != [r.value for r in b]
    # Structure (dates, ids) does not depend on the seed.
    assert [(r.series_id, r.obs_date, r.vintage_date) for r in a] == [
        (r.series_id, r.obs_date, r.vintage_date) for r in b
    ]


def test_release_datetimes_are_utc_midnight(rows):
    for r in rows:
        assert r.release_at.tzinfo == timezone.utc
        assert (r.release_at.hour, r.release_at.minute, r.release_at.second) == (0, 0, 0)
