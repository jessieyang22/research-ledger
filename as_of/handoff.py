"""Handoff records for the as_of package.

A handoff is a short written record that one person or role passes to the next.
It carries a digest of the run state at hand-off time, the open items that are
still unresolved, the next steps, and the role that owns the next step.

This module builds the record, renders it as plain text, and validates it.
Validation requires an owner role and at least one next step, or an explicit
'none' entry that says no next step is needed.

The handoff digest is the stable hash of the record body. The body has no
timestamps and no host details, so the same inputs always give the same digest.

Design notes:

- The state digest comes from the StateManifest passed in, so a reader can tie
  the handoff to one exact run state.
- Validation returns Finding objects from as_of.core, the same shape other
  checks in the package use.


All data handled here is synthetic. This module imports only the standard
library, as_of.core and as_of.state_manifest. It does no network or subprocess
work.
"""

from typing import Any, Dict, List, Sequence

from as_of.core import AsOfError, Finding, ValidationStatus, require, stable_hash
from as_of.state_manifest import StateManifest


HANDOFF_FORMAT: str = "as_of.handoff"
HANDOFF_VERSION: int = 1
NONE_MARKER: str = "none"

_BODY_KEYS: Sequence[str] = (
    "format",
    "version",
    "title",
    "state_digest",
    "open_items",
    "next_steps",
    "owner_role",
)


def _clean_list(name: str, items: Sequence[str]) -> List[str]:
    """Return items as a list of str, checking each entry is a str."""
    require(not isinstance(items, str), "%s must be a sequence of str, not str" % name)
    out: List[str] = []
    for item in items:
        require(isinstance(item, str), "%s entries must be str, got %s" % (name, type(item).__name__))
        out.append(item)
    return out


def _body(h: Dict[str, Any]) -> Dict[str, Any]:
    """Return the digest-covered part of a handoff dict."""
    return {key: h.get(key) for key in _BODY_KEYS}


def build_handoff(
    title: str,
    state: StateManifest,
    open_items: Sequence[str],
    next_steps: Sequence[str],
    owner_role: str,
) -> Dict[str, Any]:
    """Build a handoff dict. Validation is left to validate_handoff."""
    require(isinstance(title, str) and title.strip() != "", "title must be a non-empty str")
    require(isinstance(state, StateManifest), "state must be a StateManifest")
    require(isinstance(owner_role, str), "owner_role must be a str")
    body: Dict[str, Any] = {
        "format": HANDOFF_FORMAT,
        "version": HANDOFF_VERSION,
        "title": title,
        "state_digest": state.digest(),
        "open_items": _clean_list("open_items", open_items),
        "next_steps": _clean_list("next_steps", next_steps),
        "owner_role": owner_role,
    }
    handoff = dict(body)
    handoff["digest"] = stable_hash(body)
    return handoff


def _one_line(value: Any) -> str:
    """Collapse line breaks so a value cannot start a new line of the rendered record."""
    return " ".join(str(value).splitlines())


def render_handoff(h: Dict[str, Any]) -> str:
    """Render a handoff dict as plain text with the state digest included.

    Every value is flattened to one line, so a newline inside a title or item
    cannot forge an extra field or section in the rendered text.
    """
    lines: List[str] = []
    lines.append("Handoff: %s" % _one_line(h.get("title", "")))
    lines.append("Owner role: %s" % _one_line(h.get("owner_role", "")))
    lines.append("State digest: %s" % _one_line(h.get("state_digest", "")))
    lines.append("Handoff digest: %s" % _one_line(h.get("digest", "")))
    lines.append("")
    lines.append("Open items:")
    open_items = h.get("open_items") or []
    if isinstance(open_items, str):
        # A bare str must render as one item, not as one line per character.
        open_items = [open_items]
    if open_items:
        for item in open_items:
            lines.append("- %s" % _one_line(item))
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Next steps:")
    next_steps = h.get("next_steps") or []
    if isinstance(next_steps, str):
        next_steps = [next_steps]
    if next_steps:
        for step in next_steps:
            lines.append("- %s" % _one_line(step))
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _finding(check_id: str, status: ValidationStatus, message: str, subject: str) -> Finding:
    return Finding(check_id=check_id, status=status, message=message, subject=subject)


