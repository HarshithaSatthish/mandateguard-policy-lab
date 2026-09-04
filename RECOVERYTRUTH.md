# RecoveryTruth — provider-backed financial truth protocol

RecoveryTruth is the provider-execution safety layer that sits **after** MandateGuard's policy decision. It does not replace the nine-arm synthetic benchmark and it does not claim that a Razorpay Payment Link is an AutoPay debit retry.

The default MandateGuard benchmark remains deterministic, offline and simulator-backed. RecoveryTruth adds a separate credentialed **Razorpay Test Mode** demonstration of a bounded, customer-initiated fallback collection action. That Test Mode path performs real Razorpay Test Mode reads (not simulator reads) and may create a Standard Payment Link fallback; it is not an AutoPay retry. Current evidence status: **VERIFIED_TEST_MODE_EVIDENCE_CAPTURED**.

## The problem it solves

A webhook is evidence about an event that happened. It is not automatically the current financial truth at the moment a new recovery action is about to be created.

RecoveryTruth therefore refuses to execute from an event snapshot alone. The provider-backed path must establish this chain:

```text
MandateGuard decision authority
        |
        v
fresh Razorpay Order + all Order Payments
        |
        v
financial truth resolution
  PAID / RECOVERABLE / IN_FLIGHT / TERMINAL / UNKNOWN / CONFLICT
        |
        | only RECOVERABLE
        v
arm write fence from exact provider evidence fingerprint
        |
        v
fresh Razorpay Order + all Order Payments AGAIN
        |
        +--> changed / paid / in-flight / unknown / terminal => SAFE_BLOCK, zero write
        |
        v
recheck decision authority + amount ceiling + expiry
        |
        v
create customer-initiated Payment Link fallback with deterministic reference
        |
        +--> timeout/network ambiguity => lookup by reference before any new action
        +--> concurrent duplicate reference => lookup and reuse provider object
        |
        v
persist RecoveryActionReceipt
        |
        v
later fetch Payment Link + independently fetch exact Payment
        |
        v
require exact captured payment, amount, currency and recovery reference
        |
        v
RecoveryProof hash binds decision evidence + pre-write evidence + provider action + postcondition evidence
```

## Financial truth precedence

`bailiff/recovery_truth.py` intentionally distinguishes event history from current provider evidence.

- Historical webhook evidence can be retained with `authoritative=False`.
- Fresh Razorpay Order and Payment fetches are authoritative provider evidence.
- Current Order `paid` is `PAID`.
- Current Payment `captured` is `PAID`.
- Current Payment `created`, `authorized` or `pending` is `IN_FLIGHT`; a parallel fallback is blocked because the payment may still capture.
- A fallback is `RECOVERABLE` only when the current payment attempts associated with the exact Order are all failed and no captured or in-flight payment is present.
- Unknown provider states fail closed.
- Equal-time contradictory current observations of the same provider entity become `CONFLICT`.

This prevents a stale `payment.failed` event from authorising recovery after the underlying money state has already changed.

## Identity binding

The provider-backed runtime does not merely ask whether *a* payment was captured.

Before execution, `RazorpayTestModeClient.order_evidence()` fetches the exact Razorpay Order and all Payments associated with it. It rejects mismatched:

- Order id,
- Order amount,
- Order currency,
- Payment `order_id`,
- Payment amount,
- Payment currency.

The same bound evidence is fetched a second time immediately before the provider write.

After the fallback is paid, `verify_payment_link_capture()` verifies:

- exact Payment Link id,
- deterministic recovery `reference_id`,
- exact amount,
- exact currency,
- non-partial-payment contract,
- exactly one captured Payment entry for the link,
- Payment-to-Link binding when Razorpay supplies `payment_link_id`,
- independently fetched current Payment status is `captured`,
- independently fetched Payment amount and currency match.

Raw Razorpay Payment Link and Payment responses are hashed before local binding fields are added. `postcondition_evidence_hash` binds those raw hashes to the provider entity ids and recovery reference.

## Write-time fence

The write fence is deliberately stricter than a normal idempotency key.

A fence can only be armed from `RECOVERABLE`. Immediately before the write, a second provider read must produce the same authoritative evidence fingerprint and still resolve to `RECOVERABLE`.

Examples of zero-write blocks:

- `SAFE_BLOCK_ALREADY_PAID`
- `SAFE_BLOCK_IN_FLIGHT`
- `SAFE_BLOCK_TERMINAL`
- `SAFE_BLOCK_UNKNOWN`
- `SAFE_BLOCK_CONFLICT`
- `SAFE_BLOCK_STATE_CHANGED_BEFORE_WRITE`
- `SAFE_BLOCK_AUTHORITY_EXPIRED`
- `SAFE_BLOCK_AUTHORITY_EXPIRED_AT_WRITE`

## Decision authority

RecoveryTruth cannot create provider actions merely because the financial state is recoverable.

