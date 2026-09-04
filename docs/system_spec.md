# MandateGuard Policy Lab: Complete System Specification

## 1. Executive definition

MandateGuard is a policy evaluation laboratory and bounded execution runtime for scheduled UPI AutoPay debit failures. It is not a generic retry bot and it is not a replacement for Razorpay recovery products. It compares recovery policies on the same immutable event ledger, executes only through a deterministic authority gate, and reports both money recovered and legitimate recovery value that the controls deliberately refused.

> **The bounded interpreter interprets. The policy engine decides. The provider adapter executes. The audit chain proves.**

The central evaluation question is not “can an agent recover money?” The question is “which recovery policy recovers incremental value without silently expanding authority, violating consent, ignoring timing, or hiding the economic cost of abstention?”

## 2. Track and product position

The product is scoped to the scheduled AutoPay recovery problem: detect a failed scheduled debit, diagnose its reason, choose a bounded intervention, measure the outcome, and stop when authority or safety conditions require stopping.

Razorpay already has subscription recovery and retry capabilities. MandateGuard therefore does not claim that Razorpay lacks recovery. Its wedge is transparency and policy evaluation: an external lab that lets a merchant compare a naive retry schedule, deterministic retry policy, deterministic guarded policy, and bounded interpreter policy on a common ledger before deploying a rule.

The prototype accepts a Razorpay shaped scheduled AutoPay test payload through `bailiff.razorpay_adapter`. The adapter preserves provider error fields and payload hash, then normalizes them into the project taxonomy. Execution remains a local provider simulator for repeatable evidence. An optional OpenAI compatible bounded interpreter can interpret ambiguous payloads only; it receives no provider tools or credentials. No simulated result is production revenue and no live Razorpay API call is claimed.

## 3. Scope lock

The MVP accepts Razorpay shaped scheduled UPI AutoPay debit failure payloads in INR and also exposes the canonical normalized event contract for deterministic tests. It excludes one off UPI declines, card subscriptions, refunds, write offs, mandate creation, mandate cancellation, settlement reconciliation, partial payment, and unrestricted customer messaging.

The retry cap, non peak execution window, contact ceiling, confidence threshold, and amount threshold are versioned configuration. A rule is presented as an official external rule only when the relevant source is explicitly pinned and hashed. Otherwise the UI labels it as an official page, reported requirement, or project policy according to the provenance tier.

The normalized decline taxonomy is a project taxonomy. It is not claimed to be an official universal NPCI taxonomy.

## 4. Nine policy arms

The canonical order is fixed everywhere:

```text
B0, B1, B1.5, RZP, B2.25, B2.5, B2.75, B2, B3
```

| Arm | Description | Information | Guardrails | Purpose |
|---|---|---|---|---|
| B0 | No intervention | None | None | Measures total recoverable counterfactual left untouched |
| B1 | Ungated retry baseline | No reason inspection | None | Establishes the value and harm of naive retrying |
| B1.5 | Deterministic retry only | Normalized reason | None | Tests whether reason aware retry alone improves over B1 |
| B2.25 | Timing frontier | Normalized reason | Timing only | Exposes the effect of relaxing project policy gates |
| B2.5 | Timing plus attempt frontier | Normalized reason | Timing, retry gap, attempt budget | Exposes the incremental effect of attempt controls |
| B2.75 | Timing plus attempt plus consent frontier | Normalized reason | Timing, retry gap, attempt budget, consent and opt out | Exposes the incremental effect of consent controls |
| B2 | Deterministic guarded policy | Normalized reason and rule table | Full deterministic gate | Tests whether explicit policy is sufficient without AI |
| B3 | Bounded interpreter policy | Raw failure payload plus normalized context | Full deterministic gate | Tests whether interpretation improves ambiguous cases without gaining authority |

B1 and B1.5 are intentionally ungated baselines. Their simulated policy violations are measured by an independent checker. B2.25, B2.5, and B2.75 are diagnostic frontier arms. They never expand the action allowlist, identity, authority amount, authority expiry, or idempotency behavior, but they deliberately relax named project policy gates and must not be presented as safe production arms. B2 and B3 cannot call a provider until the same full guardrail engine allows the proposed action.

## 5. Failure taxonomy

Every fixture stores both the raw provider signal and a normalized project reason. The raw signal remains visible to the interpreter and audit record. The latent truth remains hidden from every arm and is used only for outcome scoring.

