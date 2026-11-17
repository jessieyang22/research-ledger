"""Failure mode fm07: protected hash mismatch after freeze.

An input file changes after the state was frozen, and the change is not
explained. Detection pattern: recompute the digest of each protected file and
compare it with the manifest, then inspect the diff for any mismatch.

All fixtures are synthetic (SYN_ prefix) and written under pytest's tmp_path.
No network, no real data, no subprocess.

Detection points checked against the existing modules:
  - content_hash.hash_manifest recomputes SHA-256 per file. Recomputing after
    an edit yields a different digest. This part is detected and tested.
  - checkpoints.should_skip refuses to reuse a checkpoint whose recorded input
    hash differs from the current one. The step reruns. This blocks reuse
    silently. It does not report the drift, and it is tested as a block only.
  - macro_vintage_manifest refuses a second write to the same vintage key and
    its manifest hash moves on any row change. A frozen vintage cannot be
    overwritten through the API. Tested.
  - Gaps, marked strict xfail:
      * No module compares a stored ManifestEntry list with disk and returns
        Findings. Drift is found only if a caller recomputes the digests.
      * state_manifest.StateManifest.verify checks only the manifest's own
        body against its own digest. An edited input file does not fail it.
      * No module links a digest mismatch to a change record, so an explained
        edit and an unexplained edit cannot be told apart.
"""

from datetime import date, datetime, timezone

import pytest

from as_of import content_hash
from as_of.checkpoints import read_checkpoint, should_skip, write_checkpoint
from as_of.content_hash import hash_manifest
from as_of.core import AsOfError, MacroVintage
from as_of.macro_vintage_manifest import VintageManifest
from as_of.state_manifest import StateManifest

UTC = timezone.utc
PROTECTED_REL = ["inputs/prices.csv", "inputs/estimates.csv"]
ORIGINAL = {
    "inputs/prices.csv": b"SYN_TICKER,close\nSYN_A,10.0\nSYN_B,20.0\n",
    "inputs/estimates.csv": b"SYN_TICKER,eps\nSYN_A,1.5\nSYN_B,2.5\n",
}
SILENT_EDIT = b"SYN_TICKER,close\nSYN_A,10.5\nSYN_B,20.0\n"


def _write_inputs(root, files):
    for rel, data in files.items():
        full = root / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)


def _freeze(root):
    """Return (frozen manifest entries, StateManifest saved at freeze time)."""
    entries = hash_manifest(str(root), PROTECTED_REL)
    state = StateManifest()
    state.record_step(
        "load_inputs",
        inputs={e.path: e.sha256 for e in entries},
        outputs={"run_summary": "a" * 64},
        code_version="SYN_v1",
    )
    return entries, state


def _mismatches(frozen, current):
    """Return (path, frozen_sha, current_sha) for every changed or missing path."""
    current_by_path = {e.path: e for e in current}
    out = []
    for entry in frozen:
        now = current_by_path.get(entry.path)
        if now is None or now.sha256 != entry.sha256:
            out.append((entry.path, entry.sha256, None if now is None else now.sha256))
    return out


@pytest.fixture
def frozen_root(tmp_path):
    _write_inputs(tmp_path, ORIGINAL)
    entries, state = _freeze(tmp_path)
    state_path = tmp_path / "state" / "run.json"
    state.save(str(state_path))
    return {
        "root": tmp_path,
        "entries": entries,
        "state": state,
        "state_path": str(state_path),
    }


def test_unchanged_inputs_recompute_to_frozen_digests(frozen_root):
    # Control: with no edit, recomputation matches the freeze exactly.
    now = hash_manifest(str(frozen_root["root"]), PROTECTED_REL)
    assert _mismatches(frozen_root["entries"], now) == []


def test_silent_edit_to_protected_file_is_detected_by_recomputation(frozen_root):
    root = frozen_root["root"]
    _write_inputs(root, {"inputs/prices.csv": SILENT_EDIT})

    now = hash_manifest(str(root), PROTECTED_REL)
    diffs = _mismatches(frozen_root["entries"], now)

    assert [d[0] for d in diffs] == ["inputs/prices.csv"]
    _, frozen_sha, current_sha = diffs[0]
    assert frozen_sha != current_sha
    # The untouched file still matches, so the diff names exactly one path.


def test_deleted_protected_file_is_reported_as_mismatch(frozen_root):
    root = frozen_root["root"]
    (root / "inputs" / "estimates.csv").unlink()

    # hash_manifest refuses a missing file, so the recomputation itself must
    # not silently skip it. The mismatch is reported through the error.
    with pytest.raises(AsOfError):
        hash_manifest(str(root), PROTECTED_REL)


