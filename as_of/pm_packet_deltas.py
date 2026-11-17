"""PM packet deltas: compare the current PM review packet with the prior one.

Topic: PM packet deltas.

The delta report answers three questions a PM asks before reading a packet:
which sections were added or removed, which sections changed (detected by a
content hash, then by field), and which findings are new or resolved since
the prior packet. The comparison is pure: it reads two dicts and returns a
dict, with no file, network or clock access.

Packet shape assumed here:

* ``packet["sections"]`` is a dict mapping section name to section content.
  If that key is absent, every top-level key except ``"findings"`` is treated
  as a section.
* ``packet["findings"]`` is a list. Each item is either a ``Finding`` record
  from ``as_of.core`` or a dict. A finding's identity is its
  ``(check_id, subject)`` pair when both exist, otherwise a stable hash of the
  whole item.

Only ``as_of.core`` is imported. All data handled here is synthetic.
"""

from typing import Any, Dict, List, Set, Tuple

from as_of.core import AsOfError, canonical_json, require, stable_hash, to_plain


DELTA_KEYS: Tuple[str, ...] = (
    "added_sections",
    "removed_sections",
    "changed_sections",
    "changed_fields",
    "findings_new",
    "findings_resolved",
)

_WHOLE_SECTION_FIELD: str = "*"
_FINDINGS_KEY: str = "findings"


def _sections_of(packet: Dict[str, Any]) -> Dict[str, Any]:
    """Return the name-to-content mapping of sections in a packet."""
    raw = packet.get("sections")
    if isinstance(raw, dict):
        return dict(raw)
    return {k: v for k, v in packet.items() if k != _FINDINGS_KEY}


def _findings_of(packet: Dict[str, Any]) -> List[Any]:
    """Return the findings list of a packet, or an empty list when absent."""
    raw = packet.get(_FINDINGS_KEY)
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return list(raw)
    raise AsOfError("packet findings must be a list, got %s" % type(raw).__name__)


def _finding_key(item: Any) -> str:
    """Identity string for a finding, used to match findings across packets."""
    plain = to_plain(item)
    if isinstance(plain, dict) and "check_id" in plain and "subject" in plain:
        return canonical_json([plain["check_id"], plain["subject"]])
    return stable_hash(plain)


def _diff_findings(prev_items: List[Any], curr_items: List[Any]) -> Tuple[List[Any], List[Any]]:
    """Return (new, resolved) plain findings between two findings lists.

    Works as a multiset so that duplicate identities are never lost:
    1. Findings whose full content matches exactly are paired first and
       cancel out, whatever their position in the list.
    2. Leftovers that share an identity key are paired one-for-one. A pair
       is the same finding with an edited message, so it is neither new nor
       resolved.
    3. Unpaired current leftovers are new. Unpaired prior leftovers are
       resolved.
    Every finding is validated with canonical_json, so NaN raises AsOfError.
    """
    def _entries(items: List[Any]) -> List[Tuple[str, str, Any]]:
        out = []
        for item in items:
            plain = to_plain(item)
            content = canonical_json(plain)
            out.append((_finding_key(item), content, plain))
        return out

    prev_entries = _entries(items=prev_items)
    curr_entries = _entries(items=curr_items)

    prev_by_content: Dict[str, List[int]] = {}
    for idx, (_, content, _) in enumerate(prev_entries):
        prev_by_content.setdefault(content, []).append(idx)

    unmatched_curr: List[int] = []
    matched_prev: Set[int] = set()
    for cidx, (_, content, _) in enumerate(curr_entries):
        pool = prev_by_content.get(content, [])
        pool = [p for p in pool if p not in matched_prev]
        if pool:
            matched_prev.add(pool[0])
        else:
            unmatched_curr.append(cidx)

    left_prev = [p for p in range(len(prev_entries)) if p not in matched_prev]
    prev_by_key: Dict[str, List[int]] = {}
    for pidx in left_prev:
        prev_by_key.setdefault(prev_entries[pidx][0], []).append(pidx)

    new_entries: List[Tuple[str, str, Any]] = []
    for cidx in unmatched_curr:
        key, content, plain = curr_entries[cidx]
        if prev_by_key.get(key):
            prev_by_key[key].pop(0)
        else:
            new_entries.append((key, content, plain))

    resolved_entries = [
        (prev_entries[p][0], prev_entries[p][1], prev_entries[p][2])
        for remaining in prev_by_key.values()
        for p in remaining
    ]

    new_entries.sort(key=lambda e: (e[0], e[1]))
    resolved_entries.sort(key=lambda e: (e[0], e[1]))
    return [e[2] for e in new_entries], [e[2] for e in resolved_entries]


