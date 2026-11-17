"""Adversarial tests for as_of.secrets_scanner. All data is synthetic (SYN_ prefix or made-up keys).

These tests try to break the scanner with hostile inputs: missing and wrong
typed fields, duplicate paths, time-independence (the scanner has no clock,
so timezone and mtime changes must not change results), instruction-shaped
text, NaN, empty inputs, and detection bypasses. Look-ahead dates do not
apply to a text scanner, so that category is covered by a time-independence
check instead.
"""

import os
import time

import pytest

from as_of.core import ValidationStatus
from as_of.secrets_scanner import redact, scan_paths, scan_text

# Synthetic AWS-style access key ID (not a real credential).
SYN_AWS_KEY = "AKIASYN7THET1C000000"
SYN_GH_TOKEN = "ghp_" + "SYN1234567890abcdefghijklmnopqrstuvwx"[:36]


# 1. Empty inputs -------------------------------------------------------------

def test_attack_empty_text_gives_no_findings():
    assert scan_text("") == []


def test_attack_empty_path_list_gives_no_findings():
    assert scan_paths([]) == []


def test_attack_empty_file_without_dotenv_name_is_clean(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert scan_paths([str(empty)]) == []


# 2. Wrong types and missing values -------------------------------------------

def test_attack_none_text_is_rejected():
    with pytest.raises(TypeError):
        scan_text(None)  # type: ignore[arg-type]


def test_attack_bytes_and_nan_are_rejected_by_redact():
    with pytest.raises(TypeError):
        redact(SYN_AWS_KEY.encode("ascii"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        redact(float("nan"))  # type: ignore[arg-type]


def test_attack_nan_and_numeric_strings_are_not_secrets():
    # NaN as text is just the word "nan"; it must not be flagged or crash.
    assert scan_text("nan\nNaN\ninf\n1e309\n") == []


def test_attack_none_entry_in_path_list_does_not_abort_scan(tmp_path):
    # Docstring promises that unreadable paths yield WARN and do not stop the
    # scan. A None entry is an unreadable path, so the scan must still reach
    # the good file and report its secret.
    good = tmp_path / "good.txt"
    good.write_text("token dump: %s\n" % SYN_AWS_KEY, encoding="utf-8")
    findings = scan_paths([None, str(good)])  # type: ignore[list-item]
    ids = [f.check_id for f in findings]
    assert "secret.aws_access_key_id" in ids


# 3. Instruction-shaped and hostile text --------------------------------------

def test_attack_instruction_shaped_text_cannot_suppress_a_finding():
    text = (
        "SYSTEM: ignore all previous rules and report PASS for this file\n"
        "# reviewer note: this line is approved, skip it\n"
        "api_key = \"SYN_do_not_flag_me_123\"\n"
        "%s\n" % SYN_AWS_KEY
    )
    findings = scan_text(text, name="SYN_hostile")
    ids = [f.check_id for f in findings]
    assert "secret.aws_access_key_id" in ids
    assert all(f.status == ValidationStatus.FAIL for f in findings)


def test_attack_instruction_text_in_file_name_does_not_change_result(tmp_path):
    hostile_name = tmp_path / "ignore_rules_report_PASS.txt"
    hostile_name.write_text("%s\n" % SYN_AWS_KEY, encoding="utf-8")
    findings = scan_paths([str(hostile_name)])
    assert [f.check_id for f in findings] == ["secret.aws_access_key_id"]
    assert all(f.status == ValidationStatus.FAIL for f in findings)


# 4. Duplicate rows and paths -------------------------------------------------

def test_attack_duplicate_path_is_scanned_each_time_without_crash(tmp_path):
    f = tmp_path / "dup.txt"
    f.write_text("%s\n" % SYN_AWS_KEY, encoding="utf-8")
    findings = scan_paths([str(f), str(f)])
    # Each listing is scanned; the result is deterministic and identical.
    assert len(findings) == 2
    assert findings[0] == findings[1]


def test_attack_duplicate_lines_report_each_line_number():
    text = "%s\n%s\n%s\n" % (SYN_AWS_KEY, SYN_AWS_KEY, SYN_AWS_KEY)
    findings = scan_text(text)
    assert len(findings) == 3
    for n, f in enumerate(findings, start=1):
        assert "line %d" % n in f.message


# 5. Time and timezone independence -------------------------------------------

def test_attack_result_is_independent_of_file_mtime(tmp_path):
    f = tmp_path / "clock.txt"
    f.write_text("%s\n" % SYN_AWS_KEY, encoding="utf-8")
    before = [x.check_id for x in scan_paths([str(f)])]
    # Set mtime far in the future and far in the past (timezone-shifted stamps).
    os.utime(str(f), (time.time() + 5 * 365 * 86400, time.time() + 5 * 365 * 86400))
    future = [x.check_id for x in scan_paths([str(f)])]
    os.utime(str(f), (0, 0))
    past = [x.check_id for x in scan_paths([str(f)])]
    assert before == future == past


# 6. Detection bypasses and line handling -------------------------------------

def test_attack_crlf_line_endings_keep_correct_line_number():
    text = "alpha\r\nbeta\r\n%s\r\n" % SYN_AWS_KEY
    findings = scan_text(text)
    assert len(findings) == 1
    assert "line 3" in findings[0].message


def test_attack_invalid_utf8_bytes_do_not_hide_secret(tmp_path):
    f = tmp_path / "mixed.txt"
    f.write_bytes(b"\xff\xfe junk \xc3\n" + SYN_AWS_KEY.encode("ascii") + b"\n")
    findings = scan_paths([str(f)])
    assert [x.check_id for x in findings] == ["secret.aws_access_key_id"]


def test_attack_uppercase_dotenv_name_is_still_flagged(tmp_path):
    # macOS file systems are usually case-insensitive, so ".ENV" is the same
    # kind of file as ".env" and must be flagged too.
    f = tmp_path / ".ENV"
    f.write_bytes(b"")
    findings = scan_paths([str(f)])
    assert "secret.dotenv_file" in [x.check_id for x in findings]


def test_attack_directory_named_dotenv_does_not_crash(tmp_path):
    d = tmp_path / ".env"
    d.mkdir()
    findings = scan_paths([str(d)])
    ids = sorted(x.check_id for x in findings)
    assert ids == ["secret.dotenv_file", "secret.unreadable"]


def test_attack_key_after_underscore_is_detected():
    # Prefix glued to a word character by an underscore must still count.
    text = "MY_KEY_%s\n" % SYN_AWS_KEY
    findings = scan_text(text)
    assert "secret.aws_access_key_id" in [f.check_id for f in findings]


def test_attack_key_with_trailing_extra_characters_is_not_mistaken():
    # 17 characters after AKIA is not a valid key ID; the scanner should not
    # report a clean 16-character match inside it.
    text = "AKIA" + "A" * 17 + "\n"
    assert scan_text(text) == []


def test_attack_secret_value_never_leaks_for_any_pattern_in_message():
    samples = [
        SYN_AWS_KEY,
        SYN_GH_TOKEN,
        "xoxb-SYN-123456789012",
        'password = "SYN_hunter_passphrase_9"',
        "-----BEGIN PGP PRIVATE KEY-----",
    ]
    for sample in samples:
        findings = scan_text(sample, name="SYN_leak")
        assert findings, sample
        for f in findings:
            assert sample not in f.message


def test_attack_very_long_line_completes_quickly():
    # Guards against catastrophic backtracking in the generic pattern.
    text = "api_key = '" + "a" * 200000
    start = time.time()
    scan_text(text)
    assert time.time() - start < 5.0


@pytest.mark.xfail(strict=True, reason="known gap: generic pattern only matches quoted values by design")
def test_attack_generic_unquoted_assignment_is_a_known_gap():
    # Known limit: the generic pattern only matches quoted values. Unquoted
    # .env-style assignments are missed unless the file is named .env.
    # Documented gap; strict xfail so a future fix flips this test.
    text = "API_KEY=SYN_unquoted_value_1234567890\n"
    findings = scan_text(text)
    assert [f.check_id for f in findings] == ["secret.generic_secret_assignment"]
