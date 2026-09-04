# MandateGuard Selection Review Resolution

## Verdict

MandateGuard is a narrow, auditable policy laboratory and bounded runtime for scheduled UPI AutoPay debit failures. The architecture is suitable for a serious hackathon submission because it compares nine policy arms on the same ledger, applies deterministic authority controls before provider execution, and measures both recovered value and legitimate recovery forgone.

The repository has been reviewed from the perspective of a hostile judge, an engineering selector, a Razorpay product reviewer, and a competitor. The material findings from that review are resolved in the current implementation as described below.

## Architecture contract

| Layer | Current implementation | Judge evidence |
|---|---|---|
| Event layer | Razorpay shaped scheduled AutoPay payload adapter preserves provider error fields and payload hash, then produces a schema checked event with stable identities, decline taxonomy, MCC, consent, timing, and pre debit fields | Adapter, fixture, and schema tests |
| Common ledger | One deterministic ledger per regime and seed, reused by all nine arms | Shared ledger hash in every evidence row |
| Policy layer | B0, B1, B1.5, RZP, B2.25, B2.5, B2.75, B2, B3 in canonical order | Policy runner and aggregate output |
| Authority layer | Attenuating envelope with action, amount, attempt, expiry, and identity constraints | Guardrail and authority tests |
| Guardrail layer | Consent, mandate, timing, retry gap, attempt, amount, pre debit, ambiguity, and terminal gates | Independent checker and zero call proofs |
| Provider layer | Offline: Razorpay shaped input boundary plus simulated provider call ID, idempotency, timeout, postcondition, and recovery result. That adapter does not call Razorpay. Test Mode reads and Standard Payment Link fallback are a separate RecoveryTruth client. | Direct demo and adapter tests |
| Evidence layer | Compact shipped sample with per decision receipts, plus locally generated full evidence with ledger hash, audit hashes, provenance, and financial attribution | `outputs/evidence_ledger.json` and `outputs/evidence_manifest.json` |
| Evaluation layer | Twenty seed final protocol with mean, standard deviation, range, holdout manifest, metric comparability gates, and anti gaming gate | `outputs/aggregate.json` and `outputs/manifest.json` |
| Economic layer | Two pricings of a prohibited action, swept across a grid, with the crossover generated rather than asserted | `outputs/sensitivity.json` and `outputs/sensitivity.png` |
| API layer | Frozen in memory experiment ledger reused by run, metrics, case, audit, and verify endpoints, with Razorpay shaped input metadata and deterministic or optional real interpreter mode | API acceptance tests |

## Policy arm breakdown

| Arm | Role | Authority | Interpretation | Expected lesson |
|---|---|---|---|---|
| B0 | No intervention control | No action | None | Measures recoverable value left untouched |
| B1 | Ungated retry baseline | Retry without deterministic gate | No diagnosis | Shows the recovery and violation cost of naive retrying |
| B1.5 | Deterministic retry only | Retry only for normalized transient reasons, still ungated | Deterministic reason | Separates reason awareness from full guardrails |
| B2.25 | Timing frontier | Timing gate with named project policy relaxations | Deterministic reason | Exposes the recovery and violation tradeoff from timing alone |
| B2.5 | Timing plus attempt frontier | Timing, retry gap, and attempt gate | Deterministic reason | Exposes the incremental effect of attempt controls |
| B2.75 | Timing plus attempt plus consent frontier | Timing, retry gap, attempt, and consent gates | Deterministic reason | Exposes the incremental effect of consent controls |
| B2 | Deterministic guarded policy | Full authority and safety gate | Deterministic reason | Establishes the strongest non interpreter policy |
| B3 | Bounded interpreter policy | Same full gate as B2 | Raw payload interpretation only | Tests whether interpretation changes ambiguous cases without gaining authority |

B1 and B1.5 remain intentionally unsafe baselines. Their violations are measured, not hidden. B2 and B3 are the arms that can execute only after the deterministic gate allows the proposed action. B3 uses a deterministic offline bounded interpreter implementation in the reproducible benchmark. Its influence is recorded. The optional real model path accepts only strict schema output, records model name, calls, tokens, and cost, exposes no provider tools, and remains behind the same output validator and authority gate. Model failure fails closed to ABSTAIN.

## Resolved hostile findings

The final code now gives every arm at least a decision receipt and provider or denial receipt. Evidence rows carry the ledger hash, audit event hashes, audit verification status, provenance map, legitimate recovery forgone value, protected value, and bounded interpreter influence.

The API now freezes its experiment ledger. Adding final seeds extends the frozen set without regenerating an existing seed. Running an experiment uses those stored ledgers. Case views return all available arm rows. Verification recomputes the dataset hash and reports artifact hashes.

