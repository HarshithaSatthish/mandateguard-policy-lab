from datetime import datetime, timedelta, timezone

import pytest

from bailiff.benchmark import DatasetMutationDetected, freeze_dataset, summarize_seed_results, verify_dataset
from bailiff.domain import (
    ActionType,
    AuthorityEnvelope,
    ConsentState,
    Decision,
    PolicyConfig,
    RecoveryEvent,
    ScopeError,
)
from bailiff.guardrails import AuditChain, EvaluationContext, GuardrailEngine
from bailiff.replay import CommonOutcomeLedger, ReplayProvider
from bailiff.state import CaseStore


def make_event(*, attempt_count: int = 1, opted_out: bool = False, pre_debit_state: str = "valid") -> RecoveryEvent:
    return RecoveryEvent(
        event_id=f"evt_{attempt_count}_{opted_out}_{pre_debit_state}",
        merchant_id="merchant_demo",
        customer_id="customer_redacted",
        mandate_id="mandate_demo",
        scheduled_execution_id=f"exec_{attempt_count}_{opted_out}",
        recovery_case_id=f"case_{attempt_count}_{opted_out}_{pre_debit_state}",
        correlation_id=f"cid_{attempt_count}_{opted_out}_{pre_debit_state}",
        amount_minor=99900,
        currency="INR",
        failure_code="BANK_TIMEOUT",
        mandate_state="active",
        attempt_count=attempt_count,
        pre_debit_state=pre_debit_state,
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        consent=ConsentState(email=True, opted_out=opted_out),
    )


