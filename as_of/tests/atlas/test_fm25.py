"""Failure mode fm25: secret appears in a prompt or file.

A credential is written into a prompt, file or log, which exposes it outside
the approved boundary. The expected controls are: detect credential-shaped text
in files and text before it is shared, redact it in every message, block
readiness while it is present, and record the exposure so the credential is
rotated and the incident is closed with a root cause.

Fixtures use the SYN_ prefix and fake key shapes. The fake key is assembled at
runtime from two parts so that this source file does not itself contain a
credential-shaped literal, which would be flagged by the package-wide scan.

Findings from the existing modules:
- secrets_scanner detects a planted AWS-shaped key in text and in files, flags
  a .env file on name alone, and never prints the full value. Tested as
  detected.
- readiness_record blocks a go when a secrets item fails or a FAIL finding from
  the scanner is present, and allows a go once the file is clean. Tested as
  blocked, then as cleared after removal.
- cli secrets-scan returns a failing exit code and does not echo the full value.
  Tested as detected.
- incident_records can open and close an exposure incident with a root cause,
  but it has no rotation field, so rotation is not recorded. That is a gap.
- jsonl_store.append_record, pm_packet_assembly.assemble_packet and
  handoff text do not scan for credential-shaped values. Those are gaps.
  They are written as strict xfail tests and reported, not faked.
"""

import dataclasses
from datetime import date, datetime, timezone

import pytest

from as_of import cli
from as_of.core import AsOfError, ReadinessItem, Severity, ValidationStatus
from as_of.incident_records import add_timeline_event, close_incident, open_incident
from as_of.jsonl_store import append_record
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER, assemble_packet
from as_of.readiness_record import build_readiness
from as_of.secrets_scanner import redact, scan_paths, scan_text

# Synthetic AWS-shaped access key ID, built at runtime (not a real credential).
SYN_KEY = "AKIA" + "SYN7THET1C000000"
SYN_CHECK_PREFIX = "secret."


def _planted_prompt_text() -> str:
    """Prompt-like text that carries one planted key on its own line."""
    return (
        "Summarize the filing notes for SYN_TICKER.\n"
        "aws credentials for the bucket: %s\n"
        "Return the summary in plain text.\n" % SYN_KEY
    )


def _secret_findings_for(text: str, name: str = "SYN_prompt"):
    return [f for f in scan_text(text, name=name) if f.status is ValidationStatus.FAIL]


# Detection: the planted secret is found in text and in files.


def test_fm25_planted_key_in_prompt_text_is_flagged():
    findings = _secret_findings_for(_planted_prompt_text())
    assert [f.check_id for f in findings] == [SYN_CHECK_PREFIX + "aws_access_key_id"]
    assert findings[0].status is ValidationStatus.FAIL
    # The finding points at the planted line (line 2), not at a neighbour.
    assert "line 2" in findings[0].message


def test_fm25_planted_key_in_file_is_flagged(tmp_path):
    notes = tmp_path / "SYN_notes.txt"
    notes.write_text(_planted_prompt_text(), encoding="utf-8")
    findings = [f for f in scan_paths([str(notes)]) if f.status is ValidationStatus.FAIL]
    assert [f.check_id for f in findings] == [SYN_CHECK_PREFIX + "aws_access_key_id"]
    assert findings[0].subject == str(notes)


def test_fm25_planted_dotenv_file_is_flagged_on_name_alone(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"")  # empty on purpose: the name alone must block
    findings = scan_paths([str(env_file)])
    assert any(f.check_id == SYN_CHECK_PREFIX + "dotenv_file" for f in findings)
    assert all(f.status is ValidationStatus.FAIL for f in findings if f.check_id.endswith("dotenv_file"))


# Redaction: a finding must never print the full value.


def test_fm25_finding_message_never_contains_full_key():
    findings = scan_text(_planted_prompt_text(), name="SYN_prompt")
    assert findings, "precondition: the planted key must be detected"
    for finding in findings:
        assert SYN_KEY not in finding.message
        assert SYN_KEY not in finding.subject
    assert redact(SYN_KEY) == "AKIA" + "********"


