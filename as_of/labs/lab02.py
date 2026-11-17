"""Lab 02: prove the five clocks and the field dictionary (synthetic data only).

What this lab does:

* Defines a ten-field control set for as-of records. Five fields are time
  fields (effective period, published time, retrieval time, vintage date,
  approval time). Five are identity or value fields (record id, prior record
  id, source id, approver, observed value).
* Gives every field an immutability rule, an acceptance test, and a
  deliberately bad value that the acceptance test must reject.
* Gives each of the five clocks a one-row example record, and checks that
  each example passes every acceptance test and the clock ordering rules.
* Runs the verifier. It must report PASS on the real dictionary.
* Plants two failures on disposable copies: delete vintage_date, and blank
  one acceptance test. Both copies must report FAIL.
* Traces the April macro example: observation date, the June 5 eligible
  vintage, the July 3 later vintage, and why July cannot enter a June 10
  state.
* Checks an estimate ledger whose as-of times differ from the publication
  time of the result that informed a later revision.
* Checks that a revision needs a prior record id and leaves the prior row
  unchanged in an append-only JSON Lines store.
* Records date-only live sources as limitations in the source register.

The ten-field control set, the acceptance tests and the verifier rules are this
lab's own design.

Only as_of.core is imported statically. Other as_of modules are loaded with
core.component inside function bodies, so folder policy sees one import
root. Nothing here touches the network, subprocesses or any order code.

Run from the repo root:
    python -m as_of.labs.lab02

Output: as_of/labs/results/lab02.json. Exit code 0 when the lab passes.
"""

import copy
import dataclasses
import json
import math
import os
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from as_of.core import (
    AsOfError,
    EstimateRecord,
    Finding,
    MacroVintage,
    SourceRecord,
    SourceType,
    ValidationStatus,
    component,
    ensure_utc,
    sha256_text,
    stable_hash,
    to_plain,
)


LAB_ID: str = "lab02"
RESULTS_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
RESULT_PATH: str = os.path.join(RESULTS_DIR, "lab02.json")
SCRATCH_STORE: str = os.path.join(RESULTS_DIR, "lab02_revision_scratch.jsonl")
UTC = timezone.utc

# The exact ten-field control set. Order is for display only.
CONTROL_FIELDS: Tuple[str, ...] = (
    "record_id",
    "prior_record_id",
    "source_id",
    "effective_period",
    "published_at",
    "retrieved_at",
    "vintage_date",
    "approved_at",
    "approved_by",
    "observed_value",
)
# The five clocks, in the order the lab reports them. Each maps to one field.
CLOCKS: Tuple[str, ...] = ("event", "release", "ingest", "vintage", "approval")
CLOCK_FIELD: Dict[str, str] = {
    "event": "effective_period",
    "release": "published_at",
    "ingest": "retrieved_at",
    "vintage": "vintage_date",
    "approval": "approved_at",
}
MODEL_WORDS: Tuple[str, ...] = ("model", "claude", "llm", "gpt", "assistant")

SRC_MACRO = "SYN_SRC-MACRO-01"
SRC_LIVE = "SYN_SRC-LIVE-CAL-01"
SRC_NOTE = "SYN_SRC-NOTE-01"
SRC_RESULT = "SYN_SRC-RESULT-01"

LIVE_LIMITATION = (
    "Date-only live source: the page shows a calendar date and no time. "
    "published_at is set to 23:59:59Z on that date, the latest instant the "
    "date allows, so a value is never treated as visible early. The cost is "
    "that a same-day capture looks earlier than publication, so retrieval "
    "checks on this source only accept next-day captures."
)

# (source_id, source type, publisher, locator, published precision, limitation)
_SOURCE_SPECS: Tuple[Tuple[str, SourceType, str, str, str, str], ...] = (
    (SRC_MACRO, SourceType.MACRO, "SYN_PUBLISHER_A", "synthetic://macro/apr-demo", "datetime", ""),
    (SRC_LIVE, SourceType.CATALYST, "SYN_PUBLISHER_B", "synthetic://live/calendar-page", "date", LIVE_LIMITATION),
    (SRC_NOTE, SourceType.ESTIMATE, "SYN_PUBLISHER_C", "synthetic://estimates/analyst-note", "datetime", ""),
    (SRC_RESULT, SourceType.FILING, "SYN_PUBLISHER_D", "synthetic://filings/reported-result", "datetime", ""),
)


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """Aware UTC datetime helper for the synthetic examples."""
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def _mods() -> SimpleNamespace:
    """Load the as_of modules this lab uses. Called inside the entry points only."""
    names = (
        "field_dictionary",
        "clocks_record",
        "clock_ordering",
        "clock_as_of",
        "estimate_ledger",
        "macro_vintage_manifest",
        "macro_cutoff_rule",
        "jsonl_store",
        "source_register",
    )
    return SimpleNamespace(**{name: component(name) for name in names})


# ---------------------------------------------------------------------------
# Acceptance tests. Each takes (value, row, ctx) and returns True or False.
# ---------------------------------------------------------------------------


def _is_aware(value: Any) -> bool:
    """True for a datetime with a UTC offset. Naive values are False."""
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _period_start(text: Any) -> Optional[date]:
    """First day of a 'YYYY-MM' or 'YYYY-Qn' period, or None for anything else."""
    if not isinstance(text, str):
        return None
    match = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), 1)
    match = re.fullmatch(r"(\d{4})-Q([1-4])", text)
    if match:
        return date(int(match.group(1)), 3 * (int(match.group(2)) - 1) + 1, 1)
    return None