| Reason | Default class | Safe default |
|---|---|---|
| `INSUFFICIENT_FUNDS` | Transient | Retry only when authority, timing, consent, and pre debit rules pass |
| `BANK_TIMEOUT_OR_TEMPORARY_FAILURE` | Transient | Retry in a permitted future window when all gates pass |
| `MANDATE_REVOKED_OR_CANCELLED` | Terminal | Stop recovery |
| `ACCOUNT_CLOSED_OR_BLOCKED` | Terminal | Stop recovery or human review |
| `RISK_OR_FRAUD_REJECTED` | Human only | Escalate without automated money action |
| `CUSTOMER_OPTED_OUT` | Consent terminal | Stop automated contact and recovery |
| `UNKNOWN_OR_CONFLICTING` | Ambiguous | Abstain or escalate; ambiguity is not permission |

The raw code and description may disagree. B2 uses the deterministic normalized fixture label. B3 may interpret the raw payload, but the bounded interpreter may only return a reason and confidence or a bounded action proposal.

## 6. Event contract

Each event has stable identities for merchant, customer, mandate, scheduled execution, recovery case, and correlation. It includes amount in INR minor units, failure code, raw failure payload, normalized reason, mandate state, attempt count, MCC, pre debit state, consent state, event time, scheduled execution time, proposed execution time, and optional validity and prior attempt timestamps.

An event is rejected when it is not a scheduled AutoPay event, is not INR, has missing identifiers, has a negative amount, has a negative attempt count, or has an unknown normalized failure reason.

## 7. Authority envelope

The authority envelope is the narrowest executable authority for one correlated case. It contains allowed actions, maximum amount, attempts remaining, consent snapshot hash, expiry, mandate identity, scheduled execution identity, and recovery case identity.

Child envelopes may attenuate only:

| Field | Child may do |
|---|---|
| Allowed actions | Remove actions only |
| Amount ceiling | Reduce only |
| Attempts remaining | Reduce only |
| Expiry | Shorten only |
| Identity fields | Never change |

A child action may not broaden authority just because a workflow continues or because a bounded interpreter proposes it.

## 8. Guardrail contract

The deterministic guardrail engine checks the action before the provider adapter. The exact order is consent, authority allowlist, terminal case state, mandate state, authority expiry, consent channel, pre debit state, attempt cap, authority amount, proposed execution window, lead time, policy amount review, and action class.

| Guard | Required behavior |
|---|---|
| Consent and opt out | No automated contact when opted out or channel consent is absent |
| Mandate state | Active or enabled only; revoked, cancelled, paused, and expired cases cannot execute recovery |
| Attempt cap | Hard authority limit; a new retry after exhaustion is denied before provider |
| Non peak window | Proposed retry timestamp must be inside configured permitted windows |
| Pre debit notice | Required lead time unless explicitly configured MCC exemption applies |
| Amount | Execution amount cannot exceed the authority amount ceiling |
| Ambiguity | Unknown or low confidence diagnosis cannot authorize action |
| Terminal decline | Terminal reasons stop automated retry |
| Timeout | Unknown provider postcondition routes to human review before any new action |
| Idempotency | Exact replay reuses one provider result; a different action after terminal state is denied |

The three permitted non peak intervals currently configured for the benchmark are represented as data. They are before 10:00 IST, 13:00 to 17:00 IST, and after 21:30 IST. The exact external source status is preserved in provenance and is not silently promoted.

## 9. Provider shaped simulator

The provider simulator is not a fake claim of real payment execution. It exists to prove the execution boundary.

An allowed executable action creates one provider call ID, one idempotency key, one provider result, and one postcondition state. A denied action creates no provider call. An exact replay returns the original provider result and does not create a second call. A simulated timeout creates one call but leaves the postcondition unknown and transitions the case to human review.

The simulator determines recovery from the common ledger, not from the policy arm. This prevents one arm from receiving a different latent customer or bank outcome.

## 10. Audit and receipt

Every policy decision and provider event is appended to a hash chain. A receipt contains the decision ID, correlation ID, arm, proposed action, final action, reason codes, reason sources, provider call status, policy version, ledger hash, provenance block, and counterfactual financial values.

The audit tamper demo modifies an old event and runs verification. Verification must fail. The evidence layer is not allowed to recalculate or silently repair a modified historical event.

## 11. Metrics and economic objective

The benchmark reports both the value recovered and the value lost by being too strict. Amounts are shown in rupees after conversion from minor units.

