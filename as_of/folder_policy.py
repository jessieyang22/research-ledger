"""Folder and import policy checks for the as_of package.

This module is a static gate. It reads file paths and source text and returns
Finding records. It never imports or runs the code it checks, and it makes no
network calls. All data it touches is synthetic or source code.

Three entry points:

1. check_write_paths: each write path must resolve inside the allowed root.
2. check_imports: a module's import statements must follow the design rules.
3. check_tree: both checks applied to every Python file under a folder.

Import rules, taken from as_of.core:
- Any import whose top-level name is in FORBIDDEN_IMPORT_ROOTS is a FAIL.
- Third-party imports are allowed only for ALLOWED_THIRD_PARTY (numpy, pandas).
  Standard-library imports are allowed.
- A module may statically import at most one as_of module besides as_of.core.

Only as_of.core is imported here, for the shared Finding and ValidationStatus
types and the rule constants. No other as_of module is needed.

Topic: "folder policy and controls".
"""

import ast
import functools
import importlib.util
import os
import sysconfig
from typing import List, Sequence, Set, Tuple

from as_of.core import (
    ALLOWED_THIRD_PARTY,
    FORBIDDEN_IMPORT_ROOTS,
    PACKAGE_NAME,
    Finding,
    ValidationStatus,
)


CHECK_WRITE_PATH: str = "folder_policy.write_path"
CHECK_FORBIDDEN_ROOT: str = "folder_policy.forbidden_root"
CHECK_THIRD_PARTY: str = "folder_policy.third_party"
CHECK_AS_OF_IMPORTS: str = "folder_policy.as_of_imports"
CHECK_SYNTAX: str = "folder_policy.syntax"
CHECK_TREE: str = "folder_policy.tree"

CORE_MODULE: str = PACKAGE_NAME + ".core"

# Folders that check_tree never descends into. Tests are excluded because
# they legitimately import several as_of modules to exercise them, but only
# the package's own tests/ folder (see check_tree). Tooling caches and virtual
# environments are excluded at any depth. Other hidden folders are NOT skipped,
# because a hidden folder is an easy place to hide a forbidden import.
_SKIP_DIRS: Tuple[str, ...] = ("__pycache__", ".venv", "venv", "tests")
_TOOL_DIRS: Tuple[str, ...] = (
    "__pycache__",
    ".venv",
    "venv",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
)


def _finding(check_id: str, ok: bool, message: str, subject: str) -> Finding:
    """Build a PASS or FAIL Finding."""
    status = ValidationStatus.PASS if ok else ValidationStatus.FAIL
    return Finding(check_id=check_id, status=status, message=message, subject=subject)


def _is_within(path: str, root: str) -> bool:
    """Return True when path equals root or lies below it. Both must be real paths."""
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        # Different drives on Windows, or mixed absolute and relative input.
        return False


def check_write_paths(paths: Sequence[str], allowed_root: str) -> List[Finding]:
    """Check that every write path resolves inside allowed_root.

    Relative paths are taken relative to allowed_root. Absolute paths are used
    as given. Symlinks are followed before the check, so a link that points
    outside the root is a FAIL. Each path gets one Finding.
    """
    findings: List[Finding] = []
    if not isinstance(allowed_root, str) or not allowed_root:
        # An empty root would otherwise resolve to the working directory.
        return [
            _finding(CHECK_WRITE_PATH, False, "allowed root must be a non-empty str", repr(raw))
            for raw in paths
        ]
    root = os.path.realpath(os.path.abspath(allowed_root))
    for raw in paths:
        if not isinstance(raw, str) or not raw:
            findings.append(
                _finding(CHECK_WRITE_PATH, False, "write path must be a non-empty str", repr(raw))
            )
            continue
        if "\x00" in raw:
            # No OS can open such a path, so it is a FAIL rather than a silent PASS.
            findings.append(
                _finding(CHECK_WRITE_PATH, False, "write path contains a NUL byte", repr(raw))
            )
            continue
        candidate = raw if os.path.isabs(raw) else os.path.join(root, raw)
        resolved = os.path.realpath(os.path.abspath(candidate))
        if _is_within(resolved, root):
            findings.append(
                _finding(CHECK_WRITE_PATH, True, "write path stays inside allowed root", raw)
            )
        else:
            findings.append(
                _finding(
                    CHECK_WRITE_PATH,
                    False,
                    "write path resolves to %s, outside allowed root %s" % (resolved, root),
                    raw,
                )
            )
    return findings


