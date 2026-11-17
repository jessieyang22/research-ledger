"""Tests for as_of.folder_policy. All fixtures are synthetic (SYN_ prefix).

The module under test is a static gate, so these tests only read source text
and file paths. Nothing here imports the code they check, and no network is used.
"""

import os

import pytest

from as_of import folder_policy as fp
from as_of.core import ValidationStatus


def _statuses(findings):
    return [f.status for f in findings]


def _fails(findings):
    return [f for f in findings if f.status == ValidationStatus.FAIL]


# ---------------------------------------------------------------------------
# Write paths
# ---------------------------------------------------------------------------


def test_parent_escape_path_is_fail(tmp_path):
    root = str(tmp_path / "SYN_root")
    os.makedirs(root)
    findings = fp.check_write_paths(["../x"], root)
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].check_id == fp.CHECK_WRITE_PATH
    assert findings[0].subject == "../x"


def test_nested_relative_escape_is_fail(tmp_path):
    root = str(tmp_path / "SYN_root")
    os.makedirs(root)
    findings = fp.check_write_paths(["out/../../x.csv"], root)
    assert _statuses(findings) == [ValidationStatus.FAIL]


def test_absolute_path_outside_root_is_fail(tmp_path):
    root = str(tmp_path / "SYN_root")
    os.makedirs(root)
    outside = str(tmp_path / "SYN_other" / "x.csv")
    findings = fp.check_write_paths([outside], root)
    assert _statuses(findings) == [ValidationStatus.FAIL]


def test_sibling_with_shared_prefix_is_fail(tmp_path):
    # "SYN_root_evil" shares a string prefix with "SYN_root" but is not inside it.
    root = str(tmp_path / "SYN_root")
    os.makedirs(root)
    findings = fp.check_write_paths(["../SYN_root_evil/x.csv"], root)
    assert _statuses(findings) == [ValidationStatus.FAIL]


def test_relative_path_inside_root_is_pass(tmp_path):
    root = str(tmp_path / "SYN_root")
    os.makedirs(root)
    findings = fp.check_write_paths(["out/SYN_run.csv", "SYN_a.json"], root)
    assert _statuses(findings) == [ValidationStatus.PASS, ValidationStatus.PASS]


def test_root_itself_is_pass(tmp_path):
    root = str(tmp_path / "SYN_root")
    os.makedirs(root)
    findings = fp.check_write_paths(["."], root)
    assert _statuses(findings) == [ValidationStatus.PASS]


def test_absolute_path_inside_root_is_pass(tmp_path):
    root = str(tmp_path / "SYN_root")
    os.makedirs(root)
    inside = os.path.join(root, "SYN_ok.txt")
    findings = fp.check_write_paths([inside], root)
    assert _statuses(findings) == [ValidationStatus.PASS]


def test_symlink_pointing_outside_root_is_fail(tmp_path):
    root = str(tmp_path / "SYN_root")
    outside = tmp_path / "SYN_outside"
    os.makedirs(root)
    os.makedirs(str(outside))
    link = os.path.join(root, "SYN_link")
    os.symlink(str(outside), link)
    findings = fp.check_write_paths(["SYN_link/x.csv"], root)
    assert _statuses(findings) == [ValidationStatus.FAIL]


@pytest.mark.parametrize("bad", ["", None, 42])
def test_non_string_or_empty_path_is_fail(tmp_path, bad):
    root = str(tmp_path / "SYN_root")
    os.makedirs(root)
    findings = fp.check_write_paths([bad], root)
    assert _statuses(findings) == [ValidationStatus.FAIL]


def test_one_finding_per_path(tmp_path):
    root = str(tmp_path / "SYN_root")
    os.makedirs(root)
    paths = ["a.csv", "../b.csv", "c/d.csv"]
    findings = fp.check_write_paths(paths, root)
    assert len(findings) == len(paths)
    assert _statuses(findings) == [
        ValidationStatus.PASS,
        ValidationStatus.FAIL,
        ValidationStatus.PASS,
    ]


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def _import_fails(source):
    findings = fp.check_imports(source, "as_of.SYN_mod")
    return _fails(findings)


def test_import_quant_lab_is_fail():
    fails = _import_fails("import quant_lab\n")
    assert len(fails) == 1
    assert fails[0].check_id == fp.CHECK_FORBIDDEN_ROOT
    assert "quant_lab" in fails[0].message


def test_from_quant_lab_import_is_fail():
    assert _import_fails("from quant_lab.screens import run\n")


def test_import_quant_lab_submodule_is_fail():
    assert _import_fails("import quant_lab.models.hmm as hmm\n")


def test_network_and_subprocess_roots_are_fail():
    for name in ("requests", "urllib.request", "socket", "subprocess", "yfinance"):
        assert _import_fails("import %s\n" % name), name


def test_unknown_third_party_is_fail():
    fails = _import_fails("import notarealpkg_syn_xyz\n")
    assert len(fails) == 1
    assert fails[0].check_id == fp.CHECK_THIRD_PARTY


