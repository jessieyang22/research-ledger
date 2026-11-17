"""Failure mode fm08: a prior estimate row changed.

Failure mode fm08 "Prior estimate row changed": an update-in-place behavior
overwrote a prior estimate row, so approved history is lost. The detection
rule is to compare current rows with a frozen snapshot, and to require that
each revision is appended as a new linked row, never overwritten.

Everything here is synthetic (SYN_ ids, invented numbers). No network access
is used.

What the existing modules do with this failure:
    * estimate_ledger.append refuses a second row with the same
      (analyst, ticker, metric, period, knowledge_at). A revision with a new
      knowledge_at is appended as a new row, and the earlier row stays.
    * estimate_ledger has no update or delete method, so the public API
      cannot overwrite a row. The row list is a private attribute, though,
      and nothing in the module detects a change made through it.
    * estimate_ledger.validate checks only naive times and non-finite values.
      It does not compare against a snapshot, so a changed row passes.
    * content_hash.hash_records gives an order-sensitive digest of a record
      list. Taking a digest before and after shows any in-place change.
      It is a tool, not a check: nothing calls it on the ledger.
    * jsonl_store has no overwrite path, and read_records does not detect a
      rewritten line. content_hash.sha256_file detects it.
    * EstimateRecord has no field that links a revision to the row it
      supersedes, so "linked" revisions are not enforced anywhere.

So the snapshot digest detects the planted overwrite, and the public ledger
API blocks the same-key overwrite. The gaps are that the ledger never
compares against a snapshot itself, and that revisions are not linked. The
gap tests below record current behavior, or are strict xfails for the
missing detector.
"""

import dataclasses
from datetime import datetime, timezone

import pytest

from as_of.content_hash import hash_records, sha256_file
from as_of.core import AsOfError, EstimateRecord, ValidationStatus
from as_of.estimate_ledger import EstimateLedger
from as_of.jsonl_store import append_record, count_records, read_records

TICKER = "SYN_T08"
METRIC = "eps"
PERIOD = "2026Q3"
SOURCE = "SYN_SRC_FM08_01"


def _rec(est_id, analyst, value, when):
    return EstimateRecord(
        estimate_id=est_id,
        ticker=TICKER,
        metric=METRIC,
        period=PERIOD,
        analyst_id=analyst,
        value=value,
        knowledge_at=when,
        source_id=SOURCE,
    )


def _planted_ledger():
    """Two analysts with an original estimate and one later revision."""
    ledger = EstimateLedger()
    ledger.append(_rec("SYN_EST_08_A1", "SYN_AN_A", 1.00,
                       datetime(2026, 1, 10, tzinfo=timezone.utc)))
    ledger.append(_rec("SYN_EST_08_B1", "SYN_AN_B", 2.00,
                       datetime(2026, 1, 12, tzinfo=timezone.utc)))
    ledger.append(_rec("SYN_EST_08_A2", "SYN_AN_A", 1.20,
                       datetime(2026, 2, 10, tzinfo=timezone.utc)))
    return ledger


def _snapshot(ledger):
    """Frozen digest of the current rows, in ledger order."""
    return hash_records(list(ledger.rows(TICKER, METRIC, PERIOD)))


def test_fm08_revision_appended_as_new_row_keeps_prior_row():
    """Correct behavior: a revision is a new row, and the prior row stays.

    The consensus as of a date before the revision still uses the original
    value, so approved history is readable after the revision.
    """
    ledger = _planted_ledger()
    ids = [r.estimate_id for r in ledger.rows(TICKER, METRIC, PERIOD)]
    assert "SYN_EST_08_A1" in ids
    assert "SYN_EST_08_A2" in ids
    before_revision = datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert ledger.consensus_as_of(TICKER, METRIC, PERIOD, before_revision) == pytest.approx(1.50)


