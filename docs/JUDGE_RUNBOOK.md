# MandateGuard — Judge Runbook

## The sentence to remember

**Razorpay already recovers. MandateGuard is the harness in front of that engine: before a retry configuration goes live, prove what it recovers, what it refuses, and that every refusal made zero provider calls.**

MandateGuard does **not** claim to replace Intelligent Retry or Agent Studio. It evaluates recovery policy before deployment and makes unsafe non-actions visible as first-class evidence.

## The 60-second proof

Run:

```bash
pip install -r requirements.txt
python3 scripts/demo60.py
```

Show these five events in order:

1. forged webhook is refused at ingress;
2. a permitted retry makes exactly one simulated provider call;
3. B3 abstains on ambiguity with zero provider calls;
4. a timeout becomes an unknown postcondition and routes to human review;
5. audit-chain verification fails after evidence is modified.

The point of the demo is not that retries happen. The point is that **refusals are executable outcomes with provider-call evidence**.

## The benchmark

Nine policy arms are evaluated on the same frozen synthetic scheduled UPI AutoPay failure ledger:

`B0, B1, B1.5, RZP, B2.25, B2.5, B2.75, B2, B3`

`RZP` is a temporal reference derived from Razorpay's documented **card** retry schedule. It is **not** Razorpay Intelligent Retry and does not model Razorpay's production UPI decision logic.

Any result comparing `RZP` with reason-aware arms is therefore a result about this synthetic ledger and this fixed temporal reference only.

## What to lead with

Do not lead with recovered rupees. Ungated arms recover more because they also execute actions the independent checker rejects.

Lead with:

- prohibited value that never reached the provider;
- denied/abstained rows with `provider_calls = 0`;
- zero-violation guarded arms;
- the evidence receipt proving the decision path.

Synthetic rupee values are counterfactual benchmark values, not observed merchant revenue.

## Where the AI is

Eight arms are deterministic by design. B3 is the bounded interpreter arm.

The model may interpret an ambiguous provider payload and return a reason plus confidence. It cannot authorize a debit, widen an authority envelope, change mandate state, or bypass the deterministic guardrail layer.

The AI claim is therefore not "the LLM controls recovery." It is:

> **AI interprets. Policy authorizes. Provider executes. Evidence proves.**

A compromised or overconfident interpreter still cannot move a revoked mandate past the guardrail.

If a judge asks whether the AI earns its place, do not argue — run `python3 scripts/interpreter_ablation.py`. It prints B2 against B3 on the same frozen aggregate with the same guardrails, so the only difference on screen is the bounded interpreter, and the delta is whatever it is. Structural isolation is also a test, not a promise: the suite walks the interpreter's import graph and fails if it can ever reach a provider module, and asserts the wire request carries no tools and no credentials.

If a judge asks what the controls cost, run `python3 scripts/refusal_regret.py`. It prints every refusal reason with the recoverable value it forgot and the harm-bearing value it protected, including the rows where a control cost more than it protected.

## The real Test Mode proof

The optional RecoveryTruth path uses Razorpay **Test Mode only** and rejects live keys. The concrete execution action is a **Standard Payment Link fallback**. It is customer-initiated and must not be described as an AutoPay retry. Current status: **VERIFIED_TEST_MODE_EVIDENCE_CAPTURED**. The sanitized evidence bundle in `docs/testmode_evidence/` contains the real fallback receipt, captured-payment RecoveryProof, and already-paid SAFE_BLOCK; present those recorded artifacts and nothing invented beyond them.

Do not say that other entries merely trust stale webhooks — stronger entries in this field also reconcile conflicting sources. The claim that holds is narrower: **RecoveryTruth establishes authoritative provider truth immediately before the money-changing write and independently proves the exact postcondition afterward.** Put the refusal evidence directly beside that sentence: in the already-paid case, `testmode_safe_block_zero_write.json` proves Payment Links stayed `0 -> 0`, so the blocked recovery object never existed at the provider.

The final evidence bundle must contain exactly these three demonstrations:

