"""Synthetic macro series with revisions, for exercising vintage and cutoff logic.

This fixture builds a small, fully synthetic set of macro releases. Two series
are produced, SYN_GDP and SYN_CPI. Each observation (one per month) gets a
first release, and some observations get a later revised release. Every
release is a MacroVintage record from as_of.core, so a test can ask what was
known on a given date and see a different value than the latest one.

Design points:
  * Every series_id starts with SYN_ (see SYNTHETIC_PREFIX in as_of.core).
  * A release never happens before its observation date. The release date is
    the observation date plus a fixed lag, and a revision comes after that.
  * Randomness comes only from a numpy Generator built by make_rng(seed), and
    draws are taken in a fixed order, so a fixed seed gives identical output.
  * Output is sorted by (series_id, obs_date, vintage_date).

Topic: synthetic fixtures.

All data handled here is synthetic. Only as_of.core is imported.
"""

from datetime import date, datetime, timedelta, timezone
from typing import List, Tuple

from as_of.core import SYNTHETIC_SEED, AsOfError, MacroVintage, make_rng

# (series_id, base level, release lag in days, noise scale)
_SERIES_SPECS: Tuple[Tuple[str, float, int, float], ...] = (
    ("SYN_GDP", 2.0, 30, 0.6),
    ("SYN_CPI", 2.5, 14, 0.4),
)

_OBS_MONTHS: int = 12
_OBS_START: date = date(2025, 1, 1)
_REVISION_EVERY: int = 3
_REVISION_DELAY_DAYS: int = 60
_REVISION_STEPS: Tuple[float, ...] = (-0.3, -0.2, -0.1, 0.1, 0.2, 0.3)


def _add_months(start: date, months: int) -> date:
    """Return the first day of the month that is `months` after start."""
    total = start.year * 12 + (start.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def _as_release_datetime(day: date) -> datetime:
    """Midnight UTC on the given day, as an aware datetime."""
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def make_macro_fixture(seed: int = SYNTHETIC_SEED) -> List[MacroVintage]:
    """Build synthetic macro vintages for SYN_GDP and SYN_CPI.

    For each series and each monthly observation date, the first release lands
    at obs_date plus the series lag. Every third observation (by position) is
    later revised by a nonzero step, released _REVISION_DELAY_DAYS after the
    first release. Returns a list sorted by (series_id, obs_date, vintage_date).
    The same seed always returns an equal list.
    """
    # Reject seeds that numpy would accept silently or reject with a bare error.
    # None would draw OS entropy (non-reproducible); bool is an int subclass.
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise AsOfError("seed must be an int, got %s" % type(seed).__name__)
    if seed < 0:
        raise AsOfError("seed must be non-negative, got %d" % seed)
    rng = make_rng(seed)
    rows: List[MacroVintage] = []

    for series_id, base, lag_days, noise_scale in _SERIES_SPECS:
        for idx in range(_OBS_MONTHS):
            obs_date = _add_months(_OBS_START, idx)
            noise = float(rng.normal(0.0, noise_scale))
            first_value = round(base + noise, 2)

            first_day = obs_date + timedelta(days=lag_days)
            source_id = "SYN_SRC_%s" % series_id
            rows.append(
                MacroVintage(
                    series_id=series_id,
                    obs_date=obs_date,
                    vintage_date=first_day,
                    release_at=_as_release_datetime(first_day),
                    value=first_value,
                    source_id=source_id,
                )
            )

            if idx % _REVISION_EVERY == 0:
                step = _REVISION_STEPS[int(rng.integers(0, len(_REVISION_STEPS)))]
                revised_value = round(first_value + step, 2)
                revised_day = first_day + timedelta(days=_REVISION_DELAY_DAYS)
                rows.append(
                    MacroVintage(
                        series_id=series_id,
                        obs_date=obs_date,
                        vintage_date=revised_day,
                        release_at=_as_release_datetime(revised_day),
                        value=revised_value,
                        source_id=source_id,
                    )
                )

    rows.sort(key=lambda v: (v.series_id, v.obs_date, v.vintage_date))
    return rows
