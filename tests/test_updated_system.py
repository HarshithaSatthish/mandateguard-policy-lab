from datetime import datetime, timedelta, timezone

from bailiff.checker import violations
from bailiff.domain import ActionType, AuthorityEnvelope, CommonOutcome, ConsentState, Decision, PolicyConfig, RecoveryEvent
from bailiff.fixtures import generate_fixture
from bailiff.guardrails import AuditChain, EvaluationContext, GuardrailEngine
from bailiff.metrics import summarize_runs
from bailiff.policies import ARM_ORDER, default_policy, run_policy_case
from bailiff.replay import CommonOutcomeLedger, ReplayProvider
from bailiff.runner import aggregate_rows, run_experiment
from bailiff.state import CaseState, CaseStore


def event(**changes) -> RecoveryEvent:
    base = dict(
        event_id="evt_system",
        merchant_id="merchant",
        customer_id="customer",
        mandate_id="mandate",
        scheduled_execution_id="scheduled",
        recovery_case_id="case_system",
        correlation_id="cid_system",
        amount_minor=99900,
        currency="INR",
        failure_code="U30",
        mandate_state="active",
        attempt_count=1,
        pre_debit_state="valid",
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        failure_payload={"code": "U30", "description": "insufficient balance"},
        mcc="5817",
        consent=ConsentState(email=True),
        normalized_failure_reason="INSUFFICIENT_FUNDS",
        proposed_execution_at=datetime(2026, 1, 1, 3, tzinfo=timezone.utc),
    )
    base.update(changes)
    return RecoveryEvent(**base)


