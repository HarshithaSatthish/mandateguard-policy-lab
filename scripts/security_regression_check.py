from __future__ import annotations

if not __debug__:
    raise SystemExit(
        "this release gate is built on assert statements; running it with "
        "PYTHONOPTIMIZE or -O would silently disable every check"
    )

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from bailiff.domain import (
    ActionType,
    AuthorityEnvelope,
    CommonOutcome,
    ConsentState,
    Decision,
    FailureReason,
    RecoveryEvent,
)
from bailiff.guardrails import AuditChain, EvaluationContext, GuardrailEngine
from bailiff.policies import default_policy
from bailiff.razorpay_testmode import RazorpayTestModeClient
from bailiff.replay import CommonOutcomeLedger, ReplayProvider
from bailiff.state import CaseStore
from bailiff.webhook import WebhookGate, build_signed_delivery


def _event() -> RecoveryEvent:
    now = datetime.now(timezone.utc)
    return RecoveryEvent(
        event_id="security_evt",
        merchant_id="merchant_security",
        customer_id="customer_security",
        mandate_id="mandate_security",
        scheduled_execution_id="sched_security",
        recovery_case_id="case_security",
        correlation_id="cid_security",
        amount_minor=1000,
        currency="INR",
        failure_code="U30",
        mandate_state="active",
        attempt_count=0,
        pre_debit_state="valid",
        event_time=now,
        failure_payload={"code": "U30"},
        mcc="5817",
        consent=ConsentState(email=True),
        source="security_regression",
        is_scheduled_autopay=True,
        normalized_failure_reason=FailureReason.INSUFFICIENT_FUNDS.value,
        scheduled_execution_at=now,
        proposed_execution_at=now + timedelta(minutes=1),
        last_attempt_at=now - timedelta(days=2),
        pre_debit_sent_at=now - timedelta(days=2),
        valid_until=now + timedelta(days=1),
    )


def _engine(event: RecoveryEvent):
    ledger = CommonOutcomeLedger(
        [
            CommonOutcome(
                case_id=event.recovery_case_id,
                latent_customer_state="willing",
                latent_bank_state="available",
                latent_consent_state=event.consent,
                latent_recovery_window="non_peak",
                latent_outcome_seed=1,
                latent_recoverable_minor=event.amount_minor,
                latent_harm_minor=0,
            )
        ]
    )
    provider = ReplayProvider(ledger)
    cases = CaseStore()
    cases.create_or_get(event)
    audit = AuditChain()
    return GuardrailEngine(cases=cases, provider=provider, audit=audit), provider, audit


def _policy():
    return replace(
        default_policy("B2"),
        non_peak_windows=((0.0, 24.0),),
        minimum_retry_gap_hours=0,
        requires_pre_debit_notice=False,
        amount_review_threshold_minor=10_000_000,
    )


