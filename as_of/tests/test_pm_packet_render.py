"""Tests for as_of.pm_packet_render. All fixtures are synthetic (SYN_ prefix)."""

from datetime import date

import pytest

from as_of.core import AsOfError, Finding, ValidationStatus
from as_of.pm_packet_assembly import PACKET_SECTION_ORDER, assemble_packet
from as_of.pm_packet_render import escape_cell, render_delta_markdown, render_markdown


def _sections(tag="base"):
    return {
        name: {"label": "SYN_%s_%s" % (name, tag)} for name in PACKET_SECTION_ORDER
    }


def _finding(check_id, status, subject="SYN_SUBJECT", message=None):
    return Finding(
        check_id=check_id,
        status=status,
        message=message or "SYN_MESSAGE_%s" % check_id,
        subject=subject,
    )


def _packet(sections=None, findings=None, title="SYN_PACKET", as_of=date(2026, 1, 5)):
    return assemble_packet(
        title=title,
        as_of=as_of,
        sections=_sections() if sections is None else sections,
        sources=[],
        findings=[] if findings is None else findings,
    )


def _headings(text):
    return [line[3:] for line in text.splitlines() if line.startswith("## ")]


# ---------------------------------------------------------------------------
# Acceptance: headings follow PACKET_SECTION_ORDER
# ---------------------------------------------------------------------------


def test_rendered_headings_appear_in_packet_section_order():
    text = render_markdown(_packet())
    headings = _headings(text)
    expected = list(PACKET_SECTION_ORDER) + ["open_findings"]
    assert headings == expected


def test_headings_follow_order_even_when_packet_dict_is_reversed():
    packet = _packet()
    packet["sections"] = {name: packet["sections"][name] for name in reversed(PACKET_SECTION_ORDER)}
    headings = _headings(render_markdown(packet))
    assert headings[: len(PACKET_SECTION_ORDER)] == list(PACKET_SECTION_ORDER)


def test_missing_section_in_packet_raises_asof_error():
    packet = _packet()
    del packet["sections"]["controls"]
    with pytest.raises(AsOfError):
        render_markdown(packet)


def test_missing_top_level_key_raises_asof_error():
    packet = _packet()
    del packet["packet_hash"]
    with pytest.raises(AsOfError):
        render_markdown(packet)


def test_non_mapping_packet_raises_asof_error():
    with pytest.raises(AsOfError):
        render_markdown(["SYN_NOT_A_PACKET"])


def test_empty_section_body_renders_placeholder_not_table():
    sections = _sections()
    sections["risks"] = {}
    text = render_markdown(_packet(sections=sections))
    assert "## risks\n\n_No entries._" in text


# ---------------------------------------------------------------------------
# Acceptance: pipes in cells are escaped
# ---------------------------------------------------------------------------


def test_pipe_character_in_cell_is_escaped():
    sections = _sections()
    sections["thesis"] = {"label": "SYN_LEFT|SYN_RIGHT"}
    text = render_markdown(_packet(sections=sections))
    assert "SYN_LEFT\\|SYN_RIGHT" in text
    assert "SYN_LEFT|SYN_RIGHT" not in text


def test_pipe_in_open_finding_message_is_escaped():
    findings = [_finding("CHK_WARN", ValidationStatus.WARN, message="SYN_A|SYN_B")]
    text = render_markdown(_packet(findings=findings))
    assert "SYN_A\\|SYN_B" in text


def test_every_table_row_keeps_its_column_count_after_escaping():
    sections = _sections()
    sections["evidence"] = {"label": "SYN_X|SYN_Y|SYN_Z"}
    text = render_markdown(_packet(sections=sections))
    table_rows = [line for line in text.splitlines() if line.startswith("| ")]
    for row in table_rows:
        # Remove escaped pipes, then count real cell separators.
        assert row.replace("\\|", "").count("|") == 3


def test_escape_cell_escapes_backslash_before_pipe():
    assert escape_cell("a\\b|c") == "a\\\\b\\|c"