def _changed_field_names(old: Any, new: Any) -> List[str]:
    """Names of fields that differ between two section values.

    For dict sections, the result lists keys that were added, removed or whose
    values differ. For any other type, the result is the whole-section marker.
    """
    if isinstance(old, dict) and isinstance(new, dict):
        names: Set[str] = set(old.keys()) | set(new.keys())
        changed = []
        for name in names:
            if name not in old or name not in new:
                changed.append(str(name))
            elif stable_hash(old[name]) != stable_hash(new[name]):
                changed.append(str(name))
        return sorted(changed)
    return [_WHOLE_SECTION_FIELD]


def diff_packets(prev: Dict[str, Any], curr: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two PM packets and return the delta.

    Args:
        prev: the prior packet.
        curr: the current packet.

    Returns:
        A dict with the keys in ``DELTA_KEYS``:

        * ``added_sections``: sorted names present only in ``curr``.
        * ``removed_sections``: sorted names present only in ``prev``.
        * ``changed_sections``: sorted names present in both whose content
          hash differs.
        * ``changed_fields``: for each changed section, the sorted list of
          field names that differ (``["*"]`` for non-dict sections).
        * ``findings_new``: plain findings present only in ``curr``.
        * ``findings_resolved``: plain findings present only in ``prev``.

    Swapping ``prev`` and ``curr`` swaps added and removed sections, and
    identical packets give an empty delta.
    """
    require(isinstance(prev, dict), "prev packet must be a dict")
    require(isinstance(curr, dict), "curr packet must be a dict")

    prev_sections = _sections_of(prev)
    curr_sections = _sections_of(curr)

    prev_names = set(prev_sections.keys())
    curr_names = set(curr_sections.keys())

    added = sorted(curr_names - prev_names, key=str)
    removed = sorted(prev_names - curr_names, key=str)

    changed: List[str] = []
    changed_fields: Dict[str, List[str]] = {}
    for name in sorted(prev_names & curr_names, key=str):
        old_value = prev_sections[name]
        new_value = curr_sections[name]
        if stable_hash(old_value) == stable_hash(new_value):
            continue
        changed.append(name)
        changed_fields[name] = _changed_field_names(old_value, new_value)

    findings_new, findings_resolved = _diff_findings(_findings_of(prev), _findings_of(curr))

    return {
        "added_sections": added,
        "removed_sections": removed,
        "changed_sections": changed,
        "changed_fields": changed_fields,
        "findings_new": findings_new,
        "findings_resolved": findings_resolved,
    }


def _one_line(text: Any) -> str:
    """Make text safe for a single rendered line.

    Line breaks and carriage returns are escaped, so a name or message cannot
    start a fake heading line in the rendered output.
    """
    return str(text).replace("\r", "\\r").replace("\n", "\\n")


def _finding_label(item: Any) -> str:
    """Short one-line label for a plain finding dict."""
    if isinstance(item, dict):
        check = item.get("check_id")
        subject = item.get("subject")
        message = item.get("message")
        parts = [_one_line(p) for p in (check, subject) if p is not None]
        label = " / ".join(parts) if parts else "finding"
        if message:
            label = "%s: %s" % (label, _one_line(message))
        return label
    return _one_line(item)


def render_delta_lines(delta: Dict[str, Any]) -> List[str]:
    """Render a delta from ``diff_packets`` as plain-text lines.

    Each non-empty category gets a heading line followed by indented items.
    An empty delta renders as a single line saying there are no changes.
    """
    require(isinstance(delta, dict), "delta must be a dict")

    lines: List[str] = []

    def _section_block(title: str, names: List[str]) -> None:
        if names:
            lines.append("%s (%d):" % (title, len(names)))
            for name in names:
                lines.append("  - %s" % _one_line(name))

    _section_block("Added sections", list(delta.get("added_sections", [])))
    _section_block("Removed sections", list(delta.get("removed_sections", [])))

    changed = list(delta.get("changed_sections", []))
    if changed:
        fields_map: Dict[str, List[str]] = dict(delta.get("changed_fields", {}))
        lines.append("Changed sections (%d):" % len(changed))
        for name in changed:
            fields = fields_map.get(name, [])
            if fields and fields != [_WHOLE_SECTION_FIELD]:
                lines.append("  - %s: %s" % (_one_line(name), ", ".join(_one_line(f) for f in fields)))
            else:
                lines.append("  - %s" % _one_line(name))

    new_findings = list(delta.get("findings_new", []))
    if new_findings:
        lines.append("New findings (%d):" % len(new_findings))
        for item in new_findings:
            lines.append("  - %s" % _finding_label(item))

    resolved = list(delta.get("findings_resolved", []))
    if resolved:
        lines.append("Resolved findings (%d):" % len(resolved))
        for item in resolved:
            lines.append("  - %s" % _finding_label(item))

    if not lines:
        lines.append("No changes since prior packet.")
    return lines
