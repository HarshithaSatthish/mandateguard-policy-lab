"""The Razorpay documented retry model, as a benchmark arm.

Razorpay publishes a subscription retry model: "In a T+3 days cycle, we will
retry the payment thrice. That is, once every day for 3 days, excluding the
date of the charge." This arm implements exactly that and nothing more, so the
benchmark compares against a real documented policy rather than only against
ablations invented for this project.

Two qualifications are load bearing and are asserted here so they cannot be
quietly dropped:

  1. The published schedule is documented for the CARD model. Applying that
     card model to a scheduled AutoPay ledger is this benchmark's explicit
     assumption. It is not a reproduction, benchmark, or claim about Razorpay's
     current Intelligent UPI Retry Engine or production UPI behaviour.
  2. The published model is a schedule. It is silent on the failure reason, so
     this arm is silent on it too. The arm exists to measure what a purely
     temporal policy costs, not to suggest Razorpay does something wrong.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bailiff.domain import ActionType, CommonOutcome, ConsentState, FailureReason, RecoveryEvent
from bailiff.policies import ARM_ORDER, RZP_DOCUMENTED_RETRIES, proposed_action, run_policy_case
from bailiff.replay import CommonOutcomeLedger
from bailiff.rules import RuleCatalog

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(**overrides) -> RecoveryEvent:
    base = dict(
        event_id="rzp_evt", merchant_id="m", customer_id="c",
        mandate_id="mandate_rzp", scheduled_execution_id="sched_rzp",
        recovery_case_id="case_rzp", correlation_id="cid_rzp",
        amount_minor=50_000, currency="INR", failure_code="U30",
        mandate_state="active", attempt_count=0, pre_debit_state="valid",
        event_time=NOW, failure_payload={"code": "U30", "description": "insufficient balance"},
        mcc="5817", consent=ConsentState(email=True), is_scheduled_autopay=True,
        normalized_failure_reason=FailureReason.INSUFFICIENT_FUNDS.value,
        scheduled_execution_at=NOW + timedelta(days=1),
        proposed_execution_at=NOW + timedelta(hours=2),
        last_attempt_at=NOW - timedelta(hours=48),
        pre_debit_sent_at=NOW - timedelta(hours=48),
        valid_until=NOW + timedelta(days=365),
    )
    base.update(overrides)
    return RecoveryEvent(**base)


def _ledger(event: RecoveryEvent, *, harmful: bool = False) -> CommonOutcomeLedger:
    return CommonOutcomeLedger([
        CommonOutcome(
            case_id=event.recovery_case_id, latent_customer_state="willing",
            latent_bank_state="available", latent_consent_state=event.consent,
            latent_recovery_window="non_peak", latent_outcome_seed=5,
            latent_recoverable_minor=event.amount_minor,
            latent_harm_minor=event.amount_minor if harmful else 0,
        )
    ])


def test_the_arm_is_in_the_canonical_order_between_reason_gating_and_the_ablations():
    assert "RZP" in ARM_ORDER
    assert ARM_ORDER.index("B1.5") < ARM_ORDER.index("RZP") < ARM_ORDER.index("B2.25")


def test_the_attempt_budget_matches_the_published_figure():
    assert RZP_DOCUMENTED_RETRIES == 3


def test_the_published_figure_is_pinned_to_its_source_in_the_rules_catalogue():
    """A vendor documented rule must carry its URL, or it is just a number."""
    catalog = RuleCatalog.load()
    assert int(catalog.value("razorpay_documented_retry_attempts")) == RZP_DOCUMENTED_RETRIES
    provenance = catalog.provenance_map()["razorpay_documented_retry_attempts"]
    assert "VENDOR_DOCUMENTED" in provenance


@pytest.mark.parametrize("attempts,expected", [
    (0, ActionType.SCHEDULE_RETRY),
    (1, ActionType.SCHEDULE_RETRY),
    (2, ActionType.SCHEDULE_RETRY),
    (3, ActionType.STOP_RECOVERY),
    (4, ActionType.STOP_RECOVERY),
    (9, ActionType.STOP_RECOVERY),
])
def test_it_retries_exactly_three_times_and_then_halts(attempts, expected):
    """T+1, T+2, T+3, then halted. The whole published model."""
    assert proposed_action("RZP", FailureReason.INSUFFICIENT_FUNDS.value, attempt_count=attempts) == expected


@pytest.mark.parametrize("reason", [reason.value for reason in FailureReason])
def test_the_schedule_is_indifferent_to_the_failure_reason(reason):
    """The published model is temporal. It says nothing about why the debit failed.

    This is the arm's entire purpose: a schedule cannot distinguish a customer
    who is briefly short of funds from a mandate that no longer exists.
    """
    assert proposed_action("RZP", reason, attempt_count=0) == ActionType.SCHEDULE_RETRY


def test_it_retries_a_revoked_mandate_because_a_schedule_cannot_see_one():
    """The measurable consequence, stated as a test rather than as an opinion."""
    event = _event(
        mandate_state="revoked",
        normalized_failure_reason=FailureReason.MANDATE_REVOKED_OR_CANCELLED.value,
    )
    run = run_policy_case(arm="RZP", event=event, ledger=_ledger(event, harmful=True))
    assert run.decision.final_action == ActionType.SCHEDULE_RETRY
    assert run.provider_result is not None


def test_the_guarded_arms_refuse_the_same_case():
    """Same event, same ledger. The difference is policy, not luck."""
    event = _event(
        mandate_state="revoked",
        normalized_failure_reason=FailureReason.MANDATE_REVOKED_OR_CANCELLED.value,
    )
    for arm in ("B2", "B3"):
        run = run_policy_case(arm=arm, event=event, ledger=_ledger(event, harmful=True))
        assert run.provider_result is None


def test_the_arm_still_leaves_a_verifiable_receipt():
    """An ungated arm is still audited. Being wrong is not an excuse for being opaque."""
    event = _event()
    run = run_policy_case(arm="RZP", event=event, ledger=_ledger(event))
    assert run.audit_events
    assert run.audit_verified
