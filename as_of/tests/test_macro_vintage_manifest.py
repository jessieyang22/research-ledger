"""Tests for as_of.macro_vintage_manifest. All fixtures are synthetic and use the SYN_ prefix.

Topic: macro vintage manifest.
"""

from datetime import date, datetime, timezone

import pytest

from as_of.core import AsOfError, MacroVintage
from as_of.macro_vintage_manifest import VintageManifest


def _vintage(series="SYN_GDP", obs=date(2026, 1, 1), vint=date(2026, 2, 1), value=1.5, src="SYN_SRC_1"):
    return MacroVintage(
        series_id=series,
        obs_date=obs,
        vintage_date=vint,
        release_at=datetime(vint.year, vint.month, vint.day, 8, 30, tzinfo=timezone.utc),
        value=value,
        source_id=src,
    )


def test_duplicate_vintage_raises_and_changes_nothing():
    manifest = VintageManifest()
    manifest.add_vintage(_vintage(value=1.5))
    before = manifest.manifest_hash()
    with pytest.raises(AsOfError):
        manifest.add_vintage(_vintage(value=9.9))
    assert manifest.manifest_hash() == before
    rows = manifest.entries("SYN_GDP")
    assert len(rows) == 1
    assert rows[0].value == 1.5


def test_same_obs_different_vintage_is_not_duplicate():
    manifest = VintageManifest()
    manifest.add_vintage(_vintage(vint=date(2026, 2, 1)))
    manifest.add_vintage(_vintage(vint=date(2026, 3, 1), value=1.6))
    assert len(manifest.entries("SYN_GDP")) == 2


def test_same_vintage_different_series_is_not_duplicate():
    manifest = VintageManifest()
    manifest.add_vintage(_vintage(series="SYN_GDP"))
    manifest.add_vintage(_vintage(series="SYN_CPI"))
    assert len(manifest.entries("SYN_GDP")) == 1
    assert len(manifest.entries("SYN_CPI")) == 1


def test_add_rejects_non_macro_vintage():
    manifest = VintageManifest()
    with pytest.raises(AsOfError):
        manifest.add_vintage({"series_id": "SYN_GDP"})


def test_manifest_hash_same_for_same_rows_in_different_order():
    rows = [
        _vintage(obs=date(2026, 1, 1), vint=date(2026, 2, 1), value=1.0),
        _vintage(obs=date(2026, 1, 1), vint=date(2026, 3, 1), value=1.1),
        _vintage(series="SYN_CPI", obs=date(2026, 1, 1), vint=date(2026, 2, 1), value=3.0),
    ]
    forward = VintageManifest()
    for row in rows:
        forward.add_vintage(row)
    backward = VintageManifest()
    for row in reversed(rows):
        backward.add_vintage(row)
    assert forward.manifest_hash() == backward.manifest_hash()
    assert forward.to_list() == backward.to_list()


def test_changing_one_value_changes_manifest_hash():
    a = VintageManifest()
    a.add_vintage(_vintage(value=1.0))
    b = VintageManifest()
    b.add_vintage(_vintage(value=1.0001))
    assert a.manifest_hash() != b.manifest_hash()


def test_changing_one_date_changes_manifest_hash():
    a = VintageManifest()
    a.add_vintage(_vintage(obs=date(2026, 1, 1)))
    b = VintageManifest()
    b.add_vintage(_vintage(obs=date(2026, 1, 2)))
    assert a.manifest_hash() != b.manifest_hash()


def test_changing_source_id_changes_manifest_hash():
    a = VintageManifest()
    a.add_vintage(_vintage(src="SYN_SRC_1"))
    b = VintageManifest()
    b.add_vintage(_vintage(src="SYN_SRC_2"))
    assert a.manifest_hash() != b.manifest_hash()


def test_empty_manifest_hash_is_stable_and_hex():
    first = VintageManifest().manifest_hash()
    second = VintageManifest().manifest_hash()
    assert first == second
    assert len(first) == 64
    int(first, 16)


def test_entries_sorted_by_vintage_date():
    manifest = VintageManifest()
    manifest.add_vintage(_vintage(vint=date(2026, 4, 1), value=3.0))
    manifest.add_vintage(_vintage(vint=date(2026, 2, 1), value=1.0))
    manifest.add_vintage(_vintage(vint=date(2026, 3, 1), value=2.0))
    vintages = [row.vintage_date for row in manifest.entries("SYN_GDP")]
    assert vintages == sorted(vintages)
    assert [row.value for row in manifest.entries("SYN_GDP")] == [1.0, 2.0, 3.0]


def test_entries_tie_on_vintage_broken_by_obs_date():
    manifest = VintageManifest()
    manifest.add_vintage(_vintage(obs=date(2026, 2, 1), vint=date(2026, 3, 1)))
    manifest.add_vintage(_vintage(obs=date(2026, 1, 1), vint=date(2026, 3, 1)))
    obs = [row.obs_date for row in manifest.entries("SYN_GDP")]
    assert obs == [date(2026, 1, 1), date(2026, 2, 1)]


def test_entries_unknown_series_returns_empty_list():
    manifest = VintageManifest()
    manifest.add_vintage(_vintage())
    assert manifest.entries("SYN_MISSING") == []


def test_to_list_is_canonical_and_plain():
    manifest = VintageManifest()
    manifest.add_vintage(_vintage(vint=date(2026, 3, 1)))
    manifest.add_vintage(_vintage(vint=date(2026, 2, 1)))
    rows = manifest.to_list()
    assert len(rows) == 2
    assert all(isinstance(row, dict) for row in rows)
    keys = [(row["series_id"], row["obs_date"], row["vintage_date"]) for row in rows]
    assert keys == sorted(keys)
