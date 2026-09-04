from __future__ import annotations

from dataclasses import replace
from statistics import mean, pstdev
from typing import Iterable

from .checker import violations
from .domain import ActionType, Decision
from .policies import PolicyRun
from .replay import CommonOutcomeLedger


EXECUTABLE = {
    ActionType.SCHEDULE_RETRY,
    ActionType.SEND_EMAIL,
    ActionType.SEND_SMS,
    ActionType.SEND_WHATSAPP,
}


def annotate_runs(runs: Iterable[PolicyRun], ledger: CommonOutcomeLedger) -> list[PolicyRun]:
    """Attach counterfactual financial attribution to each decision receipt."""
    annotated: list[PolicyRun] = []
    for run in runs:
        outcome = ledger.get(run.event.recovery_case_id)
        recoverable = outcome.latent_recoverable_minor > 0
        harmful = outcome.latent_harm_minor > 0
        # A money action reached the provider if and only if a provider result exists.
        # This is the ONLY arm independent test. Do not branch on the symbolic
        # final action here: stop and escalate are spelled differently by the
        # baseline path and the guardrail path, and branching on that spelling
        # made this metric incomparable across arms.
        executed = run.provider_result is not None
        recoverable_forgone = run.event.amount_minor if recoverable and not executed else 0
        protected = run.event.amount_minor if harmful and not executed else 0
        realized_harm = run.event.amount_minor if harmful and executed else 0
        annotated.append(
            replace(
                run,
                decision=replace(
                    run.decision,
                    legitimate_recovery_forgone_inr_minor=recoverable_forgone,
                    protected_value_inr_minor=protected,
                    realized_harm_inr_minor=realized_harm,
                ),
                violation_codes=violations(run.event, run.decision),
            )
        )
    return annotated


def summarize_runs(
    runs: Iterable[PolicyRun],
    ledger: CommonOutcomeLedger,
    *,
    human_review_cost_inr: float = 0.0,
    violation_cost_inr: float = 0.0,
    harm_multiplier: float = 1.0,
) -> dict[str, object]:
    rows = list(runs)
    if not rows:
        raise ValueError("Cannot summarize an empty policy run")
    recovered_minor = 0
    recoverable_minor = 0
    forgone_minor = 0
    protected_minor = 0
    realized_harm_minor = 0
    harm_cases = 0
    harm_cases_executed = 0
    permitted_actions = 0
    provider_calls = 0
    violations_count = 0
    abstentions = 0
    human_reviews = 0
    contacts = 0
    model_calls = 0
    model_cost_inr = 0.0
    audit_incomplete = 0

    for run in rows:
        outcome = ledger.get(run.event.recovery_case_id)
        recoverable = outcome.latent_recoverable_minor > 0
        recoverable_minor += run.event.amount_minor if recoverable else 0
        if outcome.latent_harm_minor > 0:
            harm_cases += 1
            if run.provider_result is not None:
                harm_cases_executed += 1
        result = run.provider_result
        if result is not None:
            provider_calls += 1
            if result.recovered:
                recovered_minor += run.event.amount_minor
        if run.decision.final_action in EXECUTABLE and run.decision.decision is Decision.ALLOW:
            permitted_actions += 1
        if run.decision.legitimate_recovery_forgone_inr_minor:
            forgone_minor += run.decision.legitimate_recovery_forgone_inr_minor
        if run.decision.protected_value_inr_minor:
            protected_minor += run.decision.protected_value_inr_minor
        if run.decision.realized_harm_inr_minor:
            realized_harm_minor += run.decision.realized_harm_inr_minor
        if "ABSTAIN" in run.decision.reason_codes:
            abstentions += 1
        if run.decision.decision is Decision.ESCALATE or run.decision.final_action == ActionType.ESCALATE_TO_HUMAN:
            human_reviews += 1
        contacts += int(run.decision.final_action in {
            ActionType.SEND_EMAIL,
            ActionType.SEND_SMS,
            ActionType.SEND_WHATSAPP,
        })
        model_calls += run.decision.model_calls
        model_cost_inr += run.decision.model_cost_inr
        violations_count += len(run.violation_codes or violations(run.event, run.decision))
        audit_incomplete += int(not run.audit_verified or not run.audit_events)

    n = len(rows)
    decisions_with_action = permitted_actions or 1
    human_cost = human_reviews * human_review_cost_inr
    violation_cost = violations_count * violation_cost_inr
    realized_harm_inr = realized_harm_minor / 100
    harm_cost = realized_harm_inr * harm_multiplier
    net_value = recovered_minor / 100 - violation_cost - human_cost - model_cost_inr
    net_value_harm_priced = recovered_minor / 100 - harm_cost - human_cost - model_cost_inr
    return {
        "arm": rows[0].arm,
        "n": n,
        "recovered_inr": recovered_minor / 100,
        "incremental_recovered_inr": recovered_minor / 100,
        "recoverable_counterfactual_inr": recoverable_minor / 100,
        "forgone_inr": forgone_minor / 100,
        "legitimate_recovery_forgone_inr": forgone_minor / 100,
        "protected_inr": protected_minor / 100,
        "protected_value_by_denial_inr": protected_minor / 100,
        "realized_harm_inr": realized_harm_inr,
        "harm_cost_inr": round(harm_cost, 4),
        "harm_cases": harm_cases,
        "harm_cases_executed": harm_cases_executed,
        "prohibited_execution_rate": round(harm_cases_executed / harm_cases, 4) if harm_cases else 0.0,
        "violations": violations_count,
        "permitted_actions": permitted_actions,
        "recovered_per_permitted_action_inr": (recovered_minor / 100) / decisions_with_action,
        "abstention_rate": round(abstentions / n, 4),
        "human_reviews": human_reviews,
        "human_review_cost_inr": round(human_cost, 4),
        "violation_cost_inr": round(violation_cost, 4),
        "net_value_inr": round(net_value, 4),
        "net_value_harm_priced_inr": round(net_value_harm_priced, 4),
        "contacts_per_case": round(contacts / n, 4),
        "provider_calls": provider_calls,
        "model_calls": model_calls,
        "model_cost_inr": round(model_cost_inr, 6),
        "bounded_interpreter_influence_count": sum(int(run.decision.bounded_interpreter_influence) for run in rows),
        "audit_incomplete_rows": audit_incomplete,
    }


def summarize_seed_values(values: dict[int, float], *, minimum_seeds: int = 5) -> dict[str, object]:
    if len(values) < minimum_seeds:
        raise ValueError(f"At least {minimum_seeds} seeds are required")
    ordered = [values[key] for key in sorted(values)]
    return {
        "per_seed": {str(key): values[key] for key in sorted(values)},
        "seed_count": len(ordered),
        "mean": round(mean(ordered), 4),
        "std_dev": round(pstdev(ordered), 4),
        "min": min(ordered),
        "max": max(ordered),
        "spread": max(ordered) - min(ordered),
    }
