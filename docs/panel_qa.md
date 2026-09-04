# Panel Q&A — short answers that survive follow-up

Use these in your own words. Concede the real limitation first, then point to the executable proof.

## "Where's the agent?"

The recovery policy is the agent. MandateGuard runs competing recovery policies against the same frozen evidence and provider contract, then proves what each policy executed, refused or escalated. The interesting part is not another detect-retry dashboard; it is that unsafe non-actions are first-class outcomes with provider-call evidence.

The default benchmark uses a local provider simulator and does not call Razorpay. RecoveryTruth adds an optional Razorpay Test Mode path that does perform real Test Mode reads and one bounded customer-initiated Standard Payment Link fallback (not an AutoPay retry), with fresh provider truth, an immediate pre-write re-read, safe blocking and postcondition verification. That credentialed proof is currently VERIFIED_TEST_MODE_EVIDENCE_CAPTURED.

## "Where's the AI? This looks like rules."

That is deliberate. Most safety facts do not need an LLM: revoked mandate, exhausted attempt budget, missing consent and amount authority are deterministic constraints.

B3 is the bounded interpreter arm. A model may interpret an ambiguous provider payload and return a normalized reason plus confidence. It cannot authorize a payment action, widen an authority envelope, change mandate state or bypass the guardrail layer.

The design sentence is:

> **AI interprets. Policy authorizes. Provider executes. Evidence proves.**

The AI claim is restraint, not a chatbot. A compromised or overconfident interpreter still cannot move a revoked mandate past deterministic authority.

## "Isn't `RZP` a strawman?"

It would be if I presented it as Razorpay's current UPI retry engine. I do not.

`RZP` is a **fixed temporal reference arm** derived from Razorpay's documented **card** retry schedule. It does not reproduce Razorpay Intelligent Retry, and MandateGuard has not been evaluated against Razorpay's production decision logic.

The narrower result is: on the same frozen synthetic scheduled AutoPay ledger, the tested reason-aware policies outperform that fixed temporal reference under the stated metrics.

If asked what would change my mind: another independently reproducible policy evaluated on the same frozen ledger and independent checker that preserves mandatory refusals while matching or outperforming the reason-aware arms.

## "Is this real or just synthetic simulation?"

The benchmark is synthetic and offline, and every rupee number in it is a counterfactual benchmark value, not observed merchant revenue.

What is executable and falsifiable: webhook HMAC validation, attacked 42 ways in tests; replay/order controls; deterministic authority attenuation; guardrails; provider-call accounting; abstention; timeout handling; audit verification; and the independent checker. The baseline suite currently contains 299 tests and a 14/14 mutation check; the final verification record must quote the final frozen run rather than assume those numbers.

Separately, RecoveryTruth has a Razorpay **Test Mode only** execution path. Its concrete write is a **Standard Payment Link fallback**, not an AutoPay retry. That proof is currently VERIFIED_TEST_MODE_EVIDENCE_CAPTURED: the sanitized bundle in `docs/testmode_evidence/` contains one real fallback receipt, one real `SAFE_BLOCK_ALREADY_PAID` with its zero-new-fallback proof, and a captured-payment `RecoveryProof`. Show those recorded artifacts; do not invent anything beyond them.

## "What does the RecoveryProof actually prove?"

It binds the recovery case to the decision evidence, policy version, authority expiry, original Order, mandate, pre-write financial truth, provider action, postcondition evidence, captured Payment, amount, currency and recovery reference.

The proof hash is **tamper-evident evidence**. It does not make the underlying files tamper-proof or immutable.

## "Does the decision evidence hash mean any external caller is cryptographically authorized?"

No. In the current Test Mode harness the decision evidence hash is an operator-supplied binding to the MandateGuard decision/audit evidence. It is not a signed external capability token.

Production hardening could add a signed capability, but that is not required for the claim being demonstrated here: the in-process MandateGuard authority layer remains deterministic, and the Test Mode harness proves the provider-side truth/write/postcondition path.

## "Why not just maximize recovered money?"

Because the ungated arms demonstrate the failure mode: they can recover more by executing actions the independent checker considers prohibited. Recovery alone therefore rewards unsafe behavior.

MandateGuard reports recovery together with protected value by denial, realized harm, prohibited execution rate, violations, legitimate recovery forgone and sensitivity to the assumed harm price. The headline product is the **Refusal Report**, not the biggest rupee number.

## "What would you do inside Razorpay?"

I would not try to replace Intelligent Retry or Agent Studio. I would put this evaluation harness in front of retry templates so a merchant or internal recovery team can see recovered versus refused before a configuration is enabled.

A failure receipt proves a debit failed. MandateGuard is designed to prove a compliant non-debit: the system had a recovery opportunity, evaluated it, refused it for a specific reason, and made zero provider calls.

## "What broke during development?"

A useful example is the input boundary. The project initially focused on action authority, but an unauthenticated or badly authenticated failure event could make every downstream control irrelevant. The webhook boundary was therefore hardened around raw-body HMAC verification, duplicate delivery, replay window and out-of-order events, then attacked directly in the test suite.

Another example is ambiguous provider writes. A timeout after a provider write cannot safely be called "not executed" because the remote side may have committed it. RecoveryTruth therefore has a distinct `WRITE_OUTCOME_UNKNOWN` state and reconciliation behavior rather than encouraging an immediate repeat.

## Four sentences to remember

1. **Razorpay already recovers; MandateGuard evaluates whether a recovery policy should be trusted before it goes live.**
2. **Synthetic rupees stay synthetic; the real Test Mode artifact is separate evidence.**
3. **Payment Link fallback is not an AutoPay retry, and `RZP` is not Intelligent Retry.**
4. **The proof chain is tamper-evident, and a refusal is only interesting when provider calls are provably zero.**