| Metric | Definition |
|---|---|
| `incremental_recovered_inr` | Arm recovery minus B0 recovery on the same case ledger |
| `legitimate_recovery_forgone_inr` | Recoverable counterfactual value on which the arm made no provider call, whether it denied, stopped, escalated, or abstained |
| `protected_value_by_denial_inr` | Harm bearing value on which the arm made no provider call |
| `realized_harm_inr` | Harm bearing value on which the arm did make a provider call |
| `prohibited_execution_rate` | Harm bearing cases executed divided by harm bearing cases |
| `violations` | Count of executed simulated actions rejected by the independent checker |
| `recovered_per_permitted_action_inr` | Recovered INR divided by permitted executable actions |
| `human_review_cost_inr` | Human review count multiplied by configured review cost |
| `violation_cost_inr` | Independent violation count multiplied by the configured project violation cost |
| `net_value_inr` | Incremental recovered value minus violation cost, human review cost, and bounded interpreter cost |
| `net_value_harm_priced_inr` | Incremental recovered value minus realized harm times the harm multiplier, minus human review and bounded interpreter cost |
| `contacts_per_case` | Automated contact actions divided by cases |
| `provider_calls` | Actual simulator calls, not proposed actions |
| `model_cost_inr` | Measured bounded interpreter cost, not a hand typed estimate |

A policy that denies everything may have zero violations, but it will have high legitimate recovery forgone and low efficiency. That is why no single metric is a winner metric.

Every financial metric above is defined by whether a provider call actually happened. None of them branches on the symbolic name of the final action. This is deliberate. The ungated baseline path and the guardrail path represent a stop with different symbols, so a metric keyed on that symbol silently drops the guarded arms' stops and escalations and stops being comparable across arms. An earlier revision of this specification did key `legitimate_recovery_forgone_inr` on the symbol, which produced the impossible reading that B1.5 recovered more than B2 while also forgoing more than twice as much legitimate recovery.

`protected_value_by_denial_inr` and `realized_harm_inr` partition the total harm bearing value on every arm, so the two always sum to the same constant within a regime and seed. That identity is asserted in the test suite.

### Pricing a prohibited action

`net_value_inr` and `net_value_harm_priced_inr` encode two different theories of what a control is for, and the benchmark reports both rather than choosing.

The flat pricing charges `violation_cost_inr` per independently detected breach, regardless of the sum at stake. It is auditable but indifferent to amount, so it systematically under prices a prohibited large debit and over prices a prohibited small one.

The harm pricing charges the money the prohibited action actually moved, times `harm_multiplier`. The default multiplier of 1.0 is a lower bound rather than an estimate: a prohibited debit must at minimum be reversed, and penalty, chargeback, remediation, and reputational cost are all excluded from it.

Because the arm ordering is a joint property of the policies and of this price, `bailiff/sensitivity.py` sweeps both prices across a grid and records which arm wins at each point. The reported economic claim is therefore a threshold with a stated crossover, never an unconditional verdict. The release gate rejects a run whose recommended arm is invariant across the entire swept range, because a recommendation that never changes with its own price assumption is a constant rather than a finding.

## 12. Benchmark design

The runner generates one event set and one common outcome ledger for every regime and seed. It freezes the ledger hash before executing B0, B1, B1.5, RZP, B2.25, B2.5, B2.75, B2, and B3. No arm may call the generator independently.

The regimes are:

| Regime | Purpose |
|---|---|
| `R1_TRANSIENT` | Shows the economic cost of excessive stopping on recoverable transient failures |
| `R2_TERMINAL` | Shows the value of blocking retries against revoked, closed, risk, and opted out cases |
| `R3_AMBIGUOUS` | Tests whether the bounded interpreter improves interpretation or safely abstains |

The public final protocol uses twenty fixed seeds. Development runs may use five or more seeds, but a development manifest must never be presented as the final benchmark. The final manifest records seed list, regime list, case count, dataset hash, policy version, rules version, and final status.

Each aggregate reports mean, population standard deviation, minimum, maximum, and spread for incremental recovered INR, legitimate recovery forgone, protected value, realized harm, prohibited execution rate, violations, efficiency, abstention, review cost, net value under both pricings, contacts, provider calls, and interpreter cost.

### Latent harm generation

Compliance exposure in the fixture is drawn independently of the normalized failure reason. This is the load bearing property of the whole benchmark.

