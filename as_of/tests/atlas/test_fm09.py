"""Failure mode fm09: state manifest references a missing file.

The manifest lists a checkpoint path that does not exist, usually because the
checkpoint was incomplete. The guidance is to iterate over every path in the
manifest and confirm each file exists before the state is accepted. All
fixtures are synthetic (SYN_ prefix); no network, no real data.

Detection points checked:
  - checkpoints.should_skip returns False for a missing checkpoint file, so a
    resume never reuses a step whose file is absent. (detects, passing)
  - checkpoints.read_checkpoint raises AsOfError for a missing file. (detects)
  - checkpoints.should_skip returns False for a truncated (incomplete) file. (detects)
  - state_manifest.StateManifest.verify returns True for a manifest whose
    listed checkpoint file is missing, because it only checks the digest of
    the body and never resolves paths on disk. (gap, xfail)
  - checkpoints.latest_step reports a step whose checkpoint file exists but is
    incomplete, because it checks existence only. (gap, xfail)
  - No module iterates over the paths a manifest lists and confirms that each
    file exists before the state is accepted. (gap, xfail)
"""

import os

import pytest

from as_of.checkpoints import (
    CHECKPOINT_SUFFIX,
    latest_step,
    read_checkpoint,
    should_skip,
    write_checkpoint,
)
from as_of.core import AsOfError
from as_of.state_manifest import StateManifest

INPUT_HASH = "SYN_input_hash_1"
MISSING_STEP = "SYN_build"


def _manifest_listing_checkpoint(step):
    """A manifest whose output names a checkpoint path for the given step."""
    manifest = StateManifest()
    manifest.record_step(
        step,
        {"SYN_in.csv": "a" * 64},
        {os.path.join("SYN_checkpoints", step + CHECKPOINT_SUFFIX): "b" * 64},
        "SYN_v1",
    )
    return manifest


def _checkpoint_file(dir_path, step):
    return os.path.join(dir_path, step + CHECKPOINT_SUFFIX)


def _write_good_checkpoint(dir_path, step):
    manifest = _manifest_listing_checkpoint(step)
    return write_checkpoint(dir_path, step, {"SYN_rows": 3}, manifest, INPUT_HASH)


# --- detection points (passing) ---------------------------------------------


def test_missing_checkpoint_file_is_never_skipped(tmp_path):
    # Plant the failure: the checkpoint was written, then went missing.
    path = _write_good_checkpoint(str(tmp_path), MISSING_STEP)
    os.remove(path)
    assert should_skip(str(tmp_path), MISSING_STEP, INPUT_HASH) is False


def test_missing_checkpoint_file_raises_on_read(tmp_path):
    path = _write_good_checkpoint(str(tmp_path), MISSING_STEP)
    os.remove(path)
    with pytest.raises(AsOfError):
        read_checkpoint(str(tmp_path), MISSING_STEP)


def test_truncated_checkpoint_from_incomplete_write_is_never_skipped(tmp_path):
    # Plant the incomplete-checkpoint variant: the file exists but was cut short.
    path = _write_good_checkpoint(str(tmp_path), MISSING_STEP)
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text[: len(text) // 2])
    assert should_skip(str(tmp_path), MISSING_STEP, INPUT_HASH) is False
    with pytest.raises(AsOfError):
        read_checkpoint(str(tmp_path), MISSING_STEP)


def test_control_intact_checkpoint_is_skipped(tmp_path):
    # Control: the same step with its file intact is reusable, so the
    # rejections above come from the missing or cut file and not the fixture.
    _write_good_checkpoint(str(tmp_path), MISSING_STEP)
    assert should_skip(str(tmp_path), MISSING_STEP, INPUT_HASH) is True


# --- gaps (xfail) -----------------------------------------------------------


def test_manifest_listing_missing_checkpoint_path_is_rejected(tmp_path):
    # Plant: the manifest lists a checkpoint path, and the file does not exist.
    manifest = _manifest_listing_checkpoint(MISSING_STEP)
    manifest_path = os.path.join(str(tmp_path), "run_manifest.json")
    manifest.save(manifest_path)
    assert not os.path.exists(_checkpoint_file(str(tmp_path), MISSING_STEP))

    # Current behavior: verify() checks only the body digest, so it accepts the
    # manifest even though the listed file is absent. This is the gap.
    assert StateManifest.verify(manifest_path) is True
    pytest.xfail(
        "fm09 gap: StateManifest.verify() never resolves the paths a manifest "
        "lists, so a manifest pointing at a missing checkpoint file is accepted. "
        "No module checks that every listed path exists before state is accepted."
    )


def test_latest_step_does_not_report_an_incomplete_checkpoint(tmp_path):
    # Plant: the checkpoint file for MISSING_STEP exists but is truncated.
    path = _write_good_checkpoint(str(tmp_path), MISSING_STEP)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{")
    # Current behavior: latest_step checks file presence only, so it still
    # reports the incomplete step as the latest one. This is the gap.
    assert latest_step(str(tmp_path), [MISSING_STEP]) == MISSING_STEP
    pytest.xfail(
        "fm09 gap: checkpoints.latest_step checks existence only and does not "
        "verify content, so an incomplete checkpoint is reported as the latest step."
    )


def test_every_manifest_path_must_exist_before_state_is_accepted(tmp_path):
    # Plant two listed checkpoints; only one file is written.
    manifest = StateManifest()
    manifest.record_step(
        "SYN_ingest",
        {"SYN_in.csv": "a" * 64},
        {os.path.join("SYN_checkpoints", "SYN_ingest" + CHECKPOINT_SUFFIX): "b" * 64},
        "SYN_v1",
    )
    manifest.record_step(
        MISSING_STEP,
        {"SYN_in.csv": "a" * 64},
        {os.path.join("SYN_checkpoints", MISSING_STEP + CHECKPOINT_SUFFIX): "c" * 64},
        "SYN_v1",
    )
    os.makedirs(os.path.join(str(tmp_path), "SYN_checkpoints"))
    _write_good_checkpoint(os.path.join(str(tmp_path), "SYN_checkpoints"), "SYN_ingest")
    # A correct gate would iterate every listed path and block on the one
    # that is absent. No module in the package provides that gate.
    listed = [p for step in manifest.steps() for p in step["outputs"]]
    missing = [p for p in listed if not os.path.isfile(os.path.join(str(tmp_path), p))]
    assert missing == [os.path.join("SYN_checkpoints", MISSING_STEP + CHECKPOINT_SUFFIX)]
    pytest.xfail(
        "fm09 gap: no module exposes a gate that checks each manifest-listed path "
        "exists before accepting the run state. The check above is inlined in the "
        "test, not provided by the package."
    )
