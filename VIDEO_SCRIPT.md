# MandateGuard — 5 minute submission video

## One sentence the judges should remember

> **Razorpay already recovers. MandateGuard is the harness in front of that engine: before a retry configuration goes live, prove what it recovers, what it refuses, and that every refusal made zero provider calls.**

Do not position MandateGuard as a replacement for Intelligent Retry, Intelligent Revenue-Protect, or Agent Studio. The product is the evaluation and refusal-proof layer around recovery policy.

## 0:00–0:25 — Open on the question

Say:

> Razorpay already has recovery. The hard question is not whether we can retry a failed payment. It is whether a recovery policy can prove, before deployment, what it will recover, what it will refuse, and that every prohibited action stopped before the provider boundary.

Then state scope immediately:

> The benchmark numbers I am about to show are synthetic counterfactual INR over a frozen generated ledger. They are not Razorpay merchant revenue.

**Do not open with a recovery number.** Open with the refusal question and the scope statement above.

## 0:25–1:25 — The 60 second proof

Run:

```bash
python3 scripts/demo60.py
```

Keep the terminal on screen. Point to five facts only:

1. forged Razorpay-shaped webhook is refused at ingress;
2. a permitted retry produces exactly one simulated provider call;
3. B3 abstains on ambiguity with zero provider calls;
4. an unknown timeout postcondition routes to human review rather than being assumed failed or retried blindly;
5. modifying historical audit evidence makes verification fail.

Say:

> The headline is the refusal. A denied or abstained action is not merely logged after the fact; it terminates before the provider boundary and records zero provider calls.

Do not call the hash chain tamper-proof. Say **tamper-evident evidence chain**.

## 1:25–2:05 — Nine policy arms, one frozen ledger

Show `outputs/frontier.png` and the arm list:

`B0, B1, B1.5, RZP, B2.25, B2.5, B2.75, B2, B3`

Say the caveat before the result:

> `RZP` is a fixed temporal reference arm derived from Razorpay's published **card** retry schedule. It is not Razorpay's current Intelligent UPI Retry Engine and this project has not benchmarked Razorpay production decision logic.

Then:

> On this synthetic ledger, the tested reason-aware arms outperform that fixed temporal reference on the recovery-versus-prohibited-value frontier. That is a finding about these policies on this frozen ledger, not a claim that MandateGuard recovers more than Razorpay.

Be willing to say that ungated arms can recover more. That is why recovered INR is not the only objective.

## 2:05–2:40 — Where the AI is

Show B3 and `outputs/real_interpreter_evidence.json`.

Say:

> The non-B3 policy arms are deterministic on purpose. Cancelled mandates, withdrawn consent and exhausted retry budgets do not become safer because an LLM is placed in the loop. B3 uses a bounded real-model interpreter only for ambiguous failure meaning. The model gets no payment authority. Low confidence means abstain and zero provider calls, and even a hostile interpreter cannot turn a revoked mandate into an allowed debit.

The point is restraint, not chatbot surface area.

## 2:40–3:25 — RecoveryTruth / Razorpay Test Mode

When the real Test Mode artifacts have been captured, show three files or terminal outputs:

- one Test Mode fallback receipt;
- one `SAFE_BLOCK_ALREADY_PAID` or `SAFE_BLOCK_IN_FLIGHT` with no Payment Link write;
- one `RecoveryProof` bound to the original order, mandate, decision evidence, pre-write evidence, Payment Link action and captured payment.

Say:

> This is Razorpay Test Mode only; live keys are refused. The concrete recovery action here is a standard customer-initiated Payment Link fallback. It is **not** an AutoPay retry. Immediately before the write, RecoveryTruth re-reads the current Order and Payments. If the payment is already paid, still in flight, conflicting or unknown, it blocks instead of creating a second recovery action.

Status is **VERIFIED_TEST_MODE_EVIDENCE_CAPTURED**: the sanitized four-artifact bundle in `docs/testmode_evidence/` holds a real Test Mode Payment Link fallback receipt, a captured-payment `RecoveryProof`, an already-paid `SAFE_BLOCK`, and the zero-new-fallback proof. Show those artifacts rather than describing them, and say on camera that Test Mode means real Razorpay Test Mode reads plus a Standard Payment Link fallback — not an AutoPay retry — and that no live key is ever accepted.

## 3:25–4:10 — Refusal Report + sensitivity

Show `outputs/sensitivity.png`, then the refusal evidence/report.

Say:

> The cost assigned to a prohibited action is an assumption, so I do not hide it behind one headline number. The sensitivity sweep shows where the preferred policy changes. The product is the instrument that exposes that trade-off, including when my stricter policy loses on recovery.

Lead with:

- prohibited value stopped before provider execution;
- violations;
- provider calls on denied/abstained cases;
- legitimate recovery forgone;
- incremental synthetic recovery.

Do not present synthetic INR as observed merchant revenue.

## 4:10–4:40 — Architecture

Show `outputs/architecture.png` plus RecoveryTruth conceptually:

`Authenticate → Interpret → Deterministic authority → resolve current financial truth → pre-write re-read/write fence → provider action → postcondition verification → evidence`

Say:

> AI may interpret. Policy authorizes. RecoveryTruth checks what is financially true now. The provider executes only after a fresh write-boundary check. Evidence records what happened afterward.

## 4:40–5:00 — Close like a Razorpay recovery engineer

Say:

> If I joined, week one I would plug this harness in front of Intelligent Retry templates so a merchant can see recovered versus refused before they flip a configuration. A failed-debit diagnostic proves why a debit failed. MandateGuard proves a compliant non-debit when the recovery system should not act.

Stop there.

## Claims that are forbidden in the video

Do not say “we recover X% more than Razorpay.” Do not call a Payment Link an AutoPay retry. Do not call synthetic INR production revenue. Do not call the evidence chain tamper-proof. Do not claim a credentialed Test Mode run until its receipt, safe block and RecoveryProof actually exist. Do not describe `RZP` as Razorpay's current UPI retry engine.
