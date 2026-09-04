from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
import json
from typing import Callable

from .domain import (
    ActionType,
    AuthorityEnvelope,
    Decision,
    FailureReason,
    PolicyConfig,
    PolicyDecision,
    RecoveryEvent,
    ProviderResult,
    utc_now,
)
from .guardrails import AuditChain, EvaluationContext, GuardrailEngine
from .interpreter import InterpreterOutput
from .replay import CommonOutcomeLedger, ReplayProvider
from .rules import RuleCatalog
from .state import CaseStore


# The canonical order, declared once. Anything that needs to assert "the arms
# are what they should be" compares against this rather than re-typing a literal,
# because a stale literal in a self-verification path reports success while
# checking the wrong thing.
CANONICAL_ARM_ORDER = ("B0", "B1", "B1.5", "RZP", "B2.25", "B2.5", "B2.75", "B2", "B3")
ARM_ORDER = CANONICAL_ARM_ORDER

# Razorpay's published subscription retry model, implemented as a benchmark arm
# so the comparison is against a real documented policy rather than only against
# synthetic ablations. Razorpay documents: "In a T+3 days cycle, we will retry
# the payment thrice. That is, once every day for 3 days, excluding the date of
# the charge." The subscription then moves to `halted`.
#
# Two honest qualifications, both material:
#
#   1. That schedule is documented for the CARD model. Applying the card model
#      to a scheduled UPI AutoPay ledger is therefore an explicit assumption
#      of this benchmark, not a reproduction, benchmark, or claim about
#      Razorpay's current Intelligent UPI Retry Engine or production behaviour.
#   2. The published model is a schedule. It says nothing about reading the
#      failure reason, and this arm does not read it either. That is the point
#      of including the arm: it shows what a purely temporal retry policy costs
#      on a ledger where some failures are terminal.
#
# This arm is not a criticism of a card policy applied to cards. It is the
# reason a scheduled AutoPay policy needs a model of its own.
RZP_DOCUMENTED_RETRIES = 3

RETRYABLE_REASONS = {
    FailureReason.INSUFFICIENT_FUNDS.value,
    FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE.value,
}
TERMINAL_REASONS = {
    FailureReason.MANDATE_REVOKED_OR_CANCELLED.value,
    FailureReason.ACCOUNT_CLOSED_OR_BLOCKED.value,
    FailureReason.RISK_OR_FRAUD_REJECTED.value,
    FailureReason.CUSTOMER_OPTED_OUT.value,
}


@dataclass(frozen=True)
class PolicyRun:
    arm: str
    event: RecoveryEvent
    decision: PolicyDecision
    provider_result: ProviderResult | None
    violation_codes: tuple[str, ...] = ()
    audit_events: tuple[dict[str, object], ...] = ()
    audit_verified: bool = False
    ledger_sha256: str = ""


def default_policy(arm: str) -> PolicyConfig:
    catalog = RuleCatalog.load()
    profiles = {
        "B2.25": "timing_only",
        "B2.5": "timing_attempts",
        "B2.75": "timing_attempts_consent",
    }
    return PolicyConfig(
        policy_id=f"pid_{arm.replace('.', '_').lower()}",
        max_attempts=int(catalog.value("attempt_cap")),
        minimum_retry_gap_hours=int(catalog.value("minimum_retry_gap_hours")),
        amount_review_threshold_minor=int(catalog.value("amount_review_threshold_minor")),
        non_peak_windows=tuple(tuple(float(value) for value in window) for window in catalog.value("non_peak_windows_ist")),
        pre_debit_exempt_mcc=frozenset(str(value) for value in catalog.value("pdn_exempt_mcc")),
        guardrail_profile=profiles.get(arm, "full"),
        minimum_interpreter_confidence=float(catalog.value("minimum_interpreter_confidence")),
        version=catalog.version,
        policy_provenance=catalog.provenance_map(),
    )


def _reason_from_event(event: RecoveryEvent) -> str:
    try:
        return FailureReason(event.normalized_failure_reason).value
    except ValueError:
        return FailureReason.UNKNOWN_OR_CONFLICTING.value