- a recoverable Test Mode case that creates one fallback receipt;
- an already-paid or in-flight case that produces `SAFE_BLOCK_*` with no fallback write;
- a captured Test Mode payment that verifies into a `RecoveryProof` bound to case, decision evidence, original order, mandate, amount, currency, provider action and captured payment.

A hash chain is **tamper-evident evidence**, not "tamper-proof" storage.

## Honesty rules

Say these before a panelist has to correct you:

- all benchmark rupee figures are synthetic counterfactuals;
- Payment Link fallback is not an AutoPay debit retry;
- `RZP` is a fixed card-schedule reference, not Intelligent Retry;
- MandateGuard has not measured Razorpay production recovery performance;
- harm pricing is a project assumption and the sensitivity sweep exists so the result can be read under other prices;
- the audit hash chain detects evidence changes; it does not make files impossible to alter.

## Five-minute video order

**0:00–0:25 — Question**

"Razorpay already recovers failed payments. The question I worked on is different: before a recovery configuration goes live, can we prove what it will recover, what it must refuse, and that every refusal makes zero provider calls?"

**0:25–1:00 — Architecture**

Authenticate event → bounded interpretation where needed → deterministic policy/guardrails → provider boundary → evidence.

Add RecoveryTruth for the Test Mode path: fresh provider truth → immediate pre-write re-read → safe block on paid/in-flight/conflict → idempotent fallback → captured-payment verification → RecoveryProof.

**1:00–2:10 — Live 60-second proof**

Run `demo60.py`. Do not narrate every line. Point only to the five outcomes in the demo section above.

**2:10–3:05 — Frozen benchmark**

Show nine arms on the same ledger. State the card-vs-UPI caveat before discussing `RZP`. Show the frontier and the fact that ungated recovery can look better if safety is ignored.

**3:05–3:45 — Sensitivity**

Show that harm pricing is an assumption, then show the sensitivity crossover instead of pretending one price is objectively correct.

**3:45–4:30 — Test Mode evidence**

Status is **VERIFIED_TEST_MODE_EVIDENCE_CAPTURED**, so show the recorded artifacts in `docs/testmode_evidence/`: the fallback receipt, the `SAFE_BLOCK`, and the `RecoveryProof`. Say the offline path is a local simulator and Test Mode is a separate real Razorpay Test Mode path. Say explicitly: "This is a Standard Payment Link fallback in Test Mode, not an AutoPay retry."

**4:30–5:00 — Product fit and close**

"This sits under a recovery configuration workflow, not beside Razorpay's recovery products. If I joined, week one I'd plug this harness in front of retry templates so a merchant sees recovered versus refused before they flip a config. A failed debit receipt proves a debit failed. MandateGuard proves a compliant non-debit."

## Panel answers to memorize in your own words

### Where is the agent?

The recovery policy is the agent. The harness executes competing policy arms against the same evidence and provider contract, then proves which actions were allowed, refused or escalated. The Test Mode path demonstrates bounded execution rather than only diagnosis.

### Where is the AI?

Only ambiguity needs an LLM. B3 uses a bounded interpreter for reason/confidence, while deterministic controls retain payment authority. The restraint is intentional: an LLM is not allowed to decide whether a revoked mandate can be charged.

### Isn't `RZP` a strawman?

It would be if presented as Razorpay's current UPI engine. It is not. It is a fixed temporal reference based on Razorpay's published card schedule. The claim is only that reason-aware arms outperform that reference on this frozen synthetic ledger under the stated metrics.

### Is this real?

The benchmark is synthetic and offline. The security/state machinery is executable code with adversarial tests. RecoveryTruth additionally has a Razorpay Test Mode execution path for a Standard Payment Link fallback, a safe-block path and captured-payment verification. Production AutoPay debit execution is not claimed.

### What would change your mind?

Another policy evaluated on the same frozen ledger and independent checker that preserves the mandatory refusals while outperforming the reason-aware arms. The harness is designed so the answer can change when better policy evidence appears.