If latent harm were a pure function of the reason code, an arm gating on the reason code alone would capture every unit of harm avoidance by construction. Every control above it could then only destroy recovery, and the benchmark would return a fixed answer before any policy executed. An earlier revision did generate harm that way, and its symptom was visible in the output: `protected_value_by_denial_inr` was numerically identical for the no intervention control and for the full guardrail arms in every regime.

Real scheduled AutoPay exposure does not behave that way. A bank can return insufficient funds on a mandate the customer separately paused, on a customer who separately opted out, on an attempt already past the authority cap, or without a valid pre debit notice. Those states are visible only to the full guardrail profile, so the fixture draws them from independent draws with documented rates. Severity is expressed as a conditional harm probability per state, ordered so that executing against a dead mandate or an opted out customer is near certainly harmful while a peak window breach is largely an operational rule. These severities are project assumptions and are reported as such.

## 13. Holdout and anti gaming

The final holdout is generated once, hashed, and treated as immutable. Any mutation causes evaluation to fail before results are accepted.

The checker uses positive control fixtures. If guarded arms report zero violations, the positive controls must still prove that the checker can detect prohibited actions. Excessive abstention is a build failure. B3 must show nonzero interpreter influence and abstention on the ambiguous regime, while B3 failing to beat B2 is an honest result and must be displayed, not hidden.

## 14. API contract

The minimal implementation exposes these endpoints after the deterministic command line benchmark is reproducible. The API stores a frozen ledger per experiment and verification recomputes its dataset hash rather than checking only that a hash field exists:

| Endpoint | Purpose |
|---|---|
| `POST /experiments` | Create an experiment with `pid_b0`, `pid_b1`, `pid_b1_5`, `pid_b2_25`, `pid_b2_5`, `pid_b2_75`, `pid_b2`, and `pid_b3` in canonical order |
| `POST /experiments/{id}/run` | Execute a frozen ledger through selected arms |
| `GET /experiments/{id}/metrics` | Return all economic, safety, reproducibility, and interpreter metrics |
| `GET /experiments/{id}/cases/{case_id}` | Return one counterfactual case view |
| `GET /experiments/{id}/audit` | Return chain verified receipts and provider call evidence |
| `POST /experiments/{id}/verify` | Recompute dataset, output, and audit hashes |

The API must not accept an action request that bypasses the policy engine. The experiment run contract accepts `interpreter_mode` as either `deterministic_offline` or `real_optional`; it never accepts provider credentials or unrestricted tools. The real optional mode calls the bounded interpreter only for ambiguous B3 cases and still routes the resulting proposal through the same guardrail engine.

## 15. Four evidence screens

The minimum user interface is deliberately small.

| Screen | Required content |
|---|---|
| Control Room | Regime totals, arm selector, incremental recovery, forgone value, protected value, violations, and seed spread |
| Case Timeline | Event, raw signal, normalized reason, proposal, guard decision, provider result, postcondition, and audit hashes |
| Policy Compare | B0, B1, B1.5, RZP, B2.25, B2.5, B2.75, B2, B3 side by side for one case and aggregate metrics |
| Failure and Audit | Tampered event failure, zero provider call denial, timeout postcondition, and authority attenuation proof |

If time becomes constrained, the command line report and receipts take priority over visual polish.

## 16. Repository contract

The public repository must contain:

```text
mandateguard-policy-lab/
├── README.md
├── app.py                 # optional read only Streamlit evidence UI
├── pyproject.toml
├── .env.example
├── LICENSE
├── bailiff/
│   ├── domain.py
│   ├── state.py
│   ├── replay.py
│   ├── guardrails.py
│   ├── checker.py
│   ├── fixtures.py
│   ├── policies.py
│   ├── metrics.py
│   ├── runner.py
│   ├── report.py
│   ├── api.py
│   ├── interpreter.py
│   ├── razorpay_adapter.py
│   ├── rules.py
│   ├── rules.json
│   └── demo.py
├── tests/
│   ├── test_core.py
│   ├── test_updated_system.py
│   ├── test_api.py
│   ├── test_hostile_contract.py
│   └── test_provider_and_interpreter.py
├── scripts/
│   ├── evaluate.sh
│   ├── make_findings.py
│   ├── make_frontier.py
│   ├── release_check.sh
│   └── test.sh
├── docs/
│   ├── system_spec.md
│   └── submission_checklist.md
├── FINDINGS.md
└── outputs/
    └── compact generated benchmark artifacts; full evidence is local only
```

