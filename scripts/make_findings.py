from __future__ import annotations

# Make `bailiff` importable when this script is run directly
# (`python3 scripts/...py`), without requiring `pip install -e .` first
# or a manually exported PYTHONPATH. Idempotent if the package is
# already installed.
import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = str(_Path(__file__).resolve().parents[1])
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)

import json
from pathlib import Path

from bailiff.report import build_economic_analysis, money


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"


def mean(aggregate: dict, metric: str) -> float:
    return float(aggregate[metric]["mean"])


def main() -> int:
    manifest = json.loads((OUTPUTS / "manifest.json").read_text())
    aggregates = json.loads((OUTPUTS / "aggregate.json").read_text())
    per_seed = json.loads((OUTPUTS / "per_seed.json").read_text())
    guarded_rows = [row for row in per_seed if row["arm"] in ("B2", "B3")]
    guarded_violation_runs = sum(1 for row in guarded_rows if float(row["violations"]) != 0.0)
    guarded_harm_runs = sum(1 for row in guarded_rows if float(row["realized_harm_inr"]) != 0.0)
    analysis = json.loads((OUTPUTS / "breakeven.json").read_text()) if (OUTPUTS / "breakeven.json").exists() else build_economic_analysis(manifest, aggregates)
    sensitivity = json.loads((OUTPUTS / "sensitivity.json").read_text())
    by_key = {(row["regime"], row["arm"]): row for row in aggregates}

    lines = [
        "# MandateGuard findings",
        "",
        "> This file is generated from `outputs/manifest.json`, `outputs/aggregate.json`, and `outputs/breakeven.json`. It is not a hand typed performance claim.",
        "",
        "## Result",
        "",
        "MandateGuard compares bounded recovery policies on the same deterministic scheduled UPI AutoPay failure ledger. The benchmark measures incremental simulated recovery, legitimate recovery forgone, protected value by denial, realized harm, independent violations, human review cost, model cost, and net value.",
        "",
        "There is no single recommended arm, because the ordering depends entirely on what a prohibited action is assumed to cost. Two pricings are reported. The flat pricing charges a fixed sum per detected breach. The harm pricing charges the money the prohibited action actually moved. The crossover between them is reported rather than hidden, so a reader who disagrees with the project assumption can read their own answer off the swept curve in `outputs/report.md`.",
        "",
        f"Manifest dataset hash: `{manifest['dataset_sha256']}`",
        f"Rules hash: `{manifest['rules_sha256']}`",
        f"Seeds: `{len(manifest['seeds'])}`",
        f"Cases per seed and regime: `{manifest['n_per_seed']}`",
        f"Configured violation cost: `{money(float(manifest['violation_cost_inr']))}`",
        f"Configured human review cost: `{money(float(manifest['human_review_cost_inr']))}`",
        f"Configured harm multiplier: `{float(manifest['harm_multiplier']):.2f}` times the amount a prohibited action moved",
        "",
        "| Regime | Recommended arm (flat cost) | Recommended arm (harm priced) | Guarded arm wins at | B2 incremental recovery | B1 realized harm | B2 realized harm | B3 abstention rate | B3 interpreter influence |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for regime in manifest["regimes"]:
        item = analysis["per_regime"][regime]
        sens = sensitivity["per_regime"][regime]
        b1 = by_key[(regime, "B1")]
        b2 = by_key[(regime, "B2")]
        b3 = by_key[(regime, "B3")]
        cross = sens["guarded_arm_wins_at_harm_multiplier"]
        lines.append(
            f"| {regime} | {item['recommended_arm_at_configured_cost']} | {item['recommended_arm_at_harm_price']} | "
            f"{'never in swept range' if cross is None else f'{cross:.2f}x harm'} | "
            f"{money(mean(b2, 'incremental_recovered_inr'))} | {money(mean(b1, 'realized_harm_inr'))} | "
            f"{money(mean(b2, 'realized_harm_inr'))} | "
            f"{mean(b3, 'abstention_rate'):.4f} | {mean(b3, 'bounded_interpreter_influence_count'):.2f} |"
        )

    lines.extend(
        [
            "",
            f"Across every guarded seed-regime run in this release, the full guardrail arms recorded "
            f"**{guarded_violation_runs} independent violations and {guarded_harm_runs} runs with realized harm "
            f"out of {len(guarded_rows)} runs** (B2 and B3, {len(manifest['seeds'])} seeds, {len(manifest['regimes'])} regimes). "
            "This line is computed from `outputs/per_seed.json` at generation time, not typed.",
        ]
    )

    lines.extend(
        [
            "",
            "## Economic thresholds derived from the run",
            "",
            "| Regime | B2 versus B1 break even violation cost | B1 to B1.5 marginal recovery cost per violation avoided | B1.5 to B2 marginal recovery cost per violation avoided |",
            "|---|---:|---:|---:|",
        ]
    )
    for regime in manifest["regimes"]:
        item = analysis["per_regime"][regime]
        lines.append(
            f"| {regime} | {money(item['b2_vs_b1_breakeven_violation_cost_inr'])} | "
            f"{money(item['b1_to_b1_5_marginal_recovery_cost_per_violation_avoided_inr'])} | "
            f"{money(item['b1_5_to_b2_marginal_recovery_cost_per_violation_avoided_inr'])} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "A recommendation is conditional, not universal. Changing the violation cost, harm multiplier, human review cost, model cost, fixture regime, or policy rules can change the recommended arm, and the swept curves show exactly where it changes. The intermediate arms are diagnostic relaxations that expose where recovery and safety trade off. They are not presented as production safe defaults.",
            "",
            "The honest reading of the tables above is that guardrails do not pay for themselves at every price. Under a flat per breach charge at the configured value, reason gating alone is competitive, because a flat charge is indifferent to the size of the debit it is pricing. The guarded arms win once a prohibited action is charged the money it actually moved. That crossover is the substantive claim, and it is stated as a threshold rather than as a verdict.",
            "",
            "The latent harm model is the load bearing assumption. Compliance exposure is drawn independently of the failure reason, so an arm that reads only the reason code cannot capture harm avoidance by construction. An earlier revision of this benchmark did make harm a pure function of the reason code, which guaranteed that reason gating would win before any policy ran. `scripts/check_release.py` now rejects that shape of fixture.",
            "",
            "B2 and B3 retain the full guardrail profile. B3 is a bounded interpreter path, not a live autonomous payment model. It can interpret only the ambiguous subset, cannot call a provider, cannot widen authority, and emits `ABSTAIN` when validated confidence is below the configured threshold. An abstention routes to human review and makes zero provider calls.",
            "",
            "## Limitations",
            "",
            "The ledger is synthetic and deterministic. INR values are simulated counterfactual attribution, not production revenue, merchant collections, or Razorpay performance. The failure taxonomy is a project taxonomy and must not be described as an official universal NPCI taxonomy. Rule values are versioned project configuration with provenance tiers. This benchmark does not establish regulatory approval, production readiness, causal customer behavior, or superiority over any named competitor.",
            "",
            "## Falsification criteria",
            "",
            "The core engineering claim is falsified for a release if any arm consumes a different ledger hash for the same seed and regime, if a denied or abstained money action reaches the provider, if the full guardrail B2 or B3 arm records an independent violation, if the audit chain is incomplete, if the frozen dataset hash changes during verification, or if B3 cannot show interpreter influence and nonzero abstention on the ambiguous regime. The measurement claim is additionally falsified if legitimate recovery forgone is not monotone in policy strictness, if protected value by denial is identical across every gated arm, or if the ungated baseline records no prohibited execution. The economic recommendation is falsified whenever its configured costs are changed without recomputing the report, or whenever the recommended arm is invariant across the entire swept price range.",
            "",
            "## Reproduction",
            "",
            "Run `./scripts/test.sh` for the clean package tests. Run `./scripts/evaluate.sh` to regenerate the final benchmark, economic analysis, frontier chart, and this document. The generated outputs and manifest hashes are the evidence surface.",
        ]
    )
    path = ROOT / "FINDINGS.md"
    path.write_text("\n".join(lines) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
