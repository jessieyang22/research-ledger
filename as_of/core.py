"""Shared constants, enums, record types and helpers for the as_of package.

This module is the only piece every other as_of module may depend on. It
imports only the standard library and numpy, and it never imports another
as_of module statically. Other pieces are reached inside function bodies
through component(name) when a caller needs them.

All data handled here is synthetic. Fixture ids start with SYN_.
"""

import dataclasses
import hashlib
import importlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from types import ModuleType
from typing import Any, Dict, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PACKAGE_NAME: str = "as_of"
SYNTHETIC_SEED: int = 20261027
SYNTHETIC_PREFIX: str = "SYN_"
CLOCK_NAMES: Tuple[str, ...] = ("event", "knowledge", "report", "release", "ingest")
FORBIDDEN_IMPORT_ROOTS: Tuple[str, ...] = (
    "quant_lab",
    "yfinance",
    "requests",
    "urllib",
    "http",
    "socket",
    "subprocess",
    "ftplib",
    "smtplib",
)
ALLOWED_THIRD_PARTY: Tuple[str, ...] = ("numpy", "pandas")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ClockName(Enum):
    EVENT = "event"
    KNOWLEDGE = "knowledge"
    REPORT = "report"
    RELEASE = "release"
    INGEST = "ingest"


class SourceType(Enum):
    FILING = "filing"
    PRICE = "price"
    ESTIMATE = "estimate"
    MACRO = "macro"
    CATALYST = "catalyst"
    EXPERT_CALL = "expert_call"
    INTERNAL = "internal"
    FIXTURE = "fixture"


class Severity(Enum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


SEVERITY_RANK: Dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.WARN: 1,
    Severity.BLOCK: 2,
}


