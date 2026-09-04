from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .sensitivity import build_sensitivity

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"₹{value:,.2f}"


def _mean(row: dict[str, Any], metric: str) -> float:
    return float(row[metric]["mean"])


def _cost_per_violation_avoided(
    higher_violation_row: dict[str, Any],
    lower_violation_row: dict[str, Any],
) -> float | None:
    avoided = _mean(higher_violation_row, "violations") - _mean(lower_violation_row, "violations")
    recovery_delta = _mean(higher_violation_row, "incremental_recovered_inr") - _mean(
        lower_violation_row, "incremental_recovered_inr"
    )
    if avoided <= 0:
        return None
    return round(recovery_delta / avoided, 4)


def _breakeven_b2_vs_b1(b1: dict[str, Any], b2: dict[str, Any]) -> float | None:
    violation_delta = _mean(b1, "violations") - _mean(b2, "violations")
    recovery_delta = _mean(b1, "incremental_recovered_inr") - _mean(b2, "incremental_recovered_inr")
    if violation_delta <= 0:
        return None
    return round(recovery_delta / violation_delta, 4)


def build_economic_analysis(
    manifest: dict[str, Any], aggregates: list[dict[str, Any]]
) -> dict[str, Any]:
    arms = list(manifest["arms"])
    by_key = {(row["regime"], row["arm"]): row for row in aggregates}
    per_regime: dict[str, Any] = {}
    for regime in manifest["regimes"]:
        b1 = by_key[(regime, "B1")]
        b15 = by_key[(regime, "B1.5")]
        b2 = by_key[(regime, "B2")]
        net_values = {arm: _mean(by_key[(regime, arm)], "net_value_inr") for arm in arms}
        harm_net_values = {arm: _mean(by_key[(regime, arm)], "net_value_harm_priced_inr") for arm in arms}
        recommended_arm = max(
            arms,
            key=lambda arm: (net_values[arm], -arms.index(arm)),
        )
        harm_recommended_arm = max(
            arms,
            key=lambda arm: (harm_net_values[arm], -arms.index(arm)),
        )
        per_regime[regime] = {
            "recommended_arm_at_harm_price": harm_recommended_arm,
            "recommended_net_value_at_harm_price_inr": round(harm_net_values[harm_recommended_arm], 4),
            "net_value_harm_priced_by_arm_inr": {arm: round(harm_net_values[arm], 4) for arm in arms},
            "realized_harm_by_arm_inr": {
                arm: round(_mean(by_key[(regime, arm)], "realized_harm_inr"), 4) for arm in arms
            },
            "b2_vs_b1_breakeven_violation_cost_inr": _breakeven_b2_vs_b1(b1, b2),
            "b1_to_b1_5_marginal_recovery_cost_per_violation_avoided_inr": _cost_per_violation_avoided(b1, b15),
            "b1_5_to_b2_marginal_recovery_cost_per_violation_avoided_inr": _cost_per_violation_avoided(b15, b2),
            "recommended_arm_at_configured_cost": recommended_arm,
            "recommended_net_value_inr": round(net_values[recommended_arm], 4),
            "net_value_by_arm_inr": {arm: round(net_values[arm], 4) for arm in arms},
        }
    return {
        "method": {
            "b2_vs_b1_breakeven": "(B1 incremental recovered minus B2 incremental recovered) divided by (B1 violations minus B2 violations)",
            "marginal_cost": "recovery given up divided by violations avoided; n/a when the lower arm does not avoid violations",
            "recommendation": "highest generated mean net value at the configured project violation and human review costs, with canonical order as deterministic tie break",
            "harm_priced_recommendation": "highest generated mean net value when a prohibited action is priced at the money it actually moved times the configured harm multiplier, rather than at a flat rate per breach",
        },
        "configured_costs_inr": {
            "violation_cost": float(manifest["violation_cost_inr"]),
            "human_review_cost": float(manifest["human_review_cost_inr"]),
            "harm_multiplier": float(manifest.get("harm_multiplier", 1.0)),
        },
        "per_regime": per_regime,
    }


