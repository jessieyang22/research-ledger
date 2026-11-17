"""Failure mode fm10: new file added to an old state.

A historical backfill inserts a file into an existing frozen state. Earlier
packets were built on the old state, so they no longer describe what the
state holds. The detection method named in the failure-mode note is to compare
the file list in the state directory with the manifest. Any extra file should
trigger creation of a new linked state, not a silent reuse of the old one.

No network calls are made.

Findings from the existing modules:
- content_hash.hash_manifest hashes only the relative paths the caller passes
  in. It never lists a directory, so an extra file on disk is invisible to it.
- state_manifest.StateManifest stores caller-supplied hash strings. Its digest
  and verify() do not change when a file is added to the directory.
- checkpoints.should_skip compares the caller's input hash string. If that
  string is computed from the frozen file list, a backfilled file is not seen,
  and the stale checkpoint is reused.
- No module compares a state directory's file list with a manifest, and no
  module creates a linked successor state. Those two requirements are written
  as pytest.xfail tests below, with the gap stated.

The passing tests prove the blind spot and check that hash_manifest does detect
a change when the caller names the new file. The xfail tests are not faked.
"""

import os

import pytest

from as_of.checkpoints import should_skip, write_checkpoint
from as_of.content_hash import hash_manifest, hash_records
from as_of.state_manifest import StateManifest

FROZEN_FILES = ["SYN_fm10_prices.csv", "SYN_fm10_estimates.csv"]
BACKFILL_FILE = "SYN_fm10_backfill_late.csv"
STEP = "SYN_fm10_build"


def _write(root, name, text):
    with open(os.path.join(root, name), "w", encoding="utf-8") as handle:
        handle.write(text)


def _build_frozen_state(root):
    """Create the two frozen files, then freeze a manifest and a checkpoint on them."""
    _write(root, FROZEN_FILES[0], "date,px\n2026-01-02,100.0\n")
    _write(root, FROZEN_FILES[1], "date,eps\n2026-01-02,1.20\n")
    entries = hash_manifest(root, FROZEN_FILES)
    input_hash = hash_records(entries)
    manifest = StateManifest()
    manifest.record_step(
        "frozen_state",
        {"state_files": input_hash},
        {"state_files": input_hash},
        "SYN_fm10_v1",
    )
    manifest_path = os.path.join(root, "..", "SYN_fm10_manifest.json")
    manifest.save(manifest_path)
    checkpoint_dir = os.path.join(root, "..", "SYN_fm10_ckpt")
    write_checkpoint(checkpoint_dir, STEP, {"rows": 1}, manifest, input_hash)
    return entries, input_hash, manifest_path, checkpoint_dir


@pytest.fixture
def frozen(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    return str(state), _build_frozen_state(str(state))


def test_frozen_manifest_stays_clean_after_backfill_gap(frozen):
    # Gap proof: the manifest, its digest and its hash set do not change when a
    # file is backfilled into the directory, so nothing reports the change.
    root, (entries, input_hash, manifest_path, _) = frozen
    _write(root, BACKFILL_FILE, "date,px\n2025-12-31,99.0\n")
    assert hash_manifest(root, FROZEN_FILES) == entries
    assert hash_records(hash_manifest(root, FROZEN_FILES)) == input_hash
    assert StateManifest.verify(manifest_path) is True


def test_stale_checkpoint_is_reused_after_backfill_gap(frozen):
    # Gap proof: the checkpoint is still reused for the frozen input hash even
    # though the state directory now holds a file the packet never saw.
    root, (_, input_hash, _, checkpoint_dir) = frozen
    _write(root, BACKFILL_FILE, "date,px\n2025-12-31,99.0\n")
    assert should_skip(checkpoint_dir, STEP, input_hash) is True


def test_control_naming_the_backfill_changes_the_hash(frozen):
    # Control: hash_manifest does detect the change when the caller names the
    # new file. The blind spot is the missing directory listing, not the hash.
    root, (_, input_hash, _, _) = frozen
    _write(root, BACKFILL_FILE, "date,px\n2025-12-31,99.0\n")
    widened = hash_manifest(root, FROZEN_FILES + [BACKFILL_FILE])
    assert len(widened) == 3
    assert hash_records(widened) != input_hash


def test_extra_file_in_frozen_state_is_detected_and_blocked(frozen):
    # Required behaviour: comparing the directory listing with the manifest
    # should flag BACKFILL_FILE and block reuse of the frozen state.
    pytest.xfail(
        "GAP fm10: no module lists a state directory and compares it with the "
        "manifest. content_hash.hash_manifest hashes only caller-supplied paths, "
        "StateManifest and checkpoints.should_skip rely on a caller-supplied hash "
        "string, so an extra file in the frozen folder is not detected or blocked."
    )


def test_extra_file_creates_a_new_linked_state(frozen):
    # Required behaviour: a backfill should produce a successor state that links
    # back to the frozen one through its manifest digest. No module does this.
    pytest.xfail(
        "GAP fm10: no module creates a successor state linked to a frozen state "
        "when a file is added. StateManifest has no parent or link field, and "
        "nothing records a new state after a backfill."
    )
