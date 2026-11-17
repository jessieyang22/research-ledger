# as_of: point-in-time research-state package

`as_of` is a small Python package for keeping research state honest about time. Each record carries five clocks (`event`, `knowledge`, `report`, `release` and `ingest`, defined in `core.ClockName`), so a past research run can be replayed using only what was visible then. It also holds the controls around that state: append-only ledgers, hashes for inputs and outputs, an exception queue, a portfolio tie-out, a PM review packet, a handoff record and a go or no-go readiness record.

Everything here runs on **synthetic data** (`SYN_` prefix). The package has no network calls, no broker or order code, no secrets, and it never places or recommends a trade.

## Quick start

Run everything from the repo root with the project venv (Python 3.9):

```bash
# from the repo root

# run the test suite
.venv/bin/python -m pytest -q as_of/tests

# run the registered proof(s) on synthetic data
.venv/bin/python -m as_of.cli proofs --all

# folder and import policy check over the package
.venv/bin/python -m as_of.cli folder-check --root as_of

# scan named files for credential-shaped text
.venv/bin/python -m as_of.cli secrets-scan as_of/docs/core.md
```

Python use:

```python
from as_of import parse_ts, fmt_ts, stable_hash

print(fmt_ts(parse_ts("2026-10-27")))   # 2026-10-27T00:00:00Z
print(stable_hash({"b": 1, "a": [1, 2]}))
```

Public names are listed in `as_of.__all__`. They load on first use, so importing `as_of` never fails because one submodule is missing.

Other subcommands: `validate --root PATH` (folder check plus secrets scan with a report) and `readiness --out PATH` (runs the proofs and checks, then writes a go or no-go record to PATH). Exit codes: 0 pass, 1 fail, 2 usage error.

## Known issues (as of 2026-10-27)

These were observed when this README was written. They are not fixed here.

- Tests: `python -m pytest -q as_of/tests` is green as of 2026-10-27 (2365 passed, 78 xfailed). The 78 xfails are pre-existing, documented gaps. Two earnings attack tests were fixed by making the proof treat a row known exactly at the report time as known. A stale strict xfail in `test_wf_portfolio_tieout_factor_attack.py` was removed because `market_value` now rejects a datetime `as_of`.
- `folder-check` and `validate` FAIL on two files under `labs/`:
  - `labs/lab05.py` statically imports three `as_of` modules besides core (the limit is one).
  - `labs/lab09.py` imports `subprocess`, which the folder policy forbids.
- `validate` also FAILs the secrets scan on fake credential-shaped fixtures in `tests/` and one docs file. These are test strings, not real secrets, but they still trip the scanner.

## Module map

Generated from the first docstring line of each module in this folder. "Notes" links to `docs/<module>.md` where that file exists. The `labs/` folder holds numbered lab scripts, their data and their results. It is not part of the public API.