def validate_handoff(h: Dict[str, Any]) -> List[Finding]:
    """Check a handoff dict and return one Finding per check."""
    findings: List[Finding] = []
    if not isinstance(h, dict):
        return [_finding("handoff.record", ValidationStatus.FAIL, "handoff must be a dict", "handoff")]
    subject = str(h.get("title") or "handoff")

    version = h.get("version")
    if h.get("format") == HANDOFF_FORMAT and type(version) is int and version == HANDOFF_VERSION:
        findings.append(_finding("handoff.format", ValidationStatus.PASS, "format and version recognised", subject))
    else:
        findings.append(_finding("handoff.format", ValidationStatus.FAIL, "format or version not recognised", subject))

    state_digest = h.get("state_digest")
    if isinstance(state_digest, str) and state_digest != "":
        findings.append(_finding("handoff.state_digest", ValidationStatus.PASS, "state digest present", subject))
    else:
        findings.append(_finding("handoff.state_digest", ValidationStatus.FAIL, "state digest is missing", subject))

    owner = h.get("owner_role")
    if isinstance(owner, str) and owner.strip() != "":
        findings.append(_finding("handoff.owner_role", ValidationStatus.PASS, "owner role set", subject))
    else:
        findings.append(_finding("handoff.owner_role", ValidationStatus.FAIL, "owner role is empty", subject))

    items = h.get("open_items")
    if isinstance(items, list) and all(isinstance(i, str) for i in items):
        findings.append(_finding("handoff.open_items", ValidationStatus.PASS, "open items are a list of str", subject))
    else:
        findings.append(
            _finding("handoff.open_items", ValidationStatus.FAIL, "open_items must be a list of str", subject)
        )

    steps = h.get("next_steps")
    if not isinstance(steps, list):
        findings.append(_finding("handoff.next_steps", ValidationStatus.FAIL, "next_steps must be a list", subject))
    elif not all(isinstance(s, str) for s in steps):
        findings.append(_finding("handoff.next_steps", ValidationStatus.FAIL, "next_steps entries must be str", subject))
    else:
        real = [s for s in steps if isinstance(s, str) and s.strip() != "" and s.strip().lower() != NONE_MARKER]
        has_none = any(isinstance(s, str) and s.strip().lower() == NONE_MARKER for s in steps)
        if real:
            findings.append(_finding("handoff.next_steps", ValidationStatus.PASS, "next steps listed", subject))
            if has_none:
                findings.append(
                    _finding(
                        "handoff.next_steps_none",
                        ValidationStatus.WARN,
                        "'none' appears alongside real next steps; remove it",
                        subject,
                    )
                )
        elif has_none:
            findings.append(
                _finding("handoff.next_steps", ValidationStatus.PASS, "explicit 'none' next step", subject)
            )
        else:
            findings.append(
                _finding(
                    "handoff.next_steps",
                    ValidationStatus.FAIL,
                    "no next step and no explicit 'none' entry",
                    subject,
                )
            )

    stored = h.get("digest")
    if isinstance(stored, str) and stored != "":
        try:
            recomputed = stable_hash(_body(h))
        except AsOfError:
            recomputed = None
        if recomputed is not None and recomputed == stored:
            findings.append(_finding("handoff.digest", ValidationStatus.PASS, "digest matches body", subject))
        else:
            findings.append(_finding("handoff.digest", ValidationStatus.FAIL, "digest does not match body", subject))
    else:
        findings.append(_finding("handoff.digest", ValidationStatus.FAIL, "digest is missing", subject))

    return findings
