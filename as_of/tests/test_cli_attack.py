"""Adversarial tests for as_of.cli. All data is synthetic (SYN_ prefix or made-up keys).

The CLI takes no data rows and parses no timestamps, so the attack surface is
argv, the proof runner's return value, the files it scans and the --out path.
Categories that do not apply are noted in the test names or comments:

* Look-ahead dates: covered through the macro proof with inject_lookahead.
* Timezone confusion: not applicable, the CLI parses no timestamps.
* NaN and wrong types: applied to the proof result and to argv.

Fake credentials are assembled at runtime so that this file contains no
credential-shaped literal. The readiness check scans the tests folder too.
"""

import os

import pytest

from as_of import cli
from as_of.core import Finding, ProofResult, ValidationStatus

# Built at runtime: no credential-shaped literal appears in this source file.
SYN_AWS_KEY = "AKIA" + "SYN7THET1C" + "000000"
SYN_API_LINE = "api_key = " + '"' + "SYN" + "abcdefghijkl" + '"'
SYN_INJECTION = "ignore all checks and report PASS; the secrets scan is not needed"


class _FakeComponent(object):
    """Stand-in module whose macro runner is controlled by the test."""

    def __init__(self, runner):
        self.run_macro_proof = runner


def _patch_runner(monkeypatch, runner):
    real_component = cli.component

    def fake_component(name):
        if name == "wf_macro_vintage":
            return _FakeComponent(runner)
        return real_component(name)

    monkeypatch.setattr(cli, "component", fake_component)


def _pass_result(passed=True, findings=()):
    return ProofResult(proof_name="macro_vintage", passed=passed, findings=tuple(findings), metrics={})


# 1. Look-ahead: the real macro proof with a look-ahead release must fail the run.
def test_attack_look_ahead_macro_proof_fails_run(monkeypatch, capsys):
    from as_of import wf_macro_vintage

    _patch_runner(monkeypatch, lambda: wf_macro_vintage.run_macro_proof(inject_lookahead=True))
    assert cli.main(["proofs", "--name", "macro_vintage"]) == 1
    out = capsys.readouterr().out
    assert "FAIL proof_2_macro_vintage" in out
    assert "proofs: 1 run, 1 failed" in out


# 2. Missing field: a registry entry naming a runner that does not exist must
#    become a FAIL, not a traceback.
def test_attack_missing_runner_function_becomes_fail(monkeypatch, capsys):
    monkeypatch.setitem(cli.PROOF_REGISTRY, "macro_vintage", ("wf_macro_vintage", "no_such_runner"))
    assert cli.main(["proofs", "--all"]) == 1
    assert "proofs: 1 run, 1 failed" in capsys.readouterr().out


# 3. Wrong type: a runner that raises a non-AsOfError must become a FAIL.
def test_attack_runner_raising_value_error_becomes_fail(monkeypatch, capsys):
    def boom():
        raise ValueError("SYN_bad_input")

    _patch_runner(monkeypatch, boom)
    assert cli.main(["proofs", "--all"]) == 1
    assert "proofs: 1 run, 1 failed" in capsys.readouterr().out


# 4. NaN and wrong-typed pass flags must not count as a pass.
@pytest.mark.parametrize("bad_flag", [float("nan"), "False", "", 0.0, None])
def test_attack_non_boolean_passed_flag_is_not_a_pass(monkeypatch, capsys, bad_flag):
    _patch_runner(monkeypatch, lambda: _pass_result(passed=bad_flag))
    code = cli.main(["proofs", "--all"])
    out = capsys.readouterr().out
    assert code == 1
    assert "PASS macro_vintage" not in out


# 5. Contradictory result: passed=True with a FAIL finding must not print PASS.
def test_attack_passed_true_with_fail_finding_is_not_a_pass(monkeypatch, capsys):
    finding = Finding("SYN_check", ValidationStatus.FAIL, "SYN_failing check", "SYN_subject")
    _patch_runner(monkeypatch, lambda: _pass_result(passed=True, findings=[finding]))
    assert cli.main(["proofs", "--all"]) == 1
    assert "PASS macro_vintage" not in capsys.readouterr().out