@functools.lru_cache(maxsize=None)
def _stdlib_dirs() -> Tuple[str, ...]:
    """Real paths of the interpreter's standard library directories."""
    paths = sysconfig.get_paths()
    dirs = set()
    for key in ("stdlib", "platstdlib"):
        if key in paths:
            dirs.add(os.path.realpath(paths[key]))
    return tuple(sorted(dirs))


@functools.lru_cache(maxsize=None)
def _is_stdlib(top_name: str) -> bool:
    """Return True when a top-level module name is part of the standard library.

    Python 3.9 has no sys.stdlib_module_names, so this looks the module up
    with importlib.util.find_spec, which does not execute it. Built-in and
    frozen modules count as stdlib. Anything installed under site-packages or
    dist-packages does not. A name that cannot be found counts as not stdlib,
    so the caller reports it.
    """
    try:
        spec = importlib.util.find_spec(top_name)
    except (ImportError, ValueError):
        return False
    if spec is None:
        return False
    if spec.origin in ("built-in", "frozen"):
        return True
    if not spec.origin or not os.path.isabs(spec.origin):
        return False
    real = os.path.realpath(spec.origin)
    parts = real.split(os.sep)
    if "site-packages" in parts or "dist-packages" in parts:
        return False
    return any(_is_within(real, d) for d in _stdlib_dirs())


