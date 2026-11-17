"""Failure mode fm38: reviewer sign-off is ceremonial.

The reviewer approves the packet without checking the underlying paths or
values, so the sign-off carries no substance. The expected detection is to
require a recorded sample review: the reviewer names which sampled claims were
checked against their sources, and the run is blocked when that record is
missing or does not cover the sample.

What the existing modules can and cannot see:

- controls_checklist.missing_evidence: flags a reviewer_signoff control with no
  evidence reference. It catches an absent sign-off, but it only checks that a
  non-empty string is present. It does not read the string.
- readiness_record.build_readiness: blocks an item whose passed flag is False,
  and blocks an empty item list. A sign-off recorded as passed=True with any
  non-empty evidence_ref is a go.
- claim_sampling.sample_claims and sampling_log: deterministic, reproducible
  sample of claim ids. The log gives a reviewer a fixed list of claims to check,
  and its sample_hash changes when the sample changes. Nothing requires a
  reviewer record to cover that list.

Passing tests below show the existing detections: an absent sign-off, a failed
sign-off, and a sample that is pinned by its log. The strict xfail tests show
the gap: no module reads a sign-off's substance or compares a review record
with the sampled claim ids.

Fixtures use the SYN_ prefix and are built in memory. No I/O, no network.
"""

import pytest

from as_of.claim_sampling import sample_claims, sampling_log
from as_of.controls_checklist import CONTROL_CATALOG, missing_evidence
from as_of.core import ClaimRecord, ReadinessItem, ValidationStatus
from as_of.readiness_record import build_readiness

SIGNOFF_CONTROL = "ctl_pm_packet_reviewed"
SAMPLE_N = 3
SAMPLE_SEED = 7


def _population():
    """Twelve synthetic claims in three claim kinds, four each."""
    kinds = ("SYN_kind_a", "SYN_kind_b", "SYN_kind_c")
    claims = []
    for k_index, kind in enumerate(kinds):
        for i in range(4):
            claims.append(
                ClaimRecord(
                    claim_id="SYN_claim_%02d" % (k_index * 4 + i),
                    text="SYN_text %d" % (k_index * 4 + i),
                    claim_kind=kind,
                    source_ids=("SYN_src_%02d" % (k_index * 4 + i),),
                    status="draft",
                    section="SYN_section",
                )
            )
    return claims


def _all_controls_evidenced_except_signoff():
    evidence = {spec.control_id: "SYN_ref_%s" % spec.control_id for spec in CONTROL_CATALOG}
    evidence.pop(SIGNOFF_CONTROL)
    return evidence


def test_absent_reviewer_signoff_is_flagged():
    """Detection: with no sign-off evidence at all, the control gets a FAIL finding."""
    findings = missing_evidence(_all_controls_evidenced_except_signoff())
    by_subject = {f.subject: f for f in findings}
    assert SIGNOFF_CONTROL in by_subject
    assert by_subject[SIGNOFF_CONTROL].status is ValidationStatus.FAIL
    assert "reviewer_signoff" in by_subject[SIGNOFF_CONTROL].message


def test_failed_reviewer_item_blocks_readiness():
    """Detection: a sign-off item recorded as not passed makes the run no-go."""
    items = [
        ReadinessItem(item_id="SYN_tieout", passed=True, evidence_ref="SYN_ref_tieout"),
        ReadinessItem(item_id="SYN_pm_packet_reviewed", passed=False, evidence_ref="SYN_none"),
    ]
    rec = build_readiness(items, [], open_incident_count=0)
    assert rec["go"] is False
    assert any("SYN_pm_packet_reviewed" in reason for reason in rec["blocking"])


def test_sample_log_pins_the_claims_a_reviewer_must_check():
    """Substrate: the sample log lists the claim ids, and a changed sample changes its hash."""
    population = _population()
    sample = sample_claims(population, SAMPLE_N, seed=SAMPLE_SEED)
    log = sampling_log(sample, seed=SAMPLE_SEED, population_size=len(population))
    assert log["sample_size"] == SAMPLE_N
    assert log["claim_ids"] == sorted(c.claim_id for c in sample)

    swapped_ids = {c.claim_id for c in sample}
    unsampled = next(c for c in population if c.claim_id not in swapped_ids)
    altered = list(sample[:-1]) + [unsampled]
    altered_log = sampling_log(altered, seed=SAMPLE_SEED, population_size=len(population))
    assert altered_log["sample_hash"] != log["sample_hash"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm38 gap: controls_checklist.missing_evidence only checks that the "
        "reviewer_signoff reference is a non-empty string. A bare label such as "
        "'SYN_approved' with no record of which sampled claims were checked passes "
        "silently. No module reads a sign-off's substance."
    ),
)
def test_bare_label_signoff_without_sample_review_is_flagged():
    """Expected control: a sign-off label with no sample review record gets a FAIL."""
    evidence = _all_controls_evidenced_except_signoff()
    evidence[SIGNOFF_CONTROL] = "SYN_approved"
    findings = missing_evidence(evidence)
    flagged = [f for f in findings if f.subject == SIGNOFF_CONTROL]
    assert flagged, "a ceremonial sign-off label was accepted as reviewer evidence"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm38 gap: build_readiness has no field for a sample review. An item that is "
        "passed=True with any non-empty evidence_ref makes the run a go, even when the "
        "sampled claims were never checked against their sources. Expected control: "
        "the go is blocked until a review record covers the sampled claim ids."
    ),
)
def test_signoff_without_sample_coverage_blocks_readiness():
    """Expected control: a passed sign-off that does not cover the sample is no-go."""
    population = _population()
    sample = sample_claims(population, SAMPLE_N, seed=SAMPLE_SEED)
    sampled_ids = sorted(c.claim_id for c in sample)
    assert sampled_ids, "the sample must not be empty for this check"
    items = [
        ReadinessItem(item_id="SYN_tieout", passed=True, evidence_ref="SYN_ref_tieout"),
        # The reviewer item passes, but its reference does not name any sampled claim.
        ReadinessItem(item_id=SIGNOFF_CONTROL, passed=True, evidence_ref="SYN_signed"),
    ]
    rec = build_readiness(items, [], open_incident_count=0)
    assert rec["go"] is False, "a sign-off with no sample coverage was accepted as go"
