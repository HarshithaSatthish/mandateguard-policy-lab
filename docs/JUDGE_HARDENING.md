# Judge hardening layer

This layer strengthens MandateGuard without changing the frozen nine-arm benchmark or its frozen test suite count.

The additions are intentionally proof-oriented rather than feature-oriented:

1. **Mechanical claims registry** — `bailiff/claims.py`, `scripts/claims_check.py`.
   Required offline claims resolve directly from frozen artifacts. Sanitized Test Mode claims remain `MISSING` until the corresponding files exist; once they exist, contradictory evidence is a release failure rather than a prose footnote.
2. **B2 -> B3 interpreter ablation** — `bailiff/hardening.py`, `scripts/interpreter_ablation.py`.
   It compares the fully deterministic guarded arm with the same guarded boundary plus the bounded interpreter, on the same frozen aggregate. It reports recovery effect and safety effect separately.
3. **Refusal regret** — `bailiff/hardening.py`, `scripts/refusal_regret.py`.
   Every non-provider row is priced on both sides: legitimate recovery forgone and harmful value protected. A refusal is therefore not automatically counted as a win.
4. **Concurrent fallback serialization** — `bailiff/razorpay_testmode.py`, `scripts/hardening_check.py`.
   Same-process calls for the same recovery reference are serialized before the provider boundary. Cross-process safety still relies on the deterministic unique Razorpay `reference_id` plus duplicate/ambiguous-write lookup reconciliation; the code does not claim a distributed lock.
5. **Read-only Provider Proof viewer** — `bailiff/provider_proof.py`, `provider_proof_app.py`.
   The screen only reads sanitized files under `docs/testmode_evidence/`. It loads no credentials, opens no provider connection and exposes no execution control.

## Mandatory hardening gate

```bash
python3 scripts/hardening_check.py
```

The gate verifies:

- required artifact-backed claims;
- B2/B3 safety-bound equivalence in the frozen aggregate;
- refusal-regret accounting conservation;
- a barrier-released two-thread fallback race resolves to one process-local provider mutation and one logical Payment Link;
- if Test Mode artifacts are present, the complete bundle must prove successful fallback, captured-payment RecoveryProof and already-paid zero-write SAFE_BLOCK.

`scripts/release_check.sh` invokes this after the original frozen checks. It is deliberately outside the frozen benchmark suite count, just like RecoveryTruth.

## Judge-facing commands

```bash
python3 scripts/claims_check.py
python3 scripts/interpreter_ablation.py
python3 scripts/refusal_regret.py
python3 scripts/hardening_check.py
streamlit run provider_proof_app.py
```

The ablation and refusal-regret commands are read-only by default. Passing `--write` stores their derived JSON under `outputs/generated/`, which is excluded from the shipped checksum contract. The release gate itself never rewrites frozen benchmark outputs.

## Public design provenance

The public Track 03 field exposed several useful *verification patterns*: claim-to-artifact registries, component ablations, pricing the cost of refusals, concurrent duplicate-execution tests and judge-readable payment-state views. Those patterns informed this hardening pass.

This branch does **not** paste competitor source code. The mechanisms above were implemented against MandateGuard's existing data contracts and RecoveryTruth boundary. That keeps authorship and licensing clean while still adopting good engineering ideas that any serious payment-safety implementation should eventually converge on.

Relevant public projects reviewed during the hardening pass included:

- `vaibhav375/recovery-ledger` — artifact-backed claims discipline and refusal/regret accounting;
- `Shikari-ai/recoup` — component ablation and calibration/evaluation discipline;
- `rushmanthnalluri/AI-Revenue-Recovery` / PulseRecover — payment-action invariants and concurrent duplicate-execution testing;
- public state-resolution/recovery projects such as PayState Bridge — judge-readable payment-state framing.

These are design references, not runtime dependencies or copied modules.
