"""Proof 2: macro vintage, as-of value selection and cutoff check.

This proof builds a small synthetic macro series with revisions, records every
release in a vintage manifest, and then asks what a decision could have known
at a set of decision times. For each decision it picks the value that was
released at or before the decision time, checks that no used value was
released after the decision time, and records a state manifest that ties the
vintage set and the decisions together under one digest.

Method:
  * A value is usable at a decision time only when the vintage carrying it was
    released at or before that time. A later revision does not count until its
    own release moment has passed.
  * The vintage set is kept as a manifest, so the reader can see what was
    known on a date rather than only the latest revised value.
  * The run is reproducible. The manifest hash and the state digest are the
    same on every run with the same seed.

With inject_lookahead=True the decision picker ignores release times and takes
the newest vintage of each observation. Each revised observation then produces
a cutoff FAIL, so the proof does not pass. This is the planted fault the proof
is meant to catch.

Only as_of.core (shared types, UTC helpers, canonical hashing and the RNG) and
as_of.macro_vintage_manifest (VintageManifest) are imported. Nothing here is
read from disk or the network. All data is synthetic, with ids starting SYN_.

Public API:
    run_macro_proof(seed: int = SYNTHETIC_SEED, inject_lookahead: bool = False) -> ProofResult
"""

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from as_of.core import (
    SYNTHETIC_PREFIX,
    SYNTHETIC_SEED,
    AsOfError,
    Finding,
    MacroVintage,
    ProofResult,
    ValidationStatus,
    make_rng,
    stable_hash,
)
from as_of.macro_vintage_manifest import VintageManifest

PROOF_NAME: str = "proof_2_macro_vintage"
SERIES_ID: str = SYNTHETIC_PREFIX + "GDP"
SOURCE_ID: str = SYNTHETIC_PREFIX + "SRC_GDP"
OBS_COUNT: int = 6
OBS_START: date = date(2025, 1, 1)
RELEASE_LAG_DAYS: int = 30
REVISION_EVERY: int = 2
REVISION_DELAY_DAYS: int = 60
BASE_LEVEL: float = 2.0
NOISE_SCALE: float = 0.6
REVISION_STEPS: Tuple[float, ...] = (-0.3, -0.2, -0.1, 0.1, 0.2, 0.3)
DECISION_HOUR_UTC: int = 12


