# MandateGuard Policy Lab & RecoveryTruth — Official Submission Pack

> **Track 03: Subscription & AutoPay Payment Recovery | Agentic AI with Provable Safety Guardrails**
>
> 🌐 **Live Interactive Web Simulator**: [https://harshithasatthish.github.io/mandateguard-policy-lab/](https://harshithasatthish.github.io/mandateguard-policy-lab/)  
> 📦 **GitHub Repository**: [https://github.com/HarshithaSatthish/mandateguard-policy-lab](https://github.com/HarshithaSatthish/mandateguard-policy-lab)  
> ⚡ **Cloud / Vercel Serverless Ready**: Deployable with 1-click using included `vercel.json` and `api/index.py`

---

## 1. Executive Summary

Every month, millions of recurring subscription payments in India fail across UPI AutoPay rails due to transient bank downtimes, insufficient funds, network timeouts, or user mandate changes.

When engineering teams attempt to recover these failed recurring payments, they almost invariably fall into one of two traps:
1. **The Blind Temporal Schedule**: Blindly retrying every 24 hours (e.g., card-style $T+1, T+2, T+3$). This causes catastrophic customer complaints by repeatedly attempting debits on cancelled, paused, or expired mandates—in direct violation of Reserve Bank of India (RBI) recurring debit circulars.
2. **The Unconstrained AI Agent**: Giving an LLM agent direct API access to trigger payment links or retries whenever an error occurs. When the model hallucinates or misinterprets an unmapped bank error, unauthorized money moves without an audit trail.

### The MandateGuard Solution
**MandateGuard Policy Lab** with **RecoveryTruth** solves this with an ironclad architectural separation:
$$\textbf{The Webhook Ingress Authenticates} \longrightarrow \textbf{AI Interprets} \longrightarrow \textbf{Deterministic Policy Authorizes} \longrightarrow \textbf{Provider Adapter Executes} \longrightarrow \textbf{Cryptographic Chain Proves}$$

- **AI is an Interpreter, Never an Actor**: An LLM (`B3` arm) is bounded strictly to diagnosing ambiguous or conflicting raw bank error codes. It **cannot** authorize debits, widen authority envelopes, change consent, or touch payment provider APIs.
- **Two-Sided Proof**: We score both directions at once: **Incremental Value Recovered** vs. **Unauthorized Harm Prevented**.
- **Provable Refusal**: We prove not only that valid retries succeed, but that illegal debits (already-paid orders, cancelled mandates, paused subscriptions) produce **provably zero provider writes (`0 -> 0`)**.
- **Real Razorpay Test Mode Proof**: Includes cryptographic, tamper-evident receipts binding fresh pre-write provider truth, the decision hash, the created Standard Payment Link fallback, and an independently fetched captured payment `RecoveryProof`.

---

## 2. Competitive Matrix: Why MandateGuard Stands Out

| Dimension | Typical Hackathon Entry | Conventional Retry Engine | MandateGuard Policy Lab |
|---|---|---|---|
| **AI Role** | Direct API tool caller (high hallucination risk) | None / Rules only | **Strictly bounded interpreter** (diagnostic only; 0 authority) |
| **Optimization Target** | Gross recovered ₹ only | Gross recovered ₹ only | **Pareto Frontier**: Net ₹ (Recovery minus Realized Harm) |
| **Refusal Verification** | Logged warning / silent drop | Silent drop | **Cryptographic SHA-256 tamper-evident receipt** before provider boundary |
| **Two-Sided Proof** | One-sided (success only) | One-sided (success only) | **Two-Sided**: Fallback Payment Link vs **Already-Paid Zero Write (`0 -> 0`)** |
| **Testing Depth** | 5–10 basic mocks | Unit tests | **299 tests, 14/14 mutations caught, Hypothesis property tests, 46 red-team attacks** |
| **RBI / NPCI AutoPay Alignment** | Usually ignored | Partial | **24h pre-debit notice check, max debit caps, non-peak window gating, opt-out honor** |
| **Empirical Falsification** | None | None | **54,000 simulations over 20 seeds & 3 regimes (`ROBUSTNESS.md`)** |

---

## 3. Quick-Start Evaluation (Judge Runbook)

### Run in 60 Seconds (Zero Config, Offline, Deterministic)

#### On Windows:
Double-click `run_demo.bat` or run:
```cmd
set PYTHONUTF8=1
python scripts/demo60.py
```

#### On Linux / macOS:
```bash
python3 scripts/demo60.py
```

**What you will see in 60 seconds:**
1. A forged webhook delivery rejected at ingress with constant-time HMAC comparison (`0 provider calls`).
2. A genuine Razorpay webhook authenticated and verified.
3. A revoked mandate failure stopped by policy with zero debits attempted.
4. A legitimate transient failure safely allowed and executed.
5. An ambiguous failure where the LLM interpreter abstains and routes safely to human review.
6. A tampered audit receipt immediately detected by hash-chain verification.

---

## 4. Visual Dashboards

### 1. The Main Policy Evidence Dashboard (`app.py`)
Run with:
```bash
streamlit run app.py
```
*(Or double-click `run_app.bat` on Windows)*

- **Screen 1: Control Room**: Headline recovery metrics, protected value, realized harm, and break-even violation cost sensitivity.
- **Screen 2: Case Timeline**: Inspect any of the cases across all 9 policy arms with ordered action provenance.
- **Screen 3: Policy Compare**: The empirical recovery vs harm Pareto frontier (`frontier.png`).
- **Screen 4: Failure Lab**: Interactive live execution of runtime guardrail contracts.
- **Screen 5: Exception Queue**: Production-style human escalation queue derived strictly from existing receipts.

### 2. Provider Proof Viewer (`provider_proof_app.py`)
Run with:
```bash
streamlit run provider_proof_app.py
```
*(Or double-click `run_proof_app.bat` on Windows)*

Inspects sanitized real Razorpay Test Mode artifacts:
- **`testmode_success_execute.json`**: Fresh provider state resolved `RECOVERABLE`, write fence held, and fallback Payment Link was created.
- **`testmode_recovery_proof.json`**: Bound captured payment verified independently.
- **`testmode_safe_block_zero_write.json`**: An already-paid invoice where Payment Links remained `0 -> 0`.

---

## 5. The 3-Minute Demo Video Script & Storyboard

### [0:00 - 0:35] The Hook: The Hidden Cost of Payment Recovery
- **Visual**: Show news headlines of recurring payment debit complaints, followed by `outputs/frontier.png` showing `RZP` and `B1` deep in negative net value due to realized harm.
- **Voiceover**: *"In subscription recovery, recovering ₹1,000 while triggering ₹5,000 in unauthorized debits on cancelled mandates is not a win—it's customer churn and a regulatory violation. Most recovery bots measure only gross rupees. MandateGuard measures both sides: the money recovered and the unauthorized harm prevented."*

### [0:35 - 1:20] The Architecture & Sixty-Second Proof
- **Visual**: Run `scripts/demo60.py` in terminal. Zoom in on step [1] (webhook HMAC gate) and step [4] (revoked mandate stop).
- **Voiceover**: *"Here is the 60-second proof. First, unauthenticated webhooks are stopped dead at ingress using constant-time HMAC-SHA256. Second, when a mandate is cancelled, our deterministic guardrail stops the retry before anything touches Razorpay APIs. Third, when an AI model is asked to interpret an ambiguous code, it can only suggest an interpretation—it has zero authority to widen permissions or initiate debits."*

### [1:20 - 2:15] The Live Evidence Dashboard
- **Visual**: Switch to Streamlit `app.py`. Click through Control Room, Pareto Frontier, and Case Timeline.
- **Voiceover**: *"Here is our Control Room. Across 54,000 simulated runs over 20 seeds, our reason-aware and guarded policies consistently Pareto-dominate fixed temporal schedules. Notice that the fully guarded arms (`B2` and `B3`) achieve zero independent checker violations and zero realized harm across all 120 guarded regime runs."*

### [2:15 - 2:50] The Killer Proof: Two-Sided Razorpay Test Mode Evidence
- **Visual**: Open `provider_proof_app.py`. Show `SAFE_BLOCK_ALREADY_PAID` with Payment Links `0 -> 0`.
- **Voiceover**: *"In Razorpay Test Mode, RecoveryTruth demonstrates our most critical capability: the refusal proof. When an order is already paid, our pre-write fence re-reads provider truth and aborts. The payment links before is zero, and after is zero. The collection object was never created."*

### [2:50 - 3:00] Conclusion
- **Voiceover**: *"Authentic ingress. Bounded interpretation. Deterministic authorization. Verifiable execution. This is MandateGuard."*

---

## 6. Panel Defense: Tough Questions & Winning Answers

#### Q1: "Why not let Claude or GPT-4o decide whether to retry directly?"
> **Answer**: *"Allowing an LLM to hold financial authority violates fundamental security and regulatory principles. An LLM is non-deterministic and susceptible to prompt injection or hallucination. In MandateGuard, the LLM (`B3`) is strictly an interpreter of ambiguous bank error texts. Its output is just a label with a confidence score. The deterministic guardrail (`guardrails.py`) evaluates mandate status, customer consent, attempt counts, and pre-debit notice validity. Even if a compromised model outputs 100% confidence to retry, our adversarial test (`test_adversarial.py`) proves it cannot bypass the guardrail."*

#### Q2: "Razorpay already has an Intelligent Retry Engine. Why do we need MandateGuard?"
> **Answer**: *"We document this explicitly in `docs/competitive_position.md`. We do not compete with Razorpay's internal retry engine—we provide the evaluation and guardrail harness that sits underneath any recovery engine. MandateGuard answers what a retry engine cannot answer about itself: before you deploy a retry cadence, how much legitimate recovery will it forgo, how many prohibited debits will it attempt on cancelled mandates, and can every single refusal be mathematically proven to an auditor?"*

#### Q3: "What if a network timeout occurs right after creating a payment link?"
> **Answer**: *"RecoveryTruth enforces fail-closed idempotency and reconciliation (`bailiff/recovery_truth.py`). Every action is bound to a deterministic reference ID. If a network timeout or duplicate delivery occurs, our ambiguous write reconciliation re-reads provider truth, resolves existing payment links matching that exact reference, and prevents duplicate creations."*

#### Q4: "Why do you benchmark against Razorpay's card schedule on UPI AutoPay?"
> **Answer**: *"Razorpay's published card documentation is a classic fixed temporal reference policy ($T+1, T+2, T+3$). We benchmarked it as the `RZP` arm to evaluate what happens when an industry-standard temporal retry schedule is applied to a rail with terminal states. The empirical result is that reading failure reasons dominates temporal schedules because temporal retries repeatedly hammer dead mandates. We state clearly in our documentation that `RZP` is a reference benchmark arm, not a measurement of Razorpay's production UPI engine."*

---

## 7. Submission Checklist & Manifest Integrity

- [x] Full Pytest suite passes: **299/299 tests green**
- [x] 14/14 Safety mutations caught: **`scripts/mutation_check.py` baseline verified**
- [x] Security regression checks: **`scripts/security_regression_check.py` PASS**
- [x] RecoveryTruth contract checks: **`scripts/recoverytruth_check.py` PASS**
- [x] Hardening gate contract: **`scripts/hardening_check.py` PASS**
- [x] Release invariant checker: **`scripts/check_release.py` PASS**
- [x] Manifest cryptographic checksum: **`SHA256SUMS.txt` 100% matching**
- [x] Cross-platform execution: **Linux bash scripts + Windows `.bat` launchers**
- [x] Interactive UI: **Streamlit Control Room & Test Mode Proof Viewer**
