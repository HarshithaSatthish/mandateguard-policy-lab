# MandateGuard Policy Lab Architecture

## Purpose

MandateGuard is a replayable policy evaluation laboratory and bounded execution runtime for scheduled UPI AutoPay debit failures. It compares nine policies on one frozen synthetic ledger, executes only through a deterministic authority gate, and records why each action was allowed, denied, abstained, or routed to human review.

> The bounded interpreter interprets. The policy engine decides. The provider adapter executes. The audit chain proves.

The project does not claim that Razorpay lacks recovery, does not claim synthetic results are production revenue, and does not claim live Razorpay API execution. The adapter accepts Razorpay shaped test payloads while the benchmark provider remains a local simulator.

## Runtime flow

```text
Razorpay shaped scheduled AutoPay payload
                 |
                 v
Payload adapter preserves raw provider signal and payload hash
                 |
                 v
Project taxonomy and canonical RecoveryEvent
                 |
                 v
Policy arm proposes an action or stop
                 |
                 v
B3 bounded interpreter only for ambiguous cases
                 |
                 v
Deterministic authority and guardrail engine
          |                         |
       deny or abstain              allow
          |                         |
          v                         v
Hash chained receipt          Idempotency gate
Zero provider calls                 |
                                    v
                            Local replay provider
                                    |
                                    v
                         Postcondition and audit receipt
                                    |
                                    v
                         Frozen ledger metrics and report
```

## Policy arms

The order is part of the evidence contract and must remain unchanged.

| Arm | Role | Distinguishing behavior |
|---|---|---|
| `B0` | No intervention control | Does not attempt recovery |
| `B1` | Ungated retry baseline | Retries without reason or guardrail inspection |
| `B1.5` | Deterministic retry only | Retries only normalized transient reasons |
| `B2.25` | Timing frontier | Uses timing while relaxing other project gates; diagnostic only |
| `B2.5` | Timing and attempt frontier | Adds retry gap and attempt budget; diagnostic only |
| `B2.75` | Timing, attempt, and consent frontier | Adds consent controls; diagnostic only |
| `B2` | Deterministic guarded policy | Applies the complete deterministic guardrail set |
| `B3` | Bounded interpreter policy | Interprets ambiguous raw signals, then uses the same full guardrail engine |

The frontier arms are diagnostic counterfactuals. They are not safe production defaults. `B2` and `B3` retain the full authority and safety boundary.

## Authority boundary

Each case receives an authority envelope containing the identities, allowed actions, amount ceiling, attempts remaining, consent snapshot, and expiry for that case. A child envelope can only narrow the parent envelope. It cannot add actions, raise the amount, restore attempts, extend expiry, or change mandate, scheduled execution, or recovery case identity.

The bounded interpreter receives no provider credentials and no provider tools. Its output is a reason and confidence or a bounded proposal. The deterministic engine still decides. Malformed, unavailable, conflicting, or low confidence interpretation becomes `ABSTAIN`, routes to human review, and creates zero provider calls.

## Guardrails before execution

The guardrail engine evaluates consent, action allowlist, terminal state, mandate state, authority expiry, channel consent, pre debit validity, attempt cap, amount ceiling, proposed execution window, lead time, amount review, and action class before the provider boundary.

| Evidence case | Required result |
|---|---|
| Opted out contact | Deny before provider |
| Exhausted retry budget | Deny before provider |
| Expired, revoked, cancelled, or paused mandate | Deny before provider |
| Out of window or invalid pre debit state | Deny before provider |
| Ambiguous low confidence interpretation | Abstain before provider |
| Allowed retry | One provider call and one postcondition |
| Exact replay | Reuse the original result without a second call |
| Unknown timeout postcondition | Human review before another action |
| Tampered historical audit event | Chain verification fails |

## Benchmark contract

Every arm receives the same generated event set and the same common outcome ledger. The latent recoverable value and harmful value are hidden from policy decisions and used only for scoring. The final protocol records twenty fixed seeds and freezes the dataset hash before running the arms.

