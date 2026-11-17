"""Checkpoints for resumable runs in the as_of package.

A checkpoint is one JSON file per pipeline step. It stores a payload, the
input hash the step ran on, and the digest of the run's StateManifest at the
time of writing. Every checkpoint file carries a digest over its whole body,
so any edit to the payload, the input hash, the step name or the manifest
digest makes the read fail.

A saved checkpoint is reused (skipped on resume) only when its recorded input
hash equals the input hash of the current run. A changed input means the step
runs again, even when a checkpoint file exists.

Public functions:

- write_checkpoint: write one step's checkpoint and return its path.
- read_checkpoint: return the payload, or raise AsOfError when the stored
  digest does not match the content.
- should_skip: True only when a verified checkpoint exists with the same
  input hash.
- latest_step: the last step, in the given order, that has a checkpoint file.

Design notes:

- Payloads should be JSON-native (dict, list, str, int, float, bool, None).
  Tuples come back as lists and dataclasses come back as plain dicts after a
  round trip, so compare them in their plain form.
- Hashing goes through core.stable_hash, so datetimes and dates hash the same
  way before and after the JSON round trip.
- Files are written to a temporary name and then moved into place with
  os.replace, so an interrupted write does not leave a half-written file under
  the real name.


All data handled here is synthetic. This module imports only the standard
library and as_of.core at run time. StateManifest is imported for type hints
only. No network or subprocess work is done here.
"""

import json
import os
import re
import tempfile
from collections.abc import Sequence as SequenceABC
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence

from as_of.core import AsOfError, canonical_json, require, stable_hash

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from as_of.state_manifest import StateManifest


CHECKPOINT_FORMAT: str = "as_of.checkpoint"
CHECKPOINT_VERSION: int = 1
CHECKPOINT_SUFFIX: str = ".checkpoint.json"
_STEP_RE = re.compile(r"[A-Za-z0-9_\-]{1,64}")


def _checkpoint_path(dir_path: str, step: str) -> str:
    """Return the file path for a step's checkpoint. Rejects unsafe step names."""
    require(isinstance(dir_path, str) and dir_path != "", "dir_path must be a non-empty str")
    require(
        isinstance(step, str) and _STEP_RE.fullmatch(step) is not None,
        "invalid checkpoint step name: %r" % (step,),
    )
    return os.path.join(dir_path, step + CHECKPOINT_SUFFIX)


def _load_envelope(path: str) -> Dict[str, Any]:
    """Read and parse a checkpoint file. Raises AsOfError on I/O or JSON errors."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.loads(handle.read())
    except OSError as exc:
        raise AsOfError("cannot read checkpoint %s: %s" % (path, exc))
    except (ValueError, RecursionError) as exc:
        raise AsOfError("checkpoint %s is not valid JSON: %s" % (path, exc))
    require(isinstance(data, dict), "checkpoint envelope must be a JSON object: %s" % path)
    return data


def _read_verified_body(dir_path: str, step: str) -> Dict[str, Any]:
    """Return the verified checkpoint body. Raises AsOfError if anything is off."""
    path = _checkpoint_path(dir_path, step)
    envelope = _load_envelope(path)
    body = envelope.get("body")
    stored = envelope.get("digest")
    require(isinstance(body, dict), "checkpoint has no body: %s" % path)
    require(isinstance(stored, str), "checkpoint has no digest: %s" % path)
    try:
        digest_ok = stable_hash(body) == stored
    except RecursionError:
        raise AsOfError("checkpoint body is nested too deeply: %s" % path)
    if not digest_ok:
        raise AsOfError("checkpoint digest does not match its content: %s" % path)
    require(body.get("format") == CHECKPOINT_FORMAT, "unexpected checkpoint format in %s" % path)
    require(body.get("version") == CHECKPOINT_VERSION, "unsupported checkpoint version in %s" % path)
    require(body.get("step") == step, "checkpoint step name does not match file: %s" % path)
    require(isinstance(body.get("payload"), dict), "checkpoint payload must be a dict: %s" % path)
    require(isinstance(body.get("input_hash"), str), "checkpoint input_hash must be a str: %s" % path)
    return body


def write_checkpoint(
    dir_path: str,
    step: str,
    payload: Dict[str, Any],
    manifest: "StateManifest",
    input_hash: str,
) -> str:
    """Write the checkpoint for one step and return the file path.

    The file records the step name, the input hash, the manifest digest and
    the payload, under one digest that covers the whole body. An existing
    checkpoint for the same step is replaced.
    """
    path = _checkpoint_path(dir_path, step)
    require(isinstance(payload, dict), "payload must be a dict, got %s" % type(payload).__name__)
    require(isinstance(input_hash, str) and input_hash != "", "input_hash must be a non-empty str")
    require(callable(getattr(manifest, "digest", None)), "manifest must be a StateManifest")
    body: Dict[str, Any] = {
        "format": CHECKPOINT_FORMAT,
        "version": CHECKPOINT_VERSION,
        "step": step,
        "input_hash": input_hash,
        "manifest_digest": manifest.digest(),
        "payload": payload,
    }
    try:
        envelope = {"digest": stable_hash(body), "body": body}
        text = canonical_json(envelope) + "\n"
    except RecursionError:
        raise AsOfError("checkpoint payload is nested too deeply for step %s" % step)
    os.makedirs(dir_path, exist_ok=True)
    _atomic_write_text(path, text)
    return path


def _atomic_write_text(path: str, text: str) -> None:
    """Write text to a unique temp file in the same directory, fsync it, then rename it over path.

    A unique temp name keeps two writers of the same step from sharing one
    temp file. The fsync makes the rename safe after a crash or power loss.
    """
    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_checkpoint(dir_path: str, step: str) -> Dict[str, Any]:
    """Return the payload stored for a step.

    Raises AsOfError when the file is missing, is not valid JSON, or when its
    stored digest does not match the content.
    """
    body = _read_verified_body(dir_path, step)
    return dict(body["payload"])


def should_skip(dir_path: str, step: str, input_hash: str) -> bool:
    """Return True only when a verified checkpoint exists with the same input hash.

    A missing, unreadable or altered checkpoint returns False, so the step runs
    again. A checkpoint recorded on a different input hash also returns False.
    """
    require(isinstance(input_hash, str), "input_hash must be a str")
    try:
        body = _read_verified_body(dir_path, step)
    except AsOfError:
        return False
    return body["input_hash"] == input_hash


def latest_step(dir_path: str, ordered_steps: Sequence[str]) -> Optional[str]:
    """Return the last step in ordered_steps that has a checkpoint file, or None.

    This checks only that the file exists. It does not verify the content;
    use read_checkpoint or should_skip for that.
    """
    require(
        isinstance(ordered_steps, SequenceABC) and not isinstance(ordered_steps, str),
        "ordered_steps must be a sequence of step names, not a str or None",
    )
    latest: Optional[str] = None
    for step in ordered_steps:
        if os.path.isfile(_checkpoint_path(dir_path, step)):
            latest = step
    return latest
