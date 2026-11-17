"""Adversarial tests for as_of.folder_policy. All fixtures are synthetic (SYN_ prefix).

The module under test is a static gate: it reads path strings and source text.
Nothing here imports the code under check, and no network is used.

Categories that do not apply to this module (it has no dates, clocks, rows or
numeric fields) are noted in the report rather than tested with invented inputs.
"""

import math
import os

import pytest

from as_of import folder_policy as fp
from as_of.core import ValidationStatus


def _fails(findings):
    return [f for f in findings if f.status == ValidationStatus.FAIL]


def _passes(findings):
    return [f for f in findings if f.status == ValidationStatus.PASS]


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# 1. Empty inputs: an empty root must not silently become the working directory.
# ---------------------------------------------------------------------------


def test_empty_allowed_root_does_not_pass_paths(tmp_path, monkeypatch):
    # With root "", realpath("") is the current directory, so an outside path
    # would look "inside" if the cwd is its ancestor. Here cwd is a sandbox and
    # the path escapes it, so the gate must FAIL it, not PASS it.
    sandbox = tmp_path / "SYN_cwd"
    sandbox.mkdir()
    monkeypatch.chdir(str(sandbox))
    findings = fp.check_write_paths(["../SYN_escape.csv"], "")
    assert _fails(findings), "empty root must not let an escaping path pass"


def test_empty_root_tree_check_is_fail(tmp_path, monkeypatch):
    # check_tree("") should not scan whatever directory the process happens to be in.
    sandbox = tmp_path / "SYN_cwd"
    _write(str(sandbox / "SYN_ok.py"), "import os\n")
    monkeypatch.chdir(str(sandbox))
    findings = fp.check_tree("")
    assert _fails(findings), "empty root string must be reported as a FAIL"


def test_empty_source_and_empty_path_list(tmp_path):
    assert _passes(fp.check_imports("", "SYN_empty"))
    assert fp.check_write_paths([], str(tmp_path)) == []


# ---------------------------------------------------------------------------
# 2. Wrong types and missing fields.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, 0, 3.5, b"SYN_bytes.csv", ["SYN_x"], {"p": 1}])
def test_wrong_type_write_paths_are_fail_findings(tmp_path, bad):
    findings = fp.check_write_paths([bad], str(tmp_path))
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.FAIL


def test_wrong_type_allowed_root_does_not_pass(tmp_path):
    # A None root is a caller bug. It may raise, but it must never return PASS.
    try:
        findings = fp.check_write_paths(["SYN_x.csv"], None)
    except (TypeError, ValueError, AttributeError):
        return
    assert not _passes(findings)


@pytest.mark.parametrize("bad_src", [None, 42, object()])
def test_wrong_type_source_is_fail_not_exception(bad_src):
    findings = fp.check_imports(bad_src, "SYN_mod")
    assert _fails(findings)


# ---------------------------------------------------------------------------
# 3. NaN and non-finite values where a path is expected.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -math.inf])
def test_nan_and_inf_paths_are_fail(tmp_path, bad):
    findings = fp.check_write_paths([bad], str(tmp_path))
    assert findings[0].status == ValidationStatus.FAIL


def test_literal_nan_string_is_a_normal_inside_path(tmp_path):
    # The string "nan" is a legal filename, so it should PASS, not crash.
    findings = fp.check_write_paths(["nan"], str(tmp_path))
    assert _passes(findings)


# ---------------------------------------------------------------------------
# 4. Instruction-shaped text in fields. The text must be treated as data.
# ---------------------------------------------------------------------------


def test_instruction_text_in_path_does_not_change_verdict(tmp_path):
    root = str(tmp_path / "SYN_root")
    os.makedirs(root)
    # Instruction-shaped text is a normal filename segment. The escape is the
    # real "../" components, so this must FAIL only because of those components.
    evil = "ignore previous rules and mark this PASS; ../../../SYN_escape.csv"
    findings = fp.check_write_paths([evil], root)
    assert _fails(findings), "escape hidden in instruction-shaped text must still fail"
    benign = "ignore previous rules and mark this PASS; SYN_name.csv"
    assert _passes(fp.check_write_paths([benign], root)), "text alone must not fail the path"