Latent harm is generated from compliance exposure drawn independently of the normalized failure reason. This is load bearing rather than incidental: if harm were a pure function of the reason code, an arm gating on the reason code alone would capture all harm avoidance by construction and no stronger control could ever be shown to be worth its cost. The release gate rejects a fixture that is degenerate in this respect.

The report includes incremental recovered INR, legitimate recovery forgone, protected value by denial, realized harm, prohibited execution rate, violations, recovery per permitted action, contacts, provider calls, abstention, human review cost, interpreter cost, net value under both pricings, and seed spread. No one metric is treated as a universal winner metric.

Every financial metric is defined by whether a provider call actually happened, never by the symbolic name of the final action, because the ungated baseline path and the guardrail path spell a stop differently and a metric keyed on that symbol is not comparable across arms.

A prohibited action is priced two ways: a flat cost per detected breach, and the money the action actually moved times a configured multiplier. `bailiff/sensitivity.py` sweeps both prices and generates the crossover at which the fully guarded arms overtake reason gating alone, so the economic claim is reported as a threshold rather than as a verdict.

## Evidence surfaces

The command line path is authoritative for reproducibility. The optional `app.py` Streamlit layer is read only and displays five views over generated output files.

| View | Purpose |
|---|---|
| Control Room | Regime totals and economic and safety metrics |
| Case Timeline | One case across all nine arms, its receipts, its source lineage, and the ordered action provenance chain |
| Policy Compare | Aggregate net value comparison |
| Failure Lab | Denial, timeout, tamper, and provider call proofs |
| Exception Queue | Cases needing a human, derived from reason codes already recorded |

The UI does not create a new ledger and is not a payment console. If Streamlit is not installed, the benchmark, demo, report, and release checks remain usable.

### The inspection layer is inspection only

`bailiff/lineage.py` holds the whole of the lineage, exception queue, and action provenance logic as pure functions over evidence that already exists. It computes no benchmark metric, opens no ledger, calls no provider, writes no file, and opens no socket. `app.py` renders what those functions return.

That separation is enforced rather than asserted. `tests/test_lineage_and_exception_queue.py` replaces every public method on the provider simulator with a trap and rebuilds the queue, hashes every canonical output before and after a full render pass, and blocks `socket.connect`, `socket.create_connection` and `socket.getaddrinfo` while the view layer runs. It also scans `app.py` and `bailiff/lineage.py` for write and network operations, so a later edit that introduces one fails the suite rather than shipping quietly.

Two display rules follow from the runtime's own invariants. A field the canonical evidence does not carry renders as `not present in fixture`; it is never inferred, defaulted, or borrowed from a neighbouring record. And a denied or abstained row always shows `provider_calls = 0` — if a non executing row ever reported a call, the queue surfaces it as an invariant contradiction instead of rendering it tidily.

### Design inspiration and its boundary

Rillet's public Aura and MCP material was used as design inspiration for contextual data access, reviewable workflow actions, permission boundaries, and auditability. MandateGuard does not integrate with Rillet. It applies those ideas narrowly to scheduled AutoPay recovery policy evaluation.

There is no Rillet dependency, credential, endpoint, or runtime reference anywhere in this repository, and no Rillet name appears in the product, the UI, the policy arm list, the API, or the benchmark.

## Run sequence

```bash
./scripts/test.sh
./scripts/demo.sh
./scripts/evaluate.sh
./scripts/release_check.sh
python3 -m pip install streamlit
streamlit run app.py
```

The optional real interpreter mode is separate from the final deterministic benchmark:

```bash
python3 -m pip install -e '.[test,interpreter]'
python3 -m bailiff.demo --real-interpreter
```

## Deliberate limitations

The benchmark uses synthetic events and a local provider simulator. The Razorpay shaped adapter preserves provider fields but does not call Razorpay. The project taxonomy is not presented as an official universal NPCI taxonomy. Rules that lack a pinned primary source remain labelled as configured project rules. No production customer is contacted and no real money is moved.