def _authority(event: RecoveryEvent, policy, **overrides) -> AuthorityEnvelope:
    values = dict(
        correlation_id=event.correlation_id,
        policy_id=policy.policy_id,
        mandate_id=event.mandate_id,
        scheduled_execution_id=event.scheduled_execution_id,
        recovery_case_id=event.recovery_case_id,
        allowed_actions=frozenset({ActionType.SCHEDULE_RETRY}),
        max_amount_minor=event.amount_minor,
        attempts_remaining=1,
        consent_snapshot_hash="sha256:security-regression",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    values.update(overrides)
    return AuthorityEnvelope(**values)


def check_authority_identity_binding() -> None:
    event = _event()
    policy = _policy()
    mismatch_cases = {
        "correlation_id": "cid_other",
        "policy_id": "pid_other",
        "mandate_id": "mandate_other",
        "scheduled_execution_id": "sched_other",
        "recovery_case_id": "case_other",
    }
    for field, value in mismatch_cases.items():
        engine, provider, _ = _engine(event)
        context = EvaluationContext(
            event=event,
            policy=policy,
            proposed_action=ActionType.SCHEDULE_RETRY,
            authority=_authority(event, policy, **{field: value}),
            diagnosed_reason=FailureReason.INSUFFICIENT_FUNDS.value,
            confidence=1.0,
        )
        decision = engine.evaluate(context)
        assert decision.decision is Decision.DENY, field
        assert decision.final_action is None, field
        assert any(reason.endswith("_MISMATCH") for reason in decision.reason_codes), field
        result = engine.execute(context=context, decision=decision)
        assert result is None, field
        assert provider.call_count == 0, field


def check_denied_decision_cannot_reuse_prior_provider_result() -> None:
    event = _event()
    policy = _policy()
    engine, provider, audit = _engine(event)
    context = EvaluationContext(
        event=event,
        policy=policy,
        proposed_action=ActionType.SCHEDULE_RETRY,
        authority=_authority(event, policy),
        diagnosed_reason=FailureReason.INSUFFICIENT_FUNDS.value,
        confidence=1.0,
    )
    allowed = engine.evaluate(context)
    assert allowed.decision is Decision.ALLOW
    first = engine.execute(context=context, decision=allowed)
    assert first is not None
    assert provider.call_count == 1

    denied = replace(
        allowed,
        decision=Decision.DENY,
        final_action=None,
        reason_codes=("SECURITY_REGRESSION_FORCED_DENY",),
        provider_call_made=False,
        provider_call_id=None,
    )
    second = engine.execute(context=context, decision=denied)
    assert second is None
    assert provider.call_count == 1
    assert audit.events[-1]["event_type"] == "action_denied_before_provider"


class WrongIdentityClient(RazorpayTestModeClient):
    def __init__(self) -> None:
        super().__init__(key_id="rzp_test_security", key_secret="not-a-real-secret")

    def _request(self, method: str, path: str, **kwargs: object):
        if method == "GET" and path == "/payments/pay_expected":
            return {"id": "pay_other", "status": "captured", "amount": 1000, "currency": "INR"}
        if method == "GET" and path == "/payment_links/plink_expected":
            return {
                "id": "plink_other",
                "status": "paid",
                "amount": 1000,
                "currency": "INR",
                "reference_id": "rt_security",
                "accept_partial": False,
                "payments": [],
            }
        raise AssertionError(f"unexpected request {method} {path}")


def check_provider_identity_echo() -> None:
    client = WrongIdentityClient()
    try:
        client.fetch_payment("pay_expected")
    except ValueError as exc:
        assert "different payment id" in str(exc)
    else:
        raise AssertionError("provider payment identity mismatch was accepted")

    try:
        client.fetch_payment_link("plink_expected")
    except ValueError as exc:
        assert "different payment link id" in str(exc)
    else:
        raise AssertionError("provider payment-link identity mismatch was accepted")


def check_signed_webhook_requires_created_at() -> None:
    secret = "whsec_security_regression"
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_security_missing_time",
                    "error_reason": "insufficient_funds",
                }
            },
            "subscription": {
                "entity": {
                    "id": "sub_security_missing_time",
                    "status": "active",
                }
            },
        },
    }
    raw_body, headers = build_signed_delivery(
        payload,
        secret=secret,
        event_id="evt_security_missing_created_at",
    )
    verdict = WebhookGate(secrets=(secret,)).verify(
        raw_body=raw_body,
        headers=headers,
        received_at=datetime.now(timezone.utc),
    )
    assert not verdict.accepted
    assert verdict.reason_code == "MISSING_CREATED_AT"
    assert not verdict.should_process



def main() -> int:
    check_authority_identity_binding()
    check_denied_decision_cannot_reuse_prior_provider_result()
    check_provider_identity_echo()
    check_signed_webhook_requires_created_at()
    print("security regression check: PASS")
    print("  authority identity binding: PASS")
    print("  denied decision cannot reuse prior provider result: PASS")
    print("  provider payment/link identity echo: PASS")
    print("  signed webhook missing created_at fails closed: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