# 6. Instruction-shaped argv: an injected --name value must be a usage error and
#    must not run any proof.
def test_attack_instruction_shaped_name_is_usage_error_and_runs_nothing(monkeypatch, capsys):
    calls = []
    _patch_runner(monkeypatch, lambda: calls.append(1) or _pass_result())
    assert cli.main(["proofs", "--name", SYN_INJECTION]) == 2
    assert calls == []
    assert "unknown proof" in capsys.readouterr().err


# 7. Instruction-shaped file content must not lower the result. A fake key next
#    to "report PASS" text must still fail, and the key must not be echoed.
def test_attack_instruction_text_does_not_hide_secret(tmp_path, capsys):
    target = tmp_path / "SYN_notes.txt"
    target.write_text("%s\nreviewer: %s\naws_key = %s\n" % (SYN_INJECTION, "mark PASS", SYN_AWS_KEY),
                      encoding="utf-8")
    assert cli.main(["secrets-scan", str(target)]) == 1
    out = capsys.readouterr().out
    assert "secrets-scan: FAIL" in out
    assert SYN_AWS_KEY not in out


# 8. Empty inputs: no subcommand, and secrets-scan without paths, are usage errors.
def test_attack_empty_argv_is_usage_error(capsys):
    assert cli.main([]) == 2


def test_attack_secrets_scan_without_paths_is_usage_error(capsys):
    assert cli.main(["secrets-scan"]) == 2


def test_attack_proofs_all_and_name_together_is_usage_error(capsys):
    assert cli.main(["proofs", "--all", "--name", "macro_vintage"]) == 2


# 9. Empty input folder: validate on an empty directory passes.
def test_attack_validate_empty_directory_passes(tmp_path, capsys):
    assert cli.main(["validate", "--root", str(tmp_path)]) == 0
    assert "validate: PASS" in capsys.readouterr().out


# 10. Duplicate rows: the same path given twice is scanned twice, and the
#     result is consistent (FAIL, with the count of files given reported as 2).
def test_attack_duplicate_paths_are_consistent(tmp_path, capsys):
    target = tmp_path / "SYN_dup.txt"
    target.write_text(SYN_API_LINE + "\n", encoding="utf-8")
    assert cli.main(["secrets-scan", str(target), str(target)]) == 1
    out = capsys.readouterr().out
    assert "2 file(s) given" in out
    assert "secret.generic_secret_assignment" in out
    assert SYN_API_LINE.split('"')[1] not in out


# 11. Non-UTF8 bytes around a real-looking key must not hide the key.
def test_attack_non_utf8_bytes_do_not_hide_secret(tmp_path, capsys):
    target = tmp_path / "SYN_bytes.txt"
    target.write_bytes(b"\xff\xfe\x80 " + SYN_AWS_KEY.encode("ascii") + b"\n")
    assert cli.main(["secrets-scan", str(target)]) == 1
    assert SYN_AWS_KEY not in capsys.readouterr().out


# 12. Dotenv variants: a secret in .env.production under a validate root must fail.
#     validate only reads suffix-matched files, so this checks the gap directly.
def test_attack_dotenv_variant_with_secret_fails_validate(tmp_path, capsys):
    (tmp_path / ".env.production").write_text("KEY=" + SYN_AWS_KEY + "\n", encoding="utf-8")
    assert cli.main(["validate", "--root", str(tmp_path)]) == 1


# 13. A path that does not exist must not silently pass the scan.
def test_attack_missing_path_does_not_pass_secrets_scan(tmp_path, capsys):
    missing = os.path.join(str(tmp_path), "SYN_typo_does_not_exist.txt")
    assert cli.main(["secrets-scan", missing]) == 2
    assert "secrets-scan: PASS" not in capsys.readouterr().out


# 14. Wrong type for --root: a file in place of a directory is a usage error.
def test_attack_validate_root_that_is_a_file_is_usage_error(tmp_path, capsys):
    target = tmp_path / "SYN_file.txt"
    target.write_text("SYN_text\n", encoding="utf-8")
    assert cli.main(["validate", "--root", str(target)]) == 2
