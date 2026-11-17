# cli: command-line entry point for the as_of package

## What the module does
`as_of/cli.py` runs the package's checks from one command. Subcommands: `proofs` (run registered proofs), `validate` (folder policy check plus secrets scan, with a text report), `folder-check` (folder policy only), `secrets-scan` (scan named files for credential-shaped text), and `readiness` (run every proof, the folder check and the secrets scan over the package, then write a go or no-go record). Exit codes: 0 pass, 1 FAIL or NO-GO, 2 usage error. Synthetic data only. No network, no subprocesses, no orders.

## Design idea
The design treats controls and a handoff as the material that closes a research run. This module puts that into one gate: named checks run the same way each time, and the result is a single go or no-go with its evidence.

## API
- `main(argv=None) -> int`: parses argv, runs one subcommand, returns the exit code. `--help` exits 0 through argparse.
- Handlers: `cmd_proofs`, `cmd_validate`, `cmd_folder_check`, `cmd_secrets_scan`, `cmd_readiness`.
- Registry: `PROOF_REGISTRY` (one proof, `macro_vintage`) and `PROOF_ALIASES`.

Example (run from repo root; verified):
```python
from as_of.cli import main

print("folder-check exit:", main(["folder-check", "--root", "as_of/docs"]))
print("proofs exit:", main(["proofs", "--all"]))
```
Output:
```
folder-check: PASS (0 failing finding(s))
folder-check exit: 0
PASS proof_2_macro_vintage
proofs: 1 run, 0 failed
proofs exit: 0
```

## Known limits
- One registered proof, so `proofs --all` covers one check.
- `validate --root as_of/docs` currently returns FAIL. The secrets scanner flags an AWS-style example key in `as_of/docs/secrets_scanner.md` (line 23). The example is text, not a credential. Treat it as a scanner false positive, and fix the doc or the scanner in a later change.
- `readiness` scans the whole package, so it also flags the scanner's own test fixtures (`as_of/tests/test_secrets_scanner_attack.py`). Its go or no-go result depends on those findings.
- Incident count is hard-coded to 0; the CLI does not read the incident store.
- Only FAIL findings change the exit code; WARN does not.
- Tests: `as_of/tests/test_cli_attack.py`.
