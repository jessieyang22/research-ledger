"""Failure mode fm23: tool requests broad path access.

A tool asks for access to a wide directory tree that is larger than the task
needs. The expected control is that the request is compared with the policy
allowlist, denied, and narrowed to the required path.

Fixtures use the SYN_ prefix. The planted requests are path strings only and
are resolved against a synthetic tmp_path root. Nothing here touches the real
home folder.

Findings:
- folder_policy.check_write_paths does detect a request that escapes the
  allowed root (a parent folder or the filesystem root). That is tested as
  detected.
- It does not detect a request that stays inside the root but is wider than
  the task needs (the whole root instead of one file), because it only checks
  containment. There is no per-task allowlist of required paths in the
  package.
- folder_policy checks write paths only. Nothing checks the scope of read
  access requested by a tool, so the broad-read case is a gap.
The two gap tests are marked xfail (strict) and reported, not faked.
"""

import os

import pytest

from as_of.core import ValidationStatus
from as_of.folder_policy import CHECK_WRITE_PATH, check_write_paths

SYN_TASK_FILE = "SYN_out/SYN_required_result.csv"


def _root(tmp_path):
    root = tmp_path / "SYN_package"
    root.mkdir()
    return str(root)


def _fails(findings):
    return [f for f in findings if f.status == ValidationStatus.FAIL]


def test_parent_folder_request_is_denied(tmp_path):
    """Planted broad request: the parent of the package folder, not the task file."""
    root = _root(tmp_path)
    planted = os.path.dirname(root)
    findings = check_write_paths([planted], root)
    fails = _fails(findings)
    assert len(fails) == 1
    assert fails[0].check_id == CHECK_WRITE_PATH
    assert fails[0].subject == planted


def test_filesystem_root_request_is_denied(tmp_path):
    """Planted broad request: the filesystem root."""
    root = _root(tmp_path)
    findings = check_write_paths([os.sep], root)
    assert len(_fails(findings)) == 1


def test_traversal_to_wide_tree_is_denied(tmp_path):
    """Planted broad request reached by climbing out of the package with '..'."""
    root = _root(tmp_path)
    findings = check_write_paths(["../../.."], root)
    assert len(_fails(findings)) == 1


def test_required_path_inside_root_is_allowed(tmp_path):
    """Control: the narrow, required path passes, so the gate is not simply blocking everything."""
    root = _root(tmp_path)
    findings = check_write_paths([SYN_TASK_FILE], root)
    assert _fails(findings) == []
    assert findings[0].status == ValidationStatus.PASS


def test_broad_request_mixed_with_narrow_is_isolated(tmp_path):
    """Only the broad request fails when a narrow and a broad path are checked together."""
    root = _root(tmp_path)
    planted = os.path.dirname(root)
    findings = check_write_paths([SYN_TASK_FILE, planted], root)
    fails = _fails(findings)
    assert [f.subject for f in fails] == [planted]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm23 gap: folder_policy only checks containment in the allowed root. "
        "A request for the whole package tree (the root itself) inside the root "
        "passes, though one file was needed. No per-task allowlist of required "
        "paths exists in the package to narrow it."
    ),
)
def test_whole_root_request_for_single_file_task_is_denied(tmp_path):
    """Expected control: a write request for the whole root, when one file is needed, yields a FAIL."""
    root = _root(tmp_path)
    findings = check_write_paths(["."], root)
    assert len(_fails(findings)) == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm23 gap: folder_policy has no read-access check. A tool asking to read "
        "a wide tree (for example the whole parent folder) is not compared with "
        "any allowlist, so the broad read is neither denied nor narrowed."
    ),
)
def test_broad_read_request_is_denied(tmp_path):
    """Expected control: a read request for a parent folder yields a FAIL finding."""
    root = _root(tmp_path)
    read_request = os.path.dirname(root)
    # No read-scope API exists in the package; the write check is the only path gate.
    import as_of.folder_policy as fp

    read_checker = getattr(fp, "check_read_paths", None)
    assert read_checker is not None, "no read-path policy check exists"
    assert _fails(read_checker([read_request], root))
