"""Proof 5: PM review packet, end to end on synthetic data.

Topic: proof 5, PM review packet. Code and wording here are original.

What the proof does, in order:
  1. Builds a small synthetic set of sources and claims (SYN_ ids only).
  2. Validates every claim: it needs at least one known source, and expert
     input must not sit in a slide section.
  3. Draws a deterministic spot-check sample of claims from the seed.
  4. Assembles the packet with as_of.pm_packet_assembly.assemble_packet, which
     supplies the section order, the open-findings filter and the packet hash.
  5. Diffs the packet against the prior packet (the last clean build), section
     by section and finding by finding.
  6. Renders the packet and its delta as Markdown. The text carries the
     packet_hash so a reader can tie it back to the packet content.

Injection: with inject_expert_claim_on_slide=True, one expert-input claim is
placed in the "thesis" section. The proof then reports a FAIL and passed=False.

  * SLIDE_SECTIONS lists the sections that feed slides: thesis, evidence and
    risks.
  * The prior packet is always the clean build from the same seed.

Imports: only the standard library and as_of.core (shared types and helpers,
including make_rng, which is where numpy enters) and as_of.pm_packet_assembly
(section order and packet assembly) are imported. This module does not import
numpy or pandas itself. There is no file I/O, no network access and no trading
logic. All data handled here is synthetic.
"""

from collections.abc import Mapping as MappingABC
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from as_of.core import (
    ClaimRecord,
    Finding,
    ProofResult,
    SYNTHETIC_SEED,
    SourceRecord,
    SourceType,
    ValidationStatus,
    canonical_json,
    make_rng,
    require,
    sha256_text,
    stable_hash,
    to_plain,
)
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER, assemble_packet


PROOF_NAME: str = "pm_packet"
PACKET_TITLE: str = "SYN PM review packet (proof 5)"
PACKET_AS_OF: date = date(2026, 10, 27)
RETRIEVED_AT: datetime = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
SAMPLE_SIZE: int = 3
SLIDE_SECTIONS: Tuple[str, ...] = ("thesis", "evidence", "risks")
EXPERT_CLAIM_KIND: str = "expert_input"
EXPERT_CLAIM_ID: str = "SYN_CL_08"
_OPEN_STATUSES: Tuple[ValidationStatus, ...] = (ValidationStatus.WARN, ValidationStatus.FAIL)


# ---------------------------------------------------------------------------
# Synthetic inputs
# ---------------------------------------------------------------------------


def _build_sources(seed: int) -> List[SourceRecord]:
    """Return four synthetic sources, one per evidence type used here."""
    specs = [
        ("SYN_SRC_01", SourceType.FILING, "SYN_filing_desk", "synthetic://SYN_filing/01"),
        ("SYN_SRC_02", SourceType.PRICE, "SYN_price_desk", "synthetic://SYN_price/02"),
        ("SYN_SRC_03", SourceType.ESTIMATE, "SYN_estimate_desk", "synthetic://SYN_estimate/03"),
        ("SYN_SRC_04", SourceType.EXPERT_CALL, "SYN_expert_notes", "synthetic://SYN_expert/04"),
    ]
    sources: List[SourceRecord] = []
    for source_id, source_type, publisher, locator in specs:
        sources.append(
            SourceRecord(
                source_id=source_id,
                source_type=source_type,
                publisher=publisher,
                locator=locator,
                retrieved_at=RETRIEVED_AT,
                sha256=sha256_text("%d:%s" % (seed, source_id)),
                synthetic=True,
            )
        )
    return sources


