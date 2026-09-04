# Generated benchmark report

> All amounts below are simulated counterfactuals from the frozen ledger, not production revenue.
> Violation and human review costs are configurable project assumptions, not Razorpay or NPCI pricing.

Manifest: `cbf161e2c06c35682b696e2d3bb50c54b27c35ad28aae7a63e85bb9343ef5b4e`
Seeds: `20`
Cases per seed and regime: `100`
Configured violation cost: `₹50.00` per independent violation
Configured human review cost: `₹0.00` per review

| Regime | Arm | Incremental recovered | Legitimate recovery forgone | Protected value by denial | Realized harm | Violations | Net value (flat) | Net value (harm priced) | Recovered per permitted action | Abstention rate | Interpreter influence | Audit incomplete |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R1_TRANSIENT | B0 | ₹0.00 | ₹37,093.45 | ₹32,806.05 | ₹0.00 | 0.00 | ₹0.00 | ₹0.00 | ₹0.00 | 0.0000 | 0.00 | 0.00 |
| R1_TRANSIENT | B1 | ₹21,287.45 | ₹0.00 | ₹0.00 | ₹32,806.05 | 204.65 | ₹11,054.95 | ₹-11,518.60 | ₹212.87 | 0.0000 | 0.00 | 0.00 |
| R1_TRANSIENT | B1.5 | ₹20,560.95 | ₹5,845.20 | ₹18,521.15 | ₹14,284.90 | 63.90 | ₹17,365.95 | ₹6,276.05 | ₹310.61 | 0.0000 | 0.00 | 0.00 |
| R1_TRANSIENT | RZP | ₹12,941.30 | ₹13,094.40 | ₹13,776.40 | ₹19,029.65 | 85.80 | ₹8,651.30 | ₹-6,088.35 | ₹194.42 | 0.0000 | 0.00 | 0.00 |
| R1_TRANSIENT | B2.25 | ₹15,889.90 | ₹12,565.50 | ₹22,240.70 | ₹10,565.35 | 42.15 | ₹13,782.40 | ₹5,324.55 | ₹311.23 | 0.0000 | 0.00 | 0.00 |
| R1_TRANSIENT | B2.5 | ₹8,323.15 | ₹23,526.90 | ₹28,634.40 | ₹4,171.65 | 7.70 | ₹7,938.15 | ₹4,151.50 | ₹309.06 | 0.0000 | 0.00 | 0.00 |
| R1_TRANSIENT | B2.75 | ₹7,789.40 | ₹24,305.20 | ₹29,704.75 | ₹3,101.30 | 5.15 | ₹7,531.90 | ₹4,688.10 | ₹318.78 | 0.0000 | 0.00 | 0.00 |
| R1_TRANSIENT | B2 | ₹6,386.15 | ₹27,421.65 | ₹32,806.05 | ₹0.00 | 0.00 | ₹6,386.15 | ₹6,386.15 | ₹325.54 | 0.0000 | 0.00 | 0.00 |
| R1_TRANSIENT | B3 | ₹6,473.35 | ₹26,470.40 | ₹32,806.05 | ₹0.00 | 0.00 | ₹6,473.35 | ₹6,473.35 | ₹303.73 | 0.0240 | 9.00 | 0.00 |
| R2_TERMINAL | B0 | ₹0.00 | ₹19,492.00 | ₹53,037.05 | ₹0.00 | 0.00 | ₹0.00 | ₹0.00 | ₹0.00 | 0.0000 | 0.00 | 0.00 |
| R2_TERMINAL | B1 | ₹9,274.70 | ₹0.00 | ₹0.00 | ₹53,037.05 | 219.85 | ₹-1,717.80 | ₹-43,762.35 | ₹92.75 | 0.0000 | 0.00 | 0.00 |
| R2_TERMINAL | B1.5 | ₹8,817.70 | ₹5,178.55 | ₹47,233.05 | ₹5,804.00 | 27.10 | ₹7,462.70 | ₹3,013.70 | ₹306.93 | 0.0000 | 0.00 | 0.00 |
| R2_TERMINAL | RZP | ₹5,089.45 | ₹7,208.70 | ₹17,764.70 | ₹35,272.35 | 126.85 | ₹-1,253.05 | ₹-30,182.90 | ₹76.68 | 0.0000 | 0.00 | 0.00 |
| R2_TERMINAL | B2.25 | ₹6,985.65 | ₹8,071.65 | ₹48,935.60 | ₹4,101.45 | 16.90 | ₹6,140.65 | ₹2,884.20 | ₹314.30 | 0.0000 | 0.00 | 0.00 |
| R2_TERMINAL | B2.5 | ₹3,297.30 | ₹13,830.15 | ₹51,587.15 | ₹1,449.90 | 3.50 | ₹3,122.30 | ₹1,847.40 | ₹257.61 | 0.0000 | 0.00 | 0.00 |
| R2_TERMINAL | B2.75 | ₹3,087.65 | ₹14,102.05 | ₹52,241.25 | ₹795.80 | 2.50 | ₹2,962.65 | ₹2,291.85 | ₹264.42 | 0.0000 | 0.00 | 0.00 |
| R2_TERMINAL | B2 | ₹2,536.15 | ₹15,080.35 | ₹53,037.05 | ₹0.00 | 0.00 | ₹2,536.15 | ₹2,536.15 | ₹251.72 | 0.0000 | 0.00 | 0.00 |
| R2_TERMINAL | B3 | ₹2,705.90 | ₹14,351.45 | ₹53,037.05 | ₹0.00 | 0.00 | ₹2,705.90 | ₹2,705.90 | ₹230.76 | 0.0250 | 8.90 | 0.00 |
| R3_AMBIGUOUS | B0 | ₹0.00 | ₹35,325.70 | ₹36,801.25 | ₹0.00 | 0.00 | ₹0.00 | ₹0.00 | ₹0.00 | 0.0000 | 0.00 | 0.00 |
| R3_AMBIGUOUS | B1 | ₹9,081.15 | ₹0.00 | ₹0.00 | ₹36,801.25 | 202.65 | ₹-1,051.35 | ₹-27,720.10 | ₹90.81 | 0.0000 | 0.00 | 0.00 |
| R3_AMBIGUOUS | B1.5 | ₹8,863.90 | ₹19,649.75 | ₹28,834.10 | ₹7,967.15 | 30.35 | ₹7,346.40 | ₹896.75 | ₹285.01 | 0.0000 | 0.00 | 0.00 |
| R3_AMBIGUOUS | RZP | ₹6,620.95 | ₹10,690.80 | ₹14,444.20 | ₹22,357.05 | 106.35 | ₹1,303.45 | ₹-15,736.10 | ₹99.45 | 0.0000 | 0.00 | 0.00 |
| R3_AMBIGUOUS | B2.25 | ₹7,092.10 | ₹22,687.30 | ₹31,163.55 | ₹5,637.70 | 20.15 | ₹6,084.60 | ₹1,454.40 | ₹291.00 | 0.0000 | 0.00 | 0.00 |
| R3_AMBIGUOUS | B2.5 | ₹4,136.75 | ₹28,022.10 | ₹34,311.95 | ₹2,489.30 | 4.05 | ₹3,934.25 | ₹1,647.45 | ₹335.61 | 0.0000 | 0.00 | 0.00 |
| R3_AMBIGUOUS | B2.75 | ₹3,802.20 | ₹28,521.40 | ₹34,941.25 | ₹1,860.00 | 3.15 | ₹3,644.70 | ₹1,942.20 | ₹321.70 | 0.0000 | 0.00 | 0.00 |
| R3_AMBIGUOUS | B2 | ₹3,016.20 | ₹29,839.30 | ₹36,801.25 | ₹0.00 | 0.00 | ₹3,016.20 | ₹3,016.20 | ₹323.93 | 0.0000 | 0.00 | 0.00 |
| R3_AMBIGUOUS | B3 | ₹3,191.10 | ₹27,585.00 | ₹36,801.25 | ₹0.00 | 0.00 | ₹3,191.10 | ₹3,191.10 | ₹242.23 | 0.1205 | 29.10 | 0.00 |

