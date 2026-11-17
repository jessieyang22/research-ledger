"""Command-line entry point for the as_of research-state package.

Subcommands:

* ``proofs --all`` or ``proofs --name NAME``: run registered proofs.
* ``validate --root PATH``: run the folder policy check and the secrets scan
  over the text files under PATH and print a validation report.
* ``folder-check --root PATH``: run the folder policy check only.
* ``secrets-scan PATHS...``: scan the given files for credential-shaped text.
* ``readiness --out PATH``: run every proof, the folder policy check and the
  secrets scan over this package, then write a go or no-go readiness record.

Exit codes: 0 when everything passes, 1 when any check reports FAIL (or a
readiness record is NO-GO), 2 for a usage error (bad arguments or an unknown
proof name). ``--help`` exits through argparse with code 0.

Only ``as_of.core`` is imported statically. Every other piece is loaded with
``core.component`` inside a function body, so this module stays importable
even when a component is missing; the missing piece then shows up as a FAIL.

The proof registry holds one proof today (proof 2, macro vintage, from
``as_of.wf_macro_vintage``).

All data used here is synthetic. This module makes no network calls, starts
no subprocesses and never places orders.
"""

import argparse
import os
import sys
from typing import Dict, List, Optional, Sequence, Tuple

from as_of.core import AsOfError, Finding, ProofResult, ReadinessItem, ValidationStatus, component


PROG_NAME: str = "as_of"
PACKAGE_DIR: str = os.path.dirname(os.path.abspath(__file__))
TEXT_SUFFIXES: Tuple[str, ...] = (".py", ".md", ".json", ".txt", ".csv", ".tsv", ".yaml", ".yml", ".toml", ".cfg", ".ini")
SKIP_DIRS: Tuple[str, ...] = ("__pycache__", ".venv", "venv", "node_modules")

# Short proof name -> (component module, runner function name).
PROOF_REGISTRY: Dict[str, Tuple[str, str]] = {
    "macro_vintage": ("wf_macro_vintage", "run_macro_proof"),
}
# Long proof names that also resolve to a short name.
PROOF_ALIASES: Dict[str, str] = {
    "proof_2_macro_vintage": "macro_vintage",
}

EXIT_OK: int = 0
EXIT_FAIL: int = 1
EXIT_USAGE: int = 2


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _fail_findings(findings: Sequence[Finding]) -> List[Finding]:
    return [f for f in findings if f.status is ValidationStatus.FAIL]


def _print_findings(findings: Sequence[Finding], stream=None) -> None:
    out = stream if stream is not None else sys.stdout
    for finding in findings:
        out.write("[%s] %s: %s\n" % (finding.status.value.upper(), finding.check_id, finding.message))


def _resolve_proof(name: str) -> Optional[str]:
    """Return the short registry key for name, or None when unknown."""
    if name in PROOF_REGISTRY:
        return name
    return PROOF_ALIASES.get(name)


def _proof_passed(result: ProofResult) -> bool:
    """A proof passes only when its flag is exactly True and no finding is FAIL."""
    return result.passed is True and not _fail_findings(result.findings)


def _run_one_proof(short_name: str) -> ProofResult:
    """Run one registered proof. Errors become a failing ProofResult."""
    module_name, func_name = PROOF_REGISTRY[short_name]
    try:
        module = component(module_name)
        runner = getattr(module, func_name)
        result = runner()
    except Exception as exc:  # any failure inside a proof is a FAIL, never a traceback
        finding = Finding(
            check_id="proof.error",
            status=ValidationStatus.FAIL,
            message="proof %s could not run: %s" % (short_name, exc),
            subject=short_name,
        )
        return ProofResult(proof_name=short_name, passed=False, findings=(finding,), metrics={})
    if not isinstance(result, ProofResult):
        finding = Finding(
            check_id="proof.error",
            status=ValidationStatus.FAIL,
            message="proof %s returned %s, not ProofResult" % (short_name, type(result).__name__),
            subject=short_name,
        )
        return ProofResult(proof_name=short_name, passed=False, findings=(finding,), metrics={})
    # Malformed findings must not reach the rest of the CLI, where they would
    # raise instead of reporting a FAIL.
    if not isinstance(result.findings, (list, tuple)) or not all(
        isinstance(f, Finding) for f in result.findings
    ):
        finding = Finding(
            check_id="proof.error",
            status=ValidationStatus.FAIL,
            message="proof %s returned findings that are not a list of Finding" % short_name,
            subject=short_name,
        )
        return ProofResult(proof_name=short_name, passed=False, findings=(finding,), metrics={})
    return result