def generate_report() -> Path:
    manifest = json.loads((OUTPUTS / "manifest.json").read_text())
    aggregates = json.loads((OUTPUTS / "aggregate.json").read_text())
    anti_gaming = json.loads((OUTPUTS / "anti_gaming.json").read_text())
    analysis = build_economic_analysis(manifest, aggregates)
    (OUTPUTS / "breakeven.json").write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n")
    sensitivity = build_sensitivity(manifest, aggregates)
    (OUTPUTS / "sensitivity.json").write_text(json.dumps(sensitivity, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Generated benchmark report",
        "",
        "> All amounts below are simulated counterfactuals from the frozen ledger, not production revenue.",
        "> Violation and human review costs are configurable project assumptions, not Razorpay or NPCI pricing.",
        "",
        f"Manifest: `{manifest['dataset_sha256']}`",
        f"Seeds: `{len(manifest['seeds'])}`",
        f"Cases per seed and regime: `{manifest['n_per_seed']}`",
        f"Configured violation cost: `{money(float(manifest['violation_cost_inr']))}` per independent violation",
        f"Configured human review cost: `{money(float(manifest['human_review_cost_inr']))}` per review",
        "",
        "| Regime | Arm | Incremental recovered | Legitimate recovery forgone | Protected value by denial | Realized harm | Violations | Net value (flat) | Net value (harm priced) | Recovered per permitted action | Abstention rate | Interpreter influence | Audit incomplete |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in aggregates:
        lines.append(
            f"| {row['regime']} | {row['arm']} | {money(_mean(row, 'incremental_recovered_inr'))} | "
            f"{money(_mean(row, 'legitimate_recovery_forgone_inr'))} | "
            f"{money(_mean(row, 'protected_value_by_denial_inr'))} | "
            f"{money(_mean(row, 'realized_harm_inr'))} | "
            f"{_mean(row, 'violations'):.2f} | {money(_mean(row, 'net_value_inr'))} | "
            f"{money(_mean(row, 'net_value_harm_priced_inr'))} | "
            f"{money(_mean(row, 'recovered_per_permitted_action_inr'))} | "
            f"{_mean(row, 'abstention_rate'):.4f} | "
            f"{_mean(row, 'bounded_interpreter_influence_count'):.2f} | "
            f"{_mean(row, 'audit_incomplete_rows'):.2f} |"
        )

    lines.extend(
        [
            "",
            "## Economic break even and frontier recommendation",
            "",
            "The values in this table are calculated from the generated aggregate file at report time. They are not copied from a target table. A break even value is the maximum INR cost per avoided violation at which the stricter arm and the less strict arm have equal recovery net of violation cost, before any other business costs.",
            "",
            "| Regime | B2 vs B1 break even violation cost | B1 to B1.5 marginal recovery cost per violation avoided | B1.5 to B2 marginal recovery cost per violation avoided | Configured violation cost | Recommended arm | Recommended net value |",
            "|---|---:|---:|---:|---:|---|---:|",
        ]
    )
    for regime in manifest["regimes"]:
        item = analysis["per_regime"][regime]
        lines.append(
            f"| {regime} | {money(item['b2_vs_b1_breakeven_violation_cost_inr'])} | "
            f"{money(item['b1_to_b1_5_marginal_recovery_cost_per_violation_avoided_inr'])} | "
            f"{money(item['b1_5_to_b2_marginal_recovery_cost_per_violation_avoided_inr'])} | "
            f"{money(float(manifest['violation_cost_inr']))} | {item['recommended_arm_at_configured_cost']} | "
            f"{money(item['recommended_net_value_inr'])} |"
        )

    lines.extend(
        [
            "",
            "## How a prohibited action is priced",
            "",
            "The arm ordering above is not a property of the policies alone. It is a joint property of the policies and of what a prohibited action is assumed to cost, and that assumption is the least defensible number in this project. Two pricings are therefore reported side by side and neither is presented as the truth.",
            "",
            "The flat pricing charges a fixed amount per independently detected breach regardless of the sum at stake. The harm pricing charges the money the prohibited action actually moved, times a configured multiplier. `realized_harm_inr` counts only prohibited actions that reached the provider, so an arm that denies or abstains records zero regardless of how many prohibited actions it considered.",
            "",
            f"Configured harm multiplier: `{float(manifest.get('harm_multiplier', 1.0)):.2f}` times the amount moved. A multiplier of 1.0 is a lower bound rather than an estimate: a prohibited debit must at minimum be reversed. Penalty, chargeback, remediation, and reputational cost are all excluded.",
            "",
            "| Regime | Recommended arm (flat cost) | Recommended arm (harm priced) | Guarded arm wins at harm multiplier | Guarded arm wins at flat violation cost |",
            "|---|---|---|---:|---:|",
        ]
    )
    for regime in manifest["regimes"]:
        item = analysis["per_regime"][regime]
        sens = sensitivity["per_regime"][regime]
        harm_cross = sens["guarded_arm_wins_at_harm_multiplier"]
        flat_cross = sens["guarded_arm_wins_at_violation_cost_inr"]
        lines.append(
            f"| {regime} | {item['recommended_arm_at_configured_cost']} | {item['recommended_arm_at_harm_price']} | "
            f"{'never in swept range' if harm_cross is None else f'{harm_cross:.2f}x'} | "
            f"{'never in swept range' if flat_cross is None else money(flat_cross)} |"
        )

    lines.extend(
        [
            "",
            "### Recommended arm across the swept harm multiplier",
            "",
            "Each row re-prices the same frozen run. No arm is re-executed, so every point reads the same ledger and the same decisions.",
            "",
            "| Harm multiplier | " + " | ".join(manifest["regimes"]) + " |",
            "|---:|" + "---|" * len(manifest["regimes"]),
        ]
    )
    for index, multiplier in enumerate(sensitivity["grids"]["harm_multiplier"]):
        cells = [
            sensitivity["per_regime"][regime]["harm_multiplier_curve"][index]["recommended_arm"]
            for regime in manifest["regimes"]
        ]
        lines.append(f"| {multiplier:.2f}x | " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "### Recommended arm across the swept flat violation cost",
            "",
            "| Violation cost | " + " | ".join(manifest["regimes"]) + " |",
            "|---:|" + "---|" * len(manifest["regimes"]),
        ]
    )
    for index, cost in enumerate(sensitivity["grids"]["violation_cost_inr"]):
        cells = [
            sensitivity["per_regime"][regime]["violation_cost_curve"][index]["recommended_arm"]
            for regime in manifest["regimes"]
        ]
        lines.append(f"| {money(cost)} | " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "## Frontier arm semantics",
            "",
            "B2.25 applies the timing window but deliberately relaxes project policy gates for pre debit notice, attempt cap, consent, mandate validity, expiry, and amount review. B2.5 adds the attempt and retry gap gates. B2.75 adds consent and opt out gates. None of these experimental arms can expand the action allowlist, authority identity, amount envelope, authority expiry, or idempotency behavior. They are diagnostic frontier arms, not safe production recommendations.",
            "",
            "B2 and B3 retain the full guardrail profile. B3 invokes the bounded interpreter only for ambiguous or conflicting signals. If validated confidence is below the configured threshold, B3 emits `ABSTAIN`, routes to human review, and makes zero provider calls. The interpreter cannot call the provider or widen authority.",
            "",
            "## Integrity and advisories",
            "",
            f"Final manifest: `{str(manifest['final']).lower()}`",
            f"Arms: `{', '.join(manifest['arms'])}`",
            f"Dataset count: `{manifest['dataset_count']}`",
        ]
    )
    if anti_gaming.get("failures"):
        lines.append("\nAnti gaming failures:")
        lines.extend(f"\n* {failure}" for failure in anti_gaming["failures"])
    else:
        lines.append("\nAnti gaming failures: none")
    out = OUTPUTS / "report.md"
    out.write_text("\n".join(lines) + "\n")
    return out


if __name__ == "__main__":
    print(generate_report())
