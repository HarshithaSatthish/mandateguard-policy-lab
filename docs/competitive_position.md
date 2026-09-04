# Position relative to Razorpay's own recovery product

> Desk research conducted 24 August 2026 against public sources only. Every
> claim about Razorpay's product below is drawn from Razorpay's published
> material and is quoted or paraphrased as published. Nothing here rests on
> internal knowledge, and nothing here asserts a defect in a Razorpay product.

## Razorpay already ships recovery for UPI AutoPay — and an AI agent for it

This must be said first and plainly, because a judge will know it and a
submission that talks around it looks either uninformed or evasive.

At FTX'26 (12 March 2026) Razorpay launched **Agent Studio**, built on
Anthropic's Claude Agent SDK, with a pre-built **Subscription Recovery** agent
that "Analyzes failed subscription payments, apply smarter retry logic, and
trigger targeted customer nudges." The **Agentic Experience Platform** announced
alongside it includes "active revenue recovery on failed payments" and
"autonomous guardrails."

So the honest position is not that this space is empty. It is that Razorpay is
building an AI agent to do exactly this, and the published material for it
describes capability without describing constraint. As of this research
(24 August 2026) the Agent Studio page carries no statement about guardrails,
audit trails, approval workflows or human oversight for any of its seven
pre-built agents.

That is where this project sits: not proposing the agent, proposing the harness
the agent should be measured and bounded by.

Razorpay's **Intelligent Revenue-Protect** for UPI AutoPay is live and, as
published, includes:

- an **Intelligent Retry Engine** letting merchants "configure their own retry
  strategies, deciding when and how payment retries should happen", with the
  ability to "define retry cadence, choose predefined templates, or create
  custom templates for retry logic" — described as introduced in beta at
  FTX 2026;
- **WhatsApp-led recovery**, sending "branded recovery links on WhatsApp" for
  registration drop-off, mandate cancellation, and failed debits;
- three intervention points: registration abandonment, failed debit retry, and
  mandate cancellation win-back.

The same page quantifies the leaks it targets: roughly 30% registration
drop-off, 20% subsequent debit failure, and 18% active subscriber cancellation.

**MandateGuard does not compete with this and would lose if it tried.** A
hackathon project is not going to out-recover a shipped product built by the
team that owns the rails.

## The finding that makes this concrete

Razorpay publishes its subscription retry model: *"In a T+3 days cycle, we will
retry the payment thrice. That is, once every day for 3 days, excluding the date
of the charge."* The subscription then moves to `halted`.

MandateGuard implements exactly that as a benchmark arm, `RZP`, and runs it on
the same frozen ledger as every other policy. The result:

| Regime | RZP recovered | RZP prohibited value moved | Reason gating (B1.5) recovered | B1.5 prohibited value moved |
|---|---:|---:|---:|---:|
| R1 Transient | ₹12,941 | ₹19,030 | ₹20,561 | ₹14,285 |
| R2 Terminal | ₹5,089 | ₹35,272 | ₹8,818 | ₹5,804 |
| R3 Ambiguous | ₹6,621 | ₹22,357 | ₹8,864 | ₹7,967 |

**`RZP` is Pareto dominated in all three regimes.** Simply reading the failure
reason recovers more money while moving substantially less prohibited value — in
the terminal regime, six times less. No weighting of the two metrics prefers the
temporal schedule.

Two qualifications, both material, both enforced by tests so they cannot be
dropped:

1. **That schedule is documented for the card model.** Applying the card
   model to a scheduled UPI AutoPay ledger is this benchmark's stated
   assumption. It is not a reproduction, benchmark, or claim about Razorpay's
   current Intelligent UPI Retry Engine or production UPI behaviour.
2. **A schedule cannot see a failure reason, and this arm does not try to.**
   The result is not that Razorpay's card policy is bad at being a card policy.
   It is that a purely temporal model, moved onto a rail where some failures are
   terminal, retries mandates that no longer exist.

Read together those two points make one argument: **a scheduled UPI AutoPay
policy needs its own model.** This project is a way to evaluate what it
should be.

