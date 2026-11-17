"""Tests for as_of.core. All fixtures are synthetic and use the SYN_ prefix."""

import ast
import dataclasses
import importlib.util
import os
import sys
import sysconfig
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from as_of import core
from as_of.core import (
    ALLOWED_THIRD_PARTY,
    CLOCK_NAMES,
    FORBIDDEN_IMPORT_ROOTS,
    SEVERITY_RANK,
    SYNTHETIC_PREFIX,
    SYNTHETIC_SEED,
    AsOfError,
    ClaimRecord,
    ClockName,
    ClockSet,
    EstimateRecord,
    Finding,
    HardFailError,
    ProofResult,
    ReadinessItem,
    RunStatus,
    Severity,
    SourceRecord,
    SourceType,
    ValidationStatus,
    canonical_json,
    component,
    ensure_utc,
    fmt_ts,
    make_rng,
    parse_ts,
    require,
    sha256_text,
    stable_hash,
    to_plain,
)


CORE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core.py")


# ---------------------------------------------------------------------------
# Constants and enums
# ---------------------------------------------------------------------------


def test_clock_names_match_enum_order():
    assert CLOCK_NAMES == tuple(c.value for c in ClockName)


def test_package_constants():
    assert core.PACKAGE_NAME == "as_of"
    assert SYNTHETIC_SEED == 20261027
    assert SYNTHETIC_PREFIX == "SYN_"
    assert ALLOWED_THIRD_PARTY == ("numpy", "pandas")
    assert "quant_lab" in FORBIDDEN_IMPORT_ROOTS
    assert "subprocess" in FORBIDDEN_IMPORT_ROOTS


@pytest.mark.parametrize(
    "enum_cls",
    [ClockName, SourceType, Severity, ValidationStatus, RunStatus],
)
def test_enum_values_are_lowercase_strings(enum_cls):
    for member in enum_cls:
        assert isinstance(member.value, str)
        assert member.value == member.value.lower()


def test_severity_rank_ordering():
    assert SEVERITY_RANK[Severity.INFO] < SEVERITY_RANK[Severity.WARN] < SEVERITY_RANK[Severity.BLOCK]
    assert set(SEVERITY_RANK) == set(Severity)


def test_hard_fail_is_asof_error():
    assert issubclass(HardFailError, AsOfError)
    assert issubclass(AsOfError, Exception)


def test_require_raises_with_message():
    require(True, "unused")
    with pytest.raises(AsOfError) as info:
        require(False, "x")
    assert str(info.value) == "x"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


def test_clockset_defaults_to_none():
    cs = ClockSet()
    for name in ("event_at", "knowledge_at", "report_at", "release_at", "ingest_at"):
        assert getattr(cs, name) is None


def test_frozen_dataclass_rejects_assignment():
    cs = ClockSet()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cs.event_at = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_frozen_records_reject_assignment():
    rec = EstimateRecord(
        estimate_id="SYN_est_1",
        ticker="SYN_TKR",
        metric="SYN_eps",
        period="SYN_2026Q4",
        analyst_id="SYN_an_1",
        value=1.25,
        knowledge_at=parse_ts("2026-10-01T12:00:00Z"),
        source_id="SYN_src_1",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.value = 2.0


def test_proof_result_metrics_is_a_dict_field():
    pr = ProofResult(
        proof_name="SYN_proof",
        passed=True,
        findings=(Finding("SYN_chk", ValidationStatus.PASS, "ok", "SYN_subj"),),
        metrics={"SYN_m": 1.0},
    )
    assert pr.metrics == {"SYN_m": 1.0}
    assert pr.findings[0].status is ValidationStatus.PASS


def test_readiness_item_constructs():
    item = ReadinessItem(item_id="SYN_item", passed=False, evidence_ref="SYN_ref")
    assert item.passed is False


# ---------------------------------------------------------------------------
# Errors and require
# ---------------------------------------------------------------------------


def test_asof_error_is_exception_subclass():
    with pytest.raises(AsOfError):
        raise AsOfError("boom")


# ---------------------------------------------------------------------------
# parse_ts
# ---------------------------------------------------------------------------


def test_parse_ts_date_only_is_midnight_utc():
    value = parse_ts("2026-10-27")
    assert value == datetime(2026, 10, 27, 0, 0, 0, tzinfo=timezone.utc)
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)


def test_parse_ts_datetime_z():
    value = parse_ts("2026-10-27T13:45:09Z")
    assert value == datetime(2026, 10, 27, 13, 45, 9, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-27T13:45:09",           # naive datetime
        "2026-10-27 13:45:09Z",          # space separator
        "2026-10-27T13:45:09+00:00",     # numeric offset
        "2026-10-27T13:45:09z",          # lowercase z
        "2026-10-27T13:45:09.5Z",        # fractional seconds
        " 2026-10-27",                   # leading whitespace
        "2026-10-27 ",                   # trailing whitespace
        "2026-10-27\n",                  # trailing newline
        "2026-02-30",                    # impossible date
        "2026-10-27T25:00:00Z",          # impossible hour
        "20261027",                      # compact date
        "",                              # empty
        "SYN_not_a_time",                # garbage
    ],
)
def test_parse_ts_rejects_bad_input(text):
    with pytest.raises(AsOfError):
        parse_ts(text)


