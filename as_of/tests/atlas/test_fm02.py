"""Failure mode fm02: SEC request blocked (fair-access or traffic limits).

Planted failure: a sequence of fetch attempts against a synthetic source
returns block or throttle responses. The pipeline must detect the block,
back off, fall back to a cached or manually downloaded copy, and log the
response code per request. A silently dropped run must not look healthy.

All data here is synthetic. No network calls are made.

Findings from the existing modules:
- run_timeliness can detect a dropped run (a slot with no actual run is MISSED
  and yields a FAIL finding). That part of fm02 is covered and tested below.
- No existing module reads HTTP response codes, detects 403/429 blocks,
  applies backoff, or falls back to a cached copy when a fetch is blocked.
  Those requirements are written as strict xfail tests with the gap stated.
"""

from datetime import datetime, timezone

import pytest

from as_of.core import RunStatus, ValidationStatus
from as_of.run_timeliness import (
    ScheduleContract,
    classify_runs,
    handling_action,
    late_or_missed_findings,
)


def _utc(hour, minute=0):
    return datetime(2026, 10, 1, hour, minute, tzinfo=timezone.utc)


# Partially covered: a blocked and silently dropped run is detected as MISSED.


def test_fm02_dropped_run_after_block_is_flagged_missed():
    # Synthetic schedule: hourly fetch slots. The 10:00 fetch is blocked and
    # produces no finished run, so the pipeline must not record it as on time.
    contract = ScheduleContract(name="synthetic_sec_fetch", grace_minutes=15)
    slots = [_utc(9), _utc(10), _utc(11)]
    actual = [_utc(9, 1), _utc(11, 2)]  # no run for the blocked 10:00 slot

    rows = classify_runs(contract, slots, actual)

    assert [r["status"] for r in rows] == [RunStatus.ON_TIME, RunStatus.MISSED, RunStatus.ON_TIME]
    assert handling_action(rows[1]["status"]) == "escalate_incident"
    findings = late_or_missed_findings(rows)
    assert len(findings) == 1
    assert findings[0].check_id == "run_missed"
    assert findings[0].status is ValidationStatus.FAIL


def test_fm02_retried_run_that_lands_late_is_not_hidden():
    # A run that succeeds only after backoff lands outside the grace window.
    # It must surface as LATE (WARN), not as on time.
    contract = ScheduleContract(name="synthetic_sec_fetch", grace_minutes=15)
    rows = classify_runs(contract, [_utc(9)], [_utc(9, 40)])
    assert rows[0]["status"] is RunStatus.LATE
    findings = late_or_missed_findings(rows)
    assert [f.check_id for f in findings] == ["run_late"]
    assert findings[0].status is ValidationStatus.WARN


# Gaps: the following requirements have no implementation in as_of.


@pytest.mark.xfail(
    strict=True,
    reason="GAP fm02: no module reads HTTP status codes or detects 403/429 block or throttle responses",
)
def test_fm02_block_response_is_detected():
    from as_of import fetch_guard  # noqa: F401  (does not exist; this is the gap)

    responses = [{"url": "synthetic://edgar/filing/1", "status": 429}]
    findings = fetch_guard.check_responses(responses)
    assert any(f.status is ValidationStatus.FAIL for f in findings)


@pytest.mark.xfail(
    strict=True,
    reason="GAP fm02: no backoff or retry-limit logic exists; repeated blocked requests are not throttled",
)
def test_fm02_repeated_blocks_trigger_backoff_not_retry_storm():
    from as_of import fetch_guard  # noqa: F401  (does not exist; this is the gap)

    attempts = [{"status": 429}] * 5
    plan = fetch_guard.next_action(attempts)
    assert plan.action == "backoff"
    assert plan.max_attempts_exceeded is True


@pytest.mark.xfail(
    strict=True,
    reason="GAP fm02: no fallback to a cached or manually downloaded copy when a fetch is blocked",
)
def test_fm02_blocked_fetch_falls_back_to_cached_copy():
    from as_of import fetch_guard  # noqa: F401  (does not exist; this is the gap)

    result = fetch_guard.resolve_source(status=403, cached_copy_sha256="a" * 64)
    assert result.used_fallback is True


@pytest.mark.xfail(
    strict=True,
    reason="GAP fm02: no per-request response code log exists; the requirement is not implemented",
)
def test_fm02_every_request_logs_its_response_code():
    from as_of import fetch_guard  # noqa: F401  (does not exist; this is the gap)

    log = fetch_guard.request_log([{"url": "synthetic://x", "status": 200}])
    assert log[0]["status"] == 200