def deterministic_diagnosis(event: RecoveryEvent) -> tuple[str, float]:
    reason = _reason_from_event(event)
    confidence = 0.94 if reason != FailureReason.UNKNOWN_OR_CONFLICTING.value else 0.25
    payload = {str(k).lower(): str(v).lower() for k, v in event.failure_payload.items()}
    code = str(event.failure_code).upper()
    if payload.get("conflict") == "true" or code in {"CONFLICT", "UNKNOWN", "XX99"}:
        return FailureReason.UNKNOWN_OR_CONFLICTING.value, 0.25
    return reason, confidence


def bounded_interpreter_diagnosis(event: RecoveryEvent) -> tuple[str, float]:
    """Return only a normalized reason and confidence, never provider authority."""
    text = " ".join(str(value).lower() for value in event.failure_payload.values())
    if "mandate revoked" in text or "cancelled" in text:
        return FailureReason.MANDATE_REVOKED_OR_CANCELLED.value, 0.82
    if "account closed" in text or "invalid account" in text:
        return FailureReason.ACCOUNT_CLOSED_OR_BLOCKED.value, 0.82
    if "risk" in text or "fraud" in text:
        return FailureReason.RISK_OR_FRAUD_REJECTED.value, 0.82
    if "insufficient" in text or "balance" in text:
        return FailureReason.INSUFFICIENT_FUNDS.value, 0.80
    if "timeout" in text or "unavailable" in text:
        return FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE.value, 0.80
    return FailureReason.UNKNOWN_OR_CONFLICTING.value, 0.20


def validate_interpreter_output(output: object) -> tuple[str, float, dict[str, object]]:
    if isinstance(output, InterpreterOutput):
        reason, confidence = output.reason, output.confidence
        metadata = {
            "reason_source": output.reason_source,
            "model_calls": output.model_calls,
            "model_tokens": output.model_tokens,
            "model_cost_inr": output.model_cost_inr,
            "model": output.model,
        }
    else:
        if not isinstance(output, tuple) or len(output) != 2:
            raise ValueError("bounded interpreter output must be a (reason, confidence) tuple")
        reason, confidence = output
        metadata = {
            "reason_source": "MODEL_INTERPRETATION",
            "model_calls": 0,
            "model_tokens": 0,
            "model_cost_inr": 0.0,
            "model": "injected_callback",
        }
    if not isinstance(reason, str):
        raise ValueError("bounded interpreter reason must be a string")
    FailureReason(reason)
    if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
        raise ValueError("bounded interpreter confidence must be between zero and one")
    return reason, float(confidence), metadata


def proposed_action(arm: str, reason: str, *, attempt_count: int = 0) -> ActionType:
    if arm == "B0":
        return ActionType.STOP_RECOVERY
    if arm == "B1":
        return ActionType.SCHEDULE_RETRY
    if arm == "RZP":
        # Purely temporal: retry until the documented attempt budget is spent,
        # regardless of why the debit failed.
        return (
            ActionType.SCHEDULE_RETRY
            if attempt_count < RZP_DOCUMENTED_RETRIES
            else ActionType.STOP_RECOVERY
        )
    if arm == "B1.5":
        return ActionType.SCHEDULE_RETRY if reason in RETRYABLE_REASONS else ActionType.STOP_RECOVERY
    if arm in {"B2.25", "B2.5", "B2.75", "B2", "B3"}:
        if reason in RETRYABLE_REASONS:
            return ActionType.SCHEDULE_RETRY
        if reason in {FailureReason.RISK_OR_FRAUD_REJECTED.value, FailureReason.UNKNOWN_OR_CONFLICTING.value}:
            return ActionType.ESCALATE_TO_HUMAN
        return ActionType.STOP_RECOVERY
    raise ValueError(f"Unknown policy arm: {arm}")


def _authority(event: RecoveryEvent, policy: PolicyConfig) -> AuthorityEnvelope:
    return AuthorityEnvelope(
        correlation_id=event.correlation_id,
        policy_id=policy.policy_id,
        mandate_id=event.mandate_id,
        scheduled_execution_id=event.scheduled_execution_id,
        recovery_case_id=event.recovery_case_id,
        allowed_actions=policy.allow_actions,
        max_amount_minor=event.amount_minor,
        attempts_remaining=max(0, policy.max_attempts - event.attempt_count),
        consent_snapshot_hash="sha256:consent-snapshot",
        expires_at=utc_now() + timedelta(hours=1),
    )