class ValidationStatus(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class RunStatus(Enum):
    ON_TIME = "on_time"
    LATE = "late"
    MISSED = "missed"


# ---------------------------------------------------------------------------
# Records (all frozen)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    source_type: SourceType
    publisher: str
    locator: str
    retrieved_at: datetime
    sha256: str
    synthetic: bool


@dataclass(frozen=True)
class ClockSet:
    event_at: Optional[datetime] = None
    knowledge_at: Optional[datetime] = None
    report_at: Optional[datetime] = None
    release_at: Optional[datetime] = None
    ingest_at: Optional[datetime] = None


@dataclass(frozen=True)
class FieldSpec:
    name: str
    unit: str
    dtype: str
    clock: ClockName
    nullable: bool


@dataclass(frozen=True)
class EstimateRecord:
    estimate_id: str
    ticker: str
    metric: str
    period: str
    analyst_id: str
    value: float
    knowledge_at: datetime
    source_id: str


@dataclass(frozen=True)
class MacroVintage:
    series_id: str
    obs_date: date
    vintage_date: date
    release_at: datetime
    value: float
    source_id: str


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    text: str
    claim_kind: str
    source_ids: Tuple[str, ...]
    status: str
    section: str


@dataclass(frozen=True)
class ExceptionRecord:
    exception_id: str
    kind: str
    severity: Severity
    subject_id: str
    opened_at: datetime
    resolved_at: Optional[datetime]
    note: str


@dataclass(frozen=True)
class FilingRecord:
    filing_id: str
    ticker: str
    form_type: str
    filed_at: datetime
    accepted_at: datetime
    source_id: str


@dataclass(frozen=True)
class PositionRecord:
    book: str
    ticker: str
    quantity: float
    as_of: date


@dataclass(frozen=True)
class PriceRecord:
    ticker: str
    as_of: date
    close: float
    source_id: str


@dataclass(frozen=True)
class Finding:
    check_id: str
    status: ValidationStatus
    message: str
    subject: str


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    sha256: str
    size_bytes: int
    kind: str


@dataclass(frozen=True)
class ChangeRecord:
    change_id: str
    summary: str
    reason: str
    status: str
    opened_on: date
    evidence_ref: Optional[str]


@dataclass(frozen=True)
class IncidentRecord:
    incident_id: str
    summary: str
    severity: Severity
    opened_on: date
    status: str
    timeline: Tuple[Tuple[datetime, str], ...]
    root_cause: Optional[str]


@dataclass(frozen=True)
class ReadinessItem:
    item_id: str
    passed: bool
    evidence_ref: str


@dataclass(frozen=True)
class ProofResult:
    proof_name: str
    passed: bool
    findings: Tuple[Finding, ...]
    metrics: Dict[str, float]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AsOfError(Exception):
    """Base error for the as_of package."""


class HardFailError(AsOfError):
    """A check that must stop the pipeline."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE_ONLY_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", re.ASCII)
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def require(cond: bool, message: str) -> None:
    """Raise AsOfError(message) when cond is false."""
    if not cond:
        raise AsOfError(message)


def parse_ts(text: str) -> datetime:
    """Parse 'YYYY-MM-DD' (as 00:00Z) or 'YYYY-MM-DDTHH:MM:SSZ' into aware UTC.

    Anything else raises AsOfError. That includes naive strings, numeric
    offsets, lowercase z, fractional seconds and surrounding whitespace.
    """
    if not isinstance(text, str):
        raise AsOfError("timestamp must be a str, got %s" % type(text).__name__)
    if _DATE_ONLY_RE.fullmatch(text):
        fmt = "%Y-%m-%d"
    elif _DATETIME_RE.fullmatch(text):
        fmt = _TS_FORMAT
    else:
        raise AsOfError("unsupported timestamp format: %r" % text)
    try:
        parsed = datetime.strptime(text, fmt)
    except ValueError as exc:
        raise AsOfError("invalid timestamp %r: %s" % (text, exc))
    return parsed.replace(tzinfo=timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Return dt as aware UTC. Naive datetimes raise AsOfError."""
    if not isinstance(dt, datetime):
        raise AsOfError("expected datetime, got %s" % type(dt).__name__)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise AsOfError("naive datetime is not allowed: %r" % (dt,))
    try:
        return dt.astimezone(timezone.utc)
    except OverflowError as exc:
        raise AsOfError("datetime out of range after UTC conversion: %s" % exc)


def fmt_ts(dt: datetime) -> str:
    """Format as 'YYYY-MM-DDTHH:MM:SSZ' in UTC. Fractional seconds are dropped."""
    return ensure_utc(dt).strftime(_TS_FORMAT)


def to_plain(obj: Any) -> Any:
    """Convert records and common types into JSON-ready Python values.

    Check order matters: Enum before str/int, datetime before date (datetime
    is a subclass of date), and dataclass instances (not classes) before dict.
    """
    if isinstance(obj, Enum):
        return to_plain(obj.value)
    if isinstance(obj, datetime):
        return fmt_ts(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            plain_key = to_plain(key)
            # JSON only allows string keys; 1 and "1" or date and its ISO
            # string would otherwise serialise identically and collide.
            if not isinstance(plain_key, str):
                raise AsOfError("dict key must convert to str, got %s" % type(plain_key).__name__)
            if plain_key in out:
                raise AsOfError("duplicate dict key after conversion: %r" % plain_key)
            out[plain_key] = to_plain(value)
        return out
    if isinstance(obj, (list, tuple)):
        return [to_plain(x) for x in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    return obj


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators, NaN rejected."""
    try:
        return json.dumps(
            to_plain(obj),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AsOfError("cannot canonicalise object: %s" % exc)


def sha256_text(text: str) -> str:
    """Hex sha256 of text encoded as UTF-8."""
    if not isinstance(text, str):
        raise AsOfError("sha256_text expects str, got %s" % type(text).__name__)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_hash(obj: Any) -> str:
    """Hex sha256 of the canonical JSON form of obj."""
    return sha256_text(canonical_json(obj))


def make_rng(seed: int = SYNTHETIC_SEED) -> np.random.Generator:
    """Return a numpy Generator seeded for reproducible synthetic data."""
    return np.random.default_rng(seed)


def component(name: str) -> ModuleType:
    """Import the as_of submodule called name, for use inside function bodies.

    ImportError (including ModuleNotFoundError) is re-raised as AsOfError.
    """
    require(isinstance(name, str) and name.isidentifier(), "invalid component name: %r" % (name,))
    try:
        return importlib.import_module(PACKAGE_NAME + "." + name)
    except ImportError as exc:
        raise AsOfError("cannot import component %r: %s" % (name, exc))
