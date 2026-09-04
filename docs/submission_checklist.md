# MandateGuard submission checklist

## Release gate

Run these commands from the repository root on a clean checkout:

```bash
python3 -m pip install -e '.[test]'
./scripts/test.sh
./scripts/demo.sh
./scripts/evaluate.sh
./scripts/release_check.sh
```

Before the final submission, run the deep gate instead. It adds the mutation check and the fixture assumption sweep, and takes a few minutes:

```bash
./scripts/verify_all.sh
```

The release is not submittable if any mutation survives the suite, because a surviving mutation means the safety tests cannot detect the defect they are named after. It is also not submittable if `ROBUSTNESS.md` is absent or stale, because the economic conclusion is assumption dependent and the submission must say so in generated numbers rather than in prose.

The release is acceptable only when all commands exit with status zero, the complete test suite passes, and the demo prints a Razorpay shaped input, denied action with zero provider calls, allowed action with one provider call, explicit B3 ABSTAIN with zero provider calls, timeout with human review, and tamper result `before=True, after=False`. The optional interpreter mode is validated separately with the interpreter extra and an OpenAI compatible environment.

## Final artifact checks

The final manifest must contain `final: true`, the policy arms `B0, B1, B1.5, RZP, B2.25, B2.5, B2.75, B2, B3`, at least 20 fixed seeds, three regimes, a dataset count equal to seeds multiplied by regimes, a `harm_multiplier`, and `harm_model: compliance_exposure_independent_of_failure_reason`. The generated report must contain incremental recovered INR, legitimate recovery forgone INR, protected value by denial, realized harm, efficiency, violations, abstention, net value under both pricings, break even analysis, the swept price curves, frontier arms, and seed spread. No report number may be typed manually into the README.

The release gate additionally rejects a run in which legitimate recovery forgone is not monotone in policy strictness, in which protected value by denial is identical across every gated arm, in which a fully guarded arm records nonzero realized harm, in which the ungated baseline records no prohibited execution, or in which the recommended arm never changes across the entire swept price range. Each of these rejects a specific way the benchmark could look rigorous while measuring nothing.

The release archive must not contain `.git`, merge conflict markers, unresolved placeholders, Python cache directories, egg info directories, environment secrets, a private Rakshex dependency, or `outputs/generated/evidence_ledger_full.json`. It must contain `bailiff/razorpay_adapter.py`, `bailiff/interpreter.py`, and the adapter/interpreter tests. The compact `outputs/evidence_ledger.json` must agree with `outputs/evidence_manifest.json`. The primary scripts and `release_check.sh` must retain executable mode `755`. Demo outputs must live under `outputs/demo/` and must not overwrite the final manifest.

## Video sequence

Finish the metrics segment on the generated sensitivity chart, naming the crossover multiplier at which the fully guarded arms overtake reason gating alone. Do not claim the guarded arms win at every price; the report shows they do not.

Start at zero seconds with the denied retry receipt from a Razorpay shaped input. Show the provider error signal, normalized project reason, decision reason, provenance, authority envelope, and provider call count of zero. Show the allowed retry next, including the provider call ID and postcondition. Then show one case in the B0, B1, B1.5, RZP, B2.25, B2.5, B2.75, B2, and B3 counterfactual comparison. Finish with explicit B3 ABSTAIN on an ambiguous case, timeout to human review, audit tampering failure, the generated frontier chart, and the 20 seed report.

## Claims discipline

Treat the violation cost, harm multiplier, human review cost, retry cap, timing windows, confidence threshold, and amount threshold as versioned project configuration unless the exact primary source is pinned and hashed. State the recommendation as a threshold with its crossover, never as an unconditional verdict. Never call the intermediate frontier arms safe production policies. Never call ABSTAIN a recovery action: it is a bounded interpreter stop that routes to human review with zero provider calls.

Describe the data as synthetic counterfactual simulation. Do not call it production revenue or claim live Razorpay recovery. Describe the failure taxonomy as a project taxonomy. Describe retry and timing controls according to their recorded provenance tier. Do not state that Razorpay lacks subscription recovery. Describe MandateGuard as a transparent policy evaluation and bounded runtime layer that can complement existing recovery capabilities.

## Judge answer

The product has a narrow answer to a practical question that a shipped, configurable retry engine creates rather than removes: before a merchant deploys a recovery configuration, can they prove what it recovers, what legitimate value it forgoes, how much prohibited value it moves, and that every denied or abstained action truly made zero provider calls?

Razorpay already ships recovery for UPI AutoPay. This project is positioned underneath that, as the evaluation harness and bounded runtime, not as a competitor to it. Read `docs/competitive_position.md` before the panel and be ready to state the division of labour in one sentence. Be equally ready to say what would weaken the position; that document lists it.

For the frozen offline benchmark, the payload adapter is Razorpay shaped, execution remains a local simulator, and the numbers remain synthetic. RecoveryTruth is a separate Razorpay Test Mode path (real Test Mode reads + Standard Payment Link fallback, not AutoPay retry) and is currently VERIFIED_TEST_MODE_EVIDENCE_CAPTURED.

## Claims that must not be made

Do not say Razorpay lacks subscription recovery. It does not lack it, and the submission says so first.

Do not describe the complaint evidence in `docs/problem_evidence.md` as a rate, a trend, or a comparison against another provider. It is a self-selected sample and establishes only that the failure mode recurs and is describable.

Do not present a recovery figure as the headline. The ungated arms beat the guarded arms on recovery in this benchmark, and the report says so.