`RecoveryRequest` also binds the action to MandateGuard's decision evidence:

- `decision_id`
- `decision_evidence_hash`
- `policy_version`
- exact action type
- amount ceiling
- short-lived authority expiry

The amount cannot exceed the policy authority and the authority is checked both before provider reads and again immediately before the write.

Caller-supplied `mandate_status` is **not** called Razorpay provider truth. Until an independent current mandate-state source is actually queried, mandate/consent permission remains part of the expiring MandateGuard decision authority. This distinction is intentional.

## Exactly-once logical fallback

The fallback provider reference is deterministic:

```text
rt_<first 32 hex characters of SHA256(case_id)>
```

It fits Razorpay's 40-character Payment Link `reference_id` contract.

Execution does:

1. lookup by reference,
2. create only when no object exists,
3. on timeout/network ambiguity, lookup again,
4. on Razorpay duplicate-reference 400/409, lookup and reuse the object,
5. never generate a second random reference to escape an ambiguous first write.

This is a logical exactly-once/reconciliation contract, not a claim that a distributed network call itself executes atomically.

## What the real Test Mode action is

The real provider-backed action is:

```text
CREATE_PAYMENT_LINK_FALLBACK
```

It is a **customer-initiated fallback collection path**. It is not described as a scheduled UPI AutoPay debit retry.

The Payment Link is created with:

- Test Mode credentials only,
- `accept_partial=false`,
- automatic SMS/email notification disabled,
- reminders disabled,
- deterministic recovery reference in both `reference_id` and notes.

`RazorpayTestModeClient.from_env()` refuses any key that does not begin with `rzp_test_`.

## Offline acceptance gate

The mandatory release gate runs:

```bash
python3 scripts/recoverytruth_check.py
```

It attacks at least these properties without requiring credentials:

- stale failed history loses to fresh captured truth,
- `authorized`/`pending` blocks parallel collection,
- unknown and terminal state fail closed,
- stale authority makes zero provider writes,
- amount authority cannot be widened,
- exact order/amount/currency are passed into both state reads,
- the write boundary is read twice,
- capture between diagnosis and write produces zero writes,
- an in-flight payment appearing between diagnosis and write produces zero writes,
- repeating the same logical fallback reuses the same provider object,
- RecoveryProof binds the decision evidence and postcondition evidence,
- live Razorpay credentials are refused.

`scripts/release_check.sh` runs this acceptance gate before a release can pass.

## Credentialed Razorpay Test Mode demo

Set credentials only in the process environment. Never commit them.

```bash
export RAZORPAY_TEST_KEY_ID='rzp_test_...'
export RAZORPAY_TEST_KEY_SECRET='...'
```

Run the bounded execution step with an existing Test Mode Order that has a failed payment attempt:

```bash
python3 scripts/razorpay_testmode_demo.py execute \
  --order-id order_... \
  --case-id demo_case_001 \
  --mandate-id demo_mandate_001 \
  --mandate-status active \
  --amount-minor 1000 \
  --decision-id dec_... \
  --decision-evidence-hash <sha256-of-mandateguard-decision-evidence> \
  --receipt-out /tmp/recoverytruth_receipt.json
```

The output either shows a `SAFE_BLOCK_*` reason with no fallback creation, or returns one Test Mode Payment Link receipt.

After completing that Test Mode Payment Link through Razorpay's hosted checkout, verify the exact receipt from the execution step:

```bash
python3 scripts/razorpay_testmode_demo.py verify \
  --receipt /tmp/recoverytruth_receipt.json
```

Verification emits the bound `RecoveryProof` and its hash. The verify command cannot fabricate missing pre-write evidence; it requires the exact execution receipt schema.

## Claims we deliberately do not make

- The synthetic benchmark is not observed production revenue.
- The Payment Link fallback is not an AutoPay debit retry.
- The project does not reproduce Razorpay's current production Intelligent UPI Retry Engine.
- The current B3 abstention is confidence-gated; this document does not claim statistical calibration metrics such as ECE/Brier unless those are separately measured.
- The hash-bound RecoveryProof is **tamper-evident**, not cryptographically notarised or tamper-proof.
- Routing to human review is implemented; a full authenticated human approval/execution console is not claimed.
- Caller-supplied mandate state is not presented as fresh Razorpay provider truth.
- No production/live Razorpay credentials are accepted by the Test Mode client.

## Source files

- `bailiff/recovery_truth.py` — truth states, precedence, write fence, captured-payment proof, RecoveryProof.
- `bailiff/recovery_runtime.py` — decision authority + two-read write boundary + receipt.
- `bailiff/razorpay_testmode.py` — Test Mode provider reads, fallback creation, ambiguity reconciliation, independent postcondition reads.
- `scripts/recoverytruth_check.py` — mandatory offline acceptance/adversarial gate.
- `scripts/razorpay_testmode_demo.py` — credentialed provider-backed execution and verification path.