@pytest.mark.parametrize("bad", [None, 20261027, date(2026, 10, 27), datetime(2026, 10, 27)])
def test_parse_ts_rejects_non_str(bad):
    with pytest.raises(AsOfError):
        parse_ts(bad)


# ---------------------------------------------------------------------------
# ensure_utc and fmt_ts
# ---------------------------------------------------------------------------


def test_ensure_utc_rejects_naive_datetime():
    with pytest.raises(AsOfError):
        ensure_utc(datetime(2026, 10, 27, 12, 0, 0))


def test_ensure_utc_converts_offset_to_utc():
    plus5 = timezone(timedelta(hours=5))
    original = datetime(2026, 10, 27, 17, 0, 0, tzinfo=plus5)
    converted = ensure_utc(original)
    assert converted == datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    assert converted.utcoffset() == timedelta(0)


def test_ensure_utc_keeps_utc_unchanged():
    value = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    assert ensure_utc(value) == value


def test_fmt_ts_format_and_offset_conversion():
    plus5 = timezone(timedelta(hours=5))
    assert fmt_ts(datetime(2026, 10, 27, 17, 0, 0, tzinfo=plus5)) == "2026-10-27T12:00:00Z"


def test_fmt_ts_rejects_naive():
    with pytest.raises(AsOfError):
        fmt_ts(datetime(2026, 10, 27))


def test_fmt_ts_drops_fractional_seconds():
    value = datetime(2026, 10, 27, 12, 0, 0, 999999, tzinfo=timezone.utc)
    assert fmt_ts(value) == "2026-10-27T12:00:00Z"


def test_parse_and_fmt_round_trip():
    text = "2026-10-27T13:45:09Z"
    assert fmt_ts(parse_ts(text)) == text


# ---------------------------------------------------------------------------
# to_plain and canonical_json
# ---------------------------------------------------------------------------


def test_to_plain_datetime_before_date():
    # datetime is a subclass of date, so the datetime branch must win.
    value = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    assert to_plain(value) == "2026-10-27T12:00:00Z"
    assert to_plain(date(2026, 10, 27)) == "2026-10-27"


def test_to_plain_enum_to_value_and_dict_keys():
    assert to_plain(Severity.BLOCK) == "block"
    assert to_plain({Severity.INFO: 0, Severity.WARN: 1}) == {"info": 0, "warn": 1}


def test_to_plain_severity_rank_has_string_keys():
    plain = to_plain(SEVERITY_RANK)
    assert plain == {"info": 0, "warn": 1, "block": 2}


def test_to_plain_tuple_becomes_list():
    assert to_plain((1, 2, (3, 4))) == [1, 2, [3, 4]]


def test_to_plain_dataclass_is_recursive():
    src = SourceRecord(
        source_id="SYN_src_1",
        source_type=SourceType.FILING,
        publisher="SYN_pub",
        locator="SYN_loc",
        retrieved_at=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
        sha256="0" * 64,
        synthetic=True,
    )
    plain = to_plain(src)
    assert plain == {
        "source_id": "SYN_src_1",
        "source_type": "filing",
        "publisher": "SYN_pub",
        "locator": "SYN_loc",
        "retrieved_at": "2026-10-27T09:00:00Z",
        "sha256": "0" * 64,
        "synthetic": True,
    }


def test_to_plain_dataclass_class_is_not_converted():
    # A dataclass class (not instance) should pass through untouched.
    assert to_plain(ClockSet) is ClockSet


def test_to_plain_numpy_scalars():
    assert type(to_plain(np.int64(7))) is int
    assert to_plain(np.int64(7)) == 7
    assert type(to_plain(np.float64(1.5))) is float
    assert to_plain(np.float32(0.25)) == 0.25
    assert type(to_plain(np.bool_(True))) is bool
    assert to_plain(np.bool_(False)) is False


def test_to_plain_nested_record_with_clockset():
    cs = ClockSet(event_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    plain = to_plain(cs)
    assert plain["event_at"] == "2026-10-01T00:00:00Z"
    assert plain["knowledge_at"] is None


def test_canonical_json_is_key_order_independent():
    a = {"b": 1, "a": {"y": 2, "x": 3}}
    b = {"a": {"x": 3, "y": 2}, "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert canonical_json(a) == '{"a":{"x":3,"y":2},"b":1}'


def test_canonical_json_rejects_nan():
    with pytest.raises(AsOfError):
        canonical_json({"v": float("nan")})


def test_canonical_json_uses_plain_conversion():
    value = {"when": datetime(2026, 10, 27, tzinfo=timezone.utc), "sev": Severity.WARN}
    assert canonical_json(value) == '{"sev":"warn","when":"2026-10-27T00:00:00Z"}'


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def test_sha256_text_known_value():
    assert sha256_text("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_stable_hash_ignores_key_insertion_order():
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})


def test_stable_hash_changes_with_content():
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})


