"""Failure mode fm24: manual run needs many unrelated commands.

The manual procedure is under-specified, so an operator runs a long list of
commands that are not part of the task. The detection is to compare the
executed actions with the task contract. The remedy is a deterministic script
that covers only the required steps.

Fixtures use the SYN_ prefix. The planted run is a list of step names only.
Nothing here runs a shell command or touches the real home folder.

Findings from the existing modules:
- state_manifest.StateManifest records any non-empty step name. It has no
  task contract, so an unrelated step such as a manual spreadsheet edit is
  recorded and the manifest still verifies. The unrelated steps are therefore
  not detected. This is tested as current behaviour below.
- No module compares a run's executed steps with a required step list, so no
  module flags or blocks a run padded with unrelated commands. The blocking
  test is marked xfail with the gap stated, not faked.
- cli.py is the deterministic entry point: one registered proof list, fixed
  subcommands, no operator-supplied commands. The remedy side is tested as
  present.
"""

from as_of.cli import main as cli_main
from as_of.state_manifest import StateManifest

import pytest

# Required steps for the planted task contract (synthetic names).
REQUIRED_STEPS = [
    "SYN_load_fixture",
    "SYN_run_proof",
    "SYN_validate",
    "SYN_write_manifest",
]

# Unrelated manual commands an operator ran to get the same result.
UNRELATED_STEPS = [
    "SYN_manual_edit_csv",
    "SYN_manual_copy_output",
    "SYN_manual_rename_file",
    "SYN_manual_pip_install",
    "SYN_manual_rerun_proof",
    "SYN_manual_grep_logs",
    "SYN_manual_open_spreadsheet",
    "SYN_manual_paste_numbers",
]

HASH_A = "a" * 64
HASH_B = "b" * 64
CODE_VERSION = "SYN_v1"


def _planted_manual_run():
    """Build a manifest that holds the required steps plus unrelated manual ones."""
    manifest = StateManifest()
    for name in REQUIRED_STEPS[:2]:
        manifest.record_step(name, {"SYN_input.csv": HASH_A}, {"SYN_out.csv": HASH_B}, CODE_VERSION)
    for name in UNRELATED_STEPS:
        manifest.record_step(name, {"SYN_input.csv": HASH_A}, {"SYN_out.csv": HASH_B}, CODE_VERSION)
    manifest.record_step(REQUIRED_STEPS[2], {"SYN_out.csv": HASH_B}, {"SYN_report.md": HASH_A}, CODE_VERSION)
    manifest.record_step(REQUIRED_STEPS[3], {"SYN_report.md": HASH_A}, {"SYN_manifest.json": HASH_B}, CODE_VERSION)
    return manifest


def test_fm24_state_manifest_records_unrelated_steps_without_complaint(tmp_path):
    # Current behaviour: the manifest accepts and verifies a run padded with
    # unrelated manual steps, because it has no task contract to compare with.
    manifest = _planted_manual_run()
    path = str(tmp_path / "SYN_fm24_run.json")
    manifest.save(path)

    names = [s["step_name"] for s in StateManifest.load(path).steps()]
    assert set(UNRELATED_STEPS).issubset(set(names))
    assert len(names) == len(REQUIRED_STEPS) + len(UNRELATED_STEPS)
    assert StateManifest.verify(path) is True


def test_fm24_cli_proofs_run_is_deterministic_with_no_operator_commands(capsys):
    # The remedy side that exists: the fixed proof list runs with one command
    # and needs no operator-supplied steps.
    code = cli_main(["proofs", "--all"])
    out = capsys.readouterr().out
    assert code == 0
    assert "0 failed" in out


def test_fm24_unrelated_manual_steps_are_detected_against_task_contract():
    # The detection step of fm24: compare the executed steps with the required
    # contract and flag or block the extras. No module in the as_of package
    # holds a required-step list or compares it with a run's steps, so this
    # cannot pass yet. Marked xfail, not faked.
    manifest = _planted_manual_run()
    executed = [s["step_name"] for s in manifest.steps()]
    extras = [name for name in executed if name not in REQUIRED_STEPS]
    assert extras == UNRELATED_STEPS  # the planted extras are present in the run
    pytest.xfail(
        "fm24 gap: no as_of module holds a task contract (required step list) "
        "or compares a run's executed steps with it, so unrelated manual "
        "commands are neither flagged nor blocked."
    )
