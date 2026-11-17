"""Business-day and schedule-date arithmetic with a fixed 2026 holiday set.

Used by scheduling and timeliness checks. A business day here is any Monday
through Friday that is not in HOLIDAYS_2026.

Topic: "scheduling contract".

HOLIDAYS_2026 is a hand-written set of U.S. federal holidays as observed in
2026, plus Good Friday (2026-04-03), which is a common exchange closure. It
is a project choice, not a calendar taken from a published source. Dates
that fall on a weekend are listed on their observed weekday.

All data here is synthetic. The module depends only on as_of.core.
"""

from datetime import date, datetime, timedelta
from typing import FrozenSet, List

from as_of.core import require


HOLIDAYS_2026: FrozenSet[date] = frozenset(
    {
        date(2026, 1, 1),   # New Year's Day (Thu)
        date(2026, 1, 19),  # Martin Luther King Jr. Day (3rd Mon)
        date(2026, 2, 16),  # Washington's Birthday (3rd Mon)
        date(2026, 4, 3),   # Good Friday
        date(2026, 5, 25),  # Memorial Day (last Mon)
        date(2026, 6, 19),  # Juneteenth (Fri)
        date(2026, 7, 3),   # Independence Day observed (Jul 4 is a Sat)
        date(2026, 9, 7),   # Labor Day (1st Mon)
        date(2026, 10, 12),  # Columbus Day (2nd Mon)
        date(2026, 11, 11),  # Veterans Day (Wed)
        date(2026, 11, 26),  # Thanksgiving Day (4th Thu)
        date(2026, 12, 25),  # Christmas Day (Fri)
    }
)

_WEEKEND_DAYS: int = 5  # weekday() values 5 and 6 are Saturday and Sunday


def _as_date(value: object) -> date:
    """Return value unchanged when it is a plain date, else raise TypeError.

    datetime is rejected explicitly: it is a subclass of date, but it never
    compares equal to a date, so a datetime on a holiday would slip past the
    HOLIDAYS_2026 membership test. Callers must pass a date.
    """
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError("synthetic_calendar expects datetime.date, got %r" % type(value).__name__)
    return value


def is_business_day(d: date) -> bool:
    """Return True when d is a Monday to Friday and not in HOLIDAYS_2026."""
    d = _as_date(d)
    return d.weekday() < _WEEKEND_DAYS and d not in HOLIDAYS_2026


def next_business_day(d: date) -> date:
    """Return the first business day strictly after d."""
    d = _as_date(d)
    candidate = d + timedelta(days=1)
    while not is_business_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def business_days_between(start: date, end: date) -> int:
    """Count business days in the half-open range [start, end).

    If end is earlier than start, the result is the negated count for the
    reversed range, so the function is antisymmetric in its arguments.
    """
    start = _as_date(start)
    end = _as_date(end)
    if end < start:
        return -business_days_between(end, start)
    count = 0
    current = start
    while current < end:
        if is_business_day(current):
            count += 1
        current += timedelta(days=1)
    return count


def scheduled_dates(start: date, end: date, weekdays_only: bool) -> List[date]:
    """List dates in the half-open range [start, end), in ascending order.

    When weekdays_only is True, only Monday to Friday dates are returned and
    holidays are kept. When it is False, every calendar day is returned.
    """
    start = _as_date(start)
    end = _as_date(end)
    require(start <= end, "scheduled_dates: start must not be after end")
    dates: List[date] = []
    current = start
    while current < end:
        if not weekdays_only or current.weekday() < _WEEKEND_DAYS:
            dates.append(current)
        current += timedelta(days=1)
    return dates
