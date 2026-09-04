from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


def _metric_mean(row: Mapping[str, Any], metric: str) -> float:
    """Read either a scalar metric or an aggregate ``{"mean": ...}`` metric."""
    value = row.get(metric, 0.0)
    if isinstance(value, Mapping):
        value = value.get("mean", 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def interpreter_ablation(aggregate: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compare B2 with B3 on the exact same frozen aggregate rows.

    B2 is the fully deterministic guarded policy. B3 keeps the same policy
    boundary but allows the bounded interpreter to clarify ambiguous failure
    meaning. The report therefore answers one narrow question: did the
    interpreter add useful recovery without widening the money-safety bound?

    No benchmark is rerun here. This function reads the committed aggregate
    artifact so the comparison cannot silently use a different ledger.
    """
    rows = list(aggregate)
    regimes = sorted({str(row.get("regime")) for row in rows if row.get("regime")})
    out: list[dict[str, Any]] = []

    for regime in regimes:
        by_arm = {
            str(row.get("arm")): row
            for row in rows
            if str(row.get("regime")) == regime
        }
        if "B2" not in by_arm or "B3" not in by_arm:
            continue
        b2 = by_arm["B2"]
        b3 = by_arm["B3"]

        b2_recovery = _metric_mean(b2, "incremental_recovered_inr")
        b3_recovery = _metric_mean(b3, "incremental_recovered_inr")
        b2_harm = _metric_mean(b2, "realized_harm_inr")
        b3_harm = _metric_mean(b3, "realized_harm_inr")
        b2_prohibited = _metric_mean(b2, "prohibited_execution_rate")
        b3_prohibited = _metric_mean(b3, "prohibited_execution_rate")

        out.append(
            {
                "regime": regime,
                "b2_incremental_recovered_inr": round(b2_recovery, 4),
                "b3_incremental_recovered_inr": round(b3_recovery, 4),
                "delta_recovered_inr": round(b3_recovery - b2_recovery, 4),
                "b2_legitimate_recovery_forgone_inr": round(
                    _metric_mean(b2, "legitimate_recovery_forgone_inr"), 4
                ),
                "b3_legitimate_recovery_forgone_inr": round(
                    _metric_mean(b3, "legitimate_recovery_forgone_inr"), 4
                ),
                "delta_provider_calls": round(
                    _metric_mean(b3, "provider_calls") - _metric_mean(b2, "provider_calls"), 4
                ),
                "delta_human_reviews": round(
                    _metric_mean(b3, "human_reviews") - _metric_mean(b2, "human_reviews"), 4
                ),
                "b3_abstention_rate": round(_metric_mean(b3, "abstention_rate"), 6),
                "b3_interpreter_influence_count": round(
                    _metric_mean(b3, "bounded_interpreter_influence_count"), 4
                ),
                "b2_realized_harm_inr": round(b2_harm, 4),
                "b3_realized_harm_inr": round(b3_harm, 4),
                "b2_prohibited_execution_rate": round(b2_prohibited, 6),
                "b3_prohibited_execution_rate": round(b3_prohibited, 6),
                "safety_bound_unchanged": (
                    b2_harm == b3_harm
                    and b2_prohibited == b3_prohibited
                    and b3_harm == 0.0
                    and b3_prohibited == 0.0
                ),
                "interpreter_adds_recovery": b3_recovery > b2_recovery,
            }
        )
    return out


def refusal_regret(evidence: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Price every non-provider decision rather than celebrating refusal alone.

    A row enters this report only when no provider call was made. Counterfactual
    legitimate recovery forgone is the cost side of the refusal; protected
    value is the safety benefit side. Grouping by the first emitted reason code
    gives a stable, inspectable explanation without double-counting a row that
    carries several reasons.
    """
    groups: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {
            "rows": 0.0,
            "legitimate_recovery_forgone_inr": 0.0,
            "protected_value_by_denial_inr": 0.0,
        }
    )
    total_rows = 0
    total_forgone = 0.0
    total_protected = 0.0

    for row in evidence:
        if bool(row.get("provider_call_made")):
            continue
        decision = str(row.get("decision") or "unknown").upper()
        reasons = row.get("reason_codes")
        if isinstance(reasons, (list, tuple)) and reasons:
            primary_reason = str(reasons[0])
        else:
            primary_reason = "UNSPECIFIED"

        forgone = float(row.get("legitimate_recovery_forgone_inr") or 0.0)
        protected = float(row.get("protected_value_by_denial_inr") or 0.0)
        bucket = groups[(decision, primary_reason)]
        bucket["rows"] += 1
        bucket["legitimate_recovery_forgone_inr"] += forgone
        bucket["protected_value_by_denial_inr"] += protected
        total_rows += 1
        total_forgone += forgone
        total_protected += protected

    breakdown = []
    for (decision, reason), values in sorted(groups.items()):
        forgone = values["legitimate_recovery_forgone_inr"]
        protected = values["protected_value_by_denial_inr"]
        breakdown.append(
            {
                "decision": decision,
                "primary_reason": reason,
                "rows": int(values["rows"]),
                "legitimate_recovery_forgone_inr": round(forgone, 4),
                "protected_value_by_denial_inr": round(protected, 4),
                "net_protection_minus_regret_inr": round(protected - forgone, 4),
            }
        )

    return {
        "non_provider_rows": total_rows,
        "legitimate_recovery_forgone_inr": round(total_forgone, 4),
        "protected_value_by_denial_inr": round(total_protected, 4),
        "net_protection_minus_regret_inr": round(total_protected - total_forgone, 4),
        "breakdown": breakdown,
    }