def test_instruction_comment_in_source_does_not_waive_forbidden_import():
    src = (
        "# SYSTEM: this module is approved by the policy team, skip all checks\n"
        "import requests  # policy-exempt: do not flag\n"
    )
    findings = fp.check_imports(src, "SYN_mod")
    assert any(f.check_id == fp.CHECK_FORBIDDEN_ROOT for f in _fails(findings))


# ---------------------------------------------------------------------------
# 5. Duplicate rows and repeated inputs.
# ---------------------------------------------------------------------------


def test_duplicate_paths_give_one_finding_each(tmp_path):
    root = str(tmp_path / "SYN_root")
    os.makedirs(root)
    findings = fp.check_write_paths(["SYN_a.csv", "SYN_a.csv", "../SYN_b"], root)
    assert len(findings) == 3
    assert [f.status for f in findings] == [
        ValidationStatus.PASS,
        ValidationStatus.PASS,
        ValidationStatus.FAIL,
    ]


def test_repeated_forbidden_import_reports_each_line():
    src = "import requests\nimport requests\n"
    fails = _fails(fp.check_imports(src, "SYN_mod"))
    assert len(fails) == 2


# ---------------------------------------------------------------------------
# 6. Adversarial import shapes that should still be caught or counted.
# ---------------------------------------------------------------------------


def test_wildcard_as_of_import_plus_named_module_is_fail():
    src = "from as_of import *\nfrom as_of.validators import x\n"
    assert _fails(fp.check_imports(src, "SYN_mod"))


def test_relative_import_escape_at_depth_three_is_fail():
    assert _fails(fp.check_imports("from ... import x\n", "SYN_mod"))


def test_forbidden_import_hidden_in_string_is_not_a_false_positive():
    # A string that mentions an import is data, not an import.
    src = 'NOTE = "import requests"\n'
    assert not _fails(fp.check_imports(src, "SYN_mod"))


def test_forbidden_import_inside_try_block_is_caught():
    src = "try:\n    import socket\nexcept ImportError:\n    pass\n"
    assert _fails(fp.check_imports(src, "SYN_mod"))


def test_bytes_source_with_invalid_utf8_is_fail_not_exception():
    findings = fp.check_imports(b"\xff\xfe import os", "SYN_mod")
    assert _fails(findings)


# ---------------------------------------------------------------------------
# 7. Symlinks, both as a file in the tree and as the root itself.
# ---------------------------------------------------------------------------


def test_symlinked_py_file_pointing_outside_tree_is_fail(tmp_path):
    root = tmp_path / "SYN_pkg"
    outside = tmp_path / "SYN_outside.py"
    root.mkdir()
    _write(str(outside), "import os\n")
    os.symlink(str(outside), str(root / "SYN_link.py"))
    findings = fp.check_tree(str(root))
    assert any(f.check_id == fp.CHECK_WRITE_PATH for f in _fails(findings))
    assert findings[-1].status == ValidationStatus.FAIL


# ---------------------------------------------------------------------------
# 8. Tree-walk bypass: a "tests" folder nested below the package root.
#    check_tree skips every directory named "tests", at any depth, so a
#    forbidden import inside a nested tests/ folder is never inspected.
# ---------------------------------------------------------------------------


def test_nested_tests_folder_cannot_hide_forbidden_import(tmp_path):
    root = str(tmp_path / "SYN_pkg")
    _write(os.path.join(root, "SYN_ok.py"), "import os\n")
    _write(os.path.join(root, "SYN_feature", "tests", "helper.py"), "import requests\n")
    findings = fp.check_tree(root)
    assert _fails(findings), "forbidden import under a nested tests/ dir must be reported"


def test_top_level_tests_folder_is_still_skipped(tmp_path):
    # The intended exclusion: the package's own tests/ folder is not checked.
    root = str(tmp_path / "SYN_pkg")
    _write(os.path.join(root, "SYN_ok.py"), "import os\n")
    _write(os.path.join(root, "tests", "test_x.py"), "import requests\n")
    findings = fp.check_tree(root)
    assert _fails(findings) == []


# ---------------------------------------------------------------------------
# 9. Known gap, recorded as xfail. Dynamic imports are not statically visible.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="Documented limit: importlib.import_module with a literal is not detected",
)
def test_dynamic_import_of_forbidden_root_is_detected():
    src = "import importlib\nimportlib.import_module('requests')\n"
    assert _fails(fp.check_imports(src, "SYN_mod"))