def _run_proofs(short_names: Sequence[str]) -> List[ProofResult]:
    return [_run_one_proof(name) for name in short_names]


def _folder_findings(root: str) -> List[Finding]:
    """Folder policy findings for root. A missing component is a FAIL."""
    try:
        policy = component("folder_policy")
        return list(policy.check_tree(root))
    except Exception as exc:
        return [Finding("folder.error", ValidationStatus.FAIL, str(exc), root)]


def _is_text_name(name: str) -> bool:
    """True for .env and .env.* names, and for text suffixes in any letter case."""
    lowered = name.lower()
    return lowered == ".env" or lowered.startswith(".env.") or lowered.endswith(TEXT_SUFFIXES)


def _collect_text_files(root: str) -> List[str]:
    """Text-like files under root, skipping hidden folders and SKIP_DIRS."""
    files: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if _is_text_name(name):
                files.append(os.path.join(dirpath, name))
    return files


def _secret_findings(paths: Sequence[str]) -> List[Finding]:
    try:
        scanner = component("secrets_scanner")
        return list(scanner.scan_paths(list(paths)))
    except Exception as exc:
        return [Finding("secret.error", ValidationStatus.FAIL, str(exc), "secrets")]


def _root_or_usage_error(root: str) -> Optional[str]:
    if not os.path.isdir(root):
        sys.stderr.write("error: --root is not a directory: %s\n" % root)
        return None
    return root


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_proofs(args: argparse.Namespace) -> int:
    known = sorted(PROOF_REGISTRY.keys())
    if args.all and args.name:
        sys.stderr.write("error: use either --all or --name, not both\n")
        return EXIT_USAGE
    if args.all:
        selected = known
    elif args.name:
        short = _resolve_proof(args.name)
        if short is None:
            sys.stderr.write(
                "error: unknown proof %r; known proofs: %s\n" % (args.name, ", ".join(known))
            )
            return EXIT_USAGE
        selected = [short]
    else:
        sys.stderr.write("error: proofs needs --all or --name NAME\n")
        return EXIT_USAGE

    results = _run_proofs(selected)
    failed = 0
    for result in results:
        passed = _proof_passed(result)
        status = "PASS" if passed else "FAIL"
        print("%s %s" % (status, result.proof_name))
        _print_findings(_fail_findings(result.findings))
        if not passed:
            failed += 1
    print("proofs: %d run, %d failed" % (len(results), failed))
    return EXIT_OK if failed == 0 else EXIT_FAIL


def cmd_folder_check(args: argparse.Namespace) -> int:
    root = _root_or_usage_error(args.root)
    if root is None:
        return EXIT_USAGE
    findings = _folder_findings(root)
    failed = _fail_findings(findings)
    _print_findings(failed)
    print("folder-check: %s (%d failing finding(s))" % ("PASS" if not failed else "FAIL", len(failed)))
    return EXIT_OK if not failed else EXIT_FAIL


def cmd_secrets_scan(args: argparse.Namespace) -> int:
    # A missing path or a directory would be skipped as a WARN and could pass
    # silently, so reject it up front as a usage error.
    not_files = [p for p in args.paths if not os.path.isfile(p)]
    if not_files:
        sys.stderr.write("error: not a regular file: %s\n" % ", ".join(not_files))
        return EXIT_USAGE
    findings = _secret_findings(args.paths)
    failed = _fail_findings(findings)
    _print_findings(findings)
    print("secrets-scan: %s (%d file(s) given, %d failing finding(s))" % (
        "PASS" if not failed else "FAIL", len(args.paths), len(failed)))
    return EXIT_OK if not failed else EXIT_FAIL