def _decision(
    *,
    arm: str,
    event: RecoveryEvent,
    policy: PolicyConfig,
    decision: Decision,
    proposed: ActionType | None,
    final: ActionType | None,
    reasons: tuple[str, ...],
    diagnosed_reason: str,
    confidence: float,
    model_used: bool = False,
    influence: bool = False,
) -> PolicyDecision:
    return PolicyDecision(
        decision_id=f"dec_{arm.replace('.', '_').lower()}_{event.recovery_case_id}",
        correlation_id=event.correlation_id,
        policy_id=policy.policy_id,
        recovery_case_id=event.recovery_case_id,
        decision=decision,
        proposed_action=proposed,
        final_action=final,
        reason_codes=reasons,
        diagnosed_reason=diagnosed_reason,
        confidence=confidence,
        model_used=model_used,
        policy_version=policy.version,
        reason_sources=("MODEL_INTERPRETATION",) if model_used else ("PROJECT_POLICY",),
        policy_provenance=policy.policy_provenance,
        bounded_interpreter_influence=influence,
    )


def _baseline_run(
    *,
    arm: str,
    event: RecoveryEvent,
    ledger: CommonOutcomeLedger,
    policy: PolicyConfig,
    reason: str,
    confidence: float,
) -> PolicyRun:
    action = proposed_action(arm, reason, attempt_count=event.attempt_count)
    decision = _decision(
        arm=arm,
        event=event,
        policy=policy,
        decision=Decision.ALLOW if action == ActionType.SCHEDULE_RETRY else Decision.STOP,
        proposed=action,
        final=action if action == ActionType.SCHEDULE_RETRY else None,
        reasons=("BASELINE_UNGATED",),
        diagnosed_reason=reason,
        confidence=confidence,
    )
    provider = ReplayProvider(ledger)
    audit = AuditChain()
    audit.append(
        correlation_id=event.correlation_id,
        event_type="policy_decision",
        entity_id=decision.decision_id,
        decision=decision.decision.value,
        reasons=decision.reason_codes,
        provider_call_made=False,
        metadata={"arm": arm, "policy_provenance": policy.policy_provenance},
    )
    result = None
    if decision.final_action == ActionType.SCHEDULE_RETRY:
        key = f"{event.correlation_id}:{event.scheduled_execution_id}:{action.value}"
        result = provider.execute(event=event, action=action, idempotency_key=key)
        audit.append(
            correlation_id=event.correlation_id,
            event_type="provider_action",
            entity_id=result.provider_call_id,
            decision=decision.decision.value,
            reasons=decision.reason_codes,
            provider_call_made=True,
            metadata={"arm": arm, "postcondition_state": result.postcondition_state},
        )
        decision = replace(decision, provider_call_made=True, provider_call_id=result.provider_call_id)
    else:
        audit.append(
            correlation_id=event.correlation_id,
            event_type="action_denied_before_provider",
            entity_id=decision.decision_id,
            decision=decision.decision.value,
            reasons=decision.reason_codes,
            provider_call_made=False,
            metadata={"arm": arm},
        )
    return PolicyRun(
        arm,
        event,
        decision,
        result,
        audit_events=tuple(audit.events),
        audit_verified=audit.verify(),
        ledger_sha256=ledger.sha256(),
    )


