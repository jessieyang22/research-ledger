"""Scheduling contract: a named cadence, due time, grace window and business-day rule.

A ScheduleContract describes when a recurring as-of run is expected. It holds
a name, a cadence ('daily', 'weekly' or 'monthly'), a due time of day as
'HH:MM', a grace window in minutes and a flag that drops weekend dates.

expected_runs() turns a contract and a date range into the naive local
datetimes at which runs are due. Grace minutes are stored and exposed but are
not applied here; a later status check decides whether a run was on time, late
or missed.

Conventions used by this module:
    - weekly runs fall on the weekday of the range start, every 7 days;
    - monthly runs fall on the day of month of the range start, clamped to the
      last day of shorter months;
    - business_days_only drops Saturdays and Sundays. It does not roll the run
      forward, and no holiday calendar is applied.

Shared types and errors come from as_of.core. No other as_of module is needed,
and no network, file or market data is touched. All data is synthetic.
"""

import calendar
import re
from datetime import date, datetime, time, timedelta
from typing import List

from as_of.core import AsOfError, require


CADENCES = ("daily", "weekly", "monthly")

_DUE_TIME_RE = re.compile(r"[0-9]{2}:[0-9]{2}")


def _parse_due_time(due_time: str) -> time:
    """Return due_time as a time object. Anything not 'HH:MM' in range raises AsOfError."""
    require(isinstance(due_time, str), "due_time must be a str, got %s" % type(due_time).__name__)
    require(_DUE_TIME_RE.fullmatch(due_time) is not None, "due_time must be 'HH:MM': %r" % (due_time,))
    hour = int(due_time[0:2])
    minute = int(due_time[3:5])
    require(0 <= hour <= 23, "due_time hour out of range: %r" % (due_time,))
    require(0 <= minute <= 59, "due_time minute out of range: %r" % (due_time,))
    return time(hour, minute)


class ScheduleContract:
    """A named recurring schedule with a due time, grace window and weekend rule."""

    def __init__(
        self,
        name: str,
        cadence: str,
        due_time: str,
        grace_minutes: int,
        business_days_only: bool,
    ) -> None:
        require(isinstance(name, str) and name.strip() != "", "name must be a non-empty str")
        require(cadence in CADENCES, "cadence must be one of %s, got %r" % (CADENCES, cadence))
        due = _parse_due_time(due_time)
        require(
            isinstance(grace_minutes, int) and not isinstance(grace_minutes, bool),
            "grace_minutes must be an int, got %s" % type(grace_minutes).__name__,
        )
        require(grace_minutes >= 0, "grace_minutes must not be negative")
        require(
            isinstance(business_days_only, bool),
            "business_days_only must be a bool, got %s" % type(business_days_only).__name__,
        )
        self.name = name
        self.cadence = cadence
        self.due_time = due_time
        self.grace_minutes = grace_minutes
        self.business_days_only = business_days_only
        self._due = due

    def __repr__(self) -> str:
        return (
            "ScheduleContract(name=%r, cadence=%r, due_time=%r, grace_minutes=%r, "
            "business_days_only=%r)"
            % (self.name, self.cadence, self.due_time, self.grace_minutes, self.business_days_only)
        )


def _candidate_dates(contract: ScheduleContract, start: date, end: date) -> List[date]:
    """Return the calendar dates on which the contract cadence fires within [start, end]."""
    out: List[date] = []
    if contract.cadence == "daily":
        day = start
        while day <= end:
            out.append(day)
            day += timedelta(days=1)
    elif contract.cadence == "weekly":
        day = start
        while day <= end:
            out.append(day)
            day += timedelta(days=7)
    else:
        anchor_day = start.day
        year, month = start.year, start.month
        while date(year, month, 1) <= end:
            last = calendar.monthrange(year, month)[1]
            candidate = date(year, month, min(anchor_day, last))
            if start <= candidate <= end:
                out.append(candidate)
            month += 1
            if month == 13:
                month = 1
                year += 1
    return out


def expected_runs(contract: ScheduleContract, start: date, end: date) -> List[datetime]:
    """Return the naive local datetimes at which contract is due, for dates in [start, end].

    Each run is the scheduled calendar date combined with the contract due time.
    When business_days_only is set, Saturdays and Sundays are dropped. The
    result is in chronological order.
    """
    require(isinstance(contract, ScheduleContract), "contract must be a ScheduleContract")
    require(isinstance(start, date) and isinstance(end, date), "start and end must be dates")
    if isinstance(start, datetime) or isinstance(end, datetime):
        raise AsOfError("start and end must be dates, not datetimes")
    require(start <= end, "start must not be after end")

    runs: List[datetime] = []
    for day in _candidate_dates(contract, start, end):
        if contract.business_days_only and day.weekday() >= 5:
            continue
        runs.append(datetime.combine(day, contract._due))
    return runs