To be explicit about what the `RZP` arm is and is not: the RZP arm uses
Razorpay's documented fixed card retry schedule as a **temporal reference
policy**. It does not reproduce or benchmark Razorpay's current Intelligent
UPI Retry Engine, and MandateGuard has not been evaluated against Razorpay's
production decision logic. Razorpay ships Intelligent Revenue-Protect for UPI
AutoPay, in which merchants configure retry strategies; that production engine
is not implemented or evaluated here. Any result about `RZP` is a result about
a fixed temporal schedule on a synthetic ledger, not about Razorpay's
production recovery.

## What MandateGuard is instead

MandateGuard is not a recovery engine. It is the **evaluation harness and
bounded runtime that sits underneath one**.

A configurable retry engine turns recovery policy into a merchant-editable
setting. That is the right product decision and it creates a second-order
question that the configuration surface itself cannot answer:

> Before this retry configuration is deployed, what will it recover, what
> legitimate recovery will it refuse, how many prohibited debits will it
> attempt, and can every refusal be proven after the fact?

Razorpay's published description of Revenue-Protect covers cadence, templates
and channels. It does not describe a pre-deployment evaluation of a
configuration against attempt caps, pre-debit notice validity, consent state,
or mandate state, nor a per-decision evidence artifact. That absence in the
public material is the space MandateGuard occupies. It is an honest statement
about what is published, not a claim that the product lacks those controls
internally.

## The division of labour we are proposing

| Layer | Owner | Question it answers |
|---|---|---|
| Recovery execution | Razorpay Revenue-Protect | How do we win the payment back? |
| Recovery configuration | Merchant, via the retry engine | When and how often do we try? |
| **Policy evaluation** | **MandateGuard** | **What does that configuration cost before we deploy it?** |
| **Bounded execution and evidence** | **MandateGuard** | **Did every refusal actually happen before the provider boundary, and can we prove it?** |

## Why the evaluation layer is the defensible half

Three reasons, in order of strength.

**1. Our own benchmark says so.** MandateGuard's fully guarded arms do not win
on recovery. Reason gating alone (B1.5) recovers more in every shipped regime,
and under the fixture sweep a fully guarded arm is the recommended policy in
only 18 of 45 regime observations. If the deliverable were a recovery policy,
that result would be a failure. Because the deliverable is the instrument that
produced the result, it is the product working correctly: the harness is
capable of reporting against the interest of the person who built it, which is
the only kind of measurement worth having.

**2. The observable failure mode is over-execution, not under-recovery.** See
`docs/problem_evidence.md`. The publicly documented complaint themes around
recurring payments are unexpected and unauthorised deductions and auto-pay
charges, not merchants reporting that too little was recovered. A layer whose
headline metric is `protected_value_by_denial_inr` addresses the documented
direction of failure.

**3. Configuration surfaces create an evaluation question.** When retry
strategy is configurable, a merchant can compare candidate strategies before
deployment. MandateGuard supplies one explicit way to do that: a frozen
synthetic ledger, declared harm/recovery metrics, counterfactual policy arms,
and auditable runtime receipts.

## How to say this on camera

> Razorpay already ships recovery for UPI AutoPay, including a configurable
> retry engine in beta. I am not proposing a competitor to it. MandateGuard
> asks a separate evaluation question: before a retry strategy is deployed,
> what recovery-versus-prohibited-value trade-off does it produce under a
> declared test model? The harness measures that on a frozen synthetic ledger
> and proves every refusal with a receipt. My own benchmark says the strict policy
> is not always the profitable one, and it reports the exact price at which
> that flips. That is the product: the measurement, not the policy.

## The field is converging on money truth; the moat is the write boundary

Stronger late-stage Buildathon entries now also reason about conflicting
sources, stale events and reconciliation — dedup across webhook and REST
observation of the same logical transition, guards against a stale capture
event regressing a refunded payment. That development retires any broad
claim that other entries merely consume stale webhook truth, and this
project should not make it.

