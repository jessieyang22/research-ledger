"""Source register for the as_of package.

Every source that feeds an output (a filing, a price file, an estimate pull,
an expert-call note) gets one registry entry with an id, a type, a locator
and a content hash. Outputs list the source ids they used. Any id that is
not in the register is reported as a FAIL finding, so an output cannot quietly
rest on a source nobody recorded.

It uses synthetic data only and makes no network calls.

Only core.py is imported. No other as_of module is needed.
"""

import re
from typing import Any, Dict, List, Sequence

from as_of.core import (
    AsOfError,
    Finding,
    SourceRecord,
    SourceType,
    ValidationStatus,
    ensure_utc,
    to_plain,
)

UNREGISTERED_CHECK_ID: str = "SRC_UNREGISTERED"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _require_text(value: Any, field: str) -> None:
    """Raise AsOfError unless value is a non-empty str."""
    if not isinstance(value, str) or not value.strip():
        raise AsOfError("source field %s must be a non-empty str, got %r" % (field, value))


def _validate_record(rec: SourceRecord) -> None:
    """Reject records with missing, wrong-typed or malformed fields."""
    _require_text(rec.source_id, "source_id")
    if not isinstance(rec.source_type, SourceType):
        raise AsOfError("source_type must be a SourceType, got %r" % (rec.source_type,))
    _require_text(rec.publisher, "publisher")
    _require_text(rec.locator, "locator")
    # ensure_utc raises AsOfError for None, naive or non-datetime values.
    ensure_utc(rec.retrieved_at)
    if not isinstance(rec.sha256, str) or not _SHA256_RE.fullmatch(rec.sha256):
        raise AsOfError("sha256 must be 64 lowercase hex characters, got %r" % (rec.sha256,))
    if not isinstance(rec.synthetic, bool):
        raise AsOfError("synthetic must be a bool, got %r" % (rec.synthetic,))


class SourceRegister:
    """In-memory registry keyed by source_id.

    Duplicate ids are rejected rather than overwritten, so a source's
    recorded locator and hash cannot change silently after it is logged.
    """

    def __init__(self) -> None:
        self._sources: Dict[str, SourceRecord] = {}

    def add_source(self, rec: SourceRecord) -> None:
        """Register a source. A repeated source_id raises AsOfError."""
        if not isinstance(rec, SourceRecord):
            raise AsOfError("add_source expects a SourceRecord, got %s" % type(rec).__name__)
        _validate_record(rec)
        if rec.source_id in self._sources:
            raise AsOfError("duplicate source_id: %r" % rec.source_id)
        self._sources[rec.source_id] = rec

    def get_source(self, source_id: str) -> SourceRecord:
        """Return the registered source. A missing or unhashable id raises AsOfError."""
        try:
            return self._sources[source_id]
        except KeyError:
            raise AsOfError("unknown source_id: %r" % (source_id,))
        except TypeError:
            raise AsOfError("unhashable source_id: %r" % (source_id,))

    def has_source(self, source_id: str) -> bool:
        """Return True when source_id is registered. An unhashable id raises AsOfError."""
        try:
            return source_id in self._sources
        except TypeError:
            raise AsOfError("unhashable source_id: %r" % (source_id,))

    def to_manifest(self) -> List[Dict[str, Any]]:
        """Return all registered sources as plain dicts, sorted by source_id."""
        return [to_plain(self._sources[sid]) for sid in sorted(self._sources)]

    def check_sources_used(self, used_ids: Sequence[str]) -> List[Finding]:
        """Return one FAIL finding per distinct id in used_ids that is not registered.

        Registered ids produce no finding. Repeated unregistered ids produce
        a single finding each. Findings follow first-seen order in used_ids.
        """
        findings: List[Finding] = []
        seen: set = set()
        for sid in used_ids:
            try:
                registered = sid in self._sources
            except TypeError:
                raise AsOfError("unhashable source id in used_ids: %r" % (sid,))
            # Key on (type, repr) rather than on the object itself: two distinct
            # NaN objects are unequal, so a plain set would report one id twice.
            key = (type(sid).__name__, repr(sid))
            if key in seen:
                continue
            seen.add(key)
            if not registered:
                findings.append(
                    Finding(
                        check_id=UNREGISTERED_CHECK_ID,
                        status=ValidationStatus.FAIL,
                        message="source %r is used but not registered" % (sid,),
                        subject=str(sid),
                    )
                )
        return findings
