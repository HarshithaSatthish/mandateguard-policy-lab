# Final verification record

This is the final verification record for the submission. It deliberately separates the **frozen synthetic benchmark** from the **real Razorpay Test Mode provider proof**. The historical archive verification is preserved unchanged in `docs/OFFLINE_VERIFICATION_BASELINE.md`.

## 0. Final observed run

The complete deep gate (`./scripts/verify_all.sh`: full suite, mutation gate with baseline control, release check including full benchmark regeneration, fixture assumption sweep, closing full-manifest checksum verification) was executed from a clean `git clone` checkout, not the working tree.

- Verified tree: commit `791e033` on `cursor/hardening-fixes-a925` (this record file and the manifest line covering it are the only changes after that tree; no code, evidence, or benchmark artifact changed after the verified commit)
- Run timestamp (UTC): 2026-09-03
- Python: 3.12.3; OS/runner: Linux 6.12.94+ x86_64
- pytest: 299 passed / 0 failed / 0 skipped
- mutation check: baseline green, 14/14 caught
- deep verification: PASS, all four stages; `SHA256SUMS.txt` verified after the full workflow
- clean-checkout regeneration: every generated JSON, `outputs/report.md`, `FINDINGS.md`, and `ROBUSTNESS.md` byte-identical to the committed artifacts
- manifest: 116 entries; dataset hash `cbf161e2c06c35682b696e2d3bb50c54b27c35ad28aae7a63e85bb9343ef5b4e`; rules hash `70e2909d26598695f74ae9e4d5c81dabb4c772d1f6d376d6567923cdc8a52506`; 20 seeds, 3 regimes
- guarded-arm record, computed from `outputs/per_seed.json`: 0 independent violations and 0 realized-harm runs across all 120 guarded seed-regime runs

The evidence re-freeze in this branch changed only recorded reason labels and the dataset manifest hash after an adapter labeling fix; every benchmark value was verified identical field-by-field against the prior freeze before the new freeze was accepted.

## 1. Frozen offline proof

The offline MandateGuard benchmark remains the reproducible default and does not call Razorpay APIs.

Verified characteristics:

- **299 tests passed** on the frozen suite.
- **14/14 mutations caught**.
- RecoveryTruth offline acceptance passes: financial truth, exact order binding, provider-read fail-closed behavior, in-flight block, expiring authority, write fence, logical exactly-once behavior, timeout/duplicate reconciliation, ambiguous/malformed post-write handling, and captured-payment proof contract.
- Security regression acceptance passes: authority identity binding, denied-decision reuse prevention, provider identity echo, and webhook fail-closed handling.
- The release checker passes against the frozen sampled/full evidence hashes.
- The fixture assumption sweep completes all **15/15** settings; B3 dominates B2 in **35/45** regime observations under the shipped robustness protocol.
- The hardening layer adds mechanical claims validation, B2→B3 ablation, refusal-regret accounting, concurrent same-reference fallback protection, and a read-only provider-proof contract without changing the frozen benchmark suite; the suite later grew to 299 tests when the ingress replay, non-ASCII signature, out-of-order cancellation, route-level reason gating, and live-credential refusal defects were fixed with regression tests.

The benchmark rupee values remain **synthetic counterfactuals** over a generated ledger. They are not production revenue and are not presented as observed Razorpay recovery numbers.

## 2. Razorpay Test Mode provider proof

A real Razorpay **Test Mode-only** execution was completed with `rzp_test_` credentials. Live credentials remain intentionally refused by the client.

### Recoverable path

Sanitized artifact: `docs/testmode_evidence/testmode_success_execute.json`

Observed result:

- financial truth: `RECOVERABLE`
- execution state: `EXECUTED`
- reason: `FALLBACK_PAYMENT_LINK_CREATED`
- amount: 1000 minor units / INR
- one Standard Payment Link fallback was created
- the receipt binds the decision evidence hash, policy version, order, mandate, reference, pre-write evidence hash, and provider action ID

This is a **Standard Payment Link fallback**, not an AutoPay debit retry.

### Captured-payment postcondition

Sanitized artifact: `docs/testmode_evidence/testmode_recovery_proof.json`

Observed result:

- provider action type: `CREATE_PAYMENT_LINK_FALLBACK`
- an independently fetched Test Mode payment is bound into the proof
- `recovery_verified: true`
- the proof binds pre-write evidence, postcondition evidence, decision identity, original Order, provider action, captured Payment, policy version, and prior-proof linkage

The RecoveryProof/hash chain is **tamper-evident evidence**, not tamper-proof or cryptographically notarised storage.

### Already-paid SAFE_BLOCK

Sanitized artifacts:

- `docs/testmode_evidence/testmode_safe_block.json`
- `docs/testmode_evidence/testmode_safe_block_zero_write.json`

Observed result:

- current Order truth: `PAID`
- RecoveryTruth result: `SAFE_BLOCK_ALREADY_PAID`
- `executed: false`
- Payment Links before: **0**
- Payment Links after: **0**
- zero new fallback writes: `true`

This is the strongest refusal proof in the submission: the system did not merely log a warning after execution; the replacement collection object never existed.

## 3. Hardening gate contract

`scripts/hardening_check.py` is mandatory in the release path and verifies:

1. artifact-backed claims registry;
2. B2→B3 interpreter ablation;
3. refusal-regret accounting;
4. concurrent same-reference fallback serialization;
5. when provider artifacts are present, a complete successful-fallback + RecoveryProof + already-paid zero-write bundle.

A partial `docs/testmode_evidence/` bundle fails the hardening gate rather than being silently treated as proof.

## 4. Claims intentionally not made

The submission does **not** claim:

- production/live-money execution;
- production Razorpay recovery revenue;
- that a Payment Link fallback is an AutoPay retry;
- reproduction of Razorpay's production Intelligent UPI Retry Engine;
- official NPCI status for the project's failure taxonomy or configurable timing assumptions;
- ECE/Brier statistical calibration for B3; B3 is confidence-gated abstention;
- tamper-proof storage;
- distributed exactly-once execution across arbitrary independent processes;
- a complete authenticated human-approval operations console.

## 5. Submission freeze rule

The submitted commit is accepted only if its own GitHub Actions workflow is green and its `SHA256SUMS.txt` matches the shipped-file candidate generated on that exact tree. The Actions status on the final commit is authoritative; this document does not pre-assert the outcome of a future CI run.

No canonical policy arm, guardrail rule, webhook authentication boundary, RecoveryTruth state precedence, or write-fence rule should be changed after this freeze merely to improve a score. A safety-code change requires a new full verification run.
