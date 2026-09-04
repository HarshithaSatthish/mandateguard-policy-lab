# Evidence that the failure mode is real

> Desk research conducted 24 August 2026 against public sources. This document
> exists so the problem statement is sourced rather than asserted.

## Read the sampling caveat before the numbers

Consumer complaint aggregators are **self-selected samples**. People with an
unresolved problem write reviews; satisfied users mostly do not. The ratings
below therefore say nothing about the rate at which any failure occurs, and
this project does not use them to estimate one.

What a self-selected sample *is* good for is establishing that a failure mode
**exists, recurs, and is describable** — that a category of problem is real
rather than invented to justify a project. That is the only load these sources
carry here. No figure below is used as an input to the benchmark, and no
MandateGuard metric is derived from them.

## What the public record shows

Two independent aggregators, different populations, consistent themes.

| Source | Sample | Rating |
|---|---|---|
| ConsumerComplaints.in | 3,556 complaints | 2.8 / 5 |
| PissedConsumer | 405 verified reviews | 1.7 / 5, 84% negative |

Recurring themes, ordered as the sources present them:

| Theme | ConsumerComplaints.in | PissedConsumer |
|---|---|---|
| Amount debited but not credited | most frequent | present |
| Refunds delayed or never received | present | most frequent |
| **Unexpected or unauthorised deductions** | present, via ACH and NACH | **second most frequent** |
| Settlement holds and account restrictions | present | present |
| **Auto-pay and subscription charges** | present | **fifth** |
| KYC or verification rejection | present | — |
| Support unresponsive or repetitive | present | present |

PissedConsumer's own generated summary of its review corpus advises readers to
"watch auto-pay and subscription charges closely and confirm integrations
before use."

## Why this matters for what MandateGuard measures

The documented direction of failure in recurring payments is **over-execution**:
debits that customers did not expect or did not believe they had authorised.
It is not merchants reporting that too little was recovered.

That is worth stating precisely because it is the opposite of how recovery
systems are usually scored. A recovery benchmark that optimises money recovered
is optimising against the direction the public record actually complains about.
MandateGuard's guardrail arms are scored on the metric that matches the
documented failure:

| Metric | What it counts |
|---|---|
| `protected_value_by_denial_inr` | Value of prohibited actions that never reached the provider |
| `realized_harm_inr` | Value of prohibited actions that did reach the provider |
| `prohibited_execution_rate` | Share of harm bearing cases the arm executed on anyway |

The benchmark reports these beside recovery rather than instead of it, because
refusing everything is not a product either. `legitimate_recovery_forgone_inr`
exists to keep the guardrails honest in the other direction.

## What the runtime does about the loudest complaint

The single most specific complaint pattern in the corpus is the same amount
debited several times in one day — reviewers describing a charge taken three or
four times over, and NACH debits firing after the balance was already repaid
manually. Whatever its cause in any individual case, it is a duplicate-execution
failure, and duplicate execution is something a runtime can be built to make
impossible rather than unlikely.

Three independent defences in this repository address it, and each is a
demonstrable beat in `scripts/demo60.py` rather than a claim:

| Defence | What it stops |
|---|---|
| Duplicate delivery detection | The same signed event redelivered any number of times produces at most one provider call. The demo delivers an identical failure four times and counts zero actionable |
| Delivery-order tolerance | A `payment.failed` that arrives *after* the cycle settled is refused as superseded, so a stale event cannot retry a debit that already succeeded |
| Terminal-state closure | Once a subscription reaches a cancelled, completed or halted event, nothing later reopens it |
| Idempotency keys | Two identical permitted actions reuse the original provider call rather than issuing a second |

None of this proves anything about how any specific complaint arose. It shows
that the failure mode those complaints describe is one this runtime is built to
refuse, which is the only claim a synthetic benchmark is entitled to make.

## What this evidence does NOT establish

Stated explicitly so the submission cannot be accused of overreaching:

- It does not establish a rate, a trend, or a comparison against any other
  payment provider.
- It does not attribute any individual complaint to a specific technical cause,
  to UPI AutoPay specifically, or to any defect in a Razorpay product. Many
  complaints on these platforms concern a merchant's own conduct with Razorpay
  named as the payment processor.