def _build_claims(seed: int, inject: bool) -> Tuple[List[ClaimRecord], Tuple[str, ...]]:
    """Return the synthetic claims and the spot-check sample of claim ids.

    The rng draws (price, estimate, sample order) come from the seed, so the
    same seed always gives the same claims and the same sample.
    """
    rng = make_rng(seed)
    close = round(100.0 + 5.0 * float(rng.standard_normal()), 2)
    estimate = round(float(rng.uniform(1.0, 3.0)), 2)

    expert_section = "thesis" if inject else "open_items"
    claims: List[ClaimRecord] = [
        ClaimRecord(
            claim_id="SYN_CL_01",
            text="SYN_issuer guidance is unchanged in the latest filing",
            claim_kind="thesis_point",
            source_ids=("SYN_SRC_01",),
            status="verified",
            section="thesis",
        ),
        ClaimRecord(
            claim_id="SYN_CL_02",
            text="SYN_issuer close on the as-of date was %.2f" % close,
            claim_kind="price_fact",
            source_ids=("SYN_SRC_02",),
            status="verified",
            section="evidence",
        ),
        ClaimRecord(
            claim_id="SYN_CL_03",
            text="SYN_consensus EPS estimate sits at %.2f" % estimate,
            claim_kind="estimate_fact",
            source_ids=("SYN_SRC_03",),
            status="verified",
            section="evidence",
        ),
        ClaimRecord(
            claim_id="SYN_CL_04",
            text="SYN_guidance cut would hit the thesis",
            claim_kind="risk_note",
            source_ids=("SYN_SRC_01",),
            status="verified",
            section="risks",
        ),
        ClaimRecord(
            claim_id="SYN_CL_05",
            text="SYN_price reconciliation passed for the synthetic book",
            claim_kind="control_result",
            source_ids=("SYN_SRC_02",),
            status="verified",
            section="controls",
        ),
        ClaimRecord(
            claim_id="SYN_CL_06",
            text="SYN_one estimate revision was logged as an exception",
            claim_kind="exception_note",
            source_ids=("SYN_SRC_03",),
            status="verified",
            section="exceptions",
        ),
        ClaimRecord(
            claim_id="SYN_CL_07",
            text="SYN_position tie-out matched the synthetic ledger",
            claim_kind="tieout_fact",
            source_ids=("SYN_SRC_02",),
            status="verified",
            section="tieout",
        ),
        ClaimRecord(
            claim_id=EXPERT_CLAIM_ID,
            text="SYN_expert call notes volume may soften next quarter",
            claim_kind=EXPERT_CLAIM_KIND,
            source_ids=("SYN_SRC_04",),
            status="open",
            section=expert_section,
        ),
    ]

    order = rng.permutation(len(claims))
    sampled_idx = sorted(int(i) for i in order[:SAMPLE_SIZE])
    sampled = tuple(claims[i].claim_id for i in sampled_idx)
    return claims, sampled


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_claims(
    claims: Sequence[ClaimRecord],
    sources_by_id: Mapping[str, SourceRecord],
) -> List[Finding]:
    """Check sourcing, expert-input placement and open status for each claim."""
    findings: List[Finding] = []
    for claim in claims:
        if not claim.source_ids:
            findings.append(
                Finding("claim_sourced", ValidationStatus.FAIL, "claim has no source", claim.claim_id)
            )
            continue

        unknown = [sid for sid in claim.source_ids if sid not in sources_by_id]
        if unknown:
            findings.append(
                Finding(
                    "claim_sourced",
                    ValidationStatus.FAIL,
                    "unknown source ids: %s" % ", ".join(unknown),
                    claim.claim_id,
                )
            )
            continue

        types: Set[SourceType] = {sources_by_id[sid].source_type for sid in claim.source_ids}
        is_expert = claim.claim_kind == EXPERT_CLAIM_KIND or SourceType.EXPERT_CALL in types
        if is_expert:
            if claim.section in SLIDE_SECTIONS:
                findings.append(
                    Finding(
                        "expert_input_on_slide",
                        ValidationStatus.FAIL,
                        "expert input appears in slide section %r" % claim.section,
                        claim.claim_id,
                    )
                )
            else:
                findings.append(
                    Finding(
                        "expert_input_placement",
                        ValidationStatus.PASS,
                        "expert input kept out of slide sections",
                        claim.claim_id,
                    )
                )

        if claim.status != "verified":
            findings.append(
                Finding(
                    "claim_open",
                    ValidationStatus.WARN,
                    "claim status is %r" % claim.status,
                    claim.claim_id,
                )
            )
    return findings


def _sample_finding(sampled: Sequence[str], claims: Sequence[ClaimRecord]) -> Finding:
    """Summarise the spot-check sample. FAIL when a sampled claim is unsourced."""
    by_id = {c.claim_id: c for c in claims}
    bad = [cid for cid in sampled if cid not in by_id or not by_id[cid].source_ids]
    if bad:
        return Finding(
            "sample_spot_check",
            ValidationStatus.FAIL,
            "sampled claims lack sources: %s" % ", ".join(bad),
            "controls",
        )
    return Finding(
        "sample_spot_check",
        ValidationStatus.PASS,
        "sampled %d claims, all sourced" % len(sampled),
        "controls",
    )


# ---------------------------------------------------------------------------
# Packet build and delta
# ---------------------------------------------------------------------------


def _build_packet(seed: int, inject: bool) -> Dict[str, Any]:
    """Build one packet, its validation findings and its sample.

    Returns a dict with keys packet, findings (list of Finding), sampled and
    claims. The packet is the dict from assemble_packet.
    """
    sources = _build_sources(seed)
    sources_by_id = {s.source_id: s for s in sources}
    claims, sampled = _build_claims(seed, inject)

    findings = _validate_claims(claims, sources_by_id)
    findings.append(_sample_finding(sampled, claims))

    sections: Dict[str, Dict[str, Any]] = {}
    for name in PACKET_SECTION_ORDER:
        body: Dict[str, Any] = {}
        for claim in claims:
            if claim.section == name:
                body[claim.claim_id] = {
                    "text": claim.text,
                    "claim_kind": claim.claim_kind,
                    "status": claim.status,
                    "source_ids": list(claim.source_ids),
                }
        sections[name] = body
    sections["controls"]["sample"] = {
        "sample_size": SAMPLE_SIZE,
        "sampled_claim_ids": list(sampled),
    }

    packet = assemble_packet(
        title=PACKET_TITLE,
        as_of=PACKET_AS_OF,
        sections=sections,
        sources=sources,
        findings=findings,
    )
    return {"packet": packet, "findings": findings, "sampled": sampled, "claims": claims}