def make_runtime(event: RecoveryEvent, *, max_attempts: int = 4):
    outcomes = CommonOutcomeLedger.from_seed(seed=42, case_ids=[event.recovery_case_id])
    provider = ReplayProvider(outcomes)
    cases = CaseStore()
    cases.create_or_get(event)
    audit = AuditChain()
    engine = GuardrailEngine(cases=cases, provider=provider, audit=audit)
    policy = PolicyConfig(policy_id="pid_test", max_attempts=max_attempts)
    authority = AuthorityEnvelope(
        correlation_id=event.correlation_id,
        policy_id=policy.policy_id,
        mandate_id=event.mandate_id,
        scheduled_execution_id=event.scheduled_execution_id,
        recovery_case_id=event.recovery_case_id,
        allowed_actions=frozenset({ActionType.SCHEDULE_RETRY, ActionType.SEND_EMAIL}),
        max_amount_minor=event.amount_minor,
        attempts_remaining=max(0, max_attempts - event.attempt_count),
        consent_snapshot_hash="sha256:consent",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    return engine, provider, audit, policy, authority


def test_allowed_retry_reaches_provider():
    event = make_event(attempt_count=1)
    engine, provider, audit, policy, authority = make_runtime(event)
    context = EvaluationContext(
        event=event,
        policy=policy,
        proposed_action=ActionType.SCHEDULE_RETRY,
        authority=authority,
    )

    decision = engine.evaluate(context)
    result = engine.execute(context=context, decision=decision)

    assert decision.decision is Decision.ALLOW
    assert result is not None
    assert provider.call_count == 1
    assert audit.verify()


def test_exhausted_attempt_denies_before_provider_call():
    event = make_event(attempt_count=4)
    engine, provider, audit, policy, authority = make_runtime(event, max_attempts=4)
    context = EvaluationContext(
        event=event,
        policy=policy,
        proposed_action=ActionType.SCHEDULE_RETRY,
        authority=authority,
    )

    decision = engine.evaluate(context)
    result = engine.execute(context=context, decision=decision)

    assert decision.decision is Decision.STOP
    assert "ATTEMPT_POLICY_EXHAUSTED" in decision.reason_codes
    assert result is None
    assert provider.call_count == 0
    assert audit.verify()


def test_opt_out_denies_message_before_provider_call():
    event = make_event(attempt_count=1, opted_out=True)
    engine, provider, audit, policy, authority = make_runtime(event)
    context = EvaluationContext(
        event=event,
        policy=policy,
        proposed_action=ActionType.SEND_EMAIL,
        authority=authority,
    )

    decision = engine.evaluate(context)
    result = engine.execute(context=context, decision=decision)

    assert decision.decision is Decision.STOP
    assert "CUSTOMER_OPTED_OUT" in decision.reason_codes
    assert result is None
    assert provider.call_count == 0
    assert audit.verify()


def test_duplicate_action_reuses_provider_result():
    event = make_event(attempt_count=1)
    engine, provider, audit, policy, authority = make_runtime(event)
    context = EvaluationContext(
        event=event,
        policy=policy,
        proposed_action=ActionType.SCHEDULE_RETRY,
        authority=authority,
    )

    first_decision = engine.evaluate(context)
    first_result = engine.execute(context=context, decision=first_decision)
    second_decision = engine.evaluate(context)
    second_result = engine.execute(context=context, decision=second_decision)

    assert first_result is second_result
    assert provider.call_count == 1
    assert any(event["event_type"] == "idempotent_replay" for event in audit.events)
    assert audit.verify()


def test_duplicate_event_does_not_create_second_case():
    event = make_event(attempt_count=1)
    cases = CaseStore()
    first, created_first = cases.create_or_get(event)
    second, created_second = cases.create_or_get(event)

    assert created_first is True
    assert created_second is False
    assert first is second
    assert len(cases.all()) == 1


def test_one_off_payment_is_out_of_scope():
    with pytest.raises(ScopeError):
        RecoveryEvent(
            event_id="evt_one_off",
            merchant_id="merchant_demo",
            customer_id="customer_redacted",
            mandate_id="",
            scheduled_execution_id="",
            recovery_case_id="case_one_off",
            correlation_id="cid_one_off",
            amount_minor=100,
            currency="INR",
            failure_code="DECLINED",
            mandate_state="none",
            attempt_count=0,
            pre_debit_state="not_applicable",
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_scheduled_autopay=False,
        )


def test_authority_cannot_widen():
    event = make_event()
    engine, _, _, policy, authority = make_runtime(event)
    del engine
    with pytest.raises(ValueError):
        authority.attenuate(
            allowed_actions=frozenset(
                {ActionType.SCHEDULE_RETRY, ActionType.SEND_EMAIL, ActionType.SEND_WHATSAPP}
            )
        )


def test_dataset_hash_mutation_is_detected():
    dataset = [
        {"case_id": "case_01", "latent_outcome": "recovered"},
        {"case_id": "case_02", "latent_outcome": "unresolved"},
    ]
    manifest = freeze_dataset(
        dataset_id="holdout_v1",
        dataset=dataset,
        seeds=(17, 42, 73, 101, 202),
        generation_config={"failure_domain": "scheduled_autopay", "version": "v1"},
    )

    verify_dataset(dataset=dataset, manifest=manifest)
    dataset[0]["latent_outcome"] = "unresolved"

    with pytest.raises(DatasetMutationDetected, match="DATASET_MUTATION_DETECTED"):
        verify_dataset(dataset=dataset, manifest=manifest)


def test_audit_tampering_is_detected():
    audit = AuditChain()
    audit.append(
        correlation_id="cid_tamper",
        event_type="policy_decision",
        entity_id="dec_01",
        decision="stop",
        reasons=("ATTEMPT_POLICY_EXHAUSTED",),
        provider_call_made=False,
    )
    audit.append(
        correlation_id="cid_tamper",
        event_type="action_denied_before_provider",
        entity_id="dec_01",
        decision="stop",
        reasons=("ATTEMPT_POLICY_EXHAUSTED",),
        provider_call_made=False,
    )

    assert audit.verify() is True
    audit.events[0]["decision"] = "allow"
    assert audit.verify() is False


def test_final_multi_seed_benchmark_requires_and_reports_five_seeds():
    with pytest.raises(ValueError, match="at least five"):
        summarize_seed_results({17: 100.0, 42: 120.0, 73: 110.0, 101: 115.0})

    summary = summarize_seed_results(
        {17: 100.0, 42: 120.0, 73: 110.0, 101: 115.0, 202: 105.0}
    )

    assert summary["seed_count"] == 5
    assert summary["min"] == 100.0
    assert summary["max"] == 120.0
    assert summary["spread"] == 20.0
    assert set(summary["per_seed"]) == {"17", "42", "73", "101", "202"}