def _acc_record_id(value: Any, row: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    return isinstance(value, str) and re.fullmatch(r"REC-[A-Z0-9-]{3,}", value) is not None


def _acc_prior_record_id(value: Any, row: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    # None only for a first capture. Otherwise it must name a different row.
    if value is None:
        return True
    return isinstance(value, str) and value.strip() != "" and value != row.get("record_id")


def _acc_source_id(value: Any, row: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    return isinstance(value, str) and value in ctx["precision"]


def _acc_effective_period(value: Any, row: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    # A period must parse, and it must start on or before the publication date.
    # A timestamp string is not a period, so it fails the parse.
    start = _period_start(value)
    published = row.get("published_at")
    if start is None or not _is_aware(published):
        return False
    return start <= ensure_utc(published).date()


def _acc_published_at(value: Any, row: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    if not _is_aware(value):
        return False
    if ctx["precision"].get(row.get("source_id")) == "date":
        moment = value.astimezone(UTC)
        return (moment.hour, moment.minute, moment.second) == (23, 59, 59)
    return True


def _acc_retrieved_at(value: Any, row: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    published = row.get("published_at")
    return _is_aware(value) and _is_aware(published) and ensure_utc(value) >= ensure_utc(published)


def _acc_vintage_date(value: Any, row: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    # A plain date for the revision state, released on or after publication.
    # It is a separate field from effective_period and never replaces it.
    published = row.get("published_at")
    if not isinstance(value, date) or isinstance(value, datetime):
        return False
    return _is_aware(published) and value >= ensure_utc(published).date()


def _acc_approved_at(value: Any, row: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    # A human approval comes after the capture it approves.
    retrieved = row.get("retrieved_at")
    return _is_aware(value) and _is_aware(retrieved) and ensure_utc(value) >= ensure_utc(retrieved)


def _acc_approved_by(value: Any, row: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    # A named person, not a model, tool or assistant name.
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = value.lower()
    return not any(word in lowered for word in MODEL_WORDS)


def _acc_observed_value(value: Any, row: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    return isinstance(value, float) and not isinstance(value, bool) and math.isfinite(value)


# ---------------------------------------------------------------------------
# The field dictionary for the ten-field control set.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class LabField:
    """One control field: its clock, dtype, immutability rule and acceptance test."""

    name: str
    clock: Optional[str]
    dtype: str
    immutability: str
    acceptance_text: str
    acceptance: Optional[Callable[[Any, Dict[str, Any], Dict[str, Any]], bool]]
    bad_value: Any  # a fixed value, or a callable taking the row and returning one


def build_lab_dictionary() -> Dict[str, LabField]:
    """Return a fresh copy of the ten-field dictionary, keyed by field name."""
    fields = [
        LabField(
            "record_id", None, "str",
            "Write once. A correction is a new record with a new id; the old row is never edited or deleted.",
            "Matches REC- followed by upper-case letters, digits or hyphens.",
            _acc_record_id, "bad id",
        ),
        LabField(
            "prior_record_id", None, "str",
            "Write once at creation. Null only for a first capture; a revision names the row it replaces.",
            "Null for a first capture, or a non-blank id that differs from this row's own record_id.",
            _acc_prior_record_id, lambda row: row["record_id"],
        ),
        LabField(
            "source_id", None, "str",
            "Write once. Must name a registered source whose content hash is frozen; a re-pull is a new source.",
            "Must be a source id present in the source register.",
            _acc_source_id, "SYN_SRC-UNREGISTERED",
        ),
        LabField(
            "effective_period", "event", "str",
            "Write once. Names the period the value describes; a different period is a different record.",
            "Parses as YYYY-MM or YYYY-Qn, and the period starts on or before the published date. A timestamp fails.",
            _acc_effective_period, "2026-04-01T00:00:00Z",
        ),
        LabField(
            "published_at", "release", "datetime",
            "Write once from the source. Never overwritten with a later capture time.",
            "Aware UTC datetime. A date-only source must carry 23:59:59Z on its date (the conservative rule).",
            _acc_published_at, datetime(2026, 6, 5, 13),
        ),
        LabField(
            "retrieved_at", "ingest", "datetime",
            "Write once at capture. A re-fetch writes a new record with its own retrieved_at.",
            "Aware datetime, and not earlier than published_at.",
            _acc_retrieved_at, _utc(2000, 1, 1),
        ),
        LabField(
            "vintage_date", "vintage", "date",
            "Write once per revision row. A later vintage is a new row; earlier vintages stay in the store.",
            "Plain date (not a datetime), on or after the published date. Never used as the observation date.",
            _acc_vintage_date, _utc(2026, 6, 5, 13),
        ),
        LabField(
            "approved_at", "approval", "datetime",
            "Write once by the approval step. A re-approval is a new row.",
            "Aware datetime, not earlier than retrieved_at. Names a human decision, not a model completion.",
            _acc_approved_at, _utc(2000, 1, 1),
        ),
        LabField(
            "approved_by", None, "str",
            "Write once, together with approved_at. Must name a person.",
            "Non-blank, and contains no model, assistant or tool name.",
            _acc_approved_by, "claude-haiku-5-5",
        ),
        LabField(
            "observed_value", None, "float",
            "Write once. A change is a new row whose prior_record_id names the old row.",
            "Finite real number, not a bool.",
            _acc_observed_value, float("nan"),
        ),
    ]
    return {field.name: field for field in fields}


def build_examples() -> Dict[str, Dict[str, Any]]:
    """One full ten-field example row per clock. Each row focuses on its clock."""
    base = {
        "prior_record_id": None,
    }
    rows = {
        # event: a quarterly period, published on the quarter's last month.
        "event": dict(
            base,
            record_id="REC-EVT-0001", source_id=SRC_MACRO, effective_period="2026-Q1",
            published_at=_utc(2026, 4, 30, 13), retrieved_at=_utc(2026, 4, 30, 14),
            vintage_date=date(2026, 4, 30), approved_at=_utc(2026, 5, 1, 9),
            approved_by="SYN_ANALYST_A", observed_value=2.0,
        ),
        # release: a date-only live source, so published_at is 23:59:59Z.
        "release": dict(
            base,
            record_id="REC-REL-0001", source_id=SRC_LIVE, effective_period="2026-03",
            published_at=_utc(2026, 4, 29, 23, 59, 59), retrieved_at=_utc(2026, 4, 30, 6),
            vintage_date=date(2026, 4, 29), approved_at=_utc(2026, 4, 30, 9),
            approved_by="SYN_ANALYST_A", observed_value=2.2,
        ),
        # ingest: the April macro first vintage, captured five minutes after release.
        "ingest": dict(
            base,
            record_id="REC-APR-0001", source_id=SRC_MACRO, effective_period="2026-04",
            published_at=_utc(2026, 6, 5, 13), retrieved_at=_utc(2026, 6, 5, 13, 5),
            vintage_date=date(2026, 6, 5), approved_at=_utc(2026, 6, 8, 10),
            approved_by="SYN_ANALYST_B", observed_value=2.1,
        ),
        # vintage: the later July 3 revision, which names REC-APR-0001 as prior.
        "vintage": dict(
            base,
            record_id="REC-APR-0002", prior_record_id="REC-APR-0001", source_id=SRC_MACRO,
            effective_period="2026-04", published_at=_utc(2026, 7, 3, 13),
            retrieved_at=_utc(2026, 7, 3, 13, 2), vintage_date=date(2026, 7, 3),
            approved_at=_utc(2026, 7, 6, 10), approved_by="SYN_ANALYST_B", observed_value=2.4,
        ),
        # approval: an analyst note approved the morning after capture.
        "approval": dict(
            base,
            record_id="REC-NOTE-0001", source_id=SRC_NOTE, effective_period="2026-04",
            published_at=_utc(2026, 5, 6, 20), retrieved_at=_utc(2026, 5, 7, 8),
            vintage_date=date(2026, 5, 6), approved_at=_utc(2026, 5, 7, 9),
            approved_by="SYN_ANALYST_A", observed_value=1.2,
        ),
    }
    return rows


def _source_precision() -> Dict[str, str]:
    return {source_id: precision for source_id, _, _, _, precision, _ in _SOURCE_SPECS}


def build_context() -> Dict[str, Any]:
    """Context passed to every acceptance test: the registered sources and precision."""
    return {"precision": _source_precision()}


def _run_acceptance(spec: LabField, value: Any, row: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """Run one acceptance test. An exception counts as a failed test, not a crash."""
    if spec.acceptance is None:
        return False
    try:
        return bool(spec.acceptance(value, row, ctx))
    except Exception:
        return False


def _finding(check_id: str, passed: bool, message: str, subject: str) -> Finding:
    status = ValidationStatus.PASS if passed else ValidationStatus.FAIL
    return Finding(check_id=check_id, status=status, message=message, subject=subject)


# ---------------------------------------------------------------------------
# Lab 2 verifier
# ---------------------------------------------------------------------------


def verify_lab2(
    dictionary: Dict[str, LabField],
    examples: Dict[str, Dict[str, Any]],
    ctx: Dict[str, Any],
) -> List[Finding]:
    """Check the ten-field control set against the examples and return one Finding per check.

    Checks, in order:
      * lab2.control_set: the dictionary holds exactly the ten control fields.
      * lab2.immutability.<field>: a non-blank immutability rule.
      * lab2.acceptance_text.<field>: a non-blank acceptance text and a callable test.
      * lab2.acceptance_good.<field>: the test passes on the example row of every clock.
      * lab2.acceptance_bad.<field>: the test rejects the bad value on every clock row.
      * lab2.clock_example.<clock>: one example row per clock, with its clock field set.
      * lab2.clock_order.<clock>: the example's clocks obey the ordering rules (no FAIL).
    """
    mods = _mods()
    findings: List[Finding] = []

    names = list(dictionary.keys())
    exact = len(names) == len(CONTROL_FIELDS) and set(names) == set(CONTROL_FIELDS)
    missing = sorted(set(CONTROL_FIELDS) - set(names))
    extra = sorted(set(names) - set(CONTROL_FIELDS))
    findings.append(_finding(
        "lab2.control_set", exact,
        "dictionary holds the exact ten-field control set" if exact else
        "control set mismatch: missing=%s extra=%s count=%d" % (missing, extra, len(names)),
        "dictionary",
    ))

    for name in CONTROL_FIELDS:
        spec = dictionary.get(name)
        if spec is None:
            for prefix in ("lab2.immutability", "lab2.acceptance_text", "lab2.acceptance_good", "lab2.acceptance_bad"):
                findings.append(_finding(prefix + "." + name, False, "field is absent from the dictionary", name))
            continue

        rule_ok = isinstance(spec.immutability, str) and spec.immutability.strip() != ""
        findings.append(_finding(
            "lab2.immutability." + name, rule_ok,
            "immutability rule present" if rule_ok else "immutability rule is empty", name,
        ))

        text_ok = isinstance(spec.acceptance_text, str) and spec.acceptance_text.strip() != ""
        callable_ok = callable(spec.acceptance)
        test_ok = text_ok and callable_ok
        findings.append(_finding(
            "lab2.acceptance_text." + name, test_ok,
            "acceptance test present" if test_ok else "acceptance test is blank or missing", name,
        ))

        good_failures = []
        bad_misses = []
        for clock, row in examples.items():
            if not _run_acceptance(spec, row.get(name), row, ctx):
                good_failures.append(clock)
            bad_row = dict(row)
            # A bad value is either fixed or computed from the row, such as a
            # self-reference that must name the row's own record_id.
            bad_row[name] = spec.bad_value(row) if callable(spec.bad_value) else spec.bad_value
            if _run_acceptance(spec, bad_row.get(name), bad_row, ctx):
                bad_misses.append(clock)
        findings.append(_finding(
            "lab2.acceptance_good." + name, not good_failures,
            "passes example rows for all %d clocks" % len(examples) if not good_failures else
            "rejects the valid example on clocks %s" % good_failures, name,
        ))
        findings.append(_finding(
            "lab2.acceptance_bad." + name, bool(examples) and not bad_misses,
            "rejects the bad value on all %d clock rows" % len(examples) if not bad_misses else
            "accepts the bad value on clocks %s, so the test is not real" % bad_misses, name,
        ))

    for clock in CLOCKS:
        field_name = CLOCK_FIELD[clock]
        row = examples.get(clock)
        spec = dictionary.get(field_name)
        present = (
            row is not None and spec is not None and spec.clock == clock
            and row.get(field_name) is not None
        )
        findings.append(_finding(
            "lab2.clock_example." + clock, present,
            "one-row example present with %s set" % field_name if present else
            "no example row, or %s is not governed by the %s clock" % (field_name, clock),
            clock,
        ))

    for clock in CLOCKS:
        row = examples.get(clock)
        if row is None or any(row.get(f) is None for f in (CLOCK_FIELD["event"], "published_at", "retrieved_at", "approved_at")):
            findings.append(_finding("lab2.clock_order." + clock, False, "example row is incomplete", clock))
            continue
        start = _period_start_datetime(row["effective_period"])
        clockset = mods.clocks_record.make_clockset(
            event_at=start,
            release_at=row["published_at"],
            ingest_at=row["retrieved_at"],
            knowledge_at=row["approved_at"],
        )
        order = mods.clock_ordering.check_clock_order(clockset)
        fails = [f.check_id for f in order if f.status is ValidationStatus.FAIL]
        warns = [f.check_id for f in order if f.status is ValidationStatus.WARN]
        findings.append(_finding(
            "lab2.clock_order." + clock, not fails,
            "no ordering FAIL (warn for unset clocks: %s)" % (warns or "none") if not fails else
            "ordering FAIL: %s" % fails,
            clock,
        ))
    findings.extend(_rule_probes(dictionary, examples, ctx))
    return findings


# Rejection probes for rules that the one-bad-value-per-field check does not
# reach. Each probe takes a valid example row, breaks one rule, and must be
# rejected by the named field's acceptance test. A missing field is a FAIL.
_PROBES: Tuple[Tuple[str, str, str, str], ...] = (
    # (probe name, clock whose example is used, field to break, reason)
    ("date_only_not_end_of_day", "release", "published_at",
     "a date-only source published at 13:00 is not the conservative 23:59:59Z value"),
    ("period_starts_after_publication", "event", "effective_period",
     "a period that starts after its publication date cannot be known at publication"),
    ("vintage_before_publication", "ingest", "vintage_date",
     "a vintage date one day before the published date is impossible"),
    ("approval_before_capture", "approval", "approved_at",
     "an approval earlier than the capture it approves is rejected"),
)


def _rule_probes(dictionary: Dict[str, LabField], examples: Dict[str, Dict[str, Any]],
                 ctx: Dict[str, Any]) -> List[Finding]:
    """Run the rejection probes in _PROBES and return one Finding per probe."""
    broken: Dict[str, Any] = {
        "date_only_not_end_of_day": _utc(2026, 4, 29, 13),
        "period_starts_after_publication": "2026-05",
        "vintage_before_publication": date(2026, 6, 4),
        "approval_before_capture": _utc(2026, 5, 6, 0),
    }
    findings: List[Finding] = []
    for probe_name, clock, field_name, reason in _PROBES:
        check_id = "lab2.probe." + probe_name
        spec = dictionary.get(field_name)
        if spec is None:
            findings.append(_finding(check_id, False, "field %s is absent" % field_name, probe_name))
            continue
        row = dict(examples[clock])
        value = broken[probe_name]
        row[field_name] = value
        accepted = _run_acceptance(spec, value, row, ctx)
        findings.append(_finding(
            check_id, not accepted,
            "rejected: %s" % reason if not accepted else
            "accepted, but the rule should reject it: %s" % reason,
            probe_name,
        ))
    return findings


def _period_start_datetime(text: str) -> datetime:
    """Midnight UTC on the first day of a period string."""
    start = _period_start(text)
    if start is None:
        raise AsOfError("not a period: %r" % (text,))
    return datetime(start.year, start.month, start.day, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Source register
# ---------------------------------------------------------------------------


def build_source_register(mods: SimpleNamespace) -> Tuple[Any, List[Dict[str, Any]], List[Finding]]:
    """Register each source through SourceRegister and record its limitation.

    Returns the register, a plain list for the results file, and findings. A
    date-only source with a blank limitation is a FAIL.
    """
    register = mods.source_register.SourceRegister()
    entries: List[Dict[str, Any]] = []
    findings: List[Finding] = []
    retrieved = _utc(2026, 10, 27, 0, 0)
    for source_id, source_type, publisher, locator, precision, limitation in _SOURCE_SPECS:
        payload = "synthetic payload for %s" % source_id
        digest = sha256_text(payload)
        register.add_source(SourceRecord(
            source_id=source_id,
            source_type=source_type,
            publisher=publisher,
            locator=locator,
            retrieved_at=retrieved,
            sha256=digest,
            synthetic=True,
        ))
        entries.append({
            "source_id": source_id,
            "source_type": source_type.value,
            "publisher": publisher,
            "locator": locator,
            "sha256": digest,
            "published_precision": precision,
            "limitation": limitation,
        })
        if precision == "date":
            findings.append(_finding(
                "source.date_only_limitation." + source_id,
                bool(limitation.strip()),
                "date-only source carries a limitation" if limitation.strip() else
                "date-only source has no limitation text",
                source_id,
            ))
    for source_id in _source_precision():
        findings.append(_finding(
            "source.registered." + source_id, register.has_source(source_id),
            "source is in the register", source_id,
        ))
    # Run the unregistered-source check rather than assert that it exists: one
    # unknown id (given twice) must give exactly one FAIL, and a known id none.
    unknown = "SYN_SRC-UNREGISTERED"
    used = register.check_sources_used([SRC_MACRO, unknown, unknown])
    unreg_ids = getattr(mods.source_register, "UNREGISTERED_CHECK_ID", None)
    fails = [f for f in used if f.status is ValidationStatus.FAIL]
    findings.append(_finding(
        "source.unregistered_fails_once",
        unreg_ids is not None and len(fails) == 1 and fails[0].check_id == unreg_ids
        and not register.check_sources_used([SRC_MACRO]),
        "an unregistered source id gives one %s FAIL and a registered id gives none" % unreg_ids,
        unknown,
    ))
    return register, entries, findings


def check_existing_dictionary(mods: SimpleNamespace) -> List[Finding]:
    """Compare with the existing as_of FIELD_DICTIONARY and report the gaps.

    The existing dictionary has analogous fields for the event, release,
    ingest and knowledge clocks, so those analogues must exist with the right
    clock (PASS). It has no vintage_date and no approved_at field, so those
    are gaps (WARN). Gaps do not fail the lab; the lab carries its own fields.
    """
    fd = mods.field_dictionary
    findings: List[Finding] = []
    analogues = (
        ("price_as_of", "EVENT"),
        ("macro_release_at", "RELEASE"),
        ("ingest_at", "INGEST"),
        ("estimate_knowledge_at", "KNOWLEDGE"),
    )
    for name, clock_name in analogues:
        spec = fd.FIELD_DICTIONARY.get(name)
        ok = spec is not None and spec.clock.name == clock_name
        findings.append(_finding(
            "dictionary.analogue." + name, ok,
            "existing dictionary governs %s by the %s clock" % (name, clock_name) if ok else
            "existing dictionary does not govern %s by %s" % (name, clock_name),
            name,
        ))
    for gap in ("vintage_date", "approved_at", "approved_by"):
        present = gap in fd.FIELD_DICTIONARY
        findings.append(Finding(
            check_id="dictionary.gap." + gap,
            status=ValidationStatus.PASS if present else ValidationStatus.WARN,
            message=("existing dictionary has %s" % gap) if present else
            "gap: %s is not in the existing as_of FIELD_DICTIONARY; the lab carries it in its own dictionary" % gap,
            subject=gap,
        ))
    return findings


# ---------------------------------------------------------------------------
# Planted failures on disposable copies
# ---------------------------------------------------------------------------


def run_planted_failures(
    dictionary: Dict[str, LabField],
    examples: Dict[str, Dict[str, Any]],
    ctx: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Run two planted failures on copies. Each must make the verifier FAIL."""
    outcomes: List[Dict[str, Any]] = []

    no_vintage = copy.deepcopy(dictionary)
    del no_vintage["vintage_date"]
    findings_a = verify_lab2(no_vintage, examples, ctx)
    outcomes.append(_planted_outcome(
        "delete_vintage_date", "dictionary copy with vintage_date deleted", findings_a,
        expected_checks=("lab2.control_set", "lab2.clock_example.vintage")))

    blank_test = copy.deepcopy(dictionary)
    blank_test["approved_at"] = dataclasses.replace(
        blank_test["approved_at"], acceptance_text="", acceptance=None)
    findings_b = verify_lab2(blank_test, examples, ctx)
    outcomes.append(_planted_outcome(
        "blank_acceptance_test", "dictionary copy with approved_at acceptance test blanked", findings_b,
        expected_checks=("lab2.acceptance_text.approved_at",)))

    # A planted copy whose acceptance test is kept but made too loose: the
    # date-only rule is replaced by a test that accepts any aware datetime.
    # Only the probe for that rule may fail, which shows the probes are real.
    loose = copy.deepcopy(dictionary)
    loose["published_at"] = dataclasses.replace(
        loose["published_at"],
        acceptance=lambda value, row, ctx: _is_aware(value))
    findings_c = verify_lab2(loose, examples, ctx)
    outcomes.append(_planted_outcome(
        "loose_published_at_test", "dictionary copy whose published_at test accepts any aware datetime",
        findings_c, expected_checks=("lab2.probe.date_only_not_end_of_day",)))
    return outcomes


def _planted_outcome(name: str, description: str, findings: List[Finding],
                     expected_checks: Tuple[str, ...]) -> Dict[str, Any]:
    """Score one planted copy. It passes only when every expected check is among the FAILs.

    A FAIL from an unrelated check does not count, so the outcome shows the
    planted defect itself was caught, not just that the copy is broken.
    """
    failed = [f.check_id for f in findings if f.status is ValidationStatus.FAIL]
    missing = [c for c in expected_checks if c not in failed]
    verdict = "FAIL" if failed else "PASS"
    return {
        "name": name,
        "description": description,
        "expected": "FAIL",
        "expected_checks": list(expected_checks),
        "observed": verdict,
        "as_expected": verdict == "FAIL" and not missing,
        "missing_expected_checks": missing,
        "failing_checks": failed,
    }


# ---------------------------------------------------------------------------
# April macro trace
# ---------------------------------------------------------------------------


def trace_april_macro(mods: SimpleNamespace) -> Tuple[List[Finding], Dict[str, Any]]:
    """Trace the April macro example: observation, June 5 vintage, July 3 revision.

    The observation is April 2026 (effective period 2026-04). The June 5
    vintage is the first release. The July 3 vintage is a later revision.
    At a June 10 decision time, the June 5 vintage is eligible and the July 3
    vintage is not: its release is after June 10, so it cannot enter that state.
    """
    series = "SYN_APR_DEMO"
    obs = date(2026, 4, 1)
    june5 = MacroVintage(series_id=series, obs_date=obs, vintage_date=date(2026, 6, 5),
                         release_at=_utc(2026, 6, 5, 13), value=2.1, source_id=SRC_MACRO)
    july3 = MacroVintage(series_id=series, obs_date=obs, vintage_date=date(2026, 7, 3),
                         release_at=_utc(2026, 7, 3, 13), value=2.4, source_id=SRC_MACRO)
    manifest = mods.macro_vintage_manifest.VintageManifest()
    manifest.add_vintage(june5)
    manifest.add_vintage(july3)

    june10 = _utc(2026, 6, 10, 12)
    july3_decision = _utc(2026, 7, 3, 14)
    value_june10 = mods.macro_cutoff_rule.value_as_of(manifest, series, obs, june10)
    value_july3 = mods.macro_cutoff_rule.value_as_of(manifest, series, obs, july3_decision)
    # The June 5 vintage was released at 13:00Z. Just before that instant the
    # cutoff must return nothing, and at that instant it must return the vintage.
    before_release = mods.macro_cutoff_rule.value_as_of(manifest, series, obs, _utc(2026, 6, 5, 12, 59, 59))
    at_release = mods.macro_cutoff_rule.value_as_of(manifest, series, obs, june5.release_at)
    # Using the vintage date as an observation date selects nothing for this series.
    value_by_vintage_date = mods.macro_cutoff_rule.value_as_of(manifest, series, date(2026, 6, 5), june10)
    violations_june10 = mods.macro_cutoff_rule.cutoff_violations([july3], june10)
    clean_june10 = mods.macro_cutoff_rule.cutoff_violations([june5], june10)

    clocks = [
        mods.clocks_record.make_clockset(event_at=_utc(2026, 4, 1), release_at=june5.release_at,
                                         knowledge_at=june5.release_at),
        mods.clocks_record.make_clockset(event_at=_utc(2026, 4, 1), release_at=july3.release_at,
                                         knowledge_at=july3.release_at),
    ]
    visible_june10 = mods.clock_as_of.visible_at(clocks, june10)

    findings = [
        _finding("april.june10_uses_june5_vintage",
                 value_june10 is june5,
                 "June 10 state takes the June 5 vintage (value %s)" % (
                     value_june10.value if value_june10 else None), series),
        _finding("april.july3_vintage_at_july3",
                 value_july3 is july3,
                 "a July 3 decision time takes the July 3 vintage", series),
        _finding("april.release_instant_is_the_cutoff",
                 before_release is None and at_release is june5,
                 "one second before the 13:00Z release the cutoff returns nothing; at 13:00Z it returns the June 5 vintage",
                 series),
        _finding("april.vintage_date_not_observation_date",
                 value_by_vintage_date is None,
                 "a June 5 vintage date does not select an observation (no June 5 observation)", series),
        _finding("april.july_cannot_enter_june10_state",
                 len(violations_june10) == 1 and violations_june10[0].status is ValidationStatus.FAIL,
                 "cutoff flags the July 3 value used at June 10 (%d finding)" % len(violations_june10), series),
        _finding("april.june5_allowed_at_june10",
                 clean_june10 == [],
                 "cutoff allows the June 5 value at June 10", series),
        _finding("april.clock_visibility_june10",
                 len(visible_june10) == 1,
                 "the knowledge clock shows one vintage visible at June 10", series),
    ]
    details = {
        "series_id": series,
        "observation": {"effective_period": "2026-04", "obs_date": obs.isoformat()},
        "eligible_vintage_june5": {"vintage_date": "2026-06-05", "release_at": "2026-06-05T13:00:00Z", "value": 2.1},
        "later_vintage_july3": {"vintage_date": "2026-07-03", "release_at": "2026-07-03T13:00:00Z", "value": 2.4},
        "decision_june10": "2026-06-10T12:00:00Z",
        "value_at_june10": value_june10.value if value_june10 else None,
        "value_at_july3_decision": value_july3.value if value_july3 else None,
        "why_july_cannot_enter_june10": "release 2026-07-03T13:00:00Z is after the 2026-06-10T12:00:00Z decision time, "
                                        "so the cutoff rule and the knowledge clock both exclude it",
        "manifest_hash": manifest.manifest_hash(),
    }
    return findings, details


# ---------------------------------------------------------------------------
# Estimate ledger: as-of time versus publication time
# ---------------------------------------------------------------------------


def trace_estimates(mods: SimpleNamespace) -> Tuple[List[Finding], Dict[str, Any]]:
    """Show that an estimate's as-of time is distinct from the result's publication time.

    Two analysts estimate EPS for a period. The result is published at 20:00Z
    on May 6. Analyst A revises on May 7 after the result. The revision's
    knowledge time is May 7, not May 6, so the consensus at any time between
    the two is the pre-result consensus.
    """
    ledger_cls = mods.estimate_ledger.EstimateLedger
    ledger = ledger_cls()
    ticker, metric, period = "SYN_TKR", "EPS", "2026Q2"
    result_published = _utc(2026, 5, 6, 20)

    ledger.append(_est(ticker, metric, period, "SYN_E1", "SYN_AN_A", 1.10, _utc(2026, 4, 15, 14), SRC_NOTE))
    ledger.append(_est(ticker, metric, period, "SYN_E2", "SYN_AN_B", 1.05, _utc(2026, 4, 20, 14), SRC_NOTE))
    ledger.append(_est(ticker, metric, period, "SYN_E3", "SYN_AN_A", 1.20, _utc(2026, 5, 7, 9), SRC_NOTE))

    before = ledger.consensus_as_of(ticker, metric, period, _utc(2026, 5, 6, 19, 59))
    at_publication = ledger.consensus_as_of(ticker, metric, period, result_published)
    after = ledger.consensus_as_of(ticker, metric, period, _utc(2026, 5, 7, 12))
    rows = ledger.rows(ticker, metric, period)
    revision = [r for r in rows if r.estimate_id == "SYN_E3"][0]
    original = [r for r in rows if r.estimate_id == "SYN_E1"][0]

    findings = [
        _finding("estimate.pre_result_consensus", before is not None and abs(before - 1.075) < 1e-9,
                 "consensus before the result is 1.075 (mean of 1.10 and 1.05)", "SYN_E1,SYN_E2"),
        _finding("estimate.at_publication_excludes_revision",
                 at_publication is not None and abs(at_publication - 1.075) < 1e-9,
                 "at the publication instant the May 7 revision is not yet known", "SYN_E3"),
        _finding("estimate.revision_known_after_publication",
                 revision.knowledge_at > result_published,
                 "revision knowledge_at is after the result's publication time", "SYN_E3"),
        _finding("estimate.asof_distinct_from_publication",
                 revision.knowledge_at != result_published and revision.source_id != SRC_RESULT,
                 "revision as-of time (2026-05-07T09:00:00Z) differs from result publication (2026-05-06T20:00:00Z)",
                 "SYN_E3"),
        _finding("estimate.post_revision_consensus", after is not None and abs(after - 1.125) < 1e-9,
                 "consensus after the revision is 1.125 (mean of 1.20 and 1.05)", "SYN_E3"),
        _finding("estimate.original_row_unchanged",
                 original.value == 1.10 and original.knowledge_at == _utc(2026, 4, 15, 14),
                 "the April row keeps its value and knowledge time after the revision", "SYN_E1"),
        _finding("estimate.ledger_validates",
                 not any(f.status is ValidationStatus.FAIL for f in ledger.validate()),
                 "ledger validation has no FAIL", "ledger"),
    ]
    details = {
        "ticker": ticker, "metric": metric, "period": period,
        "result_publication_at": "2026-05-06T20:00:00Z",
        "consensus_before_result": before,
        "consensus_at_publication": at_publication,
        "consensus_after_revision": after,
        "rows": [
            {"estimate_id": r.estimate_id, "analyst_id": r.analyst_id, "value": r.value,
             "knowledge_at": r.knowledge_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "source_id": r.source_id}
            for r in rows
        ],
    }
    return findings, details


def _est(ticker: str, metric: str, period: str, estimate_id: str, analyst: str,
         value: float, knowledge_at: datetime, source_id: str) -> Any:
    """Build one EstimateRecord (a core record type)."""
    return EstimateRecord(
        estimate_id=estimate_id, ticker=ticker, metric=metric, period=period,
        analyst_id=analyst, value=value, knowledge_at=knowledge_at, source_id=source_id,
    )


# ---------------------------------------------------------------------------
# Revisions and the append-only store
# ---------------------------------------------------------------------------


def append_revision(mods: SimpleNamespace, path: str, prior_row: Dict[str, Any],
                    changes: Dict[str, Any]) -> Dict[str, Any]:
    """Append a revision of prior_row to the JSON Lines store and return the new row.

    A revision needs a prior record_id. The new row's prior_record_id is set
    from prior_row, and the new record_id must differ from it. The prior row is
    never rewritten: the store only appends.
    """
    prior_id = prior_row.get("record_id")
    if not isinstance(prior_id, str) or not prior_id.strip():
        raise AsOfError("a revision requires a prior record_id")
    new_row = dict(prior_row)
    new_row.update(changes)
    new_id = new_row.get("record_id")
    if not isinstance(new_id, str) or new_id == prior_id:
        raise AsOfError("a revision needs its own record_id, different from the prior one")
    new_row["prior_record_id"] = prior_id
    mods.jsonl_store.append_record(path, new_row)
    return new_row


def trace_revision(mods: SimpleNamespace, path: str, examples: Dict[str, Dict[str, Any]]) -> Tuple[List[Finding], Dict[str, Any]]:
    """Check that a revision needs a prior id and leaves the prior row unchanged."""
    if os.path.exists(path):
        os.remove(path)  # the lab's own disposable scratch file, not a history
    prior = to_plain(examples["ingest"])
    prior_hash = stable_hash(prior)
    mods.jsonl_store.append_record(path, prior)
    with open(path, "r", encoding="utf-8") as handle:
        first_line_before = handle.readline()

    refused = False
    try:
        append_revision(mods, path, {"observed_value": 9.9}, {"record_id": "REC-NO-PRIOR-0001"})
    except AsOfError:
        refused = True

    revision_changes = {f: examples["vintage"][f] for f in CONTROL_FIELDS if f != "prior_record_id"}
    append_revision(mods, path, examples["ingest"], revision_changes)

    records = mods.jsonl_store.read_records(path)
    with open(path, "r", encoding="utf-8") as handle:
        first_line_after = handle.readline()

    findings = [
        _finding("revision.requires_prior_record_id", refused,
                 "a revision with no prior record_id is refused", "revision"),
        _finding("revision.prior_row_unchanged",
                 stable_hash(records[0]) == prior_hash and first_line_after == first_line_before,
                 "the first stored row is byte-identical after the revision is appended", "REC-APR-0001"),
        _finding("revision.prior_link_set",
                 len(records) == 2 and records[1]["prior_record_id"] == "REC-APR-0001",
                 "the revision row names REC-APR-0001 as its prior", "REC-APR-0002"),
        _finding("revision.store_has_two_rows", len(records) == 2,
                 "the store holds exactly the prior row and the revision", path),
    ]
    details = {
        "store_file": os.path.relpath(path, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "rows_after_revision": len(records),
        "prior_row_hash": prior_hash,
        "revision_refused_without_prior": refused,
    }
    return findings, details


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _finding_dict(finding: Finding) -> Dict[str, str]:
    return {
        "check_id": finding.check_id,
        "status": finding.status.value,
        "message": finding.message,
        "subject": finding.subject,
    }


def run_lab() -> Dict[str, Any]:
    """Run every part of the lab and return the results payload."""
    mods = _mods()
    dictionary = build_lab_dictionary()
    examples = build_examples()
    ctx = build_context()

    verifier_findings = verify_lab2(dictionary, examples, ctx)
    register, register_entries, register_findings = build_source_register(mods)
    dictionary_findings = check_existing_dictionary(mods)
    planted = run_planted_failures(dictionary, examples, ctx)
    april_findings, april_details = trace_april_macro(mods)
    estimate_findings, estimate_details = trace_estimates(mods)
    revision_findings, revision_details = trace_revision(mods, SCRATCH_STORE, examples)
    if os.path.exists(SCRATCH_STORE):
        os.remove(SCRATCH_STORE)

    verifier_status = "FAIL" if any(f.status is ValidationStatus.FAIL for f in verifier_findings) else "PASS"
    all_findings = (verifier_findings + register_findings + dictionary_findings
                    + april_findings + estimate_findings + revision_findings)
    planted_ok = all(p["as_expected"] for p in planted)
    body_ok = not any(f.status is ValidationStatus.FAIL for f in all_findings)
    overall = "PASS" if (verifier_status == "PASS" and planted_ok and body_ok) else "FAIL"

    counts = {"pass": 0, "warn": 0, "fail": 0}
    for finding in all_findings:
        counts[finding.status.value] += 1

    return {
        "lab": LAB_ID,
        "title": "Prove the five clocks and the field dictionary",
        "synthetic_only": True,
        "overall": overall,
        "lab2_verifier": {
            "status": verifier_status,
            "control_fields": list(CONTROL_FIELDS),
            "clocks": list(CLOCKS),
            "clock_field": CLOCK_FIELD,
            "checks": [_finding_dict(f) for f in verifier_findings],
        },
        "planted_failures": planted,
        "source_register": {
            "entries": register_entries,
            "limitations": [e["source_id"] for e in register_entries if e["limitation"]],
            "checks": [_finding_dict(f) for f in register_findings],
            "unregistered_check": "source.unregistered_fails_once runs source_register.check_sources_used on an unknown id",
        },
        "existing_field_dictionary": [_finding_dict(f) for f in dictionary_findings],
        "april_macro": {
            "details": april_details,
            "checks": [_finding_dict(f) for f in april_findings],
        },
        "estimate_ledger": {
            "details": estimate_details,
            "checks": [_finding_dict(f) for f in estimate_findings],
        },
        "revision_store": {
            "details": revision_details,
            "checks": [_finding_dict(f) for f in revision_findings],
        },
        "counts": counts,
    }


def write_results(payload: Dict[str, Any], path: str = RESULT_PATH) -> None:
    """Write the results file. Output is sorted and deterministic."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(to_plain(payload), indent=2, sort_keys=True) + "\n")


def main() -> int:
    payload = run_lab()
    write_results(payload)
    print("lab02 overall: %s" % payload["overall"])
    print("lab2 verifier: %s" % payload["lab2_verifier"]["status"])
    for planted in payload["planted_failures"]:
        print("planted %s: observed %s (expected FAIL, as_expected=%s)" % (
            planted["name"], planted["observed"], planted["as_expected"]))
    print("counts: %s" % payload["counts"])
    print("results: %s" % RESULT_PATH)
    return 0 if payload["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
