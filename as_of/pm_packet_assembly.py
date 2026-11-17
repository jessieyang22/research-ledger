"""Assemble a PM review packet from named sections, open findings and a hash.

Topic: PM review packet. The packet is a fixed-order bundle that a portfolio
manager reads before a decision. This module only assembles and hashes it. It
does not judge the content of any section.

Rules implemented here:
  * Every section named in PACKET_SECTION_ORDER is required. A missing one,
    or an unknown one, raises AsOfError.
  * Sections are emitted in PACKET_SECTION_ORDER whatever order the caller
    used.
  * open_findings keeps only WARN and FAIL findings. PASS findings are left
    out.
  * packet_hash is a SHA-256 over the canonical JSON form of the packet
    content and its source records. Equal inputs give an equal hash.

Only the standard library and as_of.core are used. There is no network
access, no file I/O and no trading logic. All data handled here is
synthetic.
"""

import dataclasses
from collections.abc import Mapping as MappingABC
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from as_of.core import (
    AsOfError,
    Finding,
    SourceRecord,
    ValidationStatus,
    ensure_utc,
    require,
    stable_hash,
    to_plain,
)


PACKET_SECTION_ORDER: Tuple[str, ...] = (
    "thesis",
    "evidence",
    "risks",
    "controls",
    "exceptions",
    "tieout",
    "open_items",
)

OPEN_STATUSES: Tuple[ValidationStatus, ...] = (
    ValidationStatus.WARN,
    ValidationStatus.FAIL,
)


def _check_sections(sections: Mapping[str, Dict[str, Any]]) -> None:
    """Raise AsOfError unless sections has exactly the required keys."""
    require(isinstance(sections, MappingABC), "sections must be a mapping")
    for name in PACKET_SECTION_ORDER:
        if name not in sections:
            raise AsOfError("missing required packet section: %r" % name)
    for name in sections:
        if name not in PACKET_SECTION_ORDER:
            raise AsOfError("unknown packet section: %r" % (name,))
    for name in PACKET_SECTION_ORDER:
        body = sections[name]
        require(
            isinstance(body, MappingABC),
            "section %r must be a mapping, got %s" % (name, type(body).__name__),
        )


def _as_list(value: Any, label: str) -> List[Any]:
    """Return value as a list, or raise AsOfError unless it is a list or tuple.

    One-shot iterators are rejected rather than consumed: validating and then
    re-iterating a generator would silently drop every item.
    """
    require(
        isinstance(value, (list, tuple)),
        "%s must be a list or tuple, got %s" % (label, type(value).__name__),
    )
    return list(value)


def _source_plain(src: SourceRecord) -> Dict[str, Any]:
    """Plain form of a source. retrieved_at keeps microseconds so the hash can see them."""
    plain = to_plain(src)
    plain["retrieved_at"] = ensure_utc(src.retrieved_at).isoformat()
    return plain


def _hash_plain(obj: Any) -> Any:
    """Plain form used only for hashing. Datetimes keep microseconds.

    core.to_plain drops fractional seconds, so a section timestamp changed by
    a sub-second amount would leave packet_hash unchanged. Output sections
    still use to_plain; only the hashed copy keeps the extra precision.
    """
    if isinstance(obj, datetime):
        return ensure_utc(obj).isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _hash_plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, MappingABC):
        out: Dict[str, Any] = {}
        for key, value in obj.items():
            plain_key = to_plain(key)
            require(isinstance(plain_key, str), "section keys must convert to str")
            require(plain_key not in out, "duplicate section key after conversion: %r" % plain_key)
            out[plain_key] = _hash_plain(value)
        return out
    if isinstance(obj, (list, tuple)):
        return [_hash_plain(x) for x in obj]
    return to_plain(obj)


def _check_sources(sources: Sequence[SourceRecord]) -> None:
    """Raise AsOfError unless every source is a SourceRecord."""
    for src in sources:
        require(
            isinstance(src, SourceRecord),
            "sources must be SourceRecord instances, got %s" % type(src).__name__,
        )


def _check_findings(findings: Sequence[Finding]) -> None:
    """Raise AsOfError unless every finding is a Finding with a known status."""
    for item in findings:
        require(
            isinstance(item, Finding),
            "findings must be Finding instances, got %s" % type(item).__name__,
        )
        require(
            isinstance(item.status, ValidationStatus),
            "finding %r has a non-ValidationStatus status" % (item.check_id,),
        )


def _open_findings(findings: Sequence[Finding]) -> List[Dict[str, Any]]:
    """Return WARN and FAIL findings as plain dicts, in input order."""
    return [to_plain(item) for item in findings if item.status in OPEN_STATUSES]


def assemble_packet(
    title: str,
    as_of: date,
    sections: Mapping[str, Dict[str, Any]],
    sources: Sequence[SourceRecord],
    findings: Sequence[Finding],
) -> Dict[str, Any]:
    """Build the PM review packet.

    Args:
        title: Non-empty packet title.
        as_of: The as-of date the packet describes. A datetime is rejected.
        sections: Mapping with exactly the keys in PACKET_SECTION_ORDER. Each
            value is a mapping of section content.
        sources: SourceRecord instances behind the packet.
        findings: Finding instances from the checks run on the packet.

    Returns:
        A dict with keys title, as_of (ISO date string), sections (a dict in
        PACKET_SECTION_ORDER), open_findings (WARN and FAIL only) and
        packet_hash (hex SHA-256).

    Raises:
        AsOfError: On a missing or unknown section, a malformed input, or a
            non-date as_of.
    """
    require(isinstance(title, str) and title.strip() != "", "title must be a non-empty string")
    require(
        isinstance(as_of, date) and not isinstance(as_of, datetime),
        "as_of must be a date, not a datetime",
    )
    sources = _as_list(sources, "sources")
    findings = _as_list(findings, "findings")
    _check_sections(sections)
    _check_sources(sources)
    _check_findings(findings)

    ordered: Dict[str, Any] = {}
    for name in PACKET_SECTION_ORDER:
        ordered[name] = to_plain(dict(sections[name]))

    open_items = _open_findings(findings)
    content = {
        "title": title,
        "as_of": as_of.isoformat(),
        "sections": {name: _hash_plain(sections[name]) for name in PACKET_SECTION_ORDER},
        "open_findings": open_items,
        "sources": [_source_plain(src) for src in sources],
    }
    packet_hash = stable_hash(content)

    return {
        "title": title,
        "as_of": as_of.isoformat(),
        "sections": ordered,
        "open_findings": open_items,
        "packet_hash": packet_hash,
    }
