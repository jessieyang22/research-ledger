"""Tests for as_of.claim_records. All fixtures are synthetic and use the SYN_ prefix.
"""

import pytest

from as_of.claim_records import (
    CHECK_CLEAN,
    CHECK_EXPERT_VERIFIED,
    CHECK_FACT_SOURCE,
    CHECK_KIND,
    CHECK_STATUS,
    CLAIM_KINDS,
    CLAIM_STATUSES,
    make_claim,
    status_counts,
    validate_claim,
)
from as_of.core import ClaimRecord, ValidationStatus


def _fails(findings):
    return [f for f in findings if f.status == ValidationStatus.FAIL]


def _check_ids(findings):
    return [f.check_id for f in findings]


# ---- acceptance tests -----------------------------------------------------


def test_fact_with_no_source_ids_is_fail():
    rec = make_claim("SYN_C1", "SYN_TKR revenue rose", "fact", [])
    findings = validate_claim(rec)
    fails = _fails(findings)
    assert len(fails) == 1
    assert fails[0].check_id == CHECK_FACT_SOURCE
    assert fails[0].subject == "SYN_C1"


def test_expert_input_marked_verified_is_fail():
    rec = make_claim(
        "SYN_C2", "SYN_EXPERT said margins hold", "expert_input", ["SYN_S1"],
        status="verified",
    )
    findings = validate_claim(rec)
    fails = _fails(findings)
    assert len(fails) == 1
    assert fails[0].check_id == CHECK_EXPERT_VERIFIED


def test_unknown_claim_kind_is_fail():
    rec = make_claim("SYN_C3", "SYN_TKR guidance", "rumor", ["SYN_S1"])
    findings = validate_claim(rec)
    fails = _fails(findings)
    assert len(fails) == 1
    assert fails[0].check_id == CHECK_KIND
    assert "rumor" in fails[0].message


def test_status_counts_sums_to_number_of_claims():
    claims = [
        make_claim("SYN_A", "t", "fact", ["SYN_S1"], status="verified"),
        make_claim("SYN_B", "t", "estimate", ["SYN_S1"]),
        make_claim("SYN_C", "t", "opinion", [], status="rejected"),
        make_claim("SYN_D", "t", "expert_input", ["SYN_S2"], status="unverified"),
        make_claim("SYN_E", "t", "fact", ["SYN_S3"], status="bogus"),
    ]
    counts = status_counts(claims)
    assert sum(counts.values()) == len(claims)
    assert counts["verified"] == 1
    assert counts["unverified"] == 2
    assert counts["rejected"] == 1
    assert counts["bogus"] == 1


# ---- edge cases -----------------------------------------------------------


def test_clean_fact_gets_single_pass_finding():
    rec = make_claim("SYN_OK", "SYN_TKR 10-K filed", "fact", ["SYN_S1"])
    findings = validate_claim(rec)
    assert len(findings) == 1
    assert findings[0].status == ValidationStatus.PASS
    assert findings[0].check_id == CHECK_CLEAN


def test_every_claim_produces_at_least_one_finding():
    rec = make_claim("SYN_X", "opinion", "opinion", [])
    assert len(validate_claim(rec)) >= 1


def test_blank_source_ids_do_not_count_as_source():
    rec = make_claim("SYN_BLANK", "t", "fact", ["", "   "])
    fails = _fails(validate_claim(rec))
    assert [f.check_id for f in fails] == [CHECK_FACT_SOURCE]


def test_fact_with_one_real_source_among_blanks_passes_source_rule():
    rec = make_claim("SYN_MIX", "t", "fact", ["  ", "SYN_S9"])
    assert CHECK_FACT_SOURCE not in _check_ids(validate_claim(rec))


def test_non_fact_without_sources_is_not_failed_for_missing_source():
    rec = make_claim("SYN_OP", "SYN_TKR looks cheap", "opinion", [])
    assert CHECK_FACT_SOURCE not in _check_ids(validate_claim(rec))
    assert validate_claim(rec)[0].status == ValidationStatus.PASS


def test_expert_input_rejected_or_unverified_is_not_failed():
    for status in ("unverified", "rejected"):
        rec = make_claim(
            "SYN_E", "SYN_EXPERT call note", "expert_input", ["SYN_S1"],
            status=status,
        )
        assert CHECK_EXPERT_VERIFIED not in _check_ids(validate_claim(rec))


def test_verified_fact_is_not_expert_failure():
    rec = make_claim("SYN_F", "t", "fact", ["SYN_S1"], status="verified")
    assert validate_claim(rec)[0].status == ValidationStatus.PASS


def test_unknown_status_is_fail():
    rec = make_claim("SYN_ST", "t", "estimate", ["SYN_S1"], status="maybe")
    fails = _fails(validate_claim(rec))
    assert [f.check_id for f in fails] == [CHECK_STATUS]


def test_unknown_kind_and_status_both_reported():
    rec = make_claim("SYN_BOTH", "t", "rumor", ["SYN_S1"], status="maybe")
    ids = _check_ids(_fails(validate_claim(rec)))
    assert ids == [CHECK_KIND, CHECK_STATUS]


def test_fact_no_source_and_unknown_status_reports_two_fails():
    rec = make_claim("SYN_TWO", "t", "fact", [], status="maybe")
    ids = _check_ids(_fails(validate_claim(rec)))
    assert ids == [CHECK_STATUS, CHECK_FACT_SOURCE]


def test_make_claim_stores_values_and_tuples_source_ids():
    sources = ["SYN_S1", "SYN_S2"]
    rec = make_claim("SYN_M", "text", "fact", sources, section="SYN_SEC")
    assert isinstance(rec, ClaimRecord)
    assert rec.source_ids == ("SYN_S1", "SYN_S2")
    assert rec.status == "unverified"
    assert rec.section == "SYN_SEC"
    sources.append("SYN_S3")
    assert rec.source_ids == ("SYN_S1", "SYN_S2")


def test_make_claim_does_not_reject_bad_values():
    rec = make_claim("SYN_BAD", "t", "nope", [], status="nope")
    assert rec.claim_kind == "nope"
    assert rec.status == "nope"


def test_status_counts_empty_list_has_zero_for_each_allowed_status():
    counts = status_counts([])
    assert counts == {status: 0 for status in CLAIM_STATUSES}
    assert sum(counts.values()) == 0


def test_status_counts_keys_include_all_allowed_statuses():
    counts = status_counts([make_claim("SYN_Q", "t", "fact", ["SYN_S1"])])
    for status in CLAIM_STATUSES:
        assert status in counts
    assert counts["unverified"] == 1
    assert counts["verified"] == 0


def test_vocabularies_are_as_documented():
    assert CLAIM_KINDS == ("fact", "estimate", "opinion", "expert_input")
    assert CLAIM_STATUSES == ("unverified", "verified", "rejected")


@pytest.mark.parametrize("kind", CLAIM_KINDS)
def test_each_allowed_kind_is_accepted(kind):
    rec = make_claim("SYN_K", "t", kind, ["SYN_S1"])
    assert all(f.status == ValidationStatus.PASS for f in validate_claim(rec))
