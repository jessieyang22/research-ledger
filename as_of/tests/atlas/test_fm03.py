"""Failure mode fm03: "Source URL resolves but the claim is absent".

The detection method from the failure-mode note is to search the fetched
source text for the claim's locator or key phrase, and to fail the check (and
flag dependent claims) when it is missing.

All fixtures are synthetic (SYN_ prefix). No network calls are made: the
"fetched" text is an in-memory string standing in for a page that resolves.

Gap found while writing this file: no as_of module compares a claim's key
phrase with the current text of its registered source. SourceRegister stores a
sha256 and checks only that ids are registered. catalyst_claim_links checks
link and registration presence. content_hash can hash files, but nothing wires
that hash back to claims. The planted failure therefore passes every current
check. The gap test below records that behaviour, and the detection test is
marked xfail (strict) so the gap stays visible until a module covers it.
"""

import hashlib
from datetime import datetime, timezone

import pytest

from as_of.catalyst_claim_links import validate_links
from as_of.core import ClaimRecord, SourceRecord, SourceType
from as_of.source_register import SourceRegister

SYN_SOURCE_ID = "SYN_S_FM03"
SYN_CATALYST_ID = "SYN_C_FM03"
SYN_CLAIM_ID = "SYN_CL_FM03"
SYN_LOCATOR = "SYN_LOCATOR/guidance-page"
SYN_KEY_PHRASE = "SYN_KEY_PHRASE: full-year revenue guidance raised"

# Text of the source when it was registered, which contains the key phrase.
SYN_TEXT_AT_REGISTRATION = (
    "SYN_HEADER: synthetic guidance page\n"
    "SYN_BODY: %s to 4.2 billion\n" % SYN_KEY_PHRASE
)

# Text of the same locator after the page changed. It still resolves (the
# page loads) but the documented claim is gone.
SYN_TEXT_AFTER_CHANGE = (
    "SYN_HEADER: synthetic guidance page\n"
    "SYN_BODY: full-year guidance withdrawn pending review\n"
)


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _register_planted_source():
    """Register the source with the hash of the text at registration time."""
    reg = SourceRegister()
    reg.add_source(
        SourceRecord(
            source_id=SYN_SOURCE_ID,
            source_type=SourceType.FILING,
            publisher="SYN_PUBLISHER",
            locator=SYN_LOCATOR,
            retrieved_at=datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc),
            sha256=_sha256_text(SYN_TEXT_AT_REGISTRATION),
            synthetic=True,
        )
    )
    return reg


def _planted_claim():
    return ClaimRecord(
        claim_id=SYN_CLAIM_ID,
        text=SYN_KEY_PHRASE,
        claim_kind="guidance",
        source_ids=(SYN_SOURCE_ID,),
        status="draft",
        section="SYN_SECTION",
    )


def test_primitive_detects_text_change_by_hash():
    """The hash of the fetched text differs from the registered hash.

    This shows the change is visible to a plain sha256 comparison. It does not
    show that any as_of module performs the comparison.
    """
    reg = _register_planted_source()
    registered = reg.get_source(SYN_SOURCE_ID).sha256
    assert _sha256_text(SYN_TEXT_AFTER_CHANGE) != registered
    assert _sha256_text(SYN_TEXT_AT_REGISTRATION) == registered


def test_planted_key_phrase_is_absent_after_change():
    """The planted fixture really does lose the claim's key phrase."""
    assert SYN_KEY_PHRASE in SYN_TEXT_AT_REGISTRATION
    assert SYN_KEY_PHRASE not in SYN_TEXT_AFTER_CHANGE


def test_gap_current_modules_pass_planted_claim():
    """Documents the gap: current link and registration checks pass the planted claim.

    The source id is registered and the claim has a valid catalyst link, so
    validate_links reports nothing even though the cited text no longer
    supports the claim. If a module starts covering fm03, this test will fail
    and should be replaced by the detection test below.
    """
    reg = _register_planted_source()
    claim = _planted_claim()
    links = {SYN_CLAIM_ID: SYN_CATALYST_ID}
    findings = validate_links([claim], links, {SYN_CATALYST_ID}, reg)
    assert findings == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "fm03 gap: no as_of module checks that a claim's key phrase or locator "
        "is present in the current text of its registered source. Only "
        "registration and link presence are checked, so this cannot be detected "
        "yet."
    ),
)
def test_detection_claim_flagged_when_key_phrase_absent():
    """Desired behaviour: the claim is flagged when the cited text lacks its key phrase."""
    reg = _register_planted_source()
    claim = _planted_claim()
    links = {SYN_CLAIM_ID: SYN_CATALYST_ID}
    findings = validate_links([claim], links, {SYN_CATALYST_ID}, reg)
    flagged = [f for f in findings if f.subject == SYN_CLAIM_ID]
    assert flagged, "expected a finding for claim whose key phrase is absent from source text"
