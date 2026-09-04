# FINAL_VERIFICATION — Submission Freeze Template

> Fill this file only after the final offline freeze **and** the Razorpay Test Mode evidence run. Do not copy numbers forward from an older run. Every statement below must point to a reproducible command or preserved artifact.

## 1. Source freeze

- Branch: `submission-finalization`
- Commit SHA: `TO_FILL_AFTER_FREEZE`
- Freeze timestamp (UTC): `TO_FILL`
- Python: `TO_FILL`
- OS/runner: `TO_FILL`

No policy/guardrail changes are permitted after this freeze unless a verification gate fails. Any code change requires a new checksum manifest and a new verification record.

## 2. Offline proof

Run in a clean environment:

```bash
pip install -e '.[test]'
./scripts/test.sh
python3 scripts/mutation_check.py
python3 scripts/recoverytruth_check.py
python3 scripts/demo60.py
./scripts/verify_all.sh
```

Record exact observed results:

- pytest: `TO_FILL` passed / `TO_FILL` failed / `TO_FILL` skipped
- mutation check: `TO_FILL/TO_FILL` caught
- RecoveryTruth acceptance: `PASS/FAIL`
- 60-second demo: `PASS/FAIL`
- deep verification: `PASS/FAIL`

Expected historical baseline before the final freeze is 299 tests and 14/14 mutations, but this document must record the **final observed run**, not assume those numbers.

## 3. Judge demo proof

For `scripts/demo60.py`, record the exact observed claims:

- forged webhook rejected: `PASS/FAIL`
- permitted retry provider calls: `TO_FILL`
- B3 abstain provider calls: `TO_FILL`
- timeout state: `TO_FILL`
- audit verification before tamper: `TO_FILL`
- audit verification after tamper: `TO_FILL`

The provider in this demo is the local simulator.

## 4. Frozen benchmark scope

The benchmark evaluates nine arms on the same frozen synthetic scheduled UPI AutoPay failure ledger:

`B0, B1, B1.5, RZP, B2.25, B2.5, B2.75, B2, B3`

All rupee values are synthetic counterfactual benchmark values. They are not observed Razorpay merchant revenue.

`RZP` is a fixed temporal reference derived from Razorpay's documented **card** retry schedule. It is not Razorpay Intelligent Retry and does not reproduce Razorpay's production UPI decision logic.

## 5. Razorpay Test Mode proof

Credentials used: Razorpay **Test Mode only** (`rzp_test_...`). No production credentials are permitted by the client.

### 5.1 Successful fallback

Artifact: `TO_FILL`

- Test Mode Order ID: `TO_FILL_OR_REDACTED`
- execution state: `TO_FILL`
- financial truth before write: `TO_FILL`
- reason code: `TO_FILL`
- provider action type: `CREATE_PAYMENT_LINK_FALLBACK`
- Test Mode Payment Link ID: `TO_FILL_OR_REDACTED`
- exact amount/currency: `TO_FILL`
- provider write count/evidence: `TO_FILL`

This is a Standard Payment Link customer-initiated fallback. It is **not** an AutoPay retry.

### 5.2 Safe block

Artifact: `TO_FILL`

- provider truth: `PAID` or `IN_FLIGHT`
- reason code: `SAFE_BLOCK_ALREADY_PAID` or `SAFE_BLOCK_IN_FLIGHT`
- execution state: `NOT_EXECUTED`
- fallback provider write: `0`
- provider state evidence: `TO_FILL`

### 5.3 RecoveryProof

Artifact: `TO_FILL`

- recovery verified: `true/false`
- case ID: `TO_FILL_OR_REDACTED`
- decision evidence hash: `TO_FILL`
- original Order ID binding: `TO_FILL_OR_REDACTED`
- mandate binding: `TO_FILL_OR_REDACTED`
- Payment Link ID binding: `TO_FILL_OR_REDACTED`
- captured Payment ID binding: `TO_FILL_OR_REDACTED`
- amount/currency binding: `TO_FILL`
- postcondition evidence hash: `TO_FILL`
- RecoveryProof hash: `TO_FILL`

The proof hash/hash chain is **tamper-evident evidence**. It is not described as tamper-proof storage.

## 6. Checksum freeze

After all final submission evidence/docs are present and redacted:

```bash
python3 scripts/make_checksum_manifest.py > SHA256SUMS.txt
sha256sum -c SHA256SUMS.txt
```

Record:

- manifest entries: `TO_FILL`
- checksum verification: `TO_FILL/TO_FILL OK`
- manifest SHA-256: `TO_FILL`

No file covered by the manifest may change after this record without regenerating the manifest and rerunning verification.

## 7. Explicit non-claims

This submission does **not** claim:

- synthetic recovered rupees are production revenue;
- Standard Payment Link fallback is an AutoPay debit retry;
- `RZP` represents current Razorpay Intelligent Retry;
- MandateGuard has benchmarked Razorpay production decision logic;
- a hash chain makes evidence impossible to alter;
- Test Mode execution proves production readiness;
- the operator-supplied decision evidence hash is a cryptographically authenticated external capability token.

## 8. Final judge sentence

**Razorpay already recovers. MandateGuard is the harness in front of that engine: before a retry configuration goes live, prove what it recovers, what it refuses, and that every refusal made zero provider calls.**

## 9. Final status

Until Test Mode artifacts actually exist, record Test Mode status as **WAITING_FOR_TEST_MODE_CREDENTIALS**. Do not fill fabricated Payment IDs or receipts.

- Offline proof frozen: `YES/NO`
- Razorpay Test Mode status: `WAITING_FOR_TEST_MODE_CREDENTIALS` or captured
- Razorpay Test Mode successful fallback captured: `YES/NO`
- real safe block captured: `YES/NO`
- real RecoveryProof captured: `YES/NO`
- checksums regenerated after final artifacts: `YES/NO`
- submission clone-clean: `YES/NO`

**Submission ready:** `YES/NO`