def test_stable_hash_is_sha256_of_canonical_json():
    obj = {"k": [1, 2, 3]}
    assert stable_hash(obj) == sha256_text(canonical_json(obj))


# ---------------------------------------------------------------------------
# RNG
# ---------------------------------------------------------------------------


def test_make_rng_default_seed_is_reproducible():
    first = make_rng().integers(0, 1_000_000, size=10)
    second = make_rng().integers(0, 1_000_000, size=10)
    assert np.array_equal(first, second)


def test_make_rng_explicit_seed_differs_from_default():
    default_draws = make_rng().integers(0, 1_000_000, size=10)
    other_draws = make_rng(SYNTHETIC_SEED + 1).integers(0, 1_000_000, size=10)
    assert not np.array_equal(default_draws, other_draws)


def test_make_rng_returns_generator():
    assert isinstance(make_rng(), np.random.Generator)


# ---------------------------------------------------------------------------
# component
# ---------------------------------------------------------------------------


def test_component_imports_core():
    module = component("core")
    assert module is core


def test_component_missing_module_raises_asof_error():
    with pytest.raises(AsOfError):
        component("SYN_does_not_exist")


@pytest.mark.parametrize("bad", ["", "../core", "core.py", "a b", None])
def test_component_rejects_bad_names(bad):
    with pytest.raises(AsOfError):
        component(bad)


# ---------------------------------------------------------------------------
# Standalone, no-network and py39 rules, checked by parsing core.py
# ---------------------------------------------------------------------------


def _core_source():
    with open(CORE_PATH, "r", encoding="utf-8") as handle:
        return handle.read()


def _import_roots(tree):
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _is_stdlib(root):
    if root in sys.builtin_module_names:
        return True
    spec = importlib.util.find_spec(root)
    if spec is None or not spec.origin:
        return False
    stdlib_dir = os.path.realpath(sysconfig.get_paths()["stdlib"])
    origin = os.path.realpath(spec.origin)
    return origin.startswith(stdlib_dir) and "site-packages" not in origin


def test_core_import_roots_are_allowed_and_not_forbidden():
    tree = ast.parse(_core_source())
    roots = _import_roots(tree)
    assert roots, "expected core.py to import something"
    for root in roots:
        assert root not in FORBIDDEN_IMPORT_ROOTS, root
        assert root != "as_of", "core must not import other as_of modules"
        assert root in ALLOWED_THIRD_PARTY or _is_stdlib(root), root


def test_core_does_not_import_any_as_of_module():
    tree = ast.parse(_core_source())
    assert "as_of" not in _import_roots(tree)


def test_core_parses_as_python_39():
    ast.parse(_core_source(), feature_version=(3, 9))


def test_core_has_no_forbidden_syntax_markers():
    source = _core_source()
    assert "slots=True" not in source
    assert "\nmatch " not in source
    # A PEP 604 union such as "X | Y" would appear as " | " in an annotation.
    assert " | " not in source


# ---------------------------------------------------------------------------
# Acceptance checks, written in the exact form of the acceptance list
# ---------------------------------------------------------------------------


def test_acceptance_parse_ts_date_and_round_trip():
    assert parse_ts("2026-10-27") == datetime(2026, 10, 27, tzinfo=timezone.utc)
    assert fmt_ts(parse_ts("2026-10-27T13:05:00Z")) == "2026-10-27T13:05:00Z"


def test_acceptance_parse_ts_naive_raises():
    with pytest.raises(AsOfError):
        parse_ts("2026-10-27T13:05:00")


def test_acceptance_stable_hash_and_clock_plain():
    assert stable_hash({"a": 1, "b": [1, 2]}) == stable_hash({"b": [1, 2], "a": 1})
    assert to_plain(ClockName.EVENT) == "event"


def test_acceptance_hard_fail_and_require_message():
    assert issubclass(HardFailError, AsOfError)
    with pytest.raises(AsOfError) as info:
        require(False, "boom")
    assert str(info.value) == "boom"


def test_acceptance_component_missing_and_rng_random_equal():
    with pytest.raises(AsOfError):
        component("no_such_module")
    assert make_rng().random() == make_rng().random()


def test_all_fixture_ids_use_syn_prefix():
    fixtures = [
        SourceRecord(
            source_id="SYN_src_1",
            source_type=SourceType.FIXTURE,
            publisher="SYN_pub",
            locator="SYN_loc",
            retrieved_at=datetime(2026, 10, 27, tzinfo=timezone.utc),
            sha256="0" * 64,
            synthetic=True,
        ),
        ClaimRecord(
            claim_id="SYN_claim_1",
            text="SYN_text",
            claim_kind="SYN_kind",
            source_ids=("SYN_src_1",),
            status="SYN_open",
            section="SYN_section",
        ),
    ]
    for rec in fixtures:
        for field in dataclasses.fields(rec):
            value = getattr(rec, field.name)
            if field.name.endswith("_id") and isinstance(value, str):
                assert value.startswith(SYNTHETIC_PREFIX), value
    assert fixtures[1].source_ids[0].startswith(SYNTHETIC_PREFIX)