def test_frozen_state_input_hash_no_longer_matches_after_edit(frozen_root):
    root = frozen_root["root"]
    _write_inputs(root, {"inputs/prices.csv": SILENT_EDIT})

    frozen_inputs = frozen_root["state"].steps()[0]["inputs"]
    now = {e.path: e.sha256 for e in hash_manifest(str(root), PROTECTED_REL)}
    drifted = sorted(k for k, v in frozen_inputs.items() if now[k] != v)
    assert drifted == ["inputs/prices.csv"]


def test_checkpoint_is_not_reused_after_input_drift(frozen_root, tmp_path):
    root = frozen_root["root"]
    ckpt_dir = str(tmp_path / "ckpt")
    input_hash = content_hash.hash_records(
        [e.sha256 for e in frozen_root["entries"]]
    )
    write_checkpoint(
        ckpt_dir,
        "load_inputs",
        {"rows": 2},
        frozen_root["state"],
        input_hash,
    )
    assert read_checkpoint(ckpt_dir, "load_inputs") == {"rows": 2}
    assert should_skip(ckpt_dir, "load_inputs", input_hash) is True

    _write_inputs(root, {"inputs/prices.csv": SILENT_EDIT})
    drifted_hash = content_hash.hash_records(
        [e.sha256 for e in hash_manifest(str(root), PROTECTED_REL)]
    )
    assert drifted_hash != input_hash
    # Blocked from reuse: the step must run again on the drifted input.
    assert should_skip(ckpt_dir, "load_inputs", drifted_hash) is False


def test_frozen_vintage_cannot_be_overwritten_and_hash_is_stable(tmp_path):
    vm = VintageManifest()
    row = MacroVintage(
        series_id="SYN_SERIES",
        obs_date=date(2026, 3, 31),
        vintage_date=date(2026, 4, 15),
        release_at=datetime(2026, 4, 15, 12, 30, tzinfo=UTC),
        value=101.5,
        source_id="SYN_SOURCE",
    )
    vm.add_vintage(row)
    frozen_hash = vm.manifest_hash()

    revised = MacroVintage(
        series_id="SYN_SERIES",
        obs_date=date(2026, 3, 31),
        vintage_date=date(2026, 4, 15),
        release_at=datetime(2026, 4, 15, 12, 30, tzinfo=UTC),
        value=99.0,
        source_id="SYN_SOURCE",
    )
    with pytest.raises(AsOfError):
        vm.add_vintage(revised)
    # The rejected overwrite changed nothing, so the frozen digest holds.
    assert vm.manifest_hash() == frozen_hash
    assert vm.to_list()[0]["value"] == 101.5


def test_state_manifest_verify_is_true_before_any_input_edit(frozen_root):
    # Control: the saved manifest verifies while its inputs are untouched.
    assert StateManifest.verify(frozen_root["state_path"]) is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm07 gap: StateManifest.verify checks only the manifest body against "
        "its own digest. An edited protected input file does not make a saved "
        "state fail verification."
    ),
)
def test_state_manifest_verify_flags_edited_input_file(frozen_root):
    _write_inputs(frozen_root["root"], {"inputs/prices.csv": SILENT_EDIT})
    assert StateManifest.verify(frozen_root["state_path"]) is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm07 gap: no module compares a stored ManifestEntry list with the "
        "files on disk and returns Findings. content_hash.hash_manifest only "
        "computes digests, and a caller must do the diff itself."
    ),
)
def test_drift_is_reported_as_a_finding_by_a_checking_module():
    checkers = [
        name
        for name in ("verify_manifest", "check_manifest", "drift_findings")
        if hasattr(content_hash, name)
    ]
    assert checkers, "no content_hash function compares a manifest with disk"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm07 gap: an unexplained digest mismatch cannot be told apart from an "
        "explained one. change_records.ChangeRecord has no link to a file path "
        "or digest, so no module can show that an edit was approved."
    ),
)
def test_unexplained_edit_is_blocked_while_explained_edit_passes(frozen_root):
    from as_of import change_records

    root = frozen_root["root"]
    _write_inputs(root, {"inputs/prices.csv": SILENT_EDIT})
    diffs = _mismatches(
        frozen_root["entries"],
        hash_manifest(str(root), PROTECTED_REL),
    )
    assert diffs, "fixture did not drift"

    rec = change_records.open_change(
        "SYN_CHG_1", "update SYN prices", "SYN reason", date(2026, 10, 1)
    )
    link_fields = [f for f in rec.__dataclass_fields__ if "path" in f or "sha" in f]
    assert link_fields, "change record cannot name the file or digest it explains"