The repository must run from a clean checkout with no private Rakshex dependency and no required network call for the deterministic benchmark. The versioned rule catalog is stored in `bailiff/rules.json` and loaded by `bailiff/rules.py`; generated reports and receipts must be derived from the same runtime outputs.

## 17. Submission narrative

The opening sentence is:

> MandateGuard compares recovery policies on the same hidden scheduled AutoPay failure ledger, proves every denied action, prevents authority expansion, and measures actual incremental recovered INR alongside legitimate recovery forgone.

The video starts with a denied retry receipt showing zero provider calls. It then shows an allowed retry with a provider call and postcondition, the nine arm counterfactual view, the timeout and audit tamper demonstrations, and finally the multi seed metrics table plus generated frontier chart.

The Rakshex story is narrow: an earlier authority attenuation bug showed that child actions could accidentally gain broader authority. MandateGuard carries that lesson into recurring recovery. Do not feature dump Rakshex.

Do not say that Razorpay lacks recovery. Do not call the synthetic result production revenue. Do not call the project failure taxonomy an official NPCI taxonomy. Do not call a retry cap or timing window an official rule unless the exact primary source is pinned and hashed.

## 18. Final acceptance gates

The project is submission ready only when all of these are true:

1. Clean checkout installs and runs the tests.
2. The nine policy arms appear in canonical order everywhere.
3. The same immutable ledger hash is consumed by every arm.
4. Expired, opted out, exhausted, out of window, over amount, and ambiguous actions are denied or abstained before provider calls.
5. One allowed action produces exactly one provider call and postcondition.
6. Exact replay produces no duplicate call.
7. A different action after a terminal state is denied.
8. Timeout with unknown postcondition reaches human review.
9. Child authority cannot widen.
10. Audit tampering fails verification.
11. The independent checker positive controls pass.
12. Final holdout and twenty seed outputs are generated and hashed.
13. README metrics are generated from output files and contain no unresolved tokens.
14. The final report includes incremental recovered, legitimate forgone, protected value, realized harm, efficiency, violations, abstention, net value under both pricings, break even analysis, the swept price curves and their crossovers, frontier arms, and spread.
15. Legitimate recovery forgone is monotone in policy strictness, protected value by denial discriminates between arms, no fully guarded arm records nonzero realized harm, and the ungated baseline does record prohibited execution.
16. The shipped evidence is a deterministic sample with a manifest, while full evidence is generated locally and excluded from release.
17. The frontier chart and generated FINDINGS.md are reproducible from the final aggregate outputs. The frontier plots incremental recovery against realized harm rather than against violation counts, because a flat count is indifferent to the size of the debit it counts, and it marks dominated arms explicitly.
18. The video shows the actual final commit and generated outputs.
19. The Razorpay shaped adapter preserves provider signal and payload hash without claiming a live API call.
20. The optional real interpreter path uses schema validation, records model usage and cost, exposes no provider tools, and fails closed to ABSTAIN.

## 19. Build order

| Phase | Deliverable |
|---|---|
| 0 | Git repository, clean checkout scripts, CI, and no secret dependency for offline runs |
| 1 | Event schema, decline taxonomy, and fixture generator |
| 2 | Common ledger persistence and hash manifest |
| 3 | Provider shaped simulator, timeout, postcondition, and idempotency |
| 4 | Deterministic guardrail fixes and independent checker |
| 5 | B0, B1, B1.5, RZP, frontier arms, B2, and B3 runners |
| 6 | Forgone and protected metrics, efficiency, review cost, violation cost, net value, and aggregate statistics |
| 7 | Hidden holdout, twenty seed final run, output hashes, and report generation |
| 8 | B3 bounded interpreter with strict output validation and measured influence |
| 9 | API receipts and four evidence screens |
| 10 | Failure Lab, video, final clean checkout, and submission |

No new feature should be added before the acceptance gates above are green.

## 20. Source classification

The public NPCI AutoPay page is the baseline public source for recurring mandate controls and pre debit notification information. Retry caps and non peak windows are represented as configurable rules with source metadata until the precise primary circular PDFs are locally pinned and hashed. The project does not convert a secondary report into an official claim by repetition.

## References

[1]: https://www.npci.org.in/product/autopay "NPCI UPI AutoPay product page"

[2]: https://www.npci.org.in/circulars/upi "NPCI UPI circulars index"