The distinction that survives is narrower and provable: **RecoveryTruth
establishes authoritative provider truth immediately before the
money-changing write and independently proves the exact postcondition
afterward.** The pre-write fence re-reads the exact Order and Payments at
the write boundary and blocks on any change; the postcondition is verified
by an independent fetch of the exact captured Payment; and the refusal side
carries its own provider-backed proof — in the recorded already-paid case,
`docs/testmode_evidence/testmode_safe_block_zero_write.json` shows Payment
Links stayed `0 -> 0`, so the blocked recovery object provably never
existed at the provider. Proving both the completed round trip and the
zero-write refusal is the combination not yet demonstrated elsewhere in
this field's public evidence.

## Rigor is no longer rare; the combination still is

Late in the field's public window, evaluation-first entries appeared in this
exact mandate niche: matched-world multi-arm harnesses, hashed frozen
configs, oracle ceilings, sealed test splits with committed hashes, paired
bootstrap confidence intervals, and self-published negative findings. One
strong general entry additionally validated its targeting estimation on a
large public randomized dataset. The claim "nobody else evaluates rigorously"
is therefore retired; this project should not make it.

What remains defensible is the combination no public rival holds at once:
nine policy arms spanning an entire relaxation frontier plus Razorpay's own
published schedule as a reason-blind reference arm; financial metrics defined
by whether a provider call happened, immune to the stop-spelling defect class;
a fixture whose latent harm is drawn independently of the failure reason, so
reason gating cannot win by construction — enforced by a release gate; swept
price curves as a reporting requirement rather than a single asserted lift;
a mutation-tested verification suite (found in no surveyed rival); and
external grounding on the execution-and-refusal axis — Test Mode execution
behind a pre-write fence, independently verified postcondition, and the
recorded `0 -> 0` zero-write refusal. Estimation grounded on external data
and execution proven against the real provider answer the same objection on
different axes; only the second exists in this repository, and it should be
claimed precisely as that.

## Disambiguation from same-named entries

At least one other public Buildathon entry independently chose the name
"MandateGuard" — an unsurprising collision, since mandate plus guard is the
obvious compound for a UPI AutoPay guardrail project. If a judge has seen two
MandateGuards, this one is identified by what only it does: nine policy arms
benchmarked on one frozen, hash-recorded outcome ledger; denials proven by
zero provider calls rather than described; a mutation-tested verification
suite; swept price curves instead of a single asserted uplift number; and a
README whose figures regenerate from committed `outputs/` rather than being
typed. Any claim in this repository can be recomputed from a clean checkout
with `./scripts/verify_all.sh`; that reproducibility, not the name, is the
identity of this project.

## What would weaken this position

Stated so it can be checked rather than discovered:

- If Revenue-Protect does validate configured retry strategies against attempt
  caps, pre-debit notice, consent and mandate state before execution, our
  contribution narrows to the counterfactual evaluation and the evidence chain.
  Those remain unaddressed in the published material, but the claim is smaller.
- If the retry engine leaves beta with per-decision audit artefacts, the
  evidence half of this project is subsumed and only the policy comparison
  harness survives.
- The frozen benchmark has never called Razorpay APIs. Every rupee result is a
  synthetic counterfactual over a synthetic local simulator, and the input
  adapter is Razorpay shaped rather than Razorpay connected. A separate
  RecoveryTruth path performs real Razorpay Test Mode reads and a Standard
  Payment Link fallback when `rzp_test_` keys are supplied; that path is
  currently VERIFIED_TEST_MODE_EVIDENCE_CAPTURED and refuses live keys.

## Sources

- Razorpay, "UPI Autopay with Intelligent Revenue-Protect",
  https://razorpay.com/blog/upi-autopay-with-intelligent-revenue-protect/
- Razorpay, "Introducing UPI AutoPay on Razorpay Subscriptions",
  https://razorpay.com/blog/what-is-upi-autopay-recurring-payments-razorpay-subscriptions/
- Razorpay, "Payment Retries" (Subscriptions),
  https://razorpay.com/docs/payments/subscriptions/payment-retries/
- Razorpay, Agent Studio, https://razorpay.com/agent-studio/
- Razorpay newsroom, Agent Studio launch at FTX'26, built on Anthropic's Claude
  Agent SDK, https://newsroom.razorpay.in/
  (The announcement's own superlative framing is not reproduced here; it is a
  vendor claim and this document does not adopt it.)
- Razorpay AI Buildathon track definitions, https://razorpay.com/buildathon/