Timing is represented as configured data. The runtime enforces the three configured non peak intervals, the minimum retry gap, the hard attempt cap, and the configured MCC pre debit exemption. The external source tier remains visible, and no unsupported universal regulatory claim is made.

The bounded interpreter callback is now actually used by B3 only for ambiguous or conflicting signals. Its output must be a valid project reason and a confidence between zero and one. Low confidence, malformed output, unavailable model, or invalid model response emits an explicit `ABSTAIN`, routes to human review, and makes zero provider calls. The abstention rate, interpreter influence, model usage, and model cost are included in the aggregate output. The demo begins from a Razorpay shaped payload and shows allowed recovery, denial, ABSTAIN, timeout, and audit tamper-evident verification.

The generated report is based on output files. It exposes incremental recovery, legitimate recovery forgone, protected value by denial, violations, efficiency, abstention, interpreter influence, audit completeness, configured violation and review costs, net value, break even thresholds, and frontier recommendations. The release gate rejects conflicts, placeholders, missing final arms, insufficient seeds, missing executable scripts, missing compact evidence metadata, and failed tests.

## Resolved measurement findings

A later review of the generated evidence found two defects that made the benchmark unreadable regardless of how sound the runtime was. Both are fixed and both are now release gates.

The first was a metric comparability defect. `legitimate_recovery_forgone_inr` counted forgone value only when the final action was the null symbol. The ungated baseline path spells a stop that way, but the guardrail path spells it `STOP_RECOVERY` or `ESCALATE_TO_HUMAN`, so the guarded arms silently dropped their stops and escalations out of the metric the project leads with. The visible symptom was an impossible reading in the ambiguous regime, where B1.5 recovered more than B2 and also reported more than twice the legitimate recovery forgone. Every financial metric is now defined by whether a provider call actually happened, and the release gate rejects a run in which forgone value is not monotone in policy strictness.

The second was a fixture design defect with a larger consequence. Latent harm was a pure function of the normalized failure reason, so B1.5, which gates on exactly that reason, captured all harm avoidance by construction. Every gate above it, attempt cap, pre debit notice, timing, retry gap, and amount ceiling, was uncorrelated with harm and could therefore only destroy recovery. The benchmark's headline result, that the ungated deterministic arm was recommended in all three regimes, was not a finding about recovery policy but a restatement of how the data was generated. The giveaway was in the report: protected value by denial was numerically identical for the no intervention control and for the full guardrail arms. Compliance exposure is now drawn independently of the reason, and the release gate rejects a fixture in which protected value fails to discriminate between arms.

The third finding was presentational rather than a defect. The entire economic recommendation rested on one configured violation cost with no stated sensitivity, and that cost priced an event with no modelled consequence anywhere in the simulator. Prohibited actions are now priced against the money they actually moved, both pricings are reported, and the swept curve and its crossover are generated rather than asserted.

## Remaining honest limitations

The offline input adapter is Razorpay shaped and does not call Razorpay APIs; its provider is a synthetic local simulator. Separately, RecoveryTruth's Test Mode path does perform real Razorpay Test Mode reads and a Standard Payment Link fallback when credentials exist. No production customer is contacted and no production money is moved. Test Mode status is VERIFIED_TEST_MODE_EVIDENCE_CAPTURED.
 The API is in memory and does not provide production authentication or durable storage. The visual interface is a read only evidence presentation layer over generated outputs, not a production dashboard. The benchmark is a synthetic counterfactual evaluation, not a claim about observed Razorpay revenue. Violation and human review prices are project assumptions, not provider pricing.

B3 is not presented as superior by default. If the bounded interpreter ties B2, the result is shown honestly. The point is that it cannot bypass authority, not that an AI call must win every synthetic regime.

## Selection recommendation

Submit the clean release only after running the exact commands from a fresh extraction:

```bash
./scripts/test.sh
./scripts/demo.sh
./scripts/evaluate.sh
./scripts/release_check.sh
```

The recommended video order is denied action with zero provider calls, allowed action with provider call and postcondition, nine arm counterfactual case, timeout to human review, explicit ABSTAIN, audit tampering, frontier chart, sensitivity crossover chart, and final generated metrics.

The strongest selection sentence is:

> MandateGuard compares recovery policies on the same hidden scheduled AutoPay failure ledger, proves every denied action, prevents authority expansion, and measures incremental recovered INR alongside the legitimate recovery it forgoes and the prohibited value it refuses to move. It reports the exact price at which the controls start paying for themselves rather than asserting that they always do.