def run_policy_case(
    *,
    arm: str,
    event: RecoveryEvent,
    ledger: CommonOutcomeLedger,
    policy: PolicyConfig | None = None,
    interpreter: Callable[[RecoveryEvent], tuple[str, float]] = bounded_interpreter_diagnosis,
) -> PolicyRun:
    if arm not in ARM_ORDER:
        raise ValueError(f"Unknown policy arm: {arm}")
    policy = policy or default_policy(arm)
    deterministic_reason, deterministic_confidence = deterministic_diagnosis(event)
    if arm == "B0":
        decision = _decision(
            arm=arm,
            event=event,
            policy=policy,
            decision=Decision.STOP,
            proposed=None,
            final=None,
            reasons=("NO_INTERVENTION_CONTROL",),
            diagnosed_reason=FailureReason.UNKNOWN_OR_CONFLICTING.value,
            confidence=1.0,
        )
        audit = AuditChain()
        audit.append(
            correlation_id=event.correlation_id,
            event_type="policy_decision",
            entity_id=decision.decision_id,
            decision=decision.decision.value,
            reasons=decision.reason_codes,
            provider_call_made=False,
            metadata={"arm": arm, "policy_provenance": policy.policy_provenance},
        )
        audit.append(
            correlation_id=event.correlation_id,
            event_type="action_denied_before_provider",
            entity_id=decision.decision_id,
            decision=decision.decision.value,
            reasons=decision.reason_codes,
            provider_call_made=False,
            metadata={"arm": arm},
        )
        return PolicyRun(arm, event, decision, None, audit_events=tuple(audit.events), audit_verified=audit.verify(), ledger_sha256=ledger.sha256())
    if arm == "B1":
        return _baseline_run(
            arm=arm,
            event=event,
            ledger=ledger,
            policy=policy,
            reason=FailureReason.UNKNOWN_OR_CONFLICTING.value,
            confidence=1.0,
        )
    if arm == "B1.5":
        return _baseline_run(
            arm=arm,
            event=event,
            ledger=ledger,
            policy=policy,
            reason=deterministic_reason,
            confidence=deterministic_confidence,
        )
    if arm == "RZP":
        # The documented model is ungated by design, so it runs the baseline
        # path. Its diagnosis is recorded for evidence but never consulted.
        return _baseline_run(
            arm=arm,
            event=event,
            ledger=ledger,
            policy=policy,
            reason=deterministic_reason,
            confidence=deterministic_confidence,
        )

    ambiguous_payload = any(
        token in " ".join(str(value).lower() for value in event.failure_payload.values())
        for token in ("conflict", "disagree", "unknown")
    )
    should_interpret = (
        arm == "B3"
        and (
            deterministic_reason == FailureReason.UNKNOWN_OR_CONFLICTING.value
            or ambiguous_payload
        )
    )
    interpreter_metadata = {
        "reason_source": "PROJECT_POLICY",
        "model_calls": 0,
        "model_tokens": 0,
        "model_cost_inr": 0.0,
        "model": None,
    }
    if should_interpret:
        try:
            reason, confidence, interpreter_metadata = validate_interpreter_output(interpreter(event))
        except Exception:
            reason, confidence = FailureReason.UNKNOWN_OR_CONFLICTING.value, 0.0
            interpreter_metadata = {
                "reason_source": "MODEL_INTERPRETATION",
                "model_calls": 0,
                "model_tokens": 0,
                "model_cost_inr": 0.0,
                "model": None,
            }
        interpreter_influence = reason != deterministic_reason
    else:
        reason, confidence = deterministic_reason, deterministic_confidence
        interpreter_influence = False
    provider = ReplayProvider(ledger)
    cases = CaseStore()
    cases.create_or_get(event)
    audit = AuditChain()
    engine = GuardrailEngine(cases=cases, provider=provider, audit=audit)
    action = proposed_action(arm, reason, attempt_count=event.attempt_count)
    context = EvaluationContext(
        event=event,
        policy=policy,
        proposed_action=action,
        authority=_authority(event, policy),
        diagnosed_reason=reason,
        confidence=confidence,
        model_used=should_interpret,
        interpreter_reason_source=(str(interpreter_metadata["reason_source"]) if should_interpret else None),
        model_calls=int(interpreter_metadata["model_calls"]),
        model_tokens=int(interpreter_metadata["model_tokens"]),
        model_cost_inr=float(interpreter_metadata["model_cost_inr"]),
        interpreter_model=(str(interpreter_metadata["model"]) if interpreter_metadata["model"] else None),
    )
    decision = engine.evaluate(context)
    decision = replace(
        decision,
        bounded_interpreter_influence=interpreter_influence,
        model_calls=int(interpreter_metadata["model_calls"]),
        model_tokens=int(interpreter_metadata["model_tokens"]),
        model_cost_inr=float(interpreter_metadata["model_cost_inr"]),
        bounded_interpreter_model=(str(interpreter_metadata["model"]) if interpreter_metadata["model"] else None),
    )
    result = engine.execute(context=context, decision=decision)
    if result is not None:
        decision = replace(decision, provider_call_made=True, provider_call_id=result.provider_call_id)
    return PolicyRun(
        arm,
        event,
        decision,
        result,
        audit_events=tuple(audit.events),
        audit_verified=audit.verify(),
        ledger_sha256=ledger.sha256(),
    )
