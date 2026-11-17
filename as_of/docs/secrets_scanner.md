# secrets_scanner

## What it does

`as_of/secrets_scanner.py` is a control check. It looks for text shaped like credentials (cloud access key IDs, private key headers, GitHub and Slack tokens, and generic `secret = "..."` assignments) before the text reaches a repo, report or handoff packet. It is standard library only, makes no network calls, and executes nothing it reads. All fixtures are synthetic.

## Design idea

The design treats secrets as a control: credentials should be caught at the point where work is handed off, not after they are shared, and a finding should not repeat the secret. The module applies that idea with named regex patterns, line numbers, and redacted output.

## API

- `PATTERNS`: dict of pattern name to compiled regex.
- `redact(s)`: keeps 4 characters plus a mask for values of 16+ characters; fully masks shorter values.
- `scan_text(text, name="<text>")`: returns a list of `Finding` (check id `secret.<pattern>`, status FAIL).
- `scan_paths(paths)`: scans files; flags any file named `.env` (case-insensitive) even if empty; unreadable paths give WARN.

Runnable example (run from the repo root; output checked):

```python
from as_of.secrets_scanner import scan_text

text = 'line one\naws_key = AKIASYN7THET1C000000\n'
for f in scan_text(text, name="SYN_config"):
    print(f.check_id, f.status.value, f.message)
# secret.aws_access_key_id fail SYN_config line 2: possible aws_access_key_id (value redacted: AKIA********)
```

## Known limits

- Line by line only: a secret split across lines is missed.
- Pattern-based, with no entropy check: unusual token formats are missed, and only the listed providers are covered.
- The generic rule needs a quoted value of 12+ characters after a keyword such as `password`.
- The AWS secret rule needs exactly 40 characters.
- Files containing NUL bytes are skipped with no finding.
- Git history and archives are not scanned.
- Findings are a prompt for review, not proof that a value is live.