def test_fm08_same_key_overwrite_is_refused_by_append():
    """Planted overwrite: the same analyst and knowledge time with a new value.

    estimate_ledger.append blocks it with AsOfError, so the original row is
    not replaced.
    """
    ledger = _planted_ledger()
    overwrite = _rec("SYN_EST_08_A1_OVR", "SYN_AN_A", 9.99,
                     datetime(2026, 1, 10, tzinfo=timezone.utc))
    with pytest.raises(AsOfError):
        ledger.append(overwrite)
    kept = [r for r in ledger.rows(TICKER, METRIC, PERIOD) if r.analyst_id == "SYN_AN_A"]
    assert kept[0].value == pytest.approx(1.00)
    assert len(kept) == 2


def test_fm08_in_place_change_is_detected_by_snapshot_digest():
    """Planted update-in-place: a stored row is replaced through the private list.

    The public API cannot do this. The fixture simulates the failure by
    writing to the row list directly. content_hash.hash_records against the
    frozen snapshot detects the change.
    """
    ledger = _planted_ledger()
    frozen = _snapshot(ledger)

    idx = next(i for i, r in enumerate(ledger._rows) if r.estimate_id == "SYN_EST_08_A1")
    ledger._rows[idx] = dataclasses.replace(ledger._rows[idx], value=9.99)

    assert _snapshot(ledger) != frozen


def test_fm08_in_place_change_is_visible_in_consensus_before_detection():
    """Harm check: the planted overwrite moves the historical consensus.

    After the change, the as-of-January consensus is no longer the value that
    was approved at the time. This shows why the snapshot comparison matters.
    """
    ledger = _planted_ledger()
    as_of = datetime(2026, 1, 20, tzinfo=timezone.utc)
    approved = ledger.consensus_as_of(TICKER, METRIC, PERIOD, as_of)
    idx = next(i for i, r in enumerate(ledger._rows) if r.estimate_id == "SYN_EST_08_A1")
    ledger._rows[idx] = dataclasses.replace(ledger._rows[idx], value=9.99)
    assert ledger.consensus_as_of(TICKER, METRIC, PERIOD, as_of) != pytest.approx(approved)


def test_fm08_ledger_validate_misses_in_place_change():
    """Gap record: EstimateLedger.validate passes a row that was changed in place.

    validate has no snapshot argument and no history, so it reports a clean
    ledger. This asserts the current behavior so the gap stays visible.
    It is not a sign that the check is correct.
    """
    ledger = _planted_ledger()
    idx = next(i for i, r in enumerate(ledger._rows) if r.estimate_id == "SYN_EST_08_A1")
    ledger._rows[idx] = dataclasses.replace(ledger._rows[idx], value=9.99)
    findings = ledger.validate()
    assert [f for f in findings if f.status == ValidationStatus.FAIL] == []


def test_fm08_rewritten_jsonl_line_is_detected_by_file_digest(tmp_path):
    """Planted rewrite: one line of the JSONL history is edited on disk.

    jsonl_store.read_records and count_records still see two records, so the
    store alone does not detect the edit. The file digest changes.
    """
    path = str(tmp_path / "fm08_history.jsonl")
    append_record(path, {"estimate_id": "SYN_EST_08_A1", "value": 1.00})
    append_record(path, {"estimate_id": "SYN_EST_08_A2", "value": 1.20})
    frozen = sha256_file(path)
    assert count_records(path) == 2

    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    lines[0] = lines[0].replace("1.0", "9.9")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    assert count_records(path) == 2
    assert read_records(path)[0]["value"] == pytest.approx(9.9)
    assert sha256_file(path) != frozen


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm08 gap: no as_of module requires a revision to link to the row it "
        "supersedes. EstimateRecord has no supersedes field, and "
        "EstimateLedger.append accepts an unlinked row with a new knowledge "
        "time. Add a link check that refuses a revision without a reference "
        "to a known prior row to close this."
    ),
)
def test_fm08_unlinked_revision_is_refused():
    """Target behavior: a revision that does not link to a prior row is refused.

    The ledger currently accepts it, so the expected AsOfError is not raised
    and the test fails, which xfail reports as expected.
    """
    ledger = _planted_ledger()
    unlinked = _rec("SYN_EST_08_A3_UNLINKED", "SYN_AN_A", 1.30,
                    datetime(2026, 3, 10, tzinfo=timezone.utc))
    with pytest.raises(AsOfError):
        ledger.append(unlinked)