def _finding_key(item: Mapping[str, Any]) -> str:
    """Identity of a finding across packets: check_id, subject, status and message.

    Status and message are part of the key, so a finding that keeps its check
    and subject but changes status or text shows as new and resolved in the
    delta instead of being hidden.
    """
    return canonical_json(
        [item.get("check_id"), item.get("subject"), item.get("status"), item.get("message")]
    )


def _changed_keys(old: Any, new: Any) -> List[str]:
    """Sorted names of keys that differ between two section bodies."""
    if not (isinstance(old, MappingABC) and isinstance(new, MappingABC)):
        return ["*"]
    names = set(old.keys()) | set(new.keys())
    changed: List[str] = []
    for name in names:
        if name not in old or name not in new or stable_hash(old[name]) != stable_hash(new[name]):
            changed.append(str(name))
    return sorted(changed)


def diff_packets(prev: Mapping[str, Any], curr: Mapping[str, Any]) -> Dict[str, Any]:
    """Compare two packets from build_pm_packet and return the delta.

    Returns a dict with keys added_sections, removed_sections, changed_sections,
    changed_fields, findings_new and findings_resolved. Identical packets give
    empty lists and an empty dict. Swapping the arguments swaps added and
    removed sections, and new and resolved findings.
    """
    require(isinstance(prev, MappingABC), "prev packet must be a mapping")
    require(isinstance(curr, MappingABC), "curr packet must be a mapping")
    for label, packet in (("prev", prev), ("curr", curr)):
        for key in ("sections", "open_findings"):
            require(key in packet, "%s packet is missing key %r" % (label, key))

    prev_sections = dict(prev["sections"])
    curr_sections = dict(curr["sections"])
    prev_names = set(prev_sections.keys())
    curr_names = set(curr_sections.keys())

    changed: List[str] = []
    changed_fields: Dict[str, List[str]] = {}
    for name in sorted(prev_names & curr_names):
        if stable_hash(prev_sections[name]) != stable_hash(curr_sections[name]):
            changed.append(name)
            changed_fields[name] = _changed_keys(prev_sections[name], curr_sections[name])

    prev_map = {_finding_key(f): to_plain(f) for f in prev["open_findings"]}
    curr_map = {_finding_key(f): to_plain(f) for f in curr["open_findings"]}
    new_keys = sorted(k for k in curr_map if k not in prev_map)
    resolved_keys = sorted(k for k in prev_map if k not in curr_map)

    return {
        "added_sections": sorted(curr_names - prev_names),
        "removed_sections": sorted(prev_names - curr_names),
        "changed_sections": changed,
        "changed_fields": changed_fields,
        "findings_new": [curr_map[k] for k in new_keys],
        "findings_resolved": [prev_map[k] for k in resolved_keys],
    }