## Economic break even and frontier recommendation

The values in this table are calculated from the generated aggregate file at report time. They are not copied from a target table. A break even value is the maximum INR cost per avoided violation at which the stricter arm and the less strict arm have equal recovery net of violation cost, before any other business costs.

| Regime | B2 vs B1 break even violation cost | B1 to B1.5 marginal recovery cost per violation avoided | B1.5 to B2 marginal recovery cost per violation avoided | Configured violation cost | Recommended arm | Recommended net value |
|---|---:|---:|---:|---:|---|---:|
| R1_TRANSIENT | ₹72.81 | ₹5.16 | ₹221.83 | ₹50.00 | B1.5 | ₹17,365.95 |
| R2_TERMINAL | ₹30.65 | ₹2.37 | ₹231.79 | ₹50.00 | B1.5 | ₹7,462.70 |
| R3_AMBIGUOUS | ₹29.93 | ₹1.26 | ₹192.68 | ₹50.00 | B1.5 | ₹7,346.40 |

## How a prohibited action is priced

The arm ordering above is not a property of the policies alone. It is a joint property of the policies and of what a prohibited action is assumed to cost, and that assumption is the least defensible number in this project. Two pricings are therefore reported side by side and neither is presented as the truth.

The flat pricing charges a fixed amount per independently detected breach regardless of the sum at stake. The harm pricing charges the money the prohibited action actually moved, times a configured multiplier. `realized_harm_inr` counts only prohibited actions that reached the provider, so an arm that denies or abstains records zero regardless of how many prohibited actions it considered.

