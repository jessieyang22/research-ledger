# field_dictionary: field units, dtypes and governing clocks

## What the module does
`as_of/field_dictionary.py` defines one `FieldSpec` per field: unit, dtype, governing clock, and nullability. `validate_fields()` checks a record and returns one `Finding` per check. Data is synthetic (`SYN_` prefix).

## Design idea
The field dictionary topic asks that each field state its meaning and when it became known, so a reviewer can tell whether a value was usable at a past decision time.

## API
- `FIELD_DICTIONARY`: module-level mapping of name to `FieldSpec`.
- `build_field_dictionary()`: returns a fresh copy of that mapping.
- `lookup_field(name)`: returns the spec, or raises `AsOfError` for an unknown name.
- `validate_fields(record, required)`: returns `Finding` objects with check ids `field.present`, `field.null`, `field.dtype` and `field.unknown`.

Example (run from the repo root with the repo on `PYTHONPATH`; output verified):
```python
from datetime import date, datetime, timezone
from as_of.field_dictionary import lookup_field, validate_fields

print(lookup_field("price_close").unit)  # USD per share
record = {"ticker": "SYN_AAA", "price_as_of": date(2026, 10, 27),
          "price_close": 101.5, "ingest_at": datetime(2026, 10, 27, 13, tzinfo=timezone.utc),
          "accepted_at": None}
for f in validate_fields(record, ["ticker", "price_as_of", "price_close", "ingest_at", "accepted_at"]):
    print(f.check_id, f.status.value, f.subject)
# field.dtype pass ticker
# field.dtype pass price_as_of
# field.dtype pass price_close
# field.dtype pass ingest_at
# field.null fail accepted_at
```
The last line fails on purpose: `accepted_at` is non-nullable in the dictionary, so `None` is rejected.

## Known limits
- Checks one record at a time. It does not compare dates to a cutoff; ordering lives in `clock_ordering.py` and `availability_cutoff.py`.
- A future timestamp passes the dtype check.
- A bare `date` is rejected for a datetime field.
- Naive datetimes fail. Aware datetimes with any offset pass.
- NaN counts as null, so it reports under `field.null`, not as a non-finite float.
- Unknown extra fields give `WARN`, not `FAIL`.
- The dictionary is a fixed list in code. Adding a field means editing the module.
- Python 3.9 only.
