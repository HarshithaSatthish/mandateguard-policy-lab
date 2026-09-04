# Submission Readiness — evidence, not optimism

This file is the current submission-status source of truth. **VERIFIED** means the repository has executable evidence or recorded provider-backed evidence for the claim. Synthetic benchmark results and Razorpay Test Mode evidence are deliberately kept separate.

## Current status

**Offline submission path: VERIFIED AND FROZEN.**

The frozen MandateGuard benchmark remains the same 299-test, 14/14-mutation proof. Its rupee values are synthetic counterfactuals over a generated ledger and do not claim production revenue. The historical archive verification is preserved in `docs/OFFLINE_VERIFICATION_BASELINE.md`.

**Credentialed provider path: VERIFIED IN RAZORPAY TEST MODE.**

The repository now contains a sanitized four-artifact Test Mode bundle in `docs/testmode_evidence/`:

- `testmode_success_execute.json` — fresh provider state resolved `RECOVERABLE`, the write fence remained valid, and one Standard Payment Link fallback was created.
- `testmode_recovery_proof.json` — the independently fetched captured payment satisfied the postcondition and produced a bound `RecoveryProof` with `recovery_verified: true`.
- `testmode_safe_block.json` — an already-paid Order resolved `PAID` and returned `SAFE_BLOCK_ALREADY_PAID` with `executed: false`.
- `testmode_safe_block_zero_write.json` — the same already-paid case proves Payment Links remained `0 -> 0`, so no replacement collection object was created.

The hardening gate treats a partial provider bundle as a release failure. When these artifacts are present it verifies successful fallback, captured-payment RecoveryProof, and already-paid zero-write proof.

## RecoveryTruth implementation matrix

| Capability | Status | Evidence / boundary |
|---|---|---|
| Fresh current financial truth states | VERIFIED | `bailiff/recovery_truth.py`, `scripts/recoverytruth_check.py` |
| Stale failure loses to fresh captured state | VERIFIED | current provider truth resolves `PAID` |
| In-flight payment blocks parallel collection | VERIFIED OFFLINE | `created`, `authorized`, `pending` => `IN_FLIGHT` |
| Exact Razorpay Order binding | VERIFIED TEST MODE | provider-backed Order/payment evidence |
| Exact Order-payment identity binding | VERIFIED TEST MODE | exact Order/payment IDs in captured evidence |
| Razorpay Order `paid` as independent stop signal | VERIFIED TEST MODE | `SAFE_BLOCK_ALREADY_PAID` evidence |
| Immediate pre-write provider reread | VERIFIED | two-read RecoveryTruth write boundary |
| State-change SAFE_BLOCK | VERIFIED | offline TOCTOU attacks + real already-paid block |
| Expiring decision authority | VERIFIED | decision/action/amount/expiry bound and rechecked at write |
| Live credentials refused | VERIFIED | non-`rzp_test_` credentials are rejected |
| Standard Payment Link fallback | VERIFIED TEST MODE | `testmode_success_execute.json` |
| Ambiguous/duplicate write reconciliation | VERIFIED CONTRACT | deterministic reference + timeout/duplicate acceptance checks |
| Captured-payment postcondition | VERIFIED TEST MODE | independent captured Payment read |
| RecoveryProof | VERIFIED TEST MODE | `testmode_recovery_proof.json` |
| Concurrent same-reference fallback serialization | VERIFIED | `scripts/hardening_check.py` |
| Claims registry / refusal-regret / B2→B3 ablation | VERIFIED | mandatory hardening gate |
| Production AutoPay debit retry | NOT CLAIMED | fallback is a customer-initiated Standard Payment Link, not a mandate debit retry |
| Production/live money execution | NOT CLAIMED | live keys are intentionally refused |

## Submission-critical proof

The strongest provider-backed demonstration is intentionally two-sided:

1. **Allowed path:** failed current attempts -> `RECOVERABLE` -> pre-write reread -> one Test Mode Payment Link -> captured Test Mode payment -> `RecoveryProof`.
2. **Refusal path:** already-paid Order -> `PAID` -> `SAFE_BLOCK_ALREADY_PAID` -> Payment Links `0 -> 0`.

That is the product claim: recovery is not only about choosing an action; it is also about proving when an action must not exist.

## Frozen safety boundary

Do not change canonical policy arms, `guardrails.py`, webhook HMAC verification, RecoveryTruth state precedence/write fence, or benchmark rule values merely to improve a score. A safety-code change invalidates the freeze and requires a new full verification run.

OpenEvolve experiments remain outside the submission safety boundary and are not part of the final evidence claim unless separately executed and verified.

## Judge-facing wording

> **Razorpay already recovers payments. RecoveryTruth establishes authoritative provider truth immediately before the money-changing write and independently proves the exact postcondition afterward — for the action and for the refusal.**

Do not claim that other entries merely consume stale webhook truth; late-stage entries in this field also reason about conflicting sources and reconciliation. The defensible distinction is narrower and provable: the pre-write fence re-reads the provider at the write boundary, the postcondition is verified by an independent fetch of the exact captured Payment, and the refusal side carries its own provider-backed proof. Say it with the evidence beside it: `docs/testmode_evidence/testmode_safe_block_zero_write.json` shows the already-paid case left Payment Links at `0 -> 0` — the recovery object provably never existed.

Keep these limits explicit:

- benchmark rupees are synthetic counterfactuals;
- the Test Mode Standard Payment Link is not an AutoPay retry;
- the `RZP` benchmark arm is a fixed card-derived temporal reference, not Razorpay Intelligent UPI Retry;
- B3 is confidence-gated abstention, not a claim of ECE/Brier statistical calibration;
- the audit chain and RecoveryProof are tamper-evident evidence, not tamper-proof storage;
- no production/live Razorpay transaction is claimed.

## Current submission status

- Offline 299-test proof: **GREEN / FROZEN**
- Mutation proof: **14/14 CAUGHT**
- RecoveryTruth acceptance: **GREEN**
- Security regression acceptance: **GREEN**
- Claims / ablation / refusal-regret / concurrency hardening: **GREEN**
- Razorpay Test Mode fallback: **VERIFIED**
- Captured-payment RecoveryProof: **VERIFIED**
- Already-paid SAFE_BLOCK: **VERIFIED**
- Zero-new-fallback proof: **VERIFIED (`0 -> 0`)**
- Sanitized provider evidence bundle: **PRESENT**
- Production/live money execution: **NOT CLAIMED**

The final repository checksum and GitHub Actions run remain mechanical release gates: the exact commit is submission-ready only when those gates are green. This document does not pre-assert a future CI result; the Actions status on the submitted commit is authoritative.