def runtime(e: RecoveryEvent, *, provider: ReplayProvider | None = None):
    ledger = provider.outcomes if provider else CommonOutcomeLedger.from_seed(seed=7, case_ids=[e.recovery_case_id])
    provider = provider or ReplayProvider(ledger)
    cases = CaseStore()
    cases.create_or_get(e)
    audit = AuditChain()
    engine = GuardrailEngine(cases=cases, provider=provider, audit=audit)
    policy = PolicyConfig(policy_id="pid_system")
    authority = AuthorityEnvelope(
        correlation_id=e.correlation_id,
        policy_id=policy.policy_id,
        mandate_id=e.mandate_id,
        scheduled_execution_id=e.scheduled_execution_id,
        recovery_case_id=e.recovery_case_id,
        allowed_actions=policy.allow_actions,
        max_amount_minor=e.amount_minor,
        attempts_remaining=max(0, policy.max_attempts - e.attempt_count),
        consent_snapshot_hash="sha256:consent",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    return engine, provider, audit, policy, authority, ledger


def test_all_arms_share_one_ledger_and_canonical_order():
    events, ledger = generate_fixture("R3_AMBIGUOUS", 1701, 12)
    hashes = {ledger.sha256()}
    for arm in ARM_ORDER:
        runs = [run_policy_case(arm=arm, event=e, ledger=ledger) for e in events]
        assert len(runs) == len(events)
        hashes.add(ledger.sha256())
    assert ARM_ORDER == ("B0", "B1", "B1.5", "RZP", "B2.25", "B2.5", "B2.75", "B2", "B3")
    assert len(hashes) == 1


def test_frontier_profiles_are_explicit_and_full_arms_remain_protected():
    assert default_policy("B2.25").guardrail_profile == "timing_only"
    assert default_policy("B2.5").guardrail_profile == "timing_attempts"
    assert default_policy("B2.75").guardrail_profile == "timing_attempts_consent"
    assert default_policy("B2").guardrail_profile == "full"
    assert default_policy("B3").guardrail_profile == "full"

    rows, _, _ = run_experiment(
        seeds=(1701, 2029, 3313, 4157, 5011),
        n_per_seed=12,
        regimes=("R1_TRANSIENT",),
    )
    for arm in ("B2", "B3"):
        assert all(row["violations"] == 0 for row in rows if row["arm"] == arm)
    assert all(
        next(row for row in rows if row["arm"] == earlier)["violations"]
        >= next(row for row in rows if row["arm"] == later)["violations"]
        for earlier, later in (("B2.25", "B2.5"), ("B2.5", "B2.75"), ("B2.75", "B2"))
    )

    opted_out = event(
        consent=ConsentState(opted_out=True),
        last_attempt_at=datetime(2025, 12, 31, tzinfo=timezone.utc),
        proposed_execution_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    ledger = CommonOutcomeLedger.from_seed(seed=73, case_ids=[opted_out.recovery_case_id])
    relaxed = run_policy_case(arm="B2.25", event=opted_out, ledger=ledger)
    protected = run_policy_case(arm="B2.75", event=opted_out, ledger=ledger)
    assert relaxed.decision.final_action is ActionType.SCHEDULE_RETRY
    assert protected.provider_result is None
    assert "CUSTOMER_OPTED_OUT" in protected.decision.reason_codes


def test_b15_is_deterministic_retry_only_and_stops_terminal_reason():
    e = event(
        failure_code="UM3",
        normalized_failure_reason="MANDATE_REVOKED_OR_CANCELLED",
        mandate_state="revoked",
    )
    ledger = CommonOutcomeLedger.from_seed(seed=9, case_ids=[e.recovery_case_id])
    result = run_policy_case(arm="B1.5", event=e, ledger=ledger)
    assert result.decision.final_action is None
    assert result.provider_result is None
    assert result.decision.decision is Decision.STOP


def test_expired_state_and_peak_execution_are_denied_before_provider():
    e = event(mandate_state="expired")
    engine, provider, audit, policy, authority, _ = runtime(e)
    context = EvaluationContext(
        event=e,
        policy=policy,
        proposed_action=ActionType.SCHEDULE_RETRY,
        authority=authority,
        diagnosed_reason=e.normalized_failure_reason,
        confidence=0.95,
    )
    decision = engine.evaluate(context)
    assert decision.decision is Decision.STOP
    assert engine.execute(context=context, decision=decision) is None
    assert provider.call_count == 0

    e2 = event(
        recovery_case_id="case_peak",
        correlation_id="cid_peak",
        event_id="evt_peak",
        scheduled_execution_id="scheduled_peak",
        proposed_execution_at=datetime(2026, 1, 1, 5, 30, tzinfo=timezone.utc),
    )
    engine2, provider2, audit2, policy2, authority2, _ = runtime(e2)
    context2 = EvaluationContext(
        event=e2,
        policy=policy2,
        proposed_action=ActionType.SCHEDULE_RETRY,
        authority=authority2,
        diagnosed_reason=e2.normalized_failure_reason,
        confidence=0.95,
    )
    decision2 = engine2.evaluate(context2)
    assert "EXECUTION_OUTSIDE_NON_PEAK_WINDOW" in decision2.reason_codes
    assert engine2.execute(context=context2, decision=decision2) is None
    assert provider2.call_count == 0


def test_timeout_postcondition_routes_to_human_review():
    e = event()
    ledger = CommonOutcomeLedger.from_seed(seed=11, case_ids=[e.recovery_case_id])
    key = f"{e.correlation_id}:{e.scheduled_execution_id}:{ActionType.SCHEDULE_RETRY.value}"
    provider = ReplayProvider(ledger, timeout_idempotency_keys=frozenset({key}))
    engine, _, audit, policy, authority, _ = runtime(e, provider=provider)
    context = EvaluationContext(
        event=e,
        policy=policy,
        proposed_action=ActionType.SCHEDULE_RETRY,
        authority=authority,
        diagnosed_reason=e.normalized_failure_reason,
        confidence=0.95,
    )
    decision = engine.evaluate(context)
    result = engine.execute(context=context, decision=decision)
    assert result is not None
    assert result.timed_out is True
    assert engine.cases.get(e.recovery_case_id).state is CaseState.HUMAN_REVIEW
    assert any(item["event_type"] == "provider_postcondition_unknown" for item in audit.events)


def test_different_action_after_terminal_case_is_not_replayed():
    e = event()
    ledger = CommonOutcomeLedger([
        CommonOutcome(
            case_id=e.recovery_case_id,
            latent_customer_state="willing",
            latent_bank_state="available",
            latent_consent_state=e.consent,
            latent_recovery_window="non_peak",
            latent_outcome_seed=1,
            latent_recoverable_minor=e.amount_minor,
        )
    ])
    provider = ReplayProvider(ledger)
    engine, provider, audit, policy, authority, _ = runtime(e, provider=provider)
    retry_context = EvaluationContext(
        event=e,
        policy=policy,
        proposed_action=ActionType.SCHEDULE_RETRY,
        authority=authority,
        diagnosed_reason=e.normalized_failure_reason,
        confidence=0.95,
    )
    first = engine.evaluate(retry_context)
    first_result = engine.execute(context=retry_context, decision=first)
    assert first_result is not None
    email_context = EvaluationContext(
        event=e,
        policy=policy,
        proposed_action=ActionType.SEND_EMAIL,
        authority=authority,
        diagnosed_reason=e.normalized_failure_reason,
        confidence=0.95,
    )
    second = engine.evaluate(email_context)
    assert "CASE_TERMINAL" in second.reason_codes
    assert engine.execute(context=email_context, decision=second) is None
    assert provider.call_count == 1


def test_final_benchmark_has_real_forgone_and_protected_metrics():
    rows, evidence, hashes = run_experiment(seeds=(1701, 2029, 3313, 4157, 5011), n_per_seed=12)
    assert len(hashes) == 15
    assert all(arm in {row["arm"] for row in rows} for arm in ARM_ORDER)
    b2_rows = [row for row in rows if row["arm"] == "B2"]
    assert any(row["legitimate_recovery_forgone_inr"] >= 0 for row in b2_rows)
    assert any(row["protected_value_by_denial_inr"] >= 0 for row in b2_rows)
    aggregate = aggregate_rows(rows)
    assert all(row["seeds"] == 5 for row in aggregate)
    assert evidence