- It does not claim the complaints are representative, verified, or unresolved.
- It is **not** an input to any number in `outputs/`. The benchmark ledger is
  synthetic and its harm model is a declared project assumption, swept in
  `ROBUSTNESS.md`.

Its entire function is to answer one question a judge is right to ask: *is the
failure this project prevents a real one, or one you invented so your guardrails
would have something to catch?*

## Reddit corroboration (gathered by a different tool, links opened and confirmed by the submitter)

`npci.org.in` and Reddit are both unreachable to this project's own research
tooling, so a separate AI tool with live Reddit access was used to pull direct
permalinks and verbatim quotes. This session cannot fetch reddit.com itself and
so could not independently re-confirm the permalinks; the submitter opened the
links directly and confirmed they resolve and the quotes match, on 25 August
2026. That is real verification, done by a human against the live page, and is
a stronger provenance tier than this project's own automated research could
reach for this source. It is still worth a judge's own spot-check if the claim
is challenged, since no party besides the submitter has independently
confirmed it.

What came back corroborates the same failure
direction the aggregator data above shows, from a different population
(developers and founders integrating Razorpay, rather than end customers), and
surfaces one theme the complaint boards did not: **no automatic retry or
customer notification on a failed AutoPay debit**, reported by a merchant who
went looking for that capability and found nothing for Razorpay comparable to
what exists in the Stripe ecosystem —

> "when a UPI AutoPay debit fails, it looks like Razorpay just fires a webhook
> and that's it? no retry, no automatic message to the customer, nothing? [...]
> couldn't find anything similar for Razorpay"
> — r/micro_saas, [reddit.com/r/micro_saas/comments/1s0m63f](https://www.reddit.com/r/micro_saas/comments/1s0m63f/failed_upi_mandates_on_razorpay_whats_the/)

That is close to a direct statement of the gap this project's runtime exists
to fill, from someone with no connection to this submission.

Other recurring themes across independently-posted threads: webhook delivery
delay or ordering causing incorrect subscription state (r/nextjs, r/reactnative,
r/Razorpay — the same class of problem `bailiff/webhook.py`'s delivery-order
tolerance addresses), missing or undocumented mandate/token webhook events
(r/Razorpay), and episodic payment failures discussed by users as possible
outages with no official acknowledgement in the thread (r/Razorpay, two
independent comments), which lines up with the StatusGator finding below
rather than standing alone. Highest-engagement single thread found was a
settlement-hold complaint at 229 upvotes / 79 comments (r/indianstartups).

Two explicit negative findings, reported because a search that only reports
hits is not a search: no Reddit discussion of a duplicate-debit pattern was
found (the complaint-board data's most specific theme did not reproduce here),
and no Reddit discussion of Razorpay's Agent Studio product was found at all —
the closest adjacent material was general skepticism about agentic-checkout UX
and an unrelated hiring-model discussion, neither of which mentions Agent
Studio by name.

## Adjacent finding: status communication

StatusGator, which has monitored Razorpay since February 2022, assigns it an
"F" accuracy rating for status page communication — an average acknowledgement
delay of four hours or more — and records that the incidents it detected were
never officially acknowledged. This is not a MandateGuard problem and the
project makes no claim about it. It is noted only because it supports the
general design stance that **evidence a third party can verify is worth more
than a status assertion**, which is why every decision in this runtime carries
a hash-chained receipt rather than a log line.

## Sources

- ConsumerComplaints.in, Razorpay complaints board,
  https://www.consumercomplaints.in/razorpay-b115695
- PissedConsumer, Razorpay reviews,
  https://razorpay.pissedconsumer.com/review.html
- StatusGator, Razorpay status history,
  https://statusgator.com/services/razorpay
- Razorpay Docs, Downtime Updates,
  https://razorpay.com/docs/payments/payments/downtime-updates/
- Reddit threads cited in "Reddit corroboration" above, gathered 25 August
  2026 by a separate tool with live Reddit access, permalinks given inline;
  opened and confirmed to resolve by the submitter on the same date.
