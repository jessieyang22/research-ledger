"""Queue of open exceptions for the as_of research-state workflow.

An exception is a flagged problem tied to a subject (for example a catalyst
that has no confirmed date, or a source that changed after it was used). The
queue keeps one record per (kind, subject_id, opened_at) and tracks when each
record is resolved.

Behaviour:

- open() is idempotent. The record id is stable_hash of kind, subject_id and
  opened_at, so opening the same triple again returns the existing record and
  leaves it unchanged.
- resolve() closes an open record once. A second resolve raises AsOfError.
- open_items() lists records that are not resolved yet.
- prioritized() orders open records by severity (BLOCK, then WARN, then INFO)
  and then by age (earliest opened_at first).
- counts() reports open and resolved totals separately.

Topic: catalyst exception queue.

Imports from the as_of package: core.py at module level, and exception_vocabulary
loaded lazily through core.component() inside open(). The vocabulary is the
source of default severities for ExceptionKind values. The data is synthetic
and the module does no I/O.
"""

from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional, Union

from as_of.core import (
    SEVERITY_RANK,
    AsOfError,
    ExceptionRecord,
    Severity,
    component,
    ensure_utc,
    require,
    stable_hash,
)

# ExceptionKind is only needed for type hints. The vocabulary module is loaded
# inside open() through component(), following the core.py convention.
if TYPE_CHECKING:  # pragma: no cover
    from as_of.exception_vocabulary import ExceptionKind


class ExceptionQueue:
    """In-memory queue of exception records keyed by stable id.

    Records are kept in insertion order. Resolved records stay in the queue
    so that counts() can report them alongside open items.
    """

    def __init__(self) -> None:
        self._items: Dict[str, ExceptionRecord] = {}

    def open(
        self,
        kind: Union[str, "ExceptionKind"],
        subject_id: str,
        opened_at: datetime,
        note: str = "",
        severity: Optional[Severity] = None,
    ) -> ExceptionRecord:
        """Open an exception, or return the existing record with the same id.

        kind is an ExceptionKind from the vocabulary module, or a non-empty
        str for ad hoc kinds. When severity is None, an ExceptionKind takes its
        vocabulary default severity and a str kind defaults to INFO. The id is
        stable_hash of kind, subject_id and the UTC opened_at, so a repeated
        call with the same triple never adds a second item. Arguments are
        validated before the duplicate lookup, so a bad call is refused even
        when its triple is already open.
        """
        vocab = component("exception_vocabulary")
        is_kind = isinstance(kind, vocab.ExceptionKind)
        kind_name = kind.value if is_kind else kind
        require(isinstance(kind_name, str) and kind_name != "", "kind must be a non-empty str or ExceptionKind")
        require(isinstance(subject_id, str) and subject_id != "", "subject_id must be a non-empty str")
        require(isinstance(note, str), "note must be a str")
        require(severity is None or isinstance(severity, Severity), "severity must be a Severity or None")
        opened_utc = ensure_utc(opened_at)
        key = {"kind": kind_name, "subject_id": subject_id, "opened_at": opened_utc}
        if opened_utc.microsecond:
            # fmt_ts drops fractional seconds, so keep them in the key or two
            # opens a fraction of a second apart would collapse into one item.
            key["opened_us"] = opened_utc.microsecond
        exception_id = stable_hash(key)
        existing = self._items.get(exception_id)
        if existing is not None:
            return existing
        if severity is None:
            severity = vocab.default_severity(kind) if is_kind else Severity.INFO
        record = ExceptionRecord(
            exception_id=exception_id,
            kind=kind_name,
            severity=severity,
            subject_id=subject_id,
            opened_at=opened_utc,
            resolved_at=None,
            note=note,
        )
        self._items[exception_id] = record
        return record

    def resolve(self, exception_id: str, resolved_at: datetime, note: str) -> ExceptionRecord:
        """Mark an open exception as resolved.

        Raises AsOfError when the id is unknown, when the record is already
        resolved, or when resolved_at is earlier than opened_at.
        """
        require(isinstance(exception_id, str), "exception_id must be a str")
        require(isinstance(note, str), "note must be a str")
        record = self._items.get(exception_id)
        if record is None:
            raise AsOfError("unknown exception id: %r" % (exception_id,))
        if record.resolved_at is not None:
            raise AsOfError("exception already resolved: %r" % (exception_id,))
        resolved_utc = ensure_utc(resolved_at)
        require(
            resolved_utc >= record.opened_at,
            "resolved_at must not be earlier than opened_at",
        )
        # An empty resolve note keeps the note the exception was opened with.
        updated = replace(record, resolved_at=resolved_utc, note=note if note else record.note)
        self._items[exception_id] = updated
        return updated

    def open_items(self) -> List[ExceptionRecord]:
        """Return unresolved records in insertion order."""
        return [r for r in self._items.values() if r.resolved_at is None]

    def prioritized(self) -> List[ExceptionRecord]:
        """Return open records, highest severity first, oldest first within a severity."""
        return sorted(
            self.open_items(),
            key=lambda r: (-SEVERITY_RANK[r.severity], r.opened_at),
        )

    def counts(self) -> Dict[str, int]:
        """Return totals keyed by 'open', 'resolved' and 'total'."""
        open_n = len(self.open_items())
        total = len(self._items)
        return {"open": open_n, "resolved": total - open_n, "total": total}
