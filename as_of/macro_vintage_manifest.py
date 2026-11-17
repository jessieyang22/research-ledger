"""Vintage manifest for macro series.

A macro series is published many times. Each release (a vintage) can revise
the value of an observation that was published earlier. This module keeps
every release of every observation, so a later reader can see what was known
on a given date rather than only the latest revised value.

The manifest is keyed by (series_id, obs_date, vintage_date). Adding the same
key twice is an error, because a release should be recorded once. Entries can
be listed per series, sorted by vintage_date. The whole set has a stable hash,
so a change to any value, date or row order that changes the set is visible
as a change in the hash.

Topic: macro vintage manifest.

All data handled here is synthetic. Only the standard library and the shared
as_of.core and as_of.content_hash modules are used.
"""

import math
from datetime import date, datetime
from typing import Any, Dict, List, Tuple

from as_of.content_hash import hash_records
from as_of.core import AsOfError, MacroVintage, ensure_utc, require, to_plain

_KeyType = Tuple[str, Any, Any]


def _row_key(v: MacroVintage) -> _KeyType:
    """Sort key for the whole manifest: series, then observation, then vintage."""
    return (v.series_id, v.obs_date, v.vintage_date)


class VintageManifest:
    """Collection of macro vintages, one row per (series, obs date, vintage date)."""

    def __init__(self) -> None:
        self._rows: Dict[_KeyType, MacroVintage] = {}

    def add_vintage(self, v: MacroVintage) -> None:
        """Record one release. A duplicate key raises AsOfError and changes nothing."""
        require(isinstance(v, MacroVintage), "expected MacroVintage, got %s" % type(v).__name__)
        # Check every field now, so a bad row never lands in the manifest and
        # fails later inside manifest_hash() or to_list().
        require(isinstance(v.series_id, str) and v.series_id != "", "series_id must be a non-empty str")
        for name, value in (("obs_date", v.obs_date), ("vintage_date", v.vintage_date)):
            # datetime is a subclass of date; mixing the two makes sorting raise TypeError.
            require(
                isinstance(value, date) and not isinstance(value, datetime),
                "%s must be a plain date, got %s" % (name, type(value).__name__),
            )
        require(
            isinstance(v.value, (int, float)) and not isinstance(v.value, bool),
            "value must be a real number, got %s" % type(v.value).__name__,
        )
        # float(10**400) raises OverflowError; convert that to the module's own error.
        try:
            finite = math.isfinite(float(v.value))
        except OverflowError:
            raise AsOfError("value out of float range: %r" % (v.value,))
        require(finite, "value must be finite, got %r" % (v.value,))
        ensure_utc(v.release_at)
        key = _row_key(v)
        if key in self._rows:
            raise AsOfError(
                "duplicate vintage for series=%r obs=%s vintage=%s"
                % (v.series_id, v.obs_date, v.vintage_date)
            )
        self._rows[key] = v

    def entries(self, series_id: str) -> List[MacroVintage]:
        """Return every vintage for one series, sorted by vintage_date.

        Ties on vintage_date are broken by obs_date so the order is fixed.
        An unknown series returns an empty list.
        """
        selected = [v for v in self._rows.values() if v.series_id == series_id]
        selected.sort(key=lambda v: (v.vintage_date, v.obs_date))
        return selected

    def _sorted_rows(self) -> List[MacroVintage]:
        return [self._rows[key] for key in sorted(self._rows, key=lambda k: k)]

    def manifest_hash(self) -> str:
        """Hex SHA-256 over all rows in canonical order.

        The result does not depend on the order in which rows were added.
        Changing any field of any row changes the hash.
        """
        return hash_records(self._sorted_rows())

    def to_list(self) -> List[Dict[str, Any]]:
        """Return all rows as plain dicts in canonical order, ready for JSON."""
        return [to_plain(v) for v in self._sorted_rows()]