def test_numpy_pandas_and_stdlib_are_pass():
    source = "import os\nimport numpy as np\nimport pandas as pd\nfrom typing import List\n"
    findings = fp.check_imports(source, "as_of.SYN_mod")
    assert _fails(findings) == []
    assert _statuses(findings) == [ValidationStatus.PASS]


def test_core_plus_one_as_of_module_is_pass():
    source = "from as_of.core import Finding\nfrom as_of.SYN_a import thing\n"
    assert _import_fails(source) == []


def test_core_and_two_as_of_modules_is_fail():
    # Acceptance case: a module importing as_of.core and as_of.a and as_of.b is FAIL.
    source = (
        "import as_of.core\n"
        "from as_of.SYN_a import x\n"
        "from as_of.SYN_b import y\n"
    )
    fails = _import_fails(source)
    assert len(fails) == 1
    assert fails[0].check_id == fp.CHECK_AS_OF_IMPORTS
    assert "SYN_a" in fails[0].message and "SYN_b" in fails[0].message


def test_from_as_of_import_names_count_each_module():
    # `from as_of import a, b` expands to as_of.a and as_of.b.
    source = "from as_of.core import Finding\nfrom as_of import SYN_a, SYN_b\n"
    fails = _import_fails(source)
    assert [f.check_id for f in fails] == [fp.CHECK_AS_OF_IMPORTS]


def test_repeated_import_of_same_module_counts_once():
    source = "from as_of.SYN_a import x\nfrom as_of.SYN_a import y\nimport as_of.core\n"
    assert _import_fails(source) == []


def test_import_inside_function_is_still_counted():
    source = (
        "def f():\n"
        "    from as_of.SYN_a import x\n"
        "    return x\n"
        "import as_of.SYN_b\n"
        "import as_of.core\n"
    )
    fails = _import_fails(source)
    assert [f.check_id for f in fails] == [fp.CHECK_AS_OF_IMPORTS]


def test_relative_import_of_sibling_counts_as_as_of_module():
    source = "from . import SYN_a\nfrom .SYN_b import z\n"
    fails = _import_fails(source)
    assert [f.check_id for f in fails] == [fp.CHECK_AS_OF_IMPORTS]


def test_relative_import_climbing_above_package_is_fail():
    fails = _import_fails("from ..outside import thing\n")
    assert len(fails) == 1
    assert fails[0].check_id == fp.CHECK_FORBIDDEN_ROOT
    assert "above the as_of package" in fails[0].message


def test_syntax_error_becomes_fail_finding_not_exception():
    # Acceptance case: a syntax error becomes a FAIL finding rather than an exception.
    findings = fp.check_imports("def broken(:\n    pass\n", "as_of.SYN_bad")
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].check_id == fp.CHECK_SYNTAX
    assert findings[0].subject == "as_of.SYN_bad"
    assert "line" in findings[0].message


def test_null_byte_source_becomes_fail_finding_not_exception():
    findings = fp.check_imports("import os\x00\n", "as_of.SYN_nul")
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.FAIL
    assert findings[0].check_id == fp.CHECK_SYNTAX


def test_empty_source_is_pass():
    findings = fp.check_imports("", "as_of.SYN_empty")
    assert _statuses(findings) == [ValidationStatus.PASS]


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def test_check_tree_clean_tree_has_only_passing_summary(tmp_path):
    root = str(tmp_path / "SYN_pkg")
    _write(os.path.join(root, "SYN_ok.py"), "import os\n")
    findings = fp.check_tree(root)
    assert _fails(findings) == []
    summary = findings[-1]
    assert summary.check_id == fp.CHECK_TREE
    assert summary.status == ValidationStatus.PASS
    assert "1 python files checked" in summary.message


def test_check_tree_reports_violations_and_fails_summary(tmp_path):
    root = str(tmp_path / "SYN_pkg")
    _write(os.path.join(root, "SYN_bad.py"), "import quant_lab\n")
    _write(os.path.join(root, "sub", "SYN_broken.py"), "def x(:\n")
    findings = fp.check_tree(root)
    fail_ids = {f.check_id for f in _fails(findings)}
    assert fp.CHECK_FORBIDDEN_ROOT in fail_ids
    assert fp.CHECK_SYNTAX in fail_ids
    assert findings[-1].status == ValidationStatus.FAIL


def test_check_tree_skips_tests_and_venv_but_not_other_hidden(tmp_path):
    root = str(tmp_path / "SYN_pkg")
    _write(os.path.join(root, "tests", "test_x.py"), "import quant_lab\n")
    _write(os.path.join(root, ".venv", "v.py"), "import quant_lab\n")
    _write(os.path.join(root, "SYN_ok.py"), "import os\n")
    findings = fp.check_tree(root)
    assert _fails(findings) == []
    assert "1 python files checked" in findings[-1].message
    # A non-tooling hidden folder is checked, so a forbidden import there is caught.
    _write(os.path.join(root, ".hidden", "h.py"), "import quant_lab\n")
    assert _fails(fp.check_tree(root))


def test_check_tree_missing_root_is_fail(tmp_path):
    findings = fp.check_tree(str(tmp_path / "SYN_does_not_exist"))
    assert len(findings) == 1
    assert findings[0].check_id == fp.CHECK_TREE
    assert findings[0].status == ValidationStatus.FAIL