def delta_is_empty(delta: Mapping[str, Any]) -> bool:
    """True when a delta from diff_packets records no change at all."""
    return all(
        not delta.get(key)
        for key in (
            "added_sections",
            "removed_sections",
            "changed_sections",
            "changed_fields",
            "findings_new",
            "findings_resolved",
        )
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _esc(value: Any) -> str:
    """Make a value safe for one Markdown table cell."""
    text = value if isinstance(value, str) else str(value)
    text = text.replace("\\", "\\\\").replace("|", "\\|")
    return text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> List[str]:
    """Return Markdown table lines from already-escaped cells."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def render_pm_packet_markdown(packet: Mapping[str, Any], delta: Optional[Mapping[str, Any]] = None) -> str:
    """Render a packet and an optional delta as Markdown.

    The text always includes the packet_hash. Sections follow
    PACKET_SECTION_ORDER. Rendering the same inputs twice gives the same text.
    """
    require(isinstance(packet, MappingABC), "packet must be a mapping")
    for key in ("title", "as_of", "sections", "open_findings", "packet_hash"):
        require(key in packet, "packet is missing key %r" % key)

    lines: List[str] = [
        "# " + _esc(packet["title"]),
        "",
        "- As of: " + _esc(packet["as_of"]),
        "- Packet hash: `" + _esc(packet["packet_hash"]) + "`",
        "- All data synthetic (SYN_ ids).",
        "",
    ]

    for name in PACKET_SECTION_ORDER:
        body = packet["sections"][name]
        require(isinstance(body, MappingABC), "section %r must be a mapping" % (name,))
        lines.append("## " + _esc(name))
        lines.append("")
        if len(body) > 0:
            rows = [[_esc(k), _esc(canonical_json(body[k]))] for k in sorted(body.keys(), key=str)]
            lines.extend(_table(["Field", "Value"], rows))
        else:
            lines.append("_No entries._")
        lines.append("")

    lines.append("## open_findings")
    lines.append("")
    open_items = list(packet["open_findings"])
    if open_items:
        rows = [
            [
                _esc(item.get("check_id", "")),
                _esc(item.get("status", "")),
                _esc(item.get("subject", "")),
                _esc(item.get("message", "")),
            ]
            for item in open_items
        ]
        lines.extend(_table(["Check", "Status", "Subject", "Message"], rows))
    else:
        lines.append("_No entries._")
    lines.append("")

    lines.append("## Delta since prior packet")
    lines.append("")
    if delta is None or delta_is_empty(delta):
        lines.append("No changes since prior packet.")
    else:
        for label, key in (
            ("Added sections", "added_sections"),
            ("Removed sections", "removed_sections"),
            ("Changed sections", "changed_sections"),
        ):
            names = list(delta.get(key, []))
            if names:
                lines.append("- %s: %s" % (label, ", ".join(_esc(n) for n in names)))
        fields = dict(delta.get("changed_fields", {}))
        for name in sorted(fields):
            lines.append("- Changed fields in %s: %s" % (_esc(name), ", ".join(_esc(f) for f in fields[name])))
        for label, key in (("New findings", "findings_new"), ("Resolved findings", "findings_resolved")):
            items = list(delta.get(key, []))
            if items:
                lines.append("- %s:" % label)
                for item in items:
                    lines.append("  - %s / %s: %s" % (_esc(item.get("check_id", "")), _esc(item.get("subject", "")), _esc(item.get("message", ""))))
    lines.append("")
    lines.append("Packet hash: `" + _esc(packet["packet_hash"]) + "`")
    return "\n".join(lines).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def build_pm_packet(seed: int = SYNTHETIC_SEED, inject_expert_claim_on_slide: bool = False) -> Dict[str, Any]:
    """Build the current packet, the prior packet, the delta and the Markdown.

    Returns a dict with keys packet, prior_packet, delta, markdown, findings
    and passed. Raises AsOfError on bad input.
    """
    require(isinstance(seed, int) and not isinstance(seed, bool), "seed must be an int")
    require(seed >= 0, "seed must be non-negative")
    require(
        isinstance(inject_expert_claim_on_slide, bool),
        "inject_expert_claim_on_slide must be a bool, got %s" % type(inject_expert_claim_on_slide).__name__,
    )
    current = _build_packet(seed, inject_expert_claim_on_slide)
    prior = _build_packet(seed, False)
    delta = diff_packets(prior["packet"], current["packet"])
    markdown = render_pm_packet_markdown(current["packet"], delta)
    passed = not any(f.status == ValidationStatus.FAIL for f in current["findings"])
    return {
        "packet": current["packet"],
        "prior_packet": prior["packet"],
        "delta": delta,
        "markdown": markdown,
        "findings": tuple(current["findings"]),
        "passed": passed,
        "claim_count": len(current["claims"]),
        "sample_count": len(current["sampled"]),
    }


def run_pm_packet_proof(
    seed: int = SYNTHETIC_SEED,
    inject_expert_claim_on_slide: bool = False,
) -> ProofResult:
    """Run proof 5 and return a ProofResult.

    passed is False when any claim validation finds a FAIL, for example expert
    input in a slide section. With the default arguments the proof passes.

    Metrics (all floats): claims_total, claims_sampled, open_findings,
    fail_findings, changed_sections, findings_new, findings_resolved,
    rendered_chars.
    """
    bundle = build_pm_packet(seed, inject_expert_claim_on_slide)
    packet = bundle["packet"]
    delta = bundle["delta"]
    findings: Tuple[Finding, ...] = bundle["findings"]

    metrics: Dict[str, float] = {
        "claims_total": float(bundle["claim_count"]),
        "claims_sampled": float(bundle["sample_count"]),
        "open_findings": float(len(packet["open_findings"])),
        "fail_findings": float(sum(1 for f in findings if f.status == ValidationStatus.FAIL)),
        "changed_sections": float(len(delta["changed_sections"])),
        "findings_new": float(len(delta["findings_new"])),
        "findings_resolved": float(len(delta["findings_resolved"])),
        "rendered_chars": float(len(bundle["markdown"])),
    }

    return ProofResult(
        proof_name=PROOF_NAME,
        passed=bool(bundle["passed"]),
        findings=findings,
        metrics=metrics,
    )