def cmd_validate(args: argparse.Namespace) -> int:
    root = _root_or_usage_error(args.root)
    if root is None:
        return EXIT_USAGE
    folder = _folder_findings(root)
    secrets = _secret_findings(_collect_text_files(root))
    failed = _fail_findings(folder) + _fail_findings(secrets)
    try:
        report_mod = component("validation_report")
        report = report_mod.build_report(
            "as_of validate", {"folder_policy": folder, "secrets": secrets}, root
        )
        print(report_mod.render_report_text(report))
    except AsOfError as exc:
        sys.stderr.write("warning: report could not be rendered: %s\n" % exc)
        _print_findings(failed)
    overall = "PASS" if not failed else "FAIL"
    print("validate: %s" % overall)
    return EXIT_OK if not failed else EXIT_FAIL


def cmd_readiness(args: argparse.Namespace) -> int:
    proof_results = _run_proofs(sorted(PROOF_REGISTRY.keys()))
    items: List[ReadinessItem] = []
    findings: List[Finding] = []
    for result in proof_results:
        items.append(ReadinessItem(
            item_id="proof.%s" % result.proof_name,
            passed=_proof_passed(result),
            evidence_ref="cli proofs --name %s" % result.proof_name,
        ))
        findings.extend(_fail_findings(result.findings))

    folder = _folder_findings(PACKAGE_DIR)
    secrets = _secret_findings(_collect_text_files(PACKAGE_DIR))
    for label, found in (("folder_policy", folder), ("secrets_scan", secrets)):
        clean = not _fail_findings(found)
        items.append(ReadinessItem(
            item_id="check.%s" % label,
            passed=clean,
            evidence_ref="cli %s" % label,
        ))
        findings.extend(_fail_findings(found))

    try:
        readiness = component("readiness_record")
        # The incident store is not read by this CLI, so the count is 0 here.
        record = readiness.build_readiness(items, findings, 0)
        text = readiness.render_readiness(record)
    except AsOfError as exc:
        sys.stderr.write("error: readiness record could not be built: %s\n" % exc)
        return EXIT_FAIL

    try:
        out_dir = os.path.dirname(os.path.abspath(args.out))
        if not os.path.isdir(out_dir):
            sys.stderr.write("error: output folder does not exist: %s\n" % out_dir)
            return EXIT_USAGE
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text.rstrip("\n") + "\n")
    except OSError as exc:
        sys.stderr.write("error: cannot write readiness record: %s\n" % exc)
        return EXIT_FAIL

    print(text.rstrip("\n"))
    print("readiness: wrote %s" % args.out)
    return EXIT_OK if record.get("go") else EXIT_FAIL


# ---------------------------------------------------------------------------
# Parser and entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG_NAME,
        description="Run proofs, validators, the folder policy check, the secrets scan and the readiness record.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    p_proofs = sub.add_parser("proofs", help="run registered proofs")
    p_proofs.add_argument("--all", action="store_true", help="run every registered proof")
    p_proofs.add_argument("--name", help="run one proof by name")
    p_proofs.set_defaults(func=cmd_proofs)

    p_validate = sub.add_parser("validate", help="folder check and secrets scan with a report")
    p_validate.add_argument("--root", required=True, help="folder to validate")
    p_validate.set_defaults(func=cmd_validate)

    p_folder = sub.add_parser("folder-check", help="folder policy check only")
    p_folder.add_argument("--root", required=True, help="folder to check")
    p_folder.set_defaults(func=cmd_folder_check)

    p_secrets = sub.add_parser("secrets-scan", help="scan files for credential-shaped text")
    p_secrets.add_argument("paths", nargs="+", help="files to scan")
    p_secrets.set_defaults(func=cmd_secrets_scan)

    p_ready = sub.add_parser("readiness", help="write a go or no-go readiness record")
    p_ready.add_argument("--out", required=True, help="path of the readiness record to write")
    p_ready.set_defaults(func=cmd_readiness)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI and return the exit code (0 pass, 1 fail, 2 usage error).

    ``--help`` raises SystemExit(0) through argparse, as argparse does.
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        if exc.code == 0:
            raise
        return EXIT_USAGE
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return int(handler(args))


if __name__ == "__main__":
    sys.exit(main())
