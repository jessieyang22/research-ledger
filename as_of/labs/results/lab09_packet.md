# PM review packet (synthetic, lab09)

## Control header
- state_cutoff: 2026-10-27T00:00:00Z
- evidence_labels: SYNTHETIC; NO_LIVE_DATA; NO_NETWORK
- validation_status: PASS
- review_status: REVIEW_REQUIRED
- packet_type: normal
- packet_hash: 4e0ec79c96aab34922c834f20bf523231bb6f422277fcac80b5b426b0aaa41c4
- path: as_of/labs/results/lab09_packet.md

## Changed sources
- path: as_of/labs/results/lab09_evidence/changed_sources.json
- source SRC_LAB06_RESULT: as_of/labs/results/lab06.json (sha256 ebcea01c019ce908) state=changed
- source SRC_PROOF_EARNINGS: as_of/wf_earnings_reconciliation.py (sha256 7d13fe83ed124a45) state=changed
- source SRC_PROOF_MACRO: as_of/wf_macro_vintage.py (sha256 9064d9651ca848e6) state=changed
- source SRC_PROOF_CATALYST: as_of/wf_catalyst_exception_queue.py (sha256 cefea41ecdc8dc3a) state=changed
- source SRC_PROOF_PORTFOLIO: as_of/wf_portfolio_tieout_factor.py (sha256 c3d7f29935ed0726) state=changed
- source SRC_PROOF_PM_PACKET: as_of/wf_pm_packet.py (sha256 e7244739588b6aff) state=changed
- sources registered: 7; sources unchanged since prior run: 1
- section hashes not unchanged (baseline or changed): portfolio, validation

## Earnings
- path: as_of/labs/results/lab09_evidence/earnings.json
- proof: earnings_reconciliation (earnings reconciliation) passed=True
- checks: 1 run, 0 open; only open items and key metrics are shown here
- key metrics: n_beat=11, n_bridges_with_expected=24, n_inline=7, n_lookahead_rows=0, n_miss=6, n_reports=24, n_unregistered_sources=0
- open: none

## Macro
- path: as_of/labs/results/lab09_evidence/macro.json
- proof: proof_2_macro_vintage (macro vintage) passed=True
- checks: 2 run, 0 open; only open items and key metrics are shown here
- key metrics: decision_count=9, observation_count=6, revised_observation_count=3, vintage_count=9, violation_count=0
- open: none

## Catalyst
- path: as_of/labs/results/lab09_evidence/catalyst.json
- proof: catalyst_exception_queue (catalyst exception queue) passed=True
- checks: 4 run, 2 open; only open items and key metrics are shown here
- key metrics: expected_count=4, filing_occurred_count=2, matched=1, queue_size=4
- open: CLAIM_UNLINKED SYN_CLM_03 (warn): WARN: claim 'SYN_CLM_03' has no catalyst link (see Exceptions)
- open: CHECK_FAILED SYN_CLM_02 (warn): WARN: claim 'SYN_CLM_02' links to unknown catalyst 'SYN_CAT_99' (see Exceptions)

## Portfolio
- path: as_of/labs/results/lab09_evidence/portfolio.json
- proof: proof4_portfolio_tieout_factor (portfolio tie-out and factor) passed=True
- checks: 4 run, 1 open; only open items and key metrics are shown here
- key metrics: beta_max_abs_error=7.77156e-16, book_value=165797, hard_fail_count=0, tieout_break_count=1, tieout_matched=2
- open: tieout.break SYN_A (fail): [block] book_qty=416.0 custodian_qty=666.0 delta=-250.0 (see Exceptions)

## Exceptions
- path: as_of/labs/results/lab09_evidence/exceptions.json
- open exceptions: 4 (each carries its smallest repair; no repair was applied)
- exception: CLAIM_UNLINKED subject=SYN_CLM_03 status=warn source=catalyst message=WARN: claim 'SYN_CLM_03' has no catalyst link | repair: link the claim to a catalyst id in the register, or record why it has no catalyst link
- exception: CHECK_FAILED subject=SYN_CLM_02 status=warn source=catalyst message=WARN: claim 'SYN_CLM_02' links to unknown catalyst 'SYN_CAT_99' | repair: repoint the claim's catalyst link to a registered catalyst id, or remove the link
- exception: tieout.break subject=SYN_A status=fail source=portfolio message=[block] book_qty=416.0 custodian_qty=666.0 delta=-250.0 | repair: reconcile the quantity gap named in the message against the booking or custodian record
- exception: claim_open subject=SYN_CL_08 status=warn source=pm_packet message=claim status is 'open' | repair: finish the claim review and set its status, so the claim is no longer open

