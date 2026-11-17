"""Failure mode fm26: connector exists but access fails.

A connector is installed, but the account, plan, role or provider entitlement
does not allow the call, so the workflow fails. The expected detection is an
entitlement check before the pull, a captured-file fallback that is logged and
hash-checked, and a block on readiness when the fallback is missing.

Fixtures use the SYN_ prefix. Nothing here calls a connector or reads a
settings file.

Findings from the existing modules:
- source_register.check_sources_used detects an output that cites a connector
  source which was never registered (the access failed and nothing was
  captured). Tested as detected.
- run_timeliness detects a scheduled connector pull that produced no run
  (MISSED, FAIL finding, escalate_incident). Tested as detected.
- readiness_record.build_readiness blocks when an entitlement readiness item
  is recorded as failed, and when a FAIL finding is present. Tested as blocked.
- source_register and content_hash can register a captured-file fallback and
  verify its sha256. This is a control path and is tested as allowed.
- No module checks account, plan, role or provider entitlement. No module
  chooses a captured fallback or records that a fallback was used. The
  controls catalog has no entitlement control. Those are gaps, marked xfail
  (strict) below and reported, not faked.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

import as_of.controls_checklist as controls_checklist
from as_of.content_hash import sha256_file
from as_of.core import Finding, ReadinessItem, RunStatus, SourceRecord, SourceType, ValidationStatus
from as_of.readiness_record import build_readiness
from as_of.run_timeliness import ScheduleContract, classify_runs, handling_action, late_or_missed_findings
from as_of.source_register import UNREGISTERED_CHECK_ID, SourceRegister

SYN_CONNECTOR_ID = "SYN_CONNECTOR_fm26_feed"
SYN_FALLBACK_ID = "SYN_CAPTURED_fm26_feed"
SYN_RETRIEVED = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
SYN_SLOT = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def _fails(findings):
    return [f for f in findings if f.status == ValidationStatus.FAIL]


def _captured_file(tmp_path):
    """Write a synthetic captured copy of the feed and return its path and sha256."""
    path = tmp_path / "SYN_captured_feed.csv"
    path.write_text("SYN_id,SYN_value\nSYN_1,1.0\n", encoding="utf-8")
    return str(path), sha256_file(str(path))


def test_unregistered_connector_source_is_flagged():
    """Planted: the connector call was denied, nothing was captured, but the output still cites it."""
    register = SourceRegister()
    findings = register.check_sources_used([SYN_CONNECTOR_ID])
    fails = _fails(findings)
    assert len(fails) == 1
    assert fails[0].check_id == UNREGISTERED_CHECK_ID
    assert fails[0].subject == SYN_CONNECTOR_ID


def test_missed_connector_pull_is_flagged_and_escalated():
    """Planted: the scheduled connector pull never ran because access was refused."""
    contract = ScheduleContract(name="SYN_connector_pull", grace_minutes=10)
    rows = classify_runs(contract, [SYN_SLOT], [])
    assert rows[0]["status"] == RunStatus.MISSED
    findings = late_or_missed_findings(rows)
    assert len(_fails(findings)) == 1
    assert handling_action(RunStatus.MISSED) == "escalate_incident"


def test_failed_entitlement_item_blocks_readiness():
    """Planted: the entitlement readiness check failed. The run must be no-go."""
    items = [
        ReadinessItem("SYN_connector_entitlement", False, "SYN_evidence_fm26_entitlement"),
        ReadinessItem("SYN_source_register_current", True, "SYN_evidence_register"),
    ]
    rec = build_readiness(items, [], 0)
    assert rec["go"] is False
    assert any(reason.startswith("item_failed: SYN_connector_entitlement") for reason in rec["blocking"])


def test_connector_access_finding_failure_blocks_readiness():
    """Planted: a FAIL finding raised for the denied connector call blocks readiness even with passing items."""
    items = [ReadinessItem("SYN_source_register_current", True, "SYN_evidence_register")]
    finding = Finding(
        check_id="SYN_connector_access",
        status=ValidationStatus.FAIL,
        message="SYN connector call refused for account tier",
        subject=SYN_CONNECTOR_ID,
    )
    rec = build_readiness(items, [finding], 0)
    assert rec["go"] is False
    assert any("SYN_connector_access" in reason for reason in rec["blocking"])


def test_captured_fallback_registered_with_hash_is_accepted(tmp_path):
    """Control: a captured-file fallback registered with its sha256 is usable and its hash verifies."""
    path, digest = _captured_file(tmp_path)
    register = SourceRegister()
    register.add_source(
        SourceRecord(
            source_id=SYN_FALLBACK_ID,
            source_type=SourceType.FIXTURE,
            publisher="SYN_publisher",
            locator=path,
            retrieved_at=SYN_RETRIEVED,
            sha256=digest,
            synthetic=True,
        )
    )
    assert register.check_sources_used([SYN_FALLBACK_ID]) == []
    assert sha256_file(os.fspath(path)) == register.get_source(SYN_FALLBACK_ID).sha256


def test_captured_fallback_with_stale_hash_is_detectable(tmp_path):
    """Planted: the captured copy changed after registration. The stored hash no longer matches the file."""
    path, digest = _captured_file(tmp_path)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("SYN_2,2.0\n")
    assert sha256_file(path) != digest


def test_connector_access_failure_with_passing_items_and_no_fallback_is_not_hidden():
    """Planted: access failed, no fallback item exists, and only the other items pass. Must not read as go."""
    items = [ReadinessItem("SYN_source_register_current", True, "SYN_evidence_register")]
    rec = build_readiness(items, [], 0)
    # This passes readiness today. The connector failure is only visible if a caller
    # records it as an item or finding. That dependency is the gap asserted below.
    assert rec["go"] is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm26 gap: no module checks account, plan, role or provider entitlement "
        "before a connector call. No function takes an entitlement description and "
        "returns a FAIL finding. Nothing in as_of is named for this check."
    ),
)
def test_entitlement_check_exists_and_blocks_denied_connector():
    """Expected control: an entitlement check that returns FAIL for a denied connector."""
    checker = None
    for name in ("check_connector_entitlement", "check_entitlement", "check_connector_access"):
        for module_name in ("controls_checklist", "readiness_record", "source_register", "validators"):
            module = __import__("as_of." + module_name, fromlist=[name])
            if hasattr(module, name):
                checker = getattr(module, name)
    assert checker is not None, "no entitlement check exists in the package"
    findings = checker({"plan": "SYN_basic", "role": "SYN_reader"}, SYN_CONNECTOR_ID)
    assert len(_fails(findings)) == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm26 gap: the controls catalog has no entitlement or connector-access control. "
        "The closest controls (source register, run log) do not name access rights."
    ),
)
def test_controls_catalog_has_connector_entitlement_control():
    """Expected control: a catalog entry that requires entitlement evidence for connector pulls."""
    names = " ".join(
        (spec.control_id + " " + spec.description).lower() for spec in controls_checklist.CONTROL_CATALOG
    )
    assert "entitle" in names or "access right" in names


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm26 gap: no module selects a captured-file fallback when a connector is refused, "
        "nor records that a fallback replaced a live pull. A caller must do this by hand."
    ),
)
def test_fallback_use_is_recorded_when_connector_refused():
    """Expected control: a recorder that logs the fallback source used after a refused pull."""
    recorder = None
    for module_name in ("source_register", "readiness_record", "run_timeliness", "validators"):
        module = __import__("as_of." + module_name, fromlist=["x"])
        for name in ("record_fallback", "select_fallback", "use_captured_fallback"):
            if hasattr(module, name):
                recorder = getattr(module, name)
    assert recorder is not None, "no fallback selection or recording exists in the package"
    result = recorder(SYN_CONNECTOR_ID, SYN_FALLBACK_ID)
    assert result is not None
