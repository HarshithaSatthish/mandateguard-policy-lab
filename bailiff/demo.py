from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from .domain import ActionType, AuthorityEnvelope, CommonOutcome, ConsentState, PolicyConfig, RecoveryEvent
from .guardrails import AuditChain, EvaluationContext, GuardrailEngine
from .interpreter import RealBoundedInterpreter
from .policies import ARM_ORDER, bounded_interpreter_diagnosis, default_policy, run_policy_case
from .razorpay_adapter import normalize_razorpay_autopay_payload, to_razorpay_test_payload
from .replay import CommonOutcomeLedger, ReplayProvider
from .state import CaseStore


_demo_now = datetime.now(timezone.utc)
DEMO_PROPOSED = (_demo_now + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
DEMO_TIME = DEMO_PROPOSED - timedelta(days=2)


def _raw_event(
    case_id: str,
    *,
    attempt_count: int = 1,
    opted_out: bool = False,
    proposed_execution_at: datetime | None = None,
    failure_code: str = "U30",
    description: str = "insufficient balance",
    normalized_reason: str = "INSUFFICIENT_FUNDS",
) -> RecoveryEvent:
    return RecoveryEvent(
        event_id=f"evt_{case_id}",
        merchant_id="merchant_demo",
        customer_id=f"customer_{case_id}",
        mandate_id=f"mandate_{case_id}",
        scheduled_execution_id=f"execution_{case_id}",
        recovery_case_id=case_id,
        correlation_id=f"cid_{case_id}",
        amount_minor=99900,
        currency="INR",
        failure_code=failure_code,
        mandate_state="active",
        attempt_count=attempt_count,
        pre_debit_state="valid",
        event_time=DEMO_TIME,
        failure_payload={"code": failure_code, "description": description},
        mcc="5817",
        consent=ConsentState(email=True, opted_out=opted_out),
        normalized_failure_reason=normalized_reason,
        scheduled_execution_at=DEMO_TIME + timedelta(days=1),
        proposed_execution_at=proposed_execution_at or DEMO_PROPOSED,
        last_attempt_at=DEMO_TIME - timedelta(hours=48),
        pre_debit_sent_at=DEMO_TIME - timedelta(hours=48),
        valid_until=DEMO_TIME + timedelta(days=2),
    )


def make_event(case_id: str, **kwargs: object) -> RecoveryEvent:
    """Create the demo event through the same Razorpay shaped adapter as the benchmark."""
    return normalize_razorpay_autopay_payload(to_razorpay_test_payload(_raw_event(case_id, **kwargs)))


def make_ambiguous_event(case_id: str = "abstain") -> RecoveryEvent:
    return make_event(
        case_id,
        failure_code="UNKNOWN",
        description="bank signal conflicts with duplicate signal",
        normalized_reason="UNKNOWN_OR_CONFLICTING",
    )


def _ledger(event: RecoveryEvent, *, recoverable: bool = True) -> CommonOutcomeLedger:
    outcome = CommonOutcome(
        case_id=event.recovery_case_id,
        latent_customer_state="willing",
        latent_bank_state="available" if recoverable else "risk_rejected",
        latent_consent_state=event.consent,
        latent_recovery_window="non_peak",
        latent_outcome_seed=7,
        latent_recoverable_minor=event.amount_minor if recoverable else 0,
        latent_harm_minor=0 if recoverable else event.amount_minor,
    )
    return CommonOutcomeLedger([outcome])


def runtime(case_event: RecoveryEvent, *, timeout: bool = False):
    ledger = _ledger(case_event)
    key = f"{case_event.correlation_id}:{case_event.scheduled_execution_id}:{ActionType.SCHEDULE_RETRY.value}"
    provider = ReplayProvider(
        ledger,
        timeout_idempotency_keys=frozenset({key}) if timeout else frozenset(),
    )
    cases = CaseStore()
    cases.create_or_get(case_event)
    audit = AuditChain()
    engine = GuardrailEngine(cases=cases, provider=provider, audit=audit)
    policy = default_policy("B2")
    authority = AuthorityEnvelope(
        correlation_id=case_event.correlation_id,
        policy_id=policy.policy_id,
        mandate_id=case_event.mandate_id,
        scheduled_execution_id=case_event.scheduled_execution_id,
        recovery_case_id=case_event.recovery_case_id,
        allowed_actions=policy.allow_actions,
        max_amount_minor=case_event.amount_minor,
        attempts_remaining=max(0, policy.max_attempts - case_event.attempt_count),
        consent_snapshot_hash="sha256:demo-consent",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    return engine, provider, audit, policy, authority


def execute(case_event: RecoveryEvent, *, timeout: bool = False):
    engine, provider, audit, policy, authority = runtime(case_event, timeout=timeout)
    context = EvaluationContext(
        event=case_event,
        policy=policy,
        proposed_action=ActionType.SCHEDULE_RETRY,
        authority=authority,
        diagnosed_reason=case_event.normalized_failure_reason,
        confidence=0.95,
    )
    decision = engine.evaluate(context)
    result = engine.execute(context=context, decision=decision)
    return decision, result, provider, audit, engine


def main() -> None:
    parser = argparse.ArgumentParser(description="MandateGuard Razorpay shaped evidence demo")
    parser.add_argument("--real-interpreter", action="store_true", help="call the optional model for the ambiguous B3 case")
    args = parser.parse_args()

    allowed_event = make_event("allowed")
    allowed_decision, allowed_result, allowed_provider, _, _ = execute(allowed_event)

    denied_event = make_event("exhausted", attempt_count=4)
    denied_decision, denied_result, denied_provider, _, _ = execute(denied_event)

    ambiguous_event = make_ambiguous_event()
    ambiguous_ledger = _ledger(ambiguous_event, recoverable=False)
    interpreter = RealBoundedInterpreter() if args.real_interpreter else bounded_interpreter_diagnosis
    abstain_run = run_policy_case(
        arm="B3",
        event=ambiguous_event,
        ledger=ambiguous_ledger,
        interpreter=interpreter,
    )

    optout_event = make_event("optout", opted_out=True)
    optout_engine, optout_provider, _, optout_policy, optout_authority = runtime(optout_event)
    optout_context = EvaluationContext(
        event=optout_event,
        policy=optout_policy,
        proposed_action=ActionType.SEND_EMAIL,
        authority=optout_authority,
        diagnosed_reason=optout_event.normalized_failure_reason,
        confidence=0.95,
    )
    optout_decision = optout_engine.evaluate(optout_context)
    optout_result = optout_engine.execute(context=optout_context, decision=optout_decision)

    timeout_event = make_event("timeout")
    timeout_decision, timeout_result, timeout_provider, _, timeout_engine = execute(timeout_event, timeout=True)

    tamper_audit = AuditChain()
    tamper_audit.append(
        correlation_id="cid_tamper",
        event_type="policy_decision",
        entity_id="dec_tamper",
        decision="deny",
        reasons=("ATTEMPT_POLICY_EXHAUSTED",),
        provider_call_made=False,
    )
    tamper_before = tamper_audit.verify()
    tamper_audit.events[0]["decision"] = "allow"
    tamper_after = tamper_audit.verify()

    print("MandateGuard Razorpay shaped evidence demo")
    print(f"policy arms: {', '.join(ARM_ORDER)}")
    print(
        f"exhausted retry denial: decision={denied_decision.decision.value}, "
        f"provider_calls={denied_provider.call_count}, result={denied_result}"
    )
    print(f"allowed input: source={allowed_event.source}, provider_error={allowed_event.failure_payload.get('error_reason')}")
    print(
        f"allowed retry: decision={allowed_decision.decision.value}, provider_calls={allowed_provider.call_count}, "
        f"status={allowed_result.status if allowed_result else None}, "
        f"postcondition={allowed_result.postcondition_state if allowed_result else None}"
    )
    print(
        f"ambiguous B3: mode={'real_optional' if args.real_interpreter else 'deterministic_offline'}, "
        f"decision={abstain_run.decision.decision.value}, "
        f"reason={abstain_run.decision.reason_codes}, "
        f"provider_calls={0 if abstain_run.provider_result is None else 1}, "
        f"model_calls={abstain_run.decision.model_calls}, "
        f"interpreter_influence={abstain_run.decision.bounded_interpreter_influence}"
    )
    print(
        f"opted out email: decision={optout_decision.decision.value}, "
        f"provider_calls={optout_provider.call_count}, result={optout_result}"
    )
    print(
        f"timeout: decision={timeout_decision.decision.value}, provider_calls={timeout_provider.call_count}, "
        f"postcondition={timeout_result.postcondition_state if timeout_result else None}, "
        f"case_state={timeout_engine.cases.get('timeout').state.value}"
    )
    print(f"audit tamper: before={tamper_before}, after={tamper_after}")
    print("proof: denied and abstained actions create zero provider calls; timeout goes to human review")


if __name__ == "__main__":
    main()