def test_fm25_cli_secrets_scan_fails_and_does_not_echo_key(tmp_path, capsys):
    notes = tmp_path / "SYN_notes.txt"
    notes.write_text(_planted_prompt_text(), encoding="utf-8")
    code = cli.main(["secrets-scan", str(notes)])
    captured = capsys.readouterr()
    assert code == cli.EXIT_FAIL
    assert SYN_KEY not in captured.out
    assert SYN_KEY not in captured.err


# Blocking: a planted secret stops readiness until the file is clean.


def _item(item_id, passed):
    return ReadinessItem(item_id=item_id, passed=passed, evidence_ref="SYN_evidence/" + item_id)


def test_fm25_planted_secret_blocks_readiness(tmp_path):
    notes = tmp_path / "SYN_notes.txt"
    notes.write_text(_planted_prompt_text(), encoding="utf-8")
    scan = scan_paths([str(notes)])
    items = [_item("check.secrets_scan", passed=False), _item("proof.one", passed=True)]

    record = build_readiness(items, scan, 0)

    assert record["go"] is False
    assert record["blocking"], "a no-go must list at least one blocking reason"


def test_fm25_readiness_clears_after_secret_is_removed(tmp_path):
    notes = tmp_path / "SYN_notes.txt"
    notes.write_text(_planted_prompt_text(), encoding="utf-8")
    assert _secret_findings_for(notes.read_text(encoding="utf-8"))

    # Remediation: the key is removed from the file, then the scan runs again.
    notes.write_text("Summarize the filing notes for SYN_TICKER.\n", encoding="utf-8")
    scan = scan_paths([str(notes)])
    assert not [f for f in scan if f.status is ValidationStatus.FAIL]

    record = build_readiness([_item("check.secrets_scan", passed=True)], scan, 0)
    assert record["go"] is True


# Incident handling: an exposure can be recorded and closed with a root cause.


def test_fm25_exposure_incident_can_be_opened_and_closed_with_root_cause():
    inc = open_incident(
        "SYN_INC_FM25",
        "SYN planted credential found in a prompt file",
        Severity.BLOCK,
        date(2026, 10, 1),
    )
    inc = add_timeline_event(
        inc,
        datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        "SYN_detected: scanner flagged the planted key in the notes file",
    )
    closed = close_incident(inc, date(2026, 10, 2), "SYN root cause: key pasted into notes file")
    assert closed.root_cause.startswith("SYN root cause")


def test_fm25_incident_record_has_no_rotation_field_documented():
    """Documents the current design: no field records that a credential was rotated."""
    sample = open_incident("SYN_INC_FM25_B", "SYN summary", Severity.BLOCK, date(2026, 10, 1))
    names = [f.name for f in dataclasses.fields(type(sample))]
    assert not any("rotat" in n.lower() for n in names)


# Gaps: the following paths do not scan for credential-shaped values.


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GAP fm25: jsonl_store.append_record writes any dict without a secret scan, "
        "so a planted key in a log or ledger record is stored silently"
    ),
)
def test_fm25_log_record_with_planted_key_is_blocked(tmp_path):
    path = str(tmp_path / "SYN_log.jsonl")
    record = {
        "event": "SYN_run_note",
        "detail": "credential pasted: %s" % SYN_KEY,
        "at": datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
    }
    with pytest.raises(AsOfError):
        append_record(path, record)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GAP fm25: assemble_packet checks section keys and types only; a planted key "
        "in a section body is accepted into the PM packet"
    ),
)
def test_fm25_packet_section_with_planted_key_is_blocked():
    sections = {name: {} for name in PACKET_SECTION_ORDER}
    sections[PACKET_SECTION_ORDER[0]] = {"note": "credential pasted: %s" % SYN_KEY}
    with pytest.raises(AsOfError):
        assemble_packet("SYN_packet", date(2026, 10, 1), sections, [], [])
