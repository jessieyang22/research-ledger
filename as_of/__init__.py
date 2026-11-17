"""Public entry points for the as_of research-state package.

Every name listed in ``_EXPORTS`` is loaded on first access through a
module-level ``__getattr__`` (PEP 562). Importing ``as_of`` therefore never
imports the submodules, so a missing or broken submodule cannot break the
package import. It only raises when that specific name is used.

All data handled by this package is synthetic. Nothing here touches the
network, places orders or reads credentials.
"""

import importlib

_PACKAGE = __name__

# public name -> (submodule name inside this package, attribute in that module)
_EXPORTS = {
    # shared vocabulary and hashing
    "AsOfError": ("core", "AsOfError"),
    "ClockName": ("core", "ClockName"),
    "parse_ts": ("core", "parse_ts"),
    "fmt_ts": ("core", "fmt_ts"),
    "canonical_json": ("core", "canonical_json"),
    "stable_hash": ("core", "stable_hash"),
    "sha256_file": ("content_hash", "sha256_file"),
    "hash_manifest": ("content_hash", "hash_manifest"),
    # point-in-time visibility
    "known_as_of": ("clock_as_of", "known_as_of"),
    "visible_at": ("clock_as_of", "visible_at"),
    "latest_known": ("clock_as_of", "latest_known"),
    # append-only stores and registers
    "append_record": ("jsonl_store", "append_record"),
    "read_records": ("jsonl_store", "read_records"),
    "count_records": ("jsonl_store", "count_records"),
    "EstimateLedger": ("estimate_ledger", "EstimateLedger"),
    "SourceRegister": ("source_register", "SourceRegister"),
    "ExceptionQueue": ("exception_queue", "ExceptionQueue"),
    "StateManifest": ("state_manifest", "StateManifest"),
    # resumable runs
    "write_checkpoint": ("checkpoints", "write_checkpoint"),
    "read_checkpoint": ("checkpoints", "read_checkpoint"),
    "should_skip": ("checkpoints", "should_skip"),
    "latest_step": ("checkpoints", "latest_step"),
    # calendar
    "is_business_day": ("synthetic_calendar", "is_business_day"),
    "next_business_day": ("synthetic_calendar", "next_business_day"),
    # portfolio and factor checks
    "tie_out": ("portfolio_tieout", "tie_out"),
    "reproduce_exposures": ("factor_exposure", "reproduce_exposures"),
    # review packet, handoff and go/no-go
    "assemble_packet": ("pm_packet_assembly", "assemble_packet"),
    "build_handoff": ("handoff", "build_handoff"),
    "render_handoff": ("handoff", "render_handoff"),
    "validate_handoff": ("handoff", "validate_handoff"),
    "build_readiness": ("readiness_record", "build_readiness"),
    "render_readiness": ("readiness_record", "render_readiness"),
    "sample_claims": ("claim_sampling", "sample_claims"),
    "checklist_markdown": ("controls_checklist", "checklist_markdown"),
    # gates and scanners
    "check_tree": ("folder_policy", "check_tree"),
    "scan_text": ("secrets_scanner", "scan_text"),
    "scan_paths": ("secrets_scanner", "scan_paths"),
    "overall_status": ("validators", "overall_status"),
    # registered proofs (synthetic data)
    "run_macro_proof": ("wf_macro_vintage", "run_macro_proof"),
    "run_earnings_proof": ("wf_earnings_reconciliation", "run_earnings_proof"),
    "run_catalyst_proof": ("wf_catalyst_exception_queue", "run_catalyst_proof"),
    "run_tieout_factor_proof": ("wf_portfolio_tieout_factor", "run_tieout_factor_proof"),
    "run_pm_packet_proof": ("wf_pm_packet", "run_pm_packet_proof"),
    "build_pm_packet": ("wf_pm_packet", "build_pm_packet"),
    "render_pm_packet_markdown": ("wf_pm_packet", "render_pm_packet_markdown"),
    # command line
    "main": ("cli", "main"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name):
    """Load a public name on first use; unknown names raise AttributeError."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError("module %r has no attribute %r" % (_PACKAGE, name))
    submodule, attr = target
    module = importlib.import_module(_PACKAGE + "." + submodule)
    value = getattr(module, attr)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))