## Validation
- path: as_of/labs/results/lab09_evidence/validation.json
- validation_status: PASS (all 11 inputs in INPUT_SPEC passed)
- lab verifier lab01 (routing matrix): passed=True exit_code=0
- lab verifier lab02 (clock and field dictionary): passed=True exit_code=0
- lab verifier lab03 (freeze and checkpoint): passed=True exit_code=0
- lab verifier lab05 (earnings reconciliation and revision): passed=True exit_code=0
- lab verifier lab06 (macro vintage cutoff): passed=True exit_code=0
- input proof:earnings: passed=True proof=earnings_reconciliation passed=True findings=1
- input proof:macro: passed=True proof=proof_2_macro_vintage passed=True findings=2
- input proof:catalyst: passed=True proof=catalyst_exception_queue passed=True findings=4
- input proof:portfolio: passed=True proof=proof4_portfolio_tieout_factor passed=True findings=4
- input proof:pm_packet: passed=True proof=pm_packet passed=True findings=3
- input protected_hash:lab06_input: passed=True current=092afe4440af1074 recorded=092afe4440af1074
- coverage gap: no lab verifier for labs 4, 7 and 8 under as_of/labs
- coverage gap: lab10 has data files under as_of/labs/data but no lab script
- coverage gap: no packet-build prompt file in as_of; INPUT_SPEC was used
- sampling rule: one seeded draw per class (seed SYNTHETIC_SEED + class index) over items sorted by a stable key; plus the risk-based review above
- risk-based rule: every WARN or FAIL proof item is reviewed and listed under Exceptions
- sample reported_value: item=SYN_T01|eps|2025Q4 path=as_of/earnings_fixture.py result=PASS strength=reproducibility only: the same fixture generator is run a second time detail=reported_value=3.3563; matching rows in a second fixture build=1; value equal: True
- sample estimate_change: item=SYN_T01|revenue|2025Q1 path=as_of/earnings_fixture.py result=PASS strength=structural: no tied knowledge times inside the estimate group detail=3 rows; first=857.9889 last=893.7249 change=35.736; knowledge times distinct: True
- sample macro_vintage: item=SYN_GDP|2025-07-01|2025-07-31 path=as_of/macro_fixture.py result=PASS strength=rule check: newest vintage released by the decision time, on the fixture detail=value=0.74; newest vintage released by decision time 2025-08-01T00:00:00+00:00 is 2025-07-31
- sample catalyst_delta: item=CLAIM_UNLINKED|SYN_CLM_03 path=as_of/catalyst_fixture.py result=PASS strength=proof output against fixture expectations (not an independent recount) detail=subject in expected exceptions: True; open list matches expected multiset: True
- sample portfolio_total: item=book_value path=as_of/wf_portfolio_tieout_factor.py result=PASS strength=independent recount: book value re-summed from positions and close prices detail=proof book_value=165797.3039; independent re-sum=165797.3039; within tolerance: True
- sample protected_hash: item=lab06_macro_vintages.csv path=as_of/labs/data/lab06_macro_vintages.csv result=PASS strength=same comparison as the input validator, not an independent check detail=current=092afe4440af1074 recorded=092afe4440af1074
- negative control reported_value: planted=rebuilt value +1.0 and empty rebuild rejected=True detail=judge rejects both: True
- negative control estimate_change: planted=two rows with one knowledge time rejected=True detail=judge rejects: True
- negative control macro_vintage: planted=oldest vintage picked while a newer one is released rejected=True detail=judge rejects: True
- negative control catalyst_delta: planted=unexpected subject; expected subject with open list mismatch rejected=True detail=judge rejects both: True
- negative control portfolio_total: planted=proof value +1.0; one close +1.0 in the recount rejected=True detail=judge rejects both: True
- negative control protected_hash: planted=current hash replaced by zeros; recorded value missing rejected=True detail=judge rejects both: True

## Decision
- path: as_of/labs/signoffs/lab09_signoff.json
- decision: NONE_RECORDED
- review_status: REVIEW_REQUIRED
- note: this lab does not record approval; a named human reviewer does
