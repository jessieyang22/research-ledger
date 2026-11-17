"""Failure mode fm33: scheduled output differs from manual run.

Environment or state drift means a scheduled run and a manual run of the same
task produce different results. The expected detection is to compare folder,
cutoff, permissions and hashes between the two runs, then pause and reproduce
manually until the difference is explained.

What the existing modules can and cannot see:

- state_manifest: digests change when any recorded input or output hash
  changes, so a cutoff or content drift shows up as a digest mismatch, but only
  when the caller records that value as a hash input.
- checkpoints: should_skip returns False when the input hash differs, so a
  manual run does not reuse a scheduled run's checkpoint.
- folder_policy.check_write_paths: a write path that resolves outside the
  allowed root is a FAIL, which catches a folder drift.
- content_hash.hash_manifest: file hashes differ when bytes differ.
- run_timeliness: classifies finish times against slots. It does not compare
  the content of two runs, so it is not a drift detector.

Gaps (reported as strict xfail, not faked):

- No module compares run configuration, such as an as-of cutoff that the caller
  did not hash into inputs, between two runs. The state manifest has no cutoff
  or config field of its own.
- No module records or compares file permissions or modes between runs.

Fixtures use the SYN_ prefix. Everything is written under pytest's tmp_path.
"""

import os
import stat

import pytest

from as_of.checkpoints import should_skip, write_checkpoint
from as_of.content_hash import hash_manifest
from as_of.core import ValidationStatus, stable_hash
from as_of.folder_policy import check_write_paths
from as_of.state_manifest import StateManifest

SCHED_CUTOFF = "2026-10-01T09:00:00Z"
MANUAL_CUTOFF = "2026-10-01T16:30:00Z"
CODE_VERSION = "SYN_FM33_v1"


def _run_manifest(cutoff_text, include_cutoff_hash=True):
    """Build a one-step manifest for a run. The cutoff hash is optional."""
    manifest = StateManifest()
    inputs = {"fixture": stable_hash({"SYN_SERIES": [1, 2, 3]})}
    if include_cutoff_hash:
        inputs["cutoff"] = stable_hash(cutoff_text)
    manifest.record_step(
        "SYN_FM33_ingest",
        inputs=inputs,
        outputs={"result": stable_hash({"SYN_VALUE": 42})},
        code_version=CODE_VERSION,
    )
    return manifest


def test_identical_scheduled_and_manual_runs_share_a_digest():
    """Control: the same cutoff and inputs give the same manifest digest."""
    sched = _run_manifest(SCHED_CUTOFF)
    manual = _run_manifest(SCHED_CUTOFF)
    assert sched.digest() == manual.digest()


def test_cutoff_drift_changes_manifest_digest():
    """Detection: a manual run on a different cutoff gets a different digest."""
    sched = _run_manifest(SCHED_CUTOFF)
    manual = _run_manifest(MANUAL_CUTOFF)
    assert sched.digest() != manual.digest()


def test_checkpoint_from_scheduled_run_is_not_reused_by_manual_run(tmp_path):
    """Block: a checkpoint written on the scheduled input is skipped only for the same input."""
    ckpt_dir = str(tmp_path / "SYN_ckpt")
    sched_hash = stable_hash({"cutoff": SCHED_CUTOFF})
    manual_hash = stable_hash({"cutoff": MANUAL_CUTOFF})
    write_checkpoint(
        ckpt_dir,
        "SYN_FM33_ingest",
        {"SYN_VALUE": 42},
        _run_manifest(SCHED_CUTOFF),
        sched_hash,
    )
    assert should_skip(ckpt_dir, "SYN_FM33_ingest", sched_hash) is True
    assert should_skip(ckpt_dir, "SYN_FM33_ingest", manual_hash) is False


def test_folder_drift_outside_allowed_root_is_flagged(tmp_path):
    """Detection: a manual run writing to another folder gets a FAIL write-path finding."""
    allowed = tmp_path / "SYN_pkg_out"
    allowed.mkdir()
    scheduled_rel = "SYN_run/out.json"
    manual_abs = str(tmp_path / "SYN_other_home" / "out.json")
    findings = check_write_paths([scheduled_rel, manual_abs], str(allowed))
    by_subject = {f.subject: f for f in findings}
    assert by_subject[scheduled_rel].status is ValidationStatus.PASS
    assert by_subject[manual_abs].status is ValidationStatus.FAIL


def test_content_drift_changes_file_hashes(tmp_path):
    """Detection: the same file name with different bytes gets a different hash."""
    sched_dir = tmp_path / "SYN_sched"
    manual_dir = tmp_path / "SYN_manual"
    sched_dir.mkdir()
    manual_dir.mkdir()
    (sched_dir / "series.csv").write_text("date,value\n2026-10-01,1.0\n")
    (manual_dir / "series.csv").write_text("date,value\n2026-10-01,1.5\n")
    sched_entries = hash_manifest(str(sched_dir), ["series.csv"])
    manual_entries = hash_manifest(str(manual_dir), ["series.csv"])
    assert sched_entries[0].sha256 != manual_entries[0].sha256


def test_tampered_scheduled_manifest_fails_verify(tmp_path):
    """Detection: a saved scheduled manifest edited after the run fails verification."""
    path = str(tmp_path / "SYN_sched_manifest.json")
    _run_manifest(SCHED_CUTOFF).save(path)
    assert StateManifest.verify(path) is True
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    edited = text.replace(stable_hash(SCHED_CUTOFF), stable_hash(MANUAL_CUTOFF))
    assert edited != text
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(edited)
    assert StateManifest.verify(path) is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm33 gap: the state manifest only sees a cutoff that the caller records "
        "as an input hash. A manual run whose cutoff was not hashed into inputs "
        "produces the same digest as the scheduled run. No module compares run "
        "configuration (cutoff, timezone, config) between runs."
    ),
)
def test_unhashed_cutoff_drift_is_detected():
    """Expected control: a cutoff drift not recorded as an input still changes the digest."""
    sched = _run_manifest(SCHED_CUTOFF, include_cutoff_hash=False)
    manual = _run_manifest(MANUAL_CUTOFF, include_cutoff_hash=False)
    assert sched.digest() != manual.digest(), "cutoff drift is invisible to the manifest"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm33 gap: no module records or compares file permissions or modes between "
        "a scheduled run and a manual run. content_hash hashes bytes only, and "
        "folder_policy checks paths only. Expected control: a mode change yields a FAIL."
    ),
)
def test_permission_drift_is_detected(tmp_path):
    """Expected control: a mode change on a written file is reported as drift."""
    sched_file = tmp_path / "SYN_sched_out.txt"
    manual_file = tmp_path / "SYN_manual_out.txt"
    sched_file.write_text("SYN_OUTPUT\n")
    manual_file.write_text("SYN_OUTPUT\n")
    os.chmod(str(sched_file), 0o644)
    os.chmod(str(manual_file), 0o600)
    assert stat.S_IMODE(os.stat(str(sched_file)).st_mode) != stat.S_IMODE(
        os.stat(str(manual_file)).st_mode
    )
    sched_entries = hash_manifest(str(tmp_path), ["SYN_sched_out.txt"])
    manual_entries = hash_manifest(str(tmp_path), ["SYN_manual_out.txt"])
    # Same bytes, so hashes match. Only the mode differs, and the manifest
    # entry has no field that could carry the mode.
    assert sched_entries[0].sha256 == manual_entries[0].sha256
    assert "mode" in [f.name for f in dataclasses.fields(ManifestEntry)]
