"""Append-only JSON Lines store for ledgers and logs.

Each record is one line of canonical JSON (sorted keys, compact separators,
no NaN) terminated by a newline. The module offers exactly three operations:
append a record, read every record back in insertion order, and count them.
There is no overwrite, rewrite, truncate or delete path, so history written
here cannot be edited in place. A correction is recorded as a new line that
supersedes an earlier one; the earlier line stays on disk.

Topic: the estimate ledger as append-only history.

A missing file is treated as an empty history: read_records returns an empty
list and count_records returns 0. Any line that is not valid JSON, or whose
JSON value is not an object, raises AsOfError naming the 1-based line number.

All data handled here is synthetic. This module imports only the standard
library and as_of.core.
"""

import dataclasses
import json
import math
import os
from datetime import datetime
from typing import Any, Dict, List

from as_of.core import AsOfError, canonical_json, require, to_plain


def _reject_constant(name: str) -> Any:
    raise ValueError("non-finite literal %s is not allowed" % name)


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("non-finite number %s is not allowed" % text)
    return value


def _no_duplicate_keys(pairs: List[Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key %r" % key)
        result[key] = value
    return result


def _check_str_keys(value: Any) -> None:
    """Raise AsOfError if any dict in a plain value has a non-str key."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise AsOfError(
                    "record keys must be str, got %s" % type(key).__name__
                )
            _check_str_keys(nested)
    elif isinstance(value, list):
        for item in value:
            _check_str_keys(item)


def _check_no_sub_second(value: Any) -> None:
    """Raise AsOfError if any datetime in a record has microseconds.

    core.fmt_ts drops fractional seconds, so storing such a value would
    silently collapse distinct instants into the same line. Refusing is the
    only way to keep the ledger honest about what was written.
    """
    if isinstance(value, datetime):
        if value.microsecond != 0:
            raise AsOfError(
                "sub-second datetime %s would be truncated on write; "
                "round to whole seconds before appending" % value.isoformat()
            )
    elif isinstance(value, dict):
        for nested in value.values():
            _check_no_sub_second(nested)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_no_sub_second(item)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            _check_no_sub_second(getattr(value, field.name))


def append_record(path: str, record: Dict[str, Any]) -> None:
    """Append one record as a single canonical JSON line to the file at path.

    The file is opened in append mode and never rewritten. Non-dict records,
    and records that cannot be canonicalised (for example NaN values or
    sub-second datetimes), raise AsOfError before anything is written. The
    line is flushed and fsynced before the call returns.
    """
    require(isinstance(path, str) and path != "", "path must be a non-empty str")
    if not isinstance(record, dict):
        raise AsOfError("record must be a dict, got %s" % type(record).__name__)
    _check_str_keys(to_plain(record))
    _check_no_sub_second(record)
    line = canonical_json(record)
    if "\n" in line or "\r" in line:
        raise AsOfError("canonical record unexpectedly contains a line break")
    if os.path.isdir(path):
        raise AsOfError("cannot append to a directory: %s" % path)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as tail:
            tail.seek(-1, os.SEEK_END)
            last_byte = tail.read(1)
        if last_byte != b"\n":
            raise AsOfError(
                "file does not end with a newline; refusing to append to it"
            )
    try:
        handle = open(path, "a", encoding="utf-8")
    except OSError as exc:
        raise AsOfError("cannot open %s for append: %s" % (path, exc))
    with handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_records(path: str) -> List[Dict[str, Any]]:
    """Return every record in the file at path, in insertion order.

    A missing file yields an empty list. Blank lines, malformed JSON and
    non-object JSON values raise AsOfError naming the line number.
    """
    require(isinstance(path, str) and path != "", "path must be a non-empty str")
    if not os.path.exists(path):
        return []
    records: List[Dict[str, Any]] = []
    try:
        handle = open(path, "rb")
    except OSError as exc:
        raise AsOfError("cannot open %s: %s" % (path, exc))
    with handle:
        for line_no, raw_bytes in enumerate(handle, start=1):
            try:
                raw = raw_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise AsOfError("line %d is not valid UTF-8: %s" % (line_no, exc))
            text = raw.rstrip("\r\n")
            try:
                value = json.loads(
                    text,
                    parse_constant=_reject_constant,
                    parse_float=_finite_float,
                    object_pairs_hook=_no_duplicate_keys,
                )
            except ValueError as exc:
                raise AsOfError("line %d is not valid JSON: %s" % (line_no, exc))
            if not isinstance(value, dict):
                raise AsOfError(
                    "line %d is not a JSON object, got %s"
                    % (line_no, type(value).__name__)
                )
            records.append(value)
    return records


def count_records(path: str) -> int:
    """Return the number of records in the file at path.

    The file is validated the same way read_records validates it, so a
    malformed line raises AsOfError here too.
    """
    return len(read_records(path))
