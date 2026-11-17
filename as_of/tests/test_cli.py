"""Tests for as_of.cli. All fixtures are synthetic (SYN_ prefix or made-up keys)."""

import pytest

from as_of import cli

# Synthetic AWS-style access key ID: fixed prefix plus 16 upper-case letters or digits.
# It is not a real credential.
SYN_AWS_KEY = "AKIASYN7THET1C000000"


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_proofs_all_returns_zero(capsys):
    assert cli.main(["proofs", "--all"]) == 0
    out = capsys.readouterr().out
    assert "proofs: 1 run, 0 failed" in out


def test_proofs_unknown_name_returns_two(capsys):
    assert cli.main(["proofs", "--name", "nope"]) == 2
    err = capsys.readouterr().err
    assert "unknown proof" in err
    assert "macro_vintage" in err


def test_secrets_scan_fake_key_returns_one(tmp_path, capsys):
    target = tmp_path / "SYN_config.txt"
    target.write_text("line one\naws_key = %s\n" % SYN_AWS_KEY, encoding="utf-8")
    assert cli.main(["secrets-scan", str(target)]) == 1
    out = capsys.readouterr().out
    assert "secrets-scan: FAIL" in out
    # The full key value must never be echoed by the CLI.
    assert SYN_AWS_KEY not in out


def test_help_raises_system_exit_zero():
    with pytest.raises(SystemExit) as info:
        cli.main(["--help"])
    assert info.value.code == 0


# ---------------------------------------------------------------------------
# Edge cases: usage errors
# ---------------------------------------------------------------------------


def test_proofs_all_and_name_together_returns_two(capsys):
    assert cli.main(["proofs", "--all", "--name", "macro_vintage"]) == 2
    assert "either --all or --name" in capsys.readouterr().err


def test_proofs_without_selection_returns_two(capsys):
    assert cli.main(["proofs"]) == 2
    assert "needs --all or --name" in capsys.readouterr().err


def test_proofs_long_alias_resolves(capsys):
    assert cli.main(["proofs", "--name", "proof_2_macro_vintage"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("PASS proof_2_macro_vintage\n")
    assert "proofs: 1 run, 0 failed" in out


def test_no_subcommand_returns_two():
    assert cli.main([]) == 2


def test_unknown_subcommand_returns_two():
    assert cli.main(["not-a-command"]) == 2


def test_folder_check_missing_root_returns_two(tmp_path, capsys):
    missing = tmp_path / "does_not_exist"
    assert cli.main(["folder-check", "--root", str(missing)]) == 2
    assert "not a directory" in capsys.readouterr().err


def test_validate_missing_root_returns_two(tmp_path):
    assert cli.main(["validate", "--root", str(tmp_path / "nope")]) == 2


def test_readiness_missing_output_folder_returns_two(tmp_path, capsys):
    out_path = tmp_path / "no_such_dir" / "record.md"
    assert cli.main(["readiness", "--out", str(out_path)]) == 2
    assert "output folder does not exist" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Edge cases: secrets scan
# ---------------------------------------------------------------------------


def test_secrets_scan_clean_file_returns_zero(tmp_path, capsys):
    target = tmp_path / "clean.txt"
    target.write_text("no credentials here\n", encoding="utf-8")
    assert cli.main(["secrets-scan", str(target)]) == 0
    assert "secrets-scan: PASS" in capsys.readouterr().out


def test_secrets_scan_requires_at_least_one_path():
    assert cli.main(["secrets-scan"]) == 2


# ---------------------------------------------------------------------------
# Edge cases: helpers
# ---------------------------------------------------------------------------


def test_resolve_proof_known_short_name():
    assert cli._resolve_proof("macro_vintage") == "macro_vintage"


def test_resolve_proof_alias():
    assert cli._resolve_proof("proof_2_macro_vintage") == "macro_vintage"


def test_resolve_proof_unknown_is_none():
    assert cli._resolve_proof("nope") is None


def test_collect_text_files_skips_hidden_and_cache_dirs(tmp_path):
    (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "skip.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "skip.md").write_text("x\n", encoding="utf-8")
    names = sorted(p.rsplit("/", 1)[-1] for p in cli._collect_text_files(str(tmp_path)))
    assert names == [".env", "keep.py"]