Configured harm multiplier: `1.00` times the amount moved. A multiplier of 1.0 is a lower bound rather than an estimate: a prohibited debit must at minimum be reversed. Penalty, chargeback, remediation, and reputational cost are all excluded.

| Regime | Recommended arm (flat cost) | Recommended arm (harm priced) | Guarded arm wins at harm multiplier | Guarded arm wins at flat violation cost |
|---|---|---|---:|---:|
| R1_TRANSIENT | B1.5 | B3 | 1.00x | ₹400.00 |
| R2_TERMINAL | B1.5 | B1.5 | 1.50x | ₹400.00 |
| R3_AMBIGUOUS | B1.5 | B3 | 1.00x | ₹400.00 |

### Recommended arm across the swept harm multiplier

Each row re-prices the same frozen run. No arm is re-executed, so every point reads the same ledger and the same decisions.

| Harm multiplier | R1_TRANSIENT | R2_TERMINAL | R3_AMBIGUOUS |
|---:|---|---|---|
| 0.00x | B1 | B1 | B1 |
| 0.25x | B1.5 | B1.5 | B1.5 |
| 0.50x | B1.5 | B1.5 | B1.5 |
| 1.00x | B3 | B1.5 | B3 |
| 1.50x | B3 | B3 | B3 |
| 2.00x | B3 | B3 | B3 |
| 3.00x | B3 | B3 | B3 |
| 5.00x | B3 | B3 | B3 |
| 10.00x | B3 | B3 | B3 |

### Recommended arm across the swept flat violation cost

| Violation cost | R1_TRANSIENT | R2_TERMINAL | R3_AMBIGUOUS |
|---:|---|---|---|
| ₹0.00 | B1 | B1 | B1 |
| ₹10.00 | B1.5 | B1.5 | B1.5 |
| ₹25.00 | B1.5 | B1.5 | B1.5 |
| ₹50.00 | B1.5 | B1.5 | B1.5 |
| ₹100.00 | B1.5 | B1.5 | B1.5 |
| ₹200.00 | B1.5 | B2.25 | B2.5 |
| ₹400.00 | B3 | B3 | B3 |
| ₹800.00 | B3 | B3 | B3 |
| ₹1,600.00 | B3 | B3 | B3 |

## Frontier arm semantics

B2.25 applies the timing window but deliberately relaxes project policy gates for pre debit notice, attempt cap, consent, mandate validity, expiry, and amount review. B2.5 adds the attempt and retry gap gates. B2.75 adds consent and opt out gates. None of these experimental arms can expand the action allowlist, authority identity, amount envelope, authority expiry, or idempotency behavior. They are diagnostic frontier arms, not safe production recommendations.

B2 and B3 retain the full guardrail profile. B3 invokes the bounded interpreter only for ambiguous or conflicting signals. If validated confidence is below the configured threshold, B3 emits `ABSTAIN`, routes to human review, and makes zero provider calls. The interpreter cannot call the provider or widen authority.

## Integrity and advisories

Final manifest: `true`
Arms: `B0, B1, B1.5, RZP, B2.25, B2.5, B2.75, B2, B3`
Dataset count: `60`

Anti gaming failures: none
