# Razorpay Test Mode Evidence Runbook

This runbook is for the one real provider proof required before submission. It uses **Razorpay Test Mode only** (real Razorpay Test Mode reads + Standard Payment Link fallback, not AutoPay retry, not the offline simulator). Never put credentials in the repository, screenshots, shell history pasted into issues, or verification documents. Current status: **VERIFIED_TEST_MODE_EVIDENCE_CAPTURED**. Do not invent receipts, Payment IDs, or RecoveryProof.

## Required outputs

The final submission should preserve three redacted artifacts:

1. `testmode_success_execute.json` — one successful Standard Payment Link fallback receipt.
2. `testmode_safe_block.json` — one already-paid or in-flight `SAFE_BLOCK_*` result with no fallback write.
3. `testmode_recovery_proof.json` — one independently verified captured-payment `RecoveryProof`.

These artifacts are evidence of Test Mode behavior. They are not production revenue evidence and the Payment Link is not an AutoPay retry.

## 0. Local setup

Use a clean checkout of the final submission branch.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
```

Set credentials only in the shell/session or a local ignored `.env` loader:

```bash
export RAZORPAY_TEST_KEY_ID='rzp_test_...'
export RAZORPAY_TEST_KEY_SECRET='...'
```

The client intentionally rejects non-`rzp_test_` key IDs.

## 1. Prepare one recoverable Test Mode Order

Use a Test Mode Order with:

- exact INR amount known in paise;
- at least one failed payment attempt;
- no captured/authorized/pending payment currently attached;
- an active merchant-side mandate context for the demo;
- no production identifiers.

Record the Test Mode Order ID (`order_...`) and amount. Do not commit credentials.

Prepare a decision evidence hash from the exact MandateGuard decision/audit record you are demonstrating. The current CLI treats this as evidence binding supplied by the operator; it is not a cryptographic external capability token.

## 2. Execute the customer-initiated fallback

Example:

```bash
python3 scripts/razorpay_testmode_demo.py execute \
  --order-id order_TEST \
  --case-id case_testmode_success_001 \
  --mandate-id mandate_testmode_001 \
  --mandate-status active \
  --amount-minor 1000 \
  --max-authorized-amount-minor 1000 \
  --decision-id decision_testmode_001 \
  --decision-evidence-hash YOUR_REAL_DECISION_EVIDENCE_HASH \
  --policy-version mandateguard_policy_0.2 \
  --authority-ttl-seconds 300 \
  --receipt-out /tmp/testmode_receipt.json \
  | tee /tmp/testmode_success_execute.json
```

Expected shape:

```text
execution_state = EXECUTED
executed = true
write_outcome_unknown = false
reason_code = FALLBACK_PAYMENT_LINK_CREATED
financial_truth = RECOVERABLE
receipt.payment_link_id = plink_...
```

Before the write the runtime reads the Order/payment state twice. If state changes between diagnosis and execution, the fence must block instead of creating another action.

## 3. Complete the hosted Test Mode payment

Open the Test Mode Payment Link from the receipt and complete a supported Test Mode payment manually.

Do not describe this step as an AutoPay retry. It is a customer-initiated Standard Payment Link fallback used to demonstrate bounded provider execution and postcondition verification.

## 4. Verify the exact captured payment

```bash
python3 scripts/razorpay_testmode_demo.py verify \
  --receipt /tmp/testmode_receipt.json \
  | tee /tmp/testmode_recovery_proof.json
```

Expected shape:

```text
recovery_verified = true
proof.payment_id = pay_...
proof.provider_action_id = plink_...
proof.original_order_id = order_...
proof.mandate_id = mandate_...
proof.amount_minor = exact authorized amount
proof.currency = INR
proof.reference_id = deterministic rt_... reference
recovery_proof_hash = SHA-256 digest
```

The verifier independently fetches the Payment Link and captured Payment and checks identity, amount, currency and recovery reference before emitting the proof.

## 5. Produce one real safe block

Preferred proof: use a Test Mode Order whose current provider truth is already `paid`, or create a state in which a Payment is currently `authorized`/pending.

Run `execute` with the same exact expected amount/currency binding.

Expected already-paid shape:

```text
execution_state = NOT_EXECUTED
executed = false
write_outcome_unknown = false
reason_code = SAFE_BLOCK_ALREADY_PAID
financial_truth = PAID
```

Expected in-flight shape:

```text
execution_state = NOT_EXECUTED
executed = false
write_outcome_unknown = false
reason_code = SAFE_BLOCK_IN_FLIGHT
financial_truth = IN_FLIGHT
```

Save the terminal output:

```bash
... | tee /tmp/testmode_safe_block.json
```

For the judge demo, pair the JSON with the provider dashboard/API evidence showing the Order/payment state. The safety claim is that no fallback write is attempted after the runtime resolves `PAID` or `IN_FLIGHT`.

## 6. Redact and preserve evidence

Before adding any Test Mode artifact to a submission evidence folder:

- remove secrets completely;
- do not include Authorization headers;
- do not include customer PII;
- keep provider entity IDs if they are Test Mode-only and useful for proof, otherwise partially redact them consistently;
- preserve amount, currency, state, reason code, decision binding, provider action type, proof hash and timestamps needed to understand the chain.

Do **not** edit the raw evidence and then call its old checksum valid. Redaction produces a new artifact and therefore a new checksum.

## 7. Final wording for the panel

Use this exact meaning:

> "The benchmark rupees are synthetic. Separately, RecoveryTruth demonstrates one real Razorpay Test Mode provider path: it re-reads current Order/payment truth at the write boundary, creates a Standard Payment Link fallback only when still recoverable, blocks paid or in-flight cases, and verifies the exact captured payment into a RecoveryProof. This is not a production AutoPay retry."

## 8. What not to claim

Do not claim:

- recovered Test Mode value is merchant revenue;
- the fallback is Razorpay AutoPay retry;
- the `RZP` arm reproduces Intelligent Retry;
- the hash chain is tamper-proof;
- the decision evidence hash authenticates an arbitrary external caller;
- production keys or production money were used.
