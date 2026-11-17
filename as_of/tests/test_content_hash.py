"""Tests for as_of.content_hash. All fixtures are synthetic and use the SYN_ prefix."""

import dataclasses
import hashlib
import os
from datetime import date

import pytest

from as_of.content_hash import hash_manifest, hash_records, sha256_file
from as_of.core import AsOfError, ManifestEntry


@dataclasses.dataclass(frozen=True)
class _SynRecord:
    name: str
    as_of: date
    value: float


def _write(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


def test_sha256_file_matches_hashlib(tmp_path):
    payload = b"SYN_ synthetic bytes \x00\x01\xff" * 1000
    path = tmp_path / "SYN_payload.bin"
    _write(str(path), payload)
    assert sha256_file(str(path)) == hashlib.sha256(payload).hexdigest()


def test_sha256_file_empty_file_matches_hashlib(tmp_path):
    path = tmp_path / "SYN_empty.bin"
    _write(str(path), b"")
    assert sha256_file(str(path)) == hashlib.sha256(b"").hexdigest()


def test_sha256_file_spans_multiple_chunks(tmp_path):
    # Larger than the 1 MiB internal chunk so the streaming loop runs more than once.
    payload = (b"SYN_chunk" * 200000) + b"tail"
    path = tmp_path / "SYN_big.bin"
    _write(str(path), payload)
    assert sha256_file(str(path)) == hashlib.sha256(payload).hexdigest()


def test_sha256_file_missing_path_raises(tmp_path):
    with pytest.raises(OSError):
        sha256_file(str(tmp_path / "SYN_absent.bin"))


def test_hash_records_order_sensitive_and_stable():
    a = _SynRecord("SYN_A", date(2026, 1, 2), 1.5)
    b = _SynRecord("SYN_B", date(2026, 1, 3), -2.0)
    forward = hash_records([a, b])
    reverse = hash_records([b, a])
    assert forward != reverse
    assert hash_records([a, b]) == forward
    assert hash_records([a, b]) == hash_records([a, b])


def test_hash_records_changes_when_content_changes():
    a = _SynRecord("SYN_A", date(2026, 1, 2), 1.5)
    a_changed = _SynRecord("SYN_A", date(2026, 1, 2), 1.6)
    assert hash_records([a]) != hash_records([a_changed])


def test_hash_records_count_matters():
    a = _SynRecord("SYN_A", date(2026, 1, 2), 1.5)
    assert hash_records([a]) != hash_records([a, a])


def test_hash_records_accepts_plain_dicts_and_empty_input():
    rows = [{"SYN_k": 1}, {"SYN_k": 2}]
    assert hash_records(rows) == hash_records([{"SYN_k": 1}, {"SYN_k": 2}])
    assert hash_records([]) == hash_records(())
    assert hash_records([]) != hash_records(rows)


def test_hash_manifest_sorted_with_correct_sizes(tmp_path):
    root = str(tmp_path)
    _write(os.path.join(root, "SYN_zeta.txt"), b"zz")
    _write(os.path.join(root, "SYN_alpha.txt"), b"a" * 7)
    _write(os.path.join(root, "SYN_mid.txt"), b"")

    entries = hash_manifest(root, ["SYN_zeta.txt", "SYN_mid.txt", "SYN_alpha.txt"])

    assert [e.path for e in entries] == ["SYN_alpha.txt", "SYN_mid.txt", "SYN_zeta.txt"]
    sizes = {e.path: e.size_bytes for e in entries}
    assert sizes == {"SYN_alpha.txt": 7, "SYN_mid.txt": 0, "SYN_zeta.txt": 2}
    for entry in entries:
        assert isinstance(entry, ManifestEntry)
        assert entry.kind == "file"
        full = os.path.join(root, entry.path)
        with open(full, "rb") as handle:
            assert entry.sha256 == hashlib.sha256(handle.read()).hexdigest()


def test_hash_manifest_missing_path_raises_as_of_error(tmp_path):
    root = str(tmp_path)
    _write(os.path.join(root, "SYN_present.txt"), b"ok")
    with pytest.raises(AsOfError):
        hash_manifest(root, ["SYN_present.txt", "SYN_absent.txt"])


def test_hash_manifest_directory_is_not_a_file_raises(tmp_path):
    root = str(tmp_path)
    os.mkdir(os.path.join(root, "SYN_dir"))
    with pytest.raises(AsOfError):
        hash_manifest(root, ["SYN_dir"])


def test_hash_manifest_duplicate_path_rejected(tmp_path):
    root = str(tmp_path)
    _write(os.path.join(root, "SYN_dup.txt"), b"x")
    with pytest.raises(AsOfError):
        hash_manifest(root, ["SYN_dup.txt", "SYN_dup.txt"])


def test_hash_manifest_non_str_root_rejected(tmp_path):
    with pytest.raises(AsOfError):
        hash_manifest(tmp_path, [])
