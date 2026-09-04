# MandateGuard findings

> This file is generated from `outputs/manifest.json`, `outputs/aggregate.json`, and `outputs/breakeven.json`. It is not a hand typed performance claim.

## Result

MandateGuard compares bounded recovery policies on the same deterministic scheduled UPI AutoPay failure ledger. The benchmark measures incremental simulated recovery, legitimate recovery forgone, protected value by denial, realized harm, independent violations, human review cost, model cost, and net value.

There is no single recommended arm, because the ordering depends entirely on what a prohibited action is assumed to cost. Two pricings are reported. The flat pricing charges a fixed sum per detected breach. The harm pricing charges the money the prohibited action actually moved. The crossover between them is reported rather than hidden, so a reader who disagrees with the project assumption can read their own answer off the swept curve in `outputs/report.md`.

Manifest dataset hash: `cbf161e2c06c35682b696e2d3bb50c54b27c35ad28aae7a63e85bb9343ef5b4e`
Rules hash: `70e2909d26598695f74ae9e4d5c81dabb4c772d1f6d376d6567923cdc8a52506`
Seeds: `20`
Cases per seed and regime: `100`
Configured violation cost: `₹50.00`
Configured human review cost: `₹0.00`
Configured harm multiplier: `1.00` times the amount a prohibited action moved

| Regime | Recommended arm (flat cost) | Recommended arm (harm priced) | Guarded arm wins at | B2 incremental recovery | B1 realized harm | B2 realized harm | B3 abstention rate | B3 interpreter influence |
|---|---|---|---:|---:|---:|---:|---:|---:|
| R1_TRANSIENT | B1.5 | B3 | 1.00x harm | ₹6,386.15 | ₹32,806.05 | ₹0.00 | 0.0240 | 9.00 |
| R2_TERMINAL | B1.5 | B1.5 | 1.50x harm | ₹2,536.15 | ₹53,037.05 | ₹0.00 | 0.0250 | 8.90 |
| R3_AMBIGUOUS | B1.5 | B3 | 1.00x harm | ₹3,016.20 | ₹36,801.25 | ₹0.00 | 0.1205 | 29.10 |

Across every guarded seed-regime run in this release, the full guardrail arms recorded **0 independent violations and 0 runs with realized harm out of 120 runs** (B2 and B3, 20 seeds, 3 regimes). This line is computed from `outputs/per_seed.json` at generation time, not typed.

## Economic thresholds derived from the run

| Regime | B2 versus B1 break even violation cost | B1 to B1.5 marginal recovery cost per violation avoided | B1.5 to B2 marginal recovery cost per violation avoided |
|---|---:|---:|---:|
| R1_TRANSIENT | ₹72.81 | ₹5.16 | ₹221.83 |
| R2_TERMINAL | ₹30.65 | ₹2.37 | ₹231.79 |
| R3_AMBIGUOUS | ₹29.93 | ₹1.26 | ₹192.68 |

## Interpretation

A recommendation is conditional, not universal. Changing the violation cost, harm multiplier, human review cost, model cost, fixture regime, or policy rules can change the recommended arm, and the swept curves show exactly where it changes. The intermediate arms are diagnostic relaxations that expose where recovery and safety trade off. They are not presented as production safe defaults.

The honest reading of the tables above is that guardrails do not pay for themselves at every price. Under a flat per breach charge at the configured value, reason gating alone is competitive, because a flat charge is indifferent to the size of the debit it is pricing. The guarded arms win once a prohibited action is charged the money it actually moved. That crossover is the substantive claim, and it is stated as a threshold rather than as a verdict.

The latent harm model is the load bearing assumption. Compliance exposure is drawn independently of the failure reason, so an arm that reads only the reason code cannot capture harm avoidance by construction. An earlier revision of this benchmark did make harm a pure function of the reason code, which guaranteed that reason gating would win before any policy ran. `scripts/check_release.py` now rejects that shape of fixture.

B2 and B3 retain the full guardrail profile. B3 is a bounded interpreter path, not a live autonomous payment model. It can interpret only the ambiguous subset, cannot call a provider, cannot widen authority, and emits `ABSTAIN` when validated confidence is below the configured threshold. An abstention routes to human review and makes zero provider calls.

## Limitations

The ledger is synthetic and deterministic. INR values are simulated counterfactual attribution, not production revenue, merchant collections, or Razorpay performance. The failure taxonomy is a project taxonomy and must not be described as an official universal NPCI taxonomy. Rule values are versioned project configuration with provenance tiers. This benchmark does not establish regulatory approval, production readiness, causal customer behavior, or superiority over any named competitor.

## Falsification criteria

The core engineering claim is falsified for a release if any arm consumes a different ledger hash for the same seed and regime, if a denied or abstained money action reaches the provider, if the full guardrail B2 or B3 arm records an independent violation, if the audit chain is incomplete, if the frozen dataset hash changes during verification, or if B3 cannot show interpreter influence and nonzero abstention on the ambiguous regime. The measurement claim is additionally falsified if legitimate recovery forgone is not monotone in policy strictness, if protected value by denial is identical across every gated arm, or if the ungated baseline records no prohibited execution. The economic recommendation is falsified whenever its configured costs are changed without recomputing the report, or whenever the recommended arm is invariant across the entire swept price range.

## Reproduction

Run `./scripts/test.sh` for the clean package tests. Run `./scripts/evaluate.sh` to regenerate the final benchmark, economic analysis, frontier chart, and this document. The generated outputs and manifest hashes are the evidence surface.
