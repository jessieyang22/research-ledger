# jsonl_store

## What it does
`as_of/jsonl_store.py` is an append-only JSON Lines store for ledgers and logs. Each record is one line of canonical JSON (sorted keys, compact separators, no NaN). The module offers three operations: append a record, read all records in insertion order, and count them. There is no overwrite, truncate or delete path. A correction is a new line that supersedes an earlier one, and the earlier line stays on disk.

## Design idea
The module follows the idea of keeping the estimate ledger as append-only history, so past states of the ledger can be reconstructed.

## API
- `append_record(path, record)`: appends one dict as one line. Refuses non-dict records, NaN, sub-second datetimes, and files that do not end in a newline. Nothing is written when a check fails.
- `read_records(path)`: returns a list of dicts in file order. A missing file returns `[]`.
- `count_records(path)`: returns the record count, validating the file the same way.
- Errors are `as_of.core.AsOfError`, and bad lines are reported by 1-based line number.

Example (verified by running it):

```python
import os, tempfile
from as_of import jsonl_store

d = tempfile.mkdtemp()
p = os.path.join(d, "SYN_ledger.jsonl")
jsonl_store.append_record(p, {"SYN_id": 1, "SYN_eps": 10.0})
jsonl_store.append_record(p, {"SYN_id": 2, "SYN_eps": 12.0, "SYN_supersedes": 1})
print(jsonl_store.read_records(p))  # two records, in insertion order
print(jsonl_store.count_records(p))  # 2
```

Run from the repo root so `as_of` is importable.

## Known limits
- Append-only by design. Deleting or fixing a bad line requires editing the file by hand, which the module does not support.
- The file is read in full on every read or count. No indexing or streaming.
- Only the standard library and `as_of.core` are used. No locking, so concurrent writers from several processes are not coordinated.
- Supersession is a convention in the data (for example a `SYN_supersedes` field). The module does not enforce or interpret it.
- Each append is fsynced, which is safe but slow for large batches.
- Synthetic data only. Values are not checked for meaning or units.