def _add_months(start: date, months: int) -> date:
    """Return the first day of the month that is `months` after start."""
    total = start.year * 12 + (start.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def _midnight_utc(day: date) -> datetime:
    """Midnight UTC on the given day, as an aware datetime."""
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _build_vintages(seed: int) -> Tuple[List[MacroVintage], List[Tuple[date, date, Optional[date]]]]:
    """Build the synthetic release list and a plan of (obs, first day, revised day).

    Draws are taken in a fixed order from one seeded generator, so the same seed
    gives the same list. A revision is released REVISION_DELAY_DAYS after the first
    release for every REVISION_EVERY-th observation.
    """
    rng = make_rng(seed)
    rows: List[MacroVintage] = []
    plan: List[Tuple[date, date, Optional[date]]] = []
    for idx in range(OBS_COUNT):
        obs_date = _add_months(OBS_START, idx)
        first_value = round(BASE_LEVEL + float(rng.normal(0.0, NOISE_SCALE)), 2)
        first_day = obs_date + timedelta(days=RELEASE_LAG_DAYS)
        rows.append(
            MacroVintage(
                series_id=SERIES_ID,
                obs_date=obs_date,
                vintage_date=first_day,
                release_at=_midnight_utc(first_day),
                value=first_value,
                source_id=SOURCE_ID,
            )
        )
        revised_day: Optional[date] = None
        if idx % REVISION_EVERY == 0:
            step = REVISION_STEPS[int(rng.integers(0, len(REVISION_STEPS)))]
            revised_value = round(first_value + step, 2)
            revised_day = first_day + timedelta(days=REVISION_DELAY_DAYS)
            rows.append(
                MacroVintage(
                    series_id=SERIES_ID,
                    obs_date=obs_date,
                    vintage_date=revised_day,
                    release_at=_midnight_utc(revised_day),
                    value=revised_value,
                    source_id=SOURCE_ID,
                )
            )
        plan.append((obs_date, first_day, revised_day))
    rows.sort(key=lambda v: (v.series_id, v.obs_date, v.vintage_date))
    return rows, plan


def _build_manifest(rows: List[MacroVintage]) -> VintageManifest:
    """Load every release into a VintageManifest. A duplicate key would raise."""
    manifest = VintageManifest()
    for row in rows:
        manifest.add_vintage(row)
    return manifest


def _value_known_at(
    manifest: VintageManifest,
    obs_date: date,
    decision_at: datetime,
) -> Optional[MacroVintage]:
    """Return the vintage with the latest release at or before decision_at.

    Ties on release time go to the larger vintage_date. Returns None when no
    vintage of the observation was released by decision_at.
    """
    best: Optional[MacroVintage] = None
    best_key: Optional[Tuple[datetime, date]] = None
    for vintage in manifest.entries(SERIES_ID):
        if vintage.obs_date != obs_date or vintage.release_at > decision_at:
            continue
        key = (vintage.release_at, vintage.vintage_date)
        if best_key is None or key > best_key:
            best = vintage
            best_key = key
    return best


def _value_newest_ignoring_release(manifest: VintageManifest, obs_date: date) -> Optional[MacroVintage]:
    """Planted fault: return the newest vintage of an observation, ignoring release time."""
    best: Optional[MacroVintage] = None
    for vintage in manifest.entries(SERIES_ID):
        if vintage.obs_date == obs_date:
            best = vintage
    return best


def _cutoff_finding(use: MacroVintage, decision_at: datetime) -> Optional[Finding]:
    """Return a FAIL finding when the used vintage was released after decision_at."""
    if use.release_at <= decision_at:
        return None
    return Finding(
        check_id="macro_vintage_cutoff",
        status=ValidationStatus.FAIL,
        message="value released %s is after decision time %s"
        % (use.release_at.strftime("%Y-%m-%dT%H:%M:%SZ"), decision_at.strftime("%Y-%m-%dT%H:%M:%SZ")),
        subject="%s:%s:%s" % (use.series_id, use.obs_date.isoformat(), use.vintage_date.isoformat()),
    )


def run_macro_proof(seed: int = SYNTHETIC_SEED, inject_lookahead: bool = False) -> ProofResult:
    """Run proof 2 on synthetic macro vintages and return the result.

    Steps:
      1. Build the release list and load it into a VintageManifest.
      2. Check that every release is on or after its observation date.
      3. For each observation, decide at noon UTC on its first release day. If it
         was revised, also decide at noon UTC on the revision day.
      4. Pick the value each decision uses (or the planted newest value when
         inject_lookahead is True), check the release cutoff, and check the
         picked vintage against the expected value.
      5. Record the manifest hash and a state digest over the manifest and the
         decisions.

    The proof passes only when there are no FAIL findings. The metrics include
    the vintage count and the number of cutoff violations.
    """
    # Only a plain int seed gives a reproducible run. None would draw fresh
    # entropy, and a sequence would be read as a different seed.
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise AsOfError("seed must be an int, got %s" % type(seed).__name__)
    if seed < 0:
        raise AsOfError("seed must be non-negative, got %d" % seed)
    rows, plan = _build_vintages(seed)
    manifest = _build_manifest(rows)
    findings: List[Finding] = []

    # Step 2: no release may precede its observation date.
    early = [r for r in rows if r.release_at.date() < r.obs_date]
    for row in early:
        findings.append(
            Finding(
                check_id="macro_vintage_order",
                status=ValidationStatus.FAIL,
                message="release precedes observation date",
                subject="%s:%s" % (row.series_id, row.obs_date.isoformat()),
            )
        )

    # Steps 3 and 4: decisions, value selection, cutoff check.
    decisions: List[Dict[str, object]] = []
    violation_count = 0
    for obs_date, first_day, revised_day in plan:
        times: List[datetime] = [datetime(first_day.year, first_day.month, first_day.day,
                                          DECISION_HOUR_UTC, tzinfo=timezone.utc)]
        if revised_day is not None:
            times.append(datetime(revised_day.year, revised_day.month, revised_day.day,
                                  DECISION_HOUR_UTC, tzinfo=timezone.utc))
        for decision_at in times:
            expected = _value_known_at(manifest, obs_date, decision_at)
            if inject_lookahead:
                used = _value_newest_ignoring_release(manifest, obs_date)
            else:
                used = expected
            if expected is None or used is None:
                findings.append(
                    Finding(
                        check_id="macro_vintage_coverage",
                        status=ValidationStatus.FAIL,
                        message="no vintage available at decision time",
                        subject="%s:%s" % (SERIES_ID, obs_date.isoformat()),
                    )
                )
                continue
            cutoff = _cutoff_finding(used, decision_at)
            if cutoff is not None:
                violation_count += 1
                findings.append(cutoff)
            if used.value != expected.value or used.vintage_date != expected.vintage_date:
                findings.append(
                    Finding(
                        check_id="macro_vintage_pick",
                        status=ValidationStatus.FAIL,
                        message="picked vintage %s differs from the vintage known at decision time %s"
                        % (used.vintage_date.isoformat(), decision_at.strftime("%Y-%m-%dT%H:%M:%SZ")),
                        subject="%s:%s" % (SERIES_ID, obs_date.isoformat()),
                    )
                )
            decisions.append(
                {
                    "decision_at": decision_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "obs_date": obs_date.isoformat(),
                    "vintage_date": used.vintage_date.isoformat(),
                    "release_at": used.release_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "value": used.value,
                }
            )

    # An empty run has no evidence, so it must not pass.
    if not decisions:
        findings.append(
            Finding(
                check_id="macro_vintage_coverage",
                status=ValidationStatus.FAIL,
                message="no decisions were made, so nothing was checked",
                subject=SERIES_ID,
            )
        )

    if violation_count == 0:
        findings.append(
            Finding(
                check_id="macro_vintage_cutoff",
                status=ValidationStatus.PASS,
                message="no value was used before its release",
                subject=SERIES_ID,
            )
        )

    # Step 5: manifest hash and state digest.
    manifest_hash = manifest.manifest_hash()
    state_digest = stable_hash(
        {
            "proof": PROOF_NAME,
            "manifest_hash": manifest_hash,
            "decisions": decisions,
        }
    )
    findings.append(
        Finding(
            check_id="macro_vintage_manifest",
            status=ValidationStatus.PASS,
            message="manifest_hash=%s state_digest=%s" % (manifest_hash, state_digest),
            subject=SERIES_ID,
        )
    )

    vintage_count = len(rows)
    observation_count = len({r.obs_date for r in rows})
    metrics: Dict[str, float] = {
        "vintage_count": float(vintage_count),
        "observation_count": float(observation_count),
        "decision_count": float(len(decisions)),
        "violation_count": float(violation_count),
        "revised_observation_count": float(sum(1 for _, _, rd in plan if rd is not None)),
        "inject_lookahead": 1.0 if inject_lookahead else 0.0,
    }
    passed = not any(f.status is ValidationStatus.FAIL for f in findings)
    return ProofResult(
        proof_name=PROOF_NAME,
        passed=passed,
        findings=tuple(findings),
        metrics=metrics,
    )
