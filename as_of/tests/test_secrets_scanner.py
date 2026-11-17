"""Tests for as_of.secrets_scanner. All fixtures are synthetic (SYN_ prefix or made-up keys)."""

from as_of.core import ValidationStatus
from as_of.secrets_scanner import redact, scan_paths, scan_text

# Synthetic AWS-style access key ID: fixed prefix plus 16 upper-case letters or digits.
# It is not a real credential.
SYN_AWS_KEY = "AKIASYN7THET1C000000"


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_aws_style_key_is_detected_and_value_absent_from_message():
    text = "line one\naws_key = %s\n" % SYN_AWS_KEY
    findings = scan_text(text, name="SYN_config")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "secret.aws_access_key_id"
    assert finding.status == ValidationStatus.FAIL
    assert finding.subject == "SYN_config"
    assert "line 2" in finding.message
    # The full value must never appear in the message, only a masked prefix.
    assert SYN_AWS_KEY not in finding.message
    assert SYN_AWS_KEY[4:] not in finding.message


def test_clean_text_gives_empty_list():
    text = "SYN_AAA close 10.0\nSYN_BBB close 12.5\nno secrets here\n"
    assert scan_text(text) == []


def test_empty_dotenv_file_is_flagged(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"")
    findings = scan_paths([str(env_file)])
    assert len(findings) == 1
    assert findings[0].check_id == "secret.dotenv_file"
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].subject == str(env_file)


def test_file_with_nul_bytes_is_skipped_without_error(tmp_path):
    binary_file = tmp_path / "blob.dat"
    # Contains a key-shaped string, but NUL bytes mark it as binary, so it is skipped.
    binary_file.write_bytes(b"\x00\x01\x02" + SYN_AWS_KEY.encode("ascii") + b"\x00")
    findings = scan_paths([str(binary_file)])
    assert findings == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_redact_keeps_only_a_short_prefix():
    masked = redact(SYN_AWS_KEY)
    assert masked.startswith(SYN_AWS_KEY[:4])
    assert SYN_AWS_KEY not in masked
    assert redact("") == ""
    assert redact("abc") == "********"


def test_redact_rejects_non_string():
    try:
        redact(123)  # type: ignore[arg-type]
    except TypeError:
        return
    raise AssertionError("redact should reject non-str input")


def test_scan_text_rejects_non_string():
    try:
        scan_text(b"bytes")  # type: ignore[arg-type]
    except TypeError:
        return
    raise AssertionError("scan_text should reject non-str input")


def test_private_key_header_is_detected():
    text = "-----BEGIN RSA PRIVATE KEY-----\nSYN_BODY\n-----END RSA PRIVATE KEY-----"
    findings = scan_text(text, name="SYN_key")
    names = [f.check_id for f in findings]
    assert "secret.private_key_block" in names
    key_findings = [f for f in findings if f.check_id == "secret.private_key_block"]
    assert len(key_findings) == 1
    assert "-----BEGIN RSA PRIVATE KEY-----" not in key_findings[0].message


def test_generic_secret_assignment_is_detected_and_value_masked():
    value = "SYN_longvalue_123456"
    text = 'api_key = "%s"\n' % value
    findings = scan_text(text, name="SYN_py")
    assert [f.check_id for f in findings] == ["secret.generic_secret_assignment"]
    assert value not in findings[0].message


def test_one_finding_per_match_on_multiple_lines():
    text = "%s\n%s\n" % (SYN_AWS_KEY, SYN_AWS_KEY)
    findings = scan_text(text)
    assert len(findings) == 2
    assert "line 1" in findings[0].message
    assert "line 2" in findings[1].message


def test_missing_path_gives_warn_and_scan_continues(tmp_path):
    missing = tmp_path / "does_not_exist.txt"
    good = tmp_path / "good.txt"
    good.write_text("SYN_plain text only\n", encoding="utf-8")
    findings = scan_paths([str(missing), str(good)])
    assert len(findings) == 1
    assert findings[0].check_id == "secret.unreadable"
    assert findings[0].status == ValidationStatus.WARN


def test_text_file_with_key_is_found_by_scan_paths(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("token dump: %s\n" % SYN_AWS_KEY, encoding="utf-8")
    findings = scan_paths([str(f)])
    assert [x.check_id for x in findings] == ["secret.aws_access_key_id"]
    assert SYN_AWS_KEY not in findings[0].message
