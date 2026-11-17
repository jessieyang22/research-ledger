# wf_pm_packet: PM review packet, end to end

## What it does
`as_of/wf_pm_packet.py` (proof 5) builds a synthetic PM review packet from eight claims and four `SYN_` sources. It checks each claim for a known source and for expert input kept out of slide sections, draws a seeded spot-check sample, assembles the packet, diffs it against the prior clean build, and renders Markdown with the packet hash. No file I/O, network, or trading logic.

## Design idea
- A PM should read one fixed-order packet whose claims trace to sources.
- Expert-call input stays off slides until it is checked.
- A packet can be compared with the last approved one, so changes are visible.

## API
- `build_pm_packet(seed=SYNTHETIC_SEED, inject_expert_claim_on_slide=False) -> dict`: keys `packet`, `prior_packet`, `delta`, `markdown`, `findings`, `passed`, `claim_count`, `sample_count`.
- `run_pm_packet_proof(seed=SYNTHETIC_SEED, inject_expert_claim_on_slide=False) -> ProofResult`.
- `diff_packets(prev, curr) -> dict` and `delta_is_empty(delta) -> bool`.
- `render_pm_packet_markdown(packet, delta=None) -> str`.
- Seed must be a non-negative int (bools rejected). The injection flag must be a bool.

Example (run with the repo root on `PYTHONPATH`; output verified):
```python
from as_of.wf_pm_packet import run_pm_packet_proof, build_pm_packet

ok = run_pm_packet_proof()
print(ok.passed, ok.metrics["claims_total"], ok.metrics["claims_sampled"], ok.metrics["fail_findings"])
# True 8.0 3.0 0.0

bad = build_pm_packet(20261027, inject_expert_claim_on_slide=True)
print(bad["passed"], bad["delta"]["changed_sections"])
# False ['open_items', 'thesis']
print([f["check_id"] for f in bad["delta"]["findings_new"]])
# ['expert_input_on_slide']
```

## Known limits
- Synthetic data only; claims and sources are fixed templates.
- The only planted fault is expert input in a slide section. Other error types are not tested.
- The spot-check "sample" only confirms that sampled claims have a source. It does not re-verify the values.
- A claim with a known source is not checked against the source content.
- The prior packet is always rebuilt from the same seed, not loaded from an approved file.
