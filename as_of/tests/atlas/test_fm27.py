"""Failure mode fm27: output appears outside the review queue.

A file is written to a path outside the allowed review location, so it reaches
its reader without passing review. Detection is to diff the output paths
against the allowed list and reject any path that resolves outside it.

Fixtures use the SYN_ prefix and tmp_path. Nothing here touches the real home
folder or any real output location.

What the repo has today:
  - folder_policy.check_write_paths resolves each write path against an
    allowed root (symlinks followed) and returns a FAIL for any path that
    lands outside that root. That is the only output-path gate in the package.
  - folder_policy.check_tree applies the same containment check to symlinked
    files and folders found under a tree.

Gap, marked xfail (strict):
  - The package has no named review queue location, and no check that ties a
    written output to an entry in the review queue. exception_queue holds
    records in memory and never sees output paths. So a file that is inside
    the package root but was never queued for review passes the gate.
"""

import os

import pytest

from as_of.core import ValidationStatus
from as_of.folder_policy import (
    CHECK_TREE,
    CHECK_WRITE_PATH,
    check_tree,
    check_write_paths,
)

SYN_REVIEW_FILE = "SYN_review/SYN_packet_v1.md"


def _review_root(tmp_path):
    """Synthetic allowed review location, one folder under tmp_path."""
    root = tmp_path / "SYN_review_root"
    root.mkdir()
    return str(root)


def _fails(findings):
    return [f for f in findings if f.status == ValidationStatus.FAIL]


def test_planted_absolute_output_outside_review_root_is_detected(tmp_path):
    """Planted: a packet written to a sibling folder, outside the review location."""
    root = _review_root(tmp_path)
    planted = str(tmp_path / "SYN_unqueued_drop" / "SYN_packet_v1.md")
    findings = check_write_paths([planted], root)
    fails = _fails(findings)
    assert len(fails) == 1
    assert fails[0].check_id == CHECK_WRITE_PATH
    assert fails[0].subject == planted


def test_planted_traversal_output_outside_review_root_is_detected(tmp_path):
    """Planted: a relative path that climbs out of the review location with '..'."""
    root = _review_root(tmp_path)
    findings = check_write_paths(["../SYN_unqueued_drop/SYN_packet_v1.md"], root)
    assert len(_fails(findings)) == 1


def test_planted_symlink_output_outside_review_root_is_detected(tmp_path):
    """Planted: a link inside the review location that points at an unqueued folder."""
    root = _review_root(tmp_path)
    outside = tmp_path / "SYN_unqueued_drop"
    outside.mkdir()
    link = os.path.join(root, "SYN_link_out")
    os.symlink(str(outside), link)
    findings = check_write_paths([os.path.join("SYN_link_out", "SYN_packet_v1.md")], root)
    assert len(_fails(findings)) == 1


def test_planted_symlinked_file_in_tree_is_detected(tmp_path):
    """Planted: check_tree catches a .py output-like file whose link escapes the root."""
    root = _review_root(tmp_path)
    outside_file = tmp_path / "SYN_outside_out.py"
    outside_file.write_text("x = 1\n")
    link = os.path.join(root, "SYN_linked_out.py")
    os.symlink(str(outside_file), link)
    findings = check_tree(root)
    tree_fails = [f for f in _fails(findings) if f.check_id == CHECK_WRITE_PATH]
    assert len(tree_fails) == 1
    assert tree_fails[0].subject == link


def test_control_output_inside_review_root_passes(tmp_path):
    """Control: the required output inside the review location is not blocked."""
    root = _review_root(tmp_path)
    findings = check_write_paths([SYN_REVIEW_FILE], root)
    assert _fails(findings) == []
    assert findings[0].status == ValidationStatus.PASS


def test_mixed_batch_isolates_the_planted_output(tmp_path):
    """Only the planted outside path fails when inside and outside paths are checked together."""
    root = _review_root(tmp_path)
    planted = str(tmp_path / "SYN_unqueued_drop" / "SYN_packet_v1.md")
    findings = check_write_paths([SYN_REVIEW_FILE, planted], root)
    assert [f.subject for f in _fails(findings)] == [planted]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm27 gap: no named review queue location exists in the package, and no "
        "check ties a written output to a queued review entry. folder_policy only "
        "checks containment in a root passed by the caller. An output inside the "
        "package root that was never queued for review therefore passes the gate."
    ),
)
def test_output_inside_root_but_not_queued_is_blocked(tmp_path):
    """Expected control: an output path with no review-queue entry yields a FAIL."""
    root = _review_root(tmp_path)
    unqueued = os.path.join("SYN_other_area", "SYN_packet_v1.md")
    findings = check_write_paths([unqueued], root)
    # No queue-membership API exists in the package. The containment check
    # alone cannot know whether the path was queued, so this assertion is the
    # expected control that is not implemented.
    import as_of.exception_queue as eq

    queue_check = getattr(eq, "check_output_queued", None)
    assert queue_check is not None, "no review-queue membership check exists"
    assert _fails(queue_check([unqueued], root))
    assert _fails(findings)
