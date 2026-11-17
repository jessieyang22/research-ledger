# content_hash

Module: `as_of/content_hash.py`. Synthetic data only. Standard library plus `as_of.core`.

## What it does

Detects any change in file bytes, record content, or record order, so a vintage or state manifest can prove that the inputs a run used are the inputs on record. Three helpers:

- `sha256_file(path)`: streaming SHA-256 of one file.
- `hash_records(records)`: order-sensitive digest of a list or tuple of records. Each record is canonicalised first, so a date and its ISO string never collide, and microsecond differences count.
- `hash_manifest(root, rel_paths)`: `ManifestEntry` rows (path, sha256, size), sorted by path. Missing files, absolute paths, `..`, duplicates, and symlinks that leave `root` are rejected.

## Design idea

The module implements the manifest idea from the vintage manifests and state manifests topic: pin each input to a content hash so later changes are visible.

## API example

```python
from dataclasses import dataclass
from datetime import date
from as_of.content_hash import hash_records

@dataclass(frozen=True)
class Row:
    name: str
    as_of: date
    value: float

rows = [Row("SYN_A", date(2026, 1, 2), 1.5), Row("SYN_B", date(2026, 1, 3), -2.0)]
print(hash_records(rows) == hash_records(list(rows)))   # True: same content, same digest
print(hash_records(rows) == hash_records(rows[::-1]))   # False: order matters
```

Verified by running it with the repo venv.

## Known limits

- Not an as-of gate. A future-dated row still changes the digest; filtering by time happens elsewhere.
- Records must be lists or tuples. Strings, bytes, and dicts are refused as containers.
- Dict keys must be `str`; the key `__asof_type__` is reserved.
- NaN and infinity raise `AsOfError`. Numpy arrays and `datetime64`/`timedelta64` are refused.
- Nesting deeper than 64 levels, or cyclic content, is refused.
- `hash_manifest` checks containment with `realpath` prefixes. It does not guard against races after the check.
- Digests are only comparable within this module's canonical form.