def test_escape_cell_flattens_line_breaks():
    assert escape_cell("one\ntwo\r\nthree\rfour") == "one two three four"


def test_escape_cell_converts_non_string_input():
    assert escape_cell(42) == "42"


# ---------------------------------------------------------------------------
# Acceptance: determinism
# ---------------------------------------------------------------------------


def test_rendering_the_same_packet_twice_gives_identical_text():
    findings = [
        _finding("CHK_FAIL", ValidationStatus.FAIL),
        _finding("CHK_WARN", ValidationStatus.WARN),
    ]
    packet = _packet(findings=findings)
    assert render_markdown(packet) == render_markdown(packet)


def test_equal_packets_built_separately_render_identically():
    first = _packet(findings=[_finding("CHK_WARN", ValidationStatus.WARN)])
    second = _packet(findings=[_finding("CHK_WARN", ValidationStatus.WARN)])
    assert render_markdown(first) == render_markdown(second)


def test_dict_key_insertion_order_does_not_change_output():
    same_body = {"b_field": "SYN_B", "a_field": "SYN_A"}
    forward = {name: dict(same_body) for name in PACKET_SECTION_ORDER}
    reordered = {name: dict(same_body) for name in reversed(PACKET_SECTION_ORDER)}
    assert render_markdown(_packet(sections=forward)) == render_markdown(_packet(sections=reordered))


def test_nested_mapping_values_render_as_canonical_json():
    sections = _sections()
    sections["tieout"] = {"nested": {"z": 1, "a": [2, 3]}}
    text = render_markdown(_packet(sections=sections))
    assert '{"a":[2,3],"z":1}' in text


# ---------------------------------------------------------------------------
# Acceptance: packet hash appears in output
# ---------------------------------------------------------------------------


def test_output_includes_the_packet_hash():
    packet = _packet()
    text = render_markdown(packet)
    assert packet["packet_hash"] in text
    assert "`%s`" % packet["packet_hash"] in text


def test_different_packets_show_their_own_hash():
    first = _packet(sections=_sections("a"))
    second = _packet(sections=_sections("b"))
    assert first["packet_hash"] != second["packet_hash"]
    assert second["packet_hash"] in render_markdown(second)
    assert first["packet_hash"] not in render_markdown(second)


# ---------------------------------------------------------------------------
# Open findings and general output shape
# ---------------------------------------------------------------------------


def test_open_findings_table_lists_warn_and_fail_only():
    findings = [
        _finding("CHK_PASS", ValidationStatus.PASS),
        _finding("CHK_WARN", ValidationStatus.WARN),
        _finding("CHK_FAIL", ValidationStatus.FAIL),
    ]
    text = render_markdown(_packet(findings=findings))
    assert "| Check | Status | Subject | Message |" in text
    assert "CHK_WARN" in text
    assert "CHK_FAIL" in text
    assert "CHK_PASS" not in text


def test_no_open_findings_renders_placeholder():
    text = render_markdown(_packet(findings=[_finding("CHK_OK", ValidationStatus.PASS)]))
    assert text.endswith("## open_findings\n\n_No entries._\n")


def test_output_ends_with_single_newline_and_has_title():
    text = render_markdown(_packet(title="SYN_TITLE"))
    assert text.startswith("# SYN_TITLE\n")
    assert text.endswith("\n") and not text.endswith("\n\n")


# ---------------------------------------------------------------------------
# Delta rendering (same module)
# ---------------------------------------------------------------------------


def test_delta_renders_scalars_and_changes_table_deterministically():
    delta = {
        "from_hash": "SYN_HASH_A",
        "to_hash": "SYN_HASH_B",
        "changes": [
            {"section": "thesis", "kind": "edited"},
            {"section": "risks", "kind": "added"},
        ],
    }
    first = render_delta_markdown(delta)
    assert first == render_delta_markdown(delta)
    assert "SYN_HASH_A" in first and "SYN_HASH_B" in first
    assert "| kind | section |" in first


def test_delta_rejects_non_mapping():
    with pytest.raises(AsOfError):
        render_delta_markdown(["SYN_CHANGE"])