def _collect_imports(tree: ast.AST) -> List[Tuple[str, int]]:
    """Return (dotted_name, lineno) for each absolute import in the tree.

    `from as_of import a, b` is expanded to 'as_of.a' and 'as_of.b' so each
    static as_of target is counted. Relative imports are returned as 'as_of.'
    names, because a relative import inside the package reaches a sibling
    as_of module. Relative imports that climb above the package are returned
    with a leading '..' marker so the caller can flag them.
    """
    names: List[Tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level >= 2:
                names.append(("..escape", node.lineno))
                continue
            if node.level == 1:
                base = PACKAGE_NAME
                if node.module:
                    names.append((base + "." + node.module, node.lineno))
                else:
                    for alias in node.names:
                        names.append((base + "." + alias.name, node.lineno))
                continue
            module = node.module or ""
            if module == PACKAGE_NAME:
                for alias in node.names:
                    names.append((PACKAGE_NAME + "." + alias.name, node.lineno))
            elif module:
                names.append((module, node.lineno))
    return names


def check_imports(source_text: str, module_name: str) -> List[Finding]:
    """Check one module's source against the import rules.

    Returns FAIL findings for syntax errors, forbidden roots, third-party
    imports other than numpy and pandas, and more than one static as_of
    import besides as_of.core. When every rule holds, returns one PASS
    finding for the module.
    """
    subject = module_name
    try:
        tree = ast.parse(source_text, filename=module_name)
    except SyntaxError as exc:
        return [
            _finding(
                CHECK_SYNTAX,
                False,
                "syntax error at line %s: %s" % (exc.lineno, exc.msg),
                subject,
            )
        ]
    except (ValueError, TypeError) as exc:
        return [_finding(CHECK_SYNTAX, False, "source cannot be parsed: %s" % exc, subject)]

    findings: List[Finding] = []
    as_of_targets: Set[str] = set()

    for dotted, lineno in _collect_imports(tree):
        if dotted == "..escape":
            findings.append(
                _finding(
                    CHECK_FORBIDDEN_ROOT,
                    False,
                    "line %d: relative import climbs above the as_of package" % lineno,
                    subject,
                )
            )
            continue
        root = dotted.split(".")[0]
        if root in FORBIDDEN_IMPORT_ROOTS:
            findings.append(
                _finding(
                    CHECK_FORBIDDEN_ROOT,
                    False,
                    "line %d: imports forbidden root '%s'" % (lineno, root),
                    subject,
                )
            )
        elif root == PACKAGE_NAME:
            parts = dotted.split(".")
            as_of_targets.add(".".join(parts[:2]) if len(parts) > 1 else PACKAGE_NAME)
        elif root in ALLOWED_THIRD_PARTY:
            continue
        elif _is_stdlib(root):
            continue
        else:
            findings.append(
                _finding(
                    CHECK_THIRD_PARTY,
                    False,
                    "line %d: third-party import '%s' is not allowed (only %s)"
                    % (lineno, root, ", ".join(ALLOWED_THIRD_PARTY)),
                    subject,
                )
            )

    others = sorted(t for t in as_of_targets if t != CORE_MODULE)
    if len(others) > 1:
        findings.append(
            _finding(
                CHECK_AS_OF_IMPORTS,
                False,
                "statically imports %d as_of modules besides core (max 1): %s"
                % (len(others), ", ".join(others)),
                subject,
            )
        )

    if not findings:
        findings.append(
            _finding(CHECK_FORBIDDEN_ROOT, True, "imports follow the design rules", subject)
        )
    return findings


def check_tree(root: str) -> List[Finding]:
    """Apply both checks to every Python file under root.

    Skips the package's top-level tests/ folder and tooling folders (_TOOL_DIRS)
    at any depth. Other hidden folders are checked. A symlinked folder that
    points outside root is a FAIL, because os.walk does not follow it.
    Write-path checks run on each file so a symlinked file that escapes root is
    reported. Import checks run on each file's source. Only FAIL findings and
    one summary are returned, so the output stays short on a clean tree.
    """
    findings: List[Finding] = []
    if not isinstance(root, str) or not root:
        return [_finding(CHECK_TREE, False, "root must be a non-empty str", repr(root))]
    base = os.path.realpath(os.path.abspath(root))
    if not os.path.isdir(base):
        return [_finding(CHECK_TREE, False, "root is not a directory", root)]

    py_files: List[str] = []
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        # Only the package's own tests/ folder is excluded. A nested folder with
        # the same name must still be checked, or it would hide forbidden imports.
        skip = _SKIP_DIRS if dirpath == base else _TOOL_DIRS
        kept: List[str] = []
        for d in sorted(dirnames):
            full = os.path.join(dirpath, d)
            if os.path.islink(full):
                # os.walk does not descend into symlinked folders, so anything
                # behind one would go unchecked. A link that leaves the root is a FAIL.
                findings.extend(f for f in check_write_paths([full], base) if f.status == ValidationStatus.FAIL)
                continue
            if d not in skip:
                kept.append(d)
        dirnames[:] = kept
        for name in sorted(filenames):
            if name.endswith(".py"):
                py_files.append(os.path.join(dirpath, name))

    findings.extend(
        f for f in check_write_paths(py_files, base) if f.status == ValidationStatus.FAIL
    )

    for path in py_files:
        rel = os.path.relpath(path, base)
        module_name = rel[: -len(".py")].replace(os.sep, ".")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(_finding(CHECK_TREE, False, "cannot read source: %s" % exc, rel))
            continue
        findings.extend(f for f in check_imports(text, module_name) if f.status == ValidationStatus.FAIL)

    failed = [f for f in findings if f.status == ValidationStatus.FAIL]
    summary_ok = not failed
    findings.append(
        _finding(
            CHECK_TREE,
            summary_ok,
            "%d python files checked, %d failing findings" % (len(py_files), len(failed)),
            base,
        )
    )
    return findings
