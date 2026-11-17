# CLAUDE.md: working rules for research-ledger

This repo is a standalone Python project. Its main package, `as_of/`, is an independent implementation of point-in-time research-state tooling.

## Scope and safety

- **Synthetic data only.** Use `SYN_` identifiers and fixtures. Never add real holdings, real prices from a live source, real client data, or real personal data.
- **Never trade.** Do not write order, execution, broker, or position-sizing code. Outputs are research records and checks for a person to review.
- **No network calls.** Do not add code that fetches URLs, calls APIs, or opens sockets. Do not add packages that do so.
- **No secrets.** Do not write keys, tokens, or passwords into code, docs, or fixtures. If a fixture must look like a credential for testing, keep it obviously fake and say so in the test.
- **Standalone.** Do not import from, read from, or depend on any other repo, including quant-lab. Only the standard library and the packages allowed by `as_of/folder_policy.py` (numpy and pandas) may be imported.
- **Python 3.9 only.** No `X | Y` type unions, no `match` statements, and no other syntax newer than 3.9.
- **Human decides.** Tools here produce evidence, sampling logs, exception queues, readiness records, and review packets. A person makes the call. Do not write code that approves, releases, or acts on a result automatically.

## As-of discipline

- Every record carries its clocks. Keep the five clocks in `core.ClockName` (event, knowledge, report, release, ingest) separate. Do not collapse them into one timestamp.
- Visibility is decided by the as-of date. When rebuilding a past state, use only records that were known on or before that date. A later revision must not change an earlier answer.
- Timestamps are timezone-aware UTC. Reject naive datetimes rather than guessing a zone.
- When a value is revised, store the new value as a new row. Do not overwrite the old one.

## Ledgers and records

- Ledgers, logs, and histories are append-only. Add rows; never edit or delete an existing row to change history. A revision is a new row with its own knowledge time, and the earlier row stays (see `as_of/docs/estimate_ledger.md`).
- Use `as_of/jsonl_store.py` for JSON Lines files. It rejects malformed and duplicate-key input.
- Hash inputs and outputs (see `as_of/content_hash.py`) so a reviewer can confirm which version was used.
- Keep exception kinds to the fixed vocabulary in `as_of/exception_vocabulary.py`. Add a kind only with a test and a doc.

## Code conventions

- Put new modules in `as_of/` with a one-line module docstring. Add a matching test file in `as_of/tests/` and a doc in `as_of/docs/` when the module is part of the public workflow.
- Public names are exported from `as_of/__init__.py` through the lazy `_EXPORTS` table. Add a name there only after the module exists and its test passes.
- Prefer explicit errors (`AsOfError` or a clear `ValueError`) over silent fixes.
- Do not mutate records passed in by a caller.

## Running tests and checks

Run everything from the repo root with the project venv:

```bash
# from the repo root
.venv/bin/python -m pytest -q as_of/tests
.venv/bin/python -m as_of.cli proofs --all
.venv/bin/python -m as_of.cli folder-check --root as_of
```

Known failures as of 2026-10-27 are listed in `as_of/README.md` under "Known issues". Do not hide them. If you change code, say which failures are new and which were already there.

## Git and deployment

- Do not run git commands unless the user asks for them in this session.
- Do not push anywhere.
- Do not change Claude or IDE settings files from inside this repo.
- Write only inside `as_of/`, plus the `CLAUDE.md` and `as_of/README.md` files.

## live/ (real public data, separate from as_of/)
`live/` holds tools that pull real public data (SEC filings, FRED, yfinance). `as_of/` itself stays synthetic-only with no network calls. Rules for `live/`: public sources only, keys only in the git-ignored `.env`, no trading or order code, extracted numbers stay UNCONFIRMED until a person checks them, and every report ends REVIEW_REQUIRED. The earnings-night prior is frozen and hashed in `live/earnings_night/FROZEN.json`; do not edit `expectations.json` after freezing, create a new dated state instead.
