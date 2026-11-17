"""Render a PM review packet and its delta as Markdown text.

Topic: PM review packet. This module only formats a packet that
as_of.pm_packet_assembly already built. It does not judge content, change any
value and does not write files.

Rules implemented here:
  * Section headings are emitted in PACKET_SECTION_ORDER, whatever order the
    packet dict holds them in.
  * Every table cell passes through escape_cell, so a pipe or a line break in
    a value cannot break the table layout.
  * Keys are sorted and values are formatted with canonical JSON where they
    are not scalars. Rendering the same input twice gives identical text.
  * The output includes the packet_hash so a reader can tie the text back to
    the packet content.

Only the standard library, as_of.core and as_of.pm_packet_assembly (for
PACKET_SECTION_ORDER) are used. There is no network access, no file I/O and
no trading logic. All data handled here is synthetic.
"""

import math
from collections.abc import Mapping as MappingABC
from typing import Any, Dict, List, Mapping

from as_of.core import AsOfError, canonical_json, require
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER


_EMPTY_NOTE: str = "_No entries._"


def escape_cell(text: str) -> str:
    """Make text safe for one Markdown table cell.

    Backslashes and pipes are escaped. Carriage returns and newlines become
    spaces, since a table row must stay on one line. Non-string input is
    converted with str() first.
    """
    value = text if isinstance(text, str) else str(text)
    value = value.replace("\\", "\\\\")
    value = value.replace("|", "\\|")
    value = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return value


def _format_value(value: Any) -> str:
    """Return a cell-safe string for a packet value.

    Scalars are shown with str(). Lists, tuples and mappings are shown as
    canonical JSON so their layout does not depend on dict ordering.
    """
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        raise AsOfError("cannot render non-finite number")
    if isinstance(value, (MappingABC, list, tuple)):
        return escape_cell(canonical_json(value))
    return escape_cell(value)


def _code_span(text: str) -> str:
    """Wrap text in an inline code span that is not a table cell.

    Table escaping is wrong here: inside a code span a backslash or a pipe is
    shown as typed, so only line breaks are flattened and the fence is made
    longer than any backtick run in the text.
    """
    value = str(text).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    longest = 0
    run = 0
    for ch in value:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    fence = "`" * (longest + 1)
    pad = " " if value.startswith("`") or value.endswith("`") else ""
    return fence + pad + value + pad + fence


def _table(headers: List[str], rows: List[List[str]]) -> List[str]:
    """Build Markdown table lines from already-escaped cell strings."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _key_value_rows(body: Mapping[str, Any]) -> List[List[str]]:
    """Return sorted Field/Value rows for a mapping."""
    rows: List[List[str]] = []
    for key in sorted(body.keys(), key=lambda k: str(k)):
        rows.append([escape_cell(key), _format_value(body[key])])
    return rows


def _render_section(name: str, body: Any) -> List[str]:
    """Return the Markdown lines for one packet section."""
    lines = ["## " + escape_cell(name), ""]
    # A non-mapping body is refused, not shown as "No entries", so content is never hidden.
    require(isinstance(body, MappingABC), "section %r must be a mapping" % (name,))
    if len(body) == 0:
        lines.append(_EMPTY_NOTE)
        lines.append("")
        return lines
    lines.extend(_table(["Field", "Value"], _key_value_rows(body)))
    lines.append("")
    return lines


def _render_open_findings(findings: Any) -> List[str]:
    """Return the Markdown lines for the open findings list."""
    lines = ["## open_findings", ""]
    require(isinstance(findings, (list, tuple)), "open_findings must be a list")
    items = list(findings)
    if not items:
        lines.append(_EMPTY_NOTE)
        lines.append("")
        return lines
    rows: List[List[str]] = []
    for item in items:
        if isinstance(item, MappingABC):
            rows.append(
                [
                    _format_value(item.get("check_id", "")),
                    _format_value(item.get("status", "")),
                    _format_value(item.get("subject", "")),
                    _format_value(item.get("message", "")),
                ]
            )
        else:
            rows.append([_format_value(item), "", "", ""])
    lines.extend(_table(["Check", "Status", "Subject", "Message"], rows))
    lines.append("")
    return lines


def render_markdown(packet: Dict[str, Any]) -> str:
    """Render a packet from as_of.pm_packet_assembly as Markdown.

    Args:
        packet: The dict returned by assemble_packet. It needs the keys
            title, as_of, sections, open_findings and packet_hash.

    Returns:
        Markdown text. Sections follow PACKET_SECTION_ORDER. The text ends
        with a newline.

    Raises:
        AsOfError: If packet is not a mapping or lacks a required key.
    """
    require(isinstance(packet, MappingABC), "packet must be a mapping")
    for key in ("title", "as_of", "sections", "open_findings", "packet_hash"):
        require(key in packet, "packet is missing key %r" % key)

    sections = packet["sections"]
    require(isinstance(sections, MappingABC), "packet sections must be a mapping")

    lines: List[str] = [
        "# " + escape_cell(packet["title"]),
        "",
        "- As of: " + escape_cell(packet["as_of"]),
        "- Packet hash: `" + escape_cell(packet["packet_hash"]) + "`",
        "",
    ]
    for name in sections:
        if name not in PACKET_SECTION_ORDER:
            raise AsOfError("packet has unknown section %r" % (name,))
    for name in PACKET_SECTION_ORDER:
        if name not in sections:
            raise AsOfError("packet is missing section %r" % name)
        lines.extend(_render_section(name, sections[name]))

    lines.extend(_render_open_findings(packet["open_findings"]))
    return "\n".join(lines).rstrip("\n") + "\n"


def render_delta_markdown(delta: Dict[str, Any]) -> str:
    """Render a packet delta as Markdown.

    The delta is a mapping. Its scalar fields (for example from_hash and
    to_hash) go into a Field/Value table. A "changes" entry that is a list
    of mappings goes into its own table, one column per key seen in the
    changes, sorted. Other entries are shown as canonical JSON.

    Args:
        delta: Mapping describing what changed between two packets.

    Returns:
        Markdown text. Output is deterministic for equal input.

    Raises:
        AsOfError: If delta is not a mapping.
    """
    require(isinstance(delta, MappingABC), "delta must be a mapping")

    lines: List[str] = ["# Packet delta", ""]
    scalar_keys = sorted(
        (k for k in delta.keys() if k != "changes"),
        key=lambda k: str(k),
    )
    if scalar_keys:
        rows = [[escape_cell(k), _format_value(delta[k])] for k in scalar_keys]
        lines.extend(_table(["Field", "Value"], rows))
        lines.append("")
    else:
        lines.append(_EMPTY_NOTE)
        lines.append("")

    changes = delta.get("changes")
    if isinstance(changes, (list, tuple)) and changes:
        mappings = [c for c in changes if isinstance(c, MappingABC)]
        if mappings and len(mappings) == len(changes):
            columns = sorted({str(k) for c in mappings for k in c.keys()})
            rows = []
            for c in mappings:
                by_name: Dict[str, Any] = {}
                for k, v in c.items():
                    require(str(k) not in by_name, "change keys collide as %r" % str(k))
                    by_name[str(k)] = v
                rows.append([_format_value(by_name.get(col, "")) for col in columns])
            lines.append("## changes")
            lines.append("")
            lines.extend(_table([escape_cell(col) for col in columns], rows))
            lines.append("")
        else:
            lines.append("## changes")
            lines.append("")
            lines.append(_code_span(canonical_json(changes)))
            lines.append("")
    elif changes is not None:
        lines.append("## changes")
        lines.append("")
        lines.append(_format_value(changes))
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"
