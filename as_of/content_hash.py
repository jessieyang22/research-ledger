"""Content hashing for files and record collections.

Vintage manifests and state manifests need to detect any change in file
bytes, in record content, or in record order. This module provides three
helpers for that:

- sha256_file: streaming SHA-256 of one file's bytes.
- hash_records: order-sensitive SHA-256 of a list or tuple of records. Each
  record is canonicalised before hashing so that distinct content, such as
  a date and its ISO string, or two datetimes that differ only in
  microseconds, never shares a digest.
- hash_manifest: one ManifestEntry per relative path, sorted by path, with
  a missing file treated as an error rather than skipped. Paths must stay
  inside root.

Topic: vintage manifests and state manifests.

All data handled here is synthetic. Only the standard library and
as_of.core are used.
"""

import dataclasses
import hashlib
import math
import os
import posixpath
from datetime import date, datetime
from enum import Enum
from typing import Any, List, Sequence

from as_of.core import AsOfError, ManifestEntry, ensure_utc, require, stable_hash

_CHUNK_BYTES: int = 1 << 20
_FILE_KIND: str = "file"
_MAX_DEPTH: int = 64
_TYPE_KEY: str = "__asof_type__"
_NUMPY_REFUSED = frozenset(["ndarray", "datetime64", "timedelta64", "void"])


def sha256_file(path: str) -> str:
    """Return the hex SHA-256 of the bytes in the file at path.

    The file is read in fixed-size chunks so large files do not need to fit
    in memory. A missing or unreadable path raises the OSError from open().
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(obj: Any, depth: int = 0) -> Any:
    """Return a JSON-ready form of obj in which every value keeps its type.

    datetimes are stored as UTC ISO text (isoformat, which keeps microseconds
    whenever they are nonzero), and dates as ISO
    text under a type tag, so a date never collides with a plain string.
    Dict keys must be str. Cycles and very deep nesting are refused.
    """
    if depth > _MAX_DEPTH:
        raise AsOfError("content too deeply nested or cyclic to hash")
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, Enum):
        return _canonical(obj.value, depth + 1)
    if isinstance(obj, datetime):
        return {_TYPE_KEY: "datetime", "value": ensure_utc(obj).isoformat()}
    if isinstance(obj, date):
        return {_TYPE_KEY: "date", "value": obj.isoformat()}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _canonical(
            {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}, depth + 1
        )
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            require(isinstance(key, str), "dict keys must be str, got %r" % (key,))
            require(key != _TYPE_KEY, "reserved key in record: %r" % (key,))
            out[key] = _canonical(value, depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [_canonical(x, depth + 1) for x in obj]
    if isinstance(obj, str):
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        require(math.isfinite(obj), "non-finite float is not hashable: %r" % (obj,))
        return float(obj)
    # numpy scalars: convert through the Python type. Arrays and datetime64 /
    # timedelta64 are refused: an array has no single scalar value, and
    # datetime64 with nanosecond unit .item() returns a bare int, which would
    # collide with a plain integer record.
    if type(obj).__module__ == "numpy" and callable(getattr(obj, "item", None)):
        require(
            type(obj).__name__ not in _NUMPY_REFUSED,
            "unsupported numpy type for content hash: %s" % type(obj).__name__,
        )
        try:
            scalar = obj.item()
        except (TypeError, ValueError) as exc:
            raise AsOfError("cannot convert numpy value for hashing: %s" % exc)
        return _canonical(scalar, depth + 1)
    raise AsOfError("unsupported type for content hash: %s" % type(obj).__name__)


def hash_records(records: Sequence[Any]) -> str:
    """Return a hex SHA-256 over a list or tuple of records, order-sensitive.

    Each record is canonicalised, then the per-record digests are hashed
    again in input order. Swapping two records changes the result. Calling
    twice on the same input gives the same value. Strings, bytes, dicts and
    None are refused as the record container, and NaN or infinity raise
    AsOfError.
    """
    require(
        isinstance(records, (list, tuple)),
        "records must be a list or tuple, got %s" % type(records).__name__,
    )
    per_record: List[str] = [stable_hash(_canonical(record)) for record in records]
    return stable_hash({"count": len(per_record), "digests": per_record})


def hash_manifest(root: str, rel_paths: Sequence[str]) -> List[ManifestEntry]:
    """Return ManifestEntry rows for the given paths under root, sorted by path.

    Each path is joined to root, must refer to an existing regular file that
    resolves inside root, and gets its SHA-256 and byte size recorded. The
    stored path is the relative path as given. Absolute paths, parent
    traversal and symlinks that leave root are rejected. Duplicate relative
    paths are rejected. A missing file raises AsOfError.
    """
    require(isinstance(root, str), "root must be a str, got %s" % type(root).__name__)
    real_root = os.path.realpath(root)
    seen = set()
    entries: List[ManifestEntry] = []
    for rel in rel_paths:
        require(isinstance(rel, str), "manifest path must be a str, got %r" % (rel,))
        require(rel != "", "manifest path must not be empty")
        require(not os.path.isabs(rel), "manifest path must be relative: %r" % (rel,))
        slashed = rel.replace("\\", "/")
        parts = slashed.split("/")
        require(".." not in parts, "manifest path must not traverse parents: %r" % (rel,))
        # Duplicate check uses the normalised spelling, so "a.txt" and
        # "./a.txt" (or "sub//a.txt") cannot both appear for one file.
        canon = posixpath.normpath(slashed)
        require(canon != ".", "manifest path must name a file: %r" % (rel,))
        require(canon not in seen, "duplicate manifest path: %r" % (rel,))
        seen.add(canon)
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            raise AsOfError("manifest file missing: %r" % (full,))
        real_full = os.path.realpath(full)
        require(
            real_full.startswith(real_root + os.sep),
            "manifest path resolves outside root: %r" % (rel,),
        )
        entries.append(
            ManifestEntry(
                path=rel,
                sha256=sha256_file(full),
                size_bytes=os.path.getsize(full),
                kind=_FILE_KIND,
            )
        )
    entries.sort(key=lambda entry: entry.path)
    return entries
