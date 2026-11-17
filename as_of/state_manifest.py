"""Run-level state manifest for the as_of package.

A StateManifest records the steps of one pipeline run in order. Each step
carries a name, the hashes of its inputs, the hashes of its outputs and a
code version string. The whole manifest reduces to one digest, so two runs
with the same steps can be compared by digest alone, and a saved manifest can
be checked later for edits.

Design notes:

- Steps keep insertion order. The digest depends on that order.
- No timestamps or host details go into the manifest, so the digest is the
  same on every machine for the same steps.
- The digest is the stable hash of the canonical JSON form of the manifest
  body. The body is the to_dict() output.
- save() writes the body together with its digest. verify() recomputes the
  digest from the body on disk and compares it with the stored digest, so any
  edit to either part makes verification fail.


All data handled here is synthetic. This module imports only the standard
library and as_of.core. It does no network or subprocess work.
"""

import json
import os
from typing import Any, Dict, List

from as_of.core import AsOfError, canonical_json, require, stable_hash


MANIFEST_FORMAT: str = "as_of.state_manifest"
MANIFEST_VERSION: int = 1


def _check_hash_map(name: str, value: Any) -> Dict[str, str]:
    """Return a copy of value after checking it maps str keys to str hashes."""
    require(isinstance(value, dict), "%s must be a dict, got %s" % (name, type(value).__name__))
    out: Dict[str, str] = {}
    for key, item in value.items():
        require(isinstance(key, str) and key != "", "%s keys must be non-empty str" % name)
        require(isinstance(item, str) and item != "", "%s[%r] must be a non-empty str hash" % (name, key))
        out[key] = item
    return out


class StateManifest:
    """Ordered list of run steps with input hashes, output hashes and code versions."""

    def __init__(self) -> None:
        self._steps: List[Dict[str, Any]] = []

    def record_step(
        self,
        step_name: str,
        inputs: Dict[str, str],
        outputs: Dict[str, str],
        code_version: str,
    ) -> None:
        """Append one step. Input and output maps go from name to hash string."""
        require(isinstance(step_name, str) and step_name != "", "step_name must be a non-empty str")
        require(isinstance(code_version, str) and code_version != "", "code_version must be a non-empty str")
        self._steps.append(
            {
                "step_name": step_name,
                "inputs": _check_hash_map("inputs", inputs),
                "outputs": _check_hash_map("outputs", outputs),
                "code_version": code_version,
            }
        )

    def steps(self) -> List[Dict[str, Any]]:
        """Return the steps in insertion order, as copies."""
        return [
            {
                "step_name": s["step_name"],
                "inputs": dict(s["inputs"]),
                "outputs": dict(s["outputs"]),
                "code_version": s["code_version"],
            }
            for s in self._steps
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Return the manifest body as a JSON-ready dict."""
        return {
            "format": MANIFEST_FORMAT,
            "version": MANIFEST_VERSION,
            "steps": self.steps(),
        }

    def digest(self) -> str:
        """Hex sha256 of the canonical JSON form of the manifest body."""
        return stable_hash(self.to_dict())

    def save(self, path: str) -> str:
        """Write the body and its digest to path as JSON. Returns the digest."""
        digest = self.digest()
        payload = {"digest": digest, "manifest": self.to_dict()}
        text = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return digest

    @classmethod
    def load(cls, path: str) -> "StateManifest":
        """Read a manifest file written by save(). Raises AsOfError on bad content."""
        payload = _read_payload(path)
        body = payload.get("manifest")
        require(isinstance(body, dict), "manifest file has no manifest body: %s" % path)
        require(set(payload.keys()) <= {"digest", "manifest"}, "unexpected envelope keys in %s" % path)
        require(set(body.keys()) == {"format", "version", "steps"}, "unexpected body keys in %s" % path)
        require(body.get("format") == MANIFEST_FORMAT, "unexpected manifest format in %s" % path)
        version = body.get("version")
        # bool is a subclass of int and True == 1, so reject bools explicitly.
        require(
            type(version) is int and version == MANIFEST_VERSION,
            "unsupported manifest version in %s" % path,
        )
        require(stable_hash(body) == payload.get("digest"), "manifest digest mismatch in %s" % path)
        steps = body.get("steps")
        require(isinstance(steps, list), "manifest steps must be a list in %s" % path)
        manifest = cls()
        for step in steps:
            require(isinstance(step, dict), "each step must be a dict in %s" % path)
            require(
                set(step.keys()) == {"step_name", "inputs", "outputs", "code_version"},
                "unexpected step keys in %s" % path,
            )
            manifest.record_step(
                step.get("step_name"),
                step.get("inputs"),
                step.get("outputs"),
                step.get("code_version"),
            )
        return manifest

    @classmethod
    def verify(cls, path: str) -> bool:
        """Return True when the stored digest matches the body on disk.

        Returns False when the file is missing, is not valid JSON, has the
        wrong shape, or has been edited since save().
        """
        try:
            payload = _read_payload(path)
            body = payload.get("manifest")
            stored = payload.get("digest")
            if not isinstance(body, dict) or not isinstance(stored, str):
                return False
            if stable_hash(body) != stored:
                return False
            # A digest match alone is not enough: the body must also load.
            cls.load(path)
            return True
        except (AsOfError, OSError, TypeError, ValueError):
            return False


def _read_payload(path: str) -> Dict[str, Any]:
    """Read and parse the saved JSON envelope. Raises AsOfError on bad JSON."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.loads(handle.read())
    except OSError as exc:
        raise AsOfError("cannot read manifest %s: %s" % (path, exc))
    except ValueError as exc:
        raise AsOfError("manifest %s is not valid JSON: %s" % (path, exc))
    require(isinstance(data, dict), "manifest envelope must be a JSON object: %s" % path)
    return data
