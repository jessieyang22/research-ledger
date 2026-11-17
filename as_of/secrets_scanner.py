"""Scan text and files for credential-shaped strings.

This module is a control check. It looks for strings that have the shape of
credentials (cloud access keys, private key headers, tokens, and generic
secret assignments) so that they are caught before they reach a repository,
a report or a handoff packet.

Reporting rules:

* Findings carry line numbers and a redacted form of the value, never the
  value itself. A message must be safe to print to a log.
* Files that contain NUL bytes are treated as binary and skipped.
* A file named ``.env`` is always flagged, even when it is empty, because the
  file name alone signals that it is meant to hold local secrets.

Topic: controls and secrets. The patterns here are original; they are not
copied from any source.

All data handled here is synthetic. This module makes no network calls and
does not execute anything it reads.

Imports: standard library only, plus ``as_of.core`` for the shared types.
"""

import os
import re
from typing import Dict, List, Pattern, Sequence

from as_of.core import Finding, ValidationStatus


CHECK_PREFIX: str = "secret"
DOTENV_NAME: str = ".env"
_MASK: str = "********"
_KEEP_CHARS: int = 4
# Only keep a visible prefix when the value is long enough that the prefix
# reveals a small share of it. Shorter values are fully masked.
_MIN_LEN_FOR_PREFIX: int = 16


PATTERNS: Dict[str, Pattern] = {
    # AWS access key IDs: a fixed prefix followed by 16 upper-case letters or digits.
    "aws_access_key_id": re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])"),
    # AWS secret access keys, when written next to their variable name.
    # The value may end in "/", "+" or "=", so the end is checked with a
    # lookahead instead of a word boundary.
    "aws_secret_access_key": re.compile(
        r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"
    ),
    # PEM-style private key headers (RSA, EC, DSA, OpenSSH, PGP, encrypted and plain).
    "private_key_block": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"
    ),
    # GitHub personal, OAuth and server tokens with their documented prefixes.
    "github_token": re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36}(?![A-Za-z0-9])"),
    # Slack bot and user tokens.
    "slack_token": re.compile(r"\bxox[bpars]-[A-Za-z0-9-]{10,}\b"),
    # Generic assignments such as api_key = "..." with a long quoted value.
    # No leading word boundary: "_" is a word character, so \b would miss
    # names like db_password or client_secret.
    "generic_secret_assignment": re.compile(
        r"(?i)(?:api[_-]?key|secret|token|passwd|password)\s*[=:]\s*"
        r"['\"][^'\"\s]{12,}['\"]"
    ),
}


def redact(s: str) -> str:
    """Return a masked form of a secret value that is safe to print.

    The first few characters are kept so a reader can tell which kind of
    value was found. Everything after them is replaced by a fixed mask, so
    the output never reproduces the full value and its length is not leaked.
    """
    if not isinstance(s, str):
        raise TypeError("redact expects str, got %s" % type(s).__name__)
    if not s:
        return ""
    if len(s) < _MIN_LEN_FOR_PREFIX:
        return _MASK
    return s[:_KEEP_CHARS] + _MASK


def _finding(name: str, status: ValidationStatus, message: str, subject: str) -> Finding:
    """Build a Finding whose check id is namespaced under CHECK_PREFIX."""
    return Finding(
        check_id="%s.%s" % (CHECK_PREFIX, name),
        status=status,
        message=message,
        subject=subject,
    )


def scan_text(text: str, name: str = "<text>") -> List[Finding]:
    """Scan text line by line for credential-shaped strings.

    Each match becomes a FAIL finding. The message gives the pattern name,
    the source name, the 1-indexed line number and a redacted value. The
    full value never appears in the message. Clean text returns an empty
    list.
    """
    if not isinstance(text, str):
        raise TypeError("scan_text expects str, got %s" % type(text).__name__)
    findings: List[Finding] = []
    # Split on "\n" only. str.splitlines() also breaks on form feeds and other
    # separators, which would shift the reported line numbers away from what
    # an editor shows. "\r\n" endings still give correct numbers.
    for line_no, line in enumerate(text.split("\n"), start=1):
        for pattern_name, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                findings.append(
                    _finding(
                        pattern_name,
                        ValidationStatus.FAIL,
                        "%s line %d: possible %s (value redacted: %s)"
                        % (name, line_no, pattern_name, redact(match.group(0))),
                        name,
                    )
                )
    return findings


def scan_paths(paths: Sequence[str]) -> List[Finding]:
    """Scan a sequence of file paths and return the findings.

    A file named ``.env`` is flagged on name alone, even when it is empty.
    Files that contain NUL bytes are skipped without a finding, since they
    are treated as binary. Paths that cannot be read produce a WARN finding
    and do not stop the scan.
    """
    findings: List[Finding] = []
    for path in paths:
        if not isinstance(path, (str, os.PathLike)):
            findings.append(
                _finding(
                    "unreadable",
                    ValidationStatus.WARN,
                    "%r: not a path, not scanned" % (type(path).__name__,),
                    str(path),
                )
            )
            continue
        # Compare case-insensitively: macOS file systems are usually
        # case-insensitive, so ".ENV" is the same kind of file as ".env".
        if os.path.basename(path).lower() == DOTENV_NAME:
            findings.append(
                _finding(
                    "dotenv_file",
                    ValidationStatus.FAIL,
                    "%s: file named .env should not be committed or shared" % path,
                    path,
                )
            )
        if not os.path.isfile(path):
            findings.append(
                _finding(
                    "unreadable",
                    ValidationStatus.WARN,
                    "%s: not a regular file, not scanned" % path,
                    path,
                )
            )
            continue
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            findings.append(
                _finding(
                    "unreadable",
                    ValidationStatus.WARN,
                    "%s: could not read file (%s)" % (path, exc.__class__.__name__),
                    path,
                )
            )
            continue
        if b"\x00" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        findings.extend(scan_text(text, name=path))
    return findings