| Module | What it does (first docstring line) | Notes | Tests |
| --- | --- | --- | --- |
| `availability_cutoff.py` | Availability cutoff for as-of research records | [doc](docs/availability_cutoff.md) | `tests/test_availability_cutoff.py` |
| `canary_tests.py` | Instruction-shaped canary tests for the as_of pipeline | [doc](docs/canary_tests.md) | `tests/test_canary_tests.py` |
| `catalyst_claim_links.py` | Catalyst-to-claim link checks for the as_of package | [doc](docs/catalyst_claim_links.md) | `tests/test_catalyst_claim_links.py` |
| `catalyst_fixture.py` | Synthetic catalyst fixture for the as_of catalyst exception queue | [doc](docs/catalyst_fixture.md) | `tests/test_catalyst_fixture.py` |
| `change_records.py` | Change-management records with a fixed status flow | [doc](docs/change_records.md) | `tests/test_change_records.py` |
| `checkpoints.py` | Checkpoints for resumable runs in the as_of package | [doc](docs/checkpoints.md) | `tests/test_checkpoints.py` |
| `claim_records.py` | Claim records for the as_of package | [doc](docs/claim_records.md) | `tests/test_claim_records.py` |
| `claim_sampling.py` | Deterministic stratified sampling of claims for human review | [doc](docs/claim_sampling.md) | `tests/test_claim_sampling.py` |
| `cli.py` | Command-line entry point for the as_of research-state package | [doc](docs/cli.md) | `tests/test_cli.py` |
| `clock_as_of.py` | Point-in-time visibility filters for clock-stamped records | [doc](docs/clock_as_of.md) | `tests/test_clock_as_of.py` |
| `clock_ordering.py` | Ordering checks for the five as-of clocks | [doc](docs/clock_ordering.md) | `tests/test_clock_ordering.py` |
| `clocks_record.py` | Immutable clock timestamps for a record | [doc](docs/clocks_record.md) | `tests/test_clocks_record.py` |
| `content_hash.py` | Content hashing for files and record collections | [doc](docs/content_hash.md) | `tests/test_content_hash.py` |
| `controls_checklist.py` | Control catalog for the as_of package | [doc](docs/controls_checklist.md) | `tests/test_controls_checklist.py` |
| `core.py` | Shared constants, enums, record types and helpers for the as_of package | [doc](docs/core.md) | `tests/test_core.py` |
| `earnings_fixture.py` | Synthetic earnings fixture for the as_of earnings proof | [doc](docs/earnings_fixture.md) | `tests/test_earnings_fixture.py` |
| `estimate_ledger.py` | Append-only ledger of analyst estimates with knowledge-time discipline | [doc](docs/estimate_ledger.md) | `tests/test_estimate_ledger.py` |
| `estimate_revisions.py` | Estimate revision history, consensus time series and revision breadth | [doc](docs/estimate_revisions.md) | `tests/test_estimate_revisions.py` |
| `exception_queue.py` | Queue of open exceptions for the as_of research-state workflow | [doc](docs/exception_queue.md) | `tests/test_exception_queue.py` |
| `exception_vocabulary.py` | Fixed vocabulary of exception kinds for the as_of exception queue | [doc](docs/exception_vocabulary.md) | `tests/test_exception_vocabulary.py` |
| `factor_exposure.py` | Factor exposure reproduction by ordinary least squares | [doc](docs/factor_exposure.md) | `tests/test_factor_exposure.py` |
| `field_dictionary.py` | Canonical field dictionary for the as_of package | [doc](docs/field_dictionary.md) | `tests/test_field_dictionary.py` |
| `filing_monitor.py` | Filing occurrence monitor for the as_of package | [doc](docs/filing_monitor.md) | `tests/test_filing_monitor.py` |
| `folder_policy.py` | Folder and import policy checks for the as_of package | [doc](docs/folder_policy.md) | `tests/test_folder_policy.py` |
| `handoff.py` | Handoff records for the as_of package | [doc](docs/handoff.md) | `tests/test_handoff.py` |
| `incident_records.py` | Incident records: timeline, severity and root cause | [doc](docs/incident_records.md) | `tests/test_incident_records.py` |
| `jsonl_store.py` | Append-only JSON Lines store for ledgers and logs | [doc](docs/jsonl_store.md) | `tests/test_jsonl_store.py` |
| `macro_cutoff_rule.py` | No-look-ahead cutoff rule for macro values | [doc](docs/macro_cutoff_rule.md) | `tests/test_macro_cutoff_rule.py` |
| `macro_fixture.py` | Synthetic macro series with revisions, for exercising vintage and cutoff logic | [doc](docs/macro_fixture.md) | `tests/test_macro_fixture.py` |
| `macro_vintage_manifest.py` | Vintage manifest for macro series | [doc](docs/macro_vintage_manifest.md) | `tests/test_macro_vintage_manifest.py` |
| `pm_packet_assembly.py` | Assemble a PM review packet from named sections, open findings and a hash | [doc](docs/pm_packet_assembly.md) | `tests/test_pm_packet_assembly.py` |
| `pm_packet_deltas.py` | PM packet deltas: compare the current PM review packet with the prior one | [doc](docs/pm_packet_deltas.md) | `tests/test_pm_packet_deltas.py` |
| `pm_packet_render.py` | Render a PM review packet and its delta as Markdown text | [doc](docs/pm_packet_render.md) | `tests/test_pm_packet_render.py` |
| `portfolio_fixture.py` | Synthetic portfolio fixture for the as_of portfolio tie-out checks | [doc](docs/portfolio_fixture.md) | `tests/test_portfolio_fixture.py` |
| `portfolio_tieout.py` | Portfolio tie-out between the internal book and the custodian book | [doc](docs/portfolio_tieout.md) | `tests/test_portfolio_tieout.py` |
| `price_hard_fail.py` | Hard-fail price lookup for the as_of package | [doc](docs/price_hard_fail.md) | `tests/test_price_hard_fail.py` |
| `readiness_record.py` | Go or no-go readiness record for an as-of research run | [doc](docs/readiness_record.md) | `tests/test_readiness_record.py` |
| `reported_vs_expected_bridge.py` | Reported-vs-expected bridge for as-of research state | - | `tests/test_reported_vs_expected_bridge.py` |
| `run_timeliness.py` | Classify scheduled runs as on time, late or missed, and map each status to a handling action | [doc](docs/run_timeliness.md) | `tests/test_run_timeliness.py` |
| `schedule_contract.py` | Scheduling contract: a named cadence, due time, grace window and business-day rule | [doc](docs/schedule_contract.md) | `tests/test_schedule_contract.py` |
| `secrets_scanner.py` | Scan text and files for credential-shaped strings | [doc](docs/secrets_scanner.md) | `tests/test_secrets_scanner.py` |
| `source_register.py` | Source register for the as_of package | [doc](docs/source_register.md) | `tests/test_source_register.py` |
| `state_manifest.py` | Run-level state manifest for the as_of package | [doc](docs/state_manifest.md) | `tests/test_state_manifest.py` |
| `synthetic_calendar.py` | Business-day and schedule-date arithmetic with a fixed 2026 holiday set | [doc](docs/synthetic_calendar.md) | `tests/test_synthetic_calendar.py` |
| `validation_report.py` | Build and render a validation report from named check results | [doc](docs/validation_report.md) | `tests/test_validation_report.py` |
| `validators.py` | Validator registry for the as_of package | [doc](docs/validators.md) | `tests/test_validators.py` |
| `wf_catalyst_exception_queue.py` | Proof 3: catalyst exception queue | [doc](docs/wf_catalyst_exception_queue.md) | `tests/test_wf_catalyst_exception_queue.py` |
| `wf_earnings_reconciliation.py` | Proof 1: earnings reconciliation for the as_of research state | [doc](docs/wf_earnings_reconciliation.md) | `tests/test_wf_earnings_reconciliation.py` |
| `wf_macro_vintage.py` | Proof 2: macro vintage, as-of value selection and cutoff check | [doc](docs/wf_macro_vintage.md) | `tests/test_wf_macro_vintage.py` |
| `wf_pm_packet.py` | Proof 5: PM review packet, end to end on synthetic data | [doc](docs/wf_pm_packet.md) | `tests/test_wf_pm_packet.py` |
| `wf_portfolio_tieout_factor.py` | Proof 4: portfolio tie-out and factor exposure reproduction | [doc](docs/wf_portfolio_tieout_factor.md) | `tests/test_wf_portfolio_tieout_factor.py` |

## Limits

- **Synthetic data only.** Inputs are fixtures with `SYN_` identifiers. Nothing reads live market, filing or broker data.
- **Not a trading system.** There is no order, execution, broker or position-sizing code. Outputs are research records and checks for a person to review.
- **Human decides.** Readiness records, sampling logs and exception queues inform a reviewer. They do not approve or act on anything by themselves.
- **Static checks are partial.** The folder and import checks read source text. They miss dynamic imports and runtime behavior, as the folder_policy docs describe.
- **Python 3.9 and two third-party packages.** The code avoids newer syntax. The folder policy allows only numpy and pandas as third-party imports.
