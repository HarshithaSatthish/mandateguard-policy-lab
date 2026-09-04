"""Property based invariants over randomly generated events.

The example based tests check that the runtime behaves on cases someone
thought of. These check that it behaves on cases nobody thought of.

Every property here is a sentence from README.md turned into an assertion
quantified over the whole input space: not "this revoked mandate was denied"
but "no event in any reachable state produces a provider call from a decision
that was not an allow". Hypothesis generates events across mandate states,
consent, attempt counts, pre debit states, MCCs, amounts and execution times,
and shrinks any counterexample to a minimal reproduction.

These are slower than the example tests and deliberately so. They are the
difference between a suite that documents behaviour and one that constrains it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bailiff.domain import (
    ActionType,
    CommonOutcome,
    ConsentState,
    Decision,
    FailureReason,
    RecoveryEvent,
)
from bailiff.metrics import EXECUTABLE, annotate_runs, summarize_runs
from bailiff.policies import ARM_ORDER, run_policy_case
from bailiff.replay import CommonOutcomeLedger

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
GUARDED_ARMS = ("B2", "B3")

SLOW = settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@st.composite
def recovery_events(draw) -> RecoveryEvent:
    """Generate any in scope scheduled AutoPay failure event.

    Deliberately unconstrained across every field a guardrail reads, so the
    generator explores prohibited combinations as readily as permitted ones.
    """
    reason = draw(st.sampled_from([r.value for r in FailureReason]))
    amount = draw(st.integers(min_value=100, max_value=5_000_000))
    mandate_state = draw(
        st.sampled_from(["active", "enabled", "revoked", "cancelled", "paused", "expired"])
    )
    attempt_count = draw(st.integers(min_value=0, max_value=12))
    pre_debit_state = draw(st.sampled_from(["valid", "invalid", "missing"]))
    mcc = draw(st.sampled_from(["5817", "5968", "4784", "7412", "6300"]))
    opted_out = draw(st.booleans())
    offset_hours = draw(st.integers(min_value=1, max_value=72))
    expiry_days = draw(st.integers(min_value=-30, max_value=400))
    conflict = draw(st.booleans())
    description = draw(
        st.text(
            alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
            min_size=0,
            max_size=60,
        )
    )

    return RecoveryEvent(
        event_id="prop_evt",
        merchant_id="merchant",
        customer_id="customer",
        mandate_id="mandate_prop",
        scheduled_execution_id="sched_prop",
        recovery_case_id="case_prop",
        correlation_id="cid_prop",
        amount_minor=amount,
        currency="INR",
        failure_code=draw(st.sampled_from(["U30", "U69", "UM3", "U16", "U28", "OPT", "XX99"])),
        mandate_state=mandate_state,
        attempt_count=attempt_count,
        pre_debit_state=pre_debit_state,
        event_time=BASE_TIME,
        failure_payload={"description": description, "conflict": str(conflict).lower()},
        mcc=mcc,
        consent=ConsentState(
            email=True,
            sms=draw(st.booleans()),
            whatsapp=draw(st.booleans()),
            opted_out=opted_out,
        ),
        source="synthetic_fixture",
        is_scheduled_autopay=True,
        normalized_failure_reason=reason,
        scheduled_execution_at=BASE_TIME + timedelta(days=1),
        proposed_execution_at=BASE_TIME + timedelta(hours=offset_hours),
        last_attempt_at=BASE_TIME - timedelta(hours=draw(st.integers(1, 96))),
        pre_debit_sent_at=BASE_TIME - timedelta(hours=draw(st.integers(1, 96))),
        valid_until=BASE_TIME + timedelta(days=expiry_days),
    )


def _ledger(event: RecoveryEvent, recoverable: bool, harmful: bool) -> CommonOutcomeLedger:
    return CommonOutcomeLedger(
        [
            CommonOutcome(
                case_id=event.recovery_case_id,
                latent_customer_state="willing",
                latent_bank_state="available",
                latent_consent_state=event.consent,
                latent_recovery_window="non_peak",
                latent_outcome_seed=11,
                latent_recoverable_minor=event.amount_minor if recoverable else 0,
                latent_harm_minor=event.amount_minor if harmful else 0,
            )
        ]
    )


# ---------------------------------------------------------------------------
# The provider boundary
# ---------------------------------------------------------------------------


@SLOW
@given(event=recovery_events(), arm=st.sampled_from(ARM_ORDER), harmful=st.booleans())
def test_a_non_allow_decision_never_reaches_the_provider(event, arm, harmful):
    """The load bearing claim, quantified over every reachable event."""
    run = run_policy_case(arm=arm, event=event, ledger=_ledger(event, True, harmful))
    if run.decision.decision is not Decision.ALLOW:
        assert run.provider_result is None


@SLOW
@given(event=recovery_events(), arm=st.sampled_from(ARM_ORDER))
def test_a_provider_call_implies_an_allowed_executable_action(event, arm):
    """The converse: nothing reaches the provider except a permitted executable action."""
    run = run_policy_case(arm=arm, event=event, ledger=_ledger(event, True, False))
    if run.provider_result is not None:
        assert run.decision.decision is Decision.ALLOW
        assert run.decision.final_action in EXECUTABLE


@SLOW
@given(event=recovery_events())
def test_guarded_arms_never_execute_against_a_dead_mandate(event):
    """Mandate state is read from the event, so no interpretation can override it."""
    dead = event.mandate_state.lower() not in {"active", "enabled"}
    if not dead:
        return
    for arm in GUARDED_ARMS:
        run = run_policy_case(arm=arm, event=event, ledger=_ledger(event, True, True))
        assert run.provider_result is None


@SLOW
@given(event=recovery_events())
def test_guarded_arms_never_contact_an_opted_out_customer(event):
    if not event.consent.opted_out:
        return
    contact = {ActionType.SEND_EMAIL, ActionType.SEND_SMS, ActionType.SEND_WHATSAPP}
    for arm in GUARDED_ARMS:
        run = run_policy_case(arm=arm, event=event, ledger=_ledger(event, True, True))
        assert run.decision.final_action not in contact


@SLOW
@given(event=recovery_events(), arm=st.sampled_from(ARM_ORDER))
def test_every_run_leaves_a_verifiable_audit_chain(event, arm):
    """A decision with no verifiable receipt is not evidence."""
    run = run_policy_case(arm=arm, event=event, ledger=_ledger(event, True, False))
    assert run.audit_events
    assert run.audit_verified


@SLOW
@given(event=recovery_events(), arm=st.sampled_from(ARM_ORDER))
def test_a_repeated_decision_is_idempotent(event, arm):
    """Re-running the same case must not produce a second provider call."""
    ledger = _ledger(event, True, False)
    first = run_policy_case(arm=arm, event=event, ledger=ledger)
    second = run_policy_case(arm=arm, event=event, ledger=ledger)
    if first.provider_result is None:
        assert second.provider_result is None
    else:
        assert second.provider_result is not None
        assert first.provider_result.provider_call_id == second.provider_result.provider_call_id


# ---------------------------------------------------------------------------
# Metric conservation
#
# These are the properties that would have caught the forgone comparability
# bug directly, rather than by noticing an odd number in a report.
# ---------------------------------------------------------------------------


@SLOW
@given(
    events=st.lists(recovery_events(), min_size=1, max_size=6),
    arm=st.sampled_from(ARM_ORDER),
    flags=st.lists(st.tuples(st.booleans(), st.booleans()), min_size=6, max_size=6),
)
def test_harm_is_conserved_between_protected_and_realized(events, arm, flags):
    """Every rupee of latent harm is either protected or realized. Never both, never neither."""
    outcomes = []
    prepared = []
    for index, event in enumerate(events):
        recoverable, harmful = flags[index % len(flags)]
        cased = type(event)(**{**event.__dict__, "recovery_case_id": f"case_{index}"})
        prepared.append(cased)
        outcomes.append(
            CommonOutcome(
                case_id=cased.recovery_case_id,
                latent_customer_state="willing",
                latent_bank_state="available",
                latent_consent_state=cased.consent,
                latent_recovery_window="non_peak",
                latent_outcome_seed=index,
                latent_recoverable_minor=cased.amount_minor if recoverable else 0,
                latent_harm_minor=cased.amount_minor if harmful else 0,
            )
        )
    ledger = CommonOutcomeLedger(outcomes)
    runs = annotate_runs(
        [run_policy_case(arm=arm, event=event, ledger=ledger) for event in prepared], ledger
    )
    summary = summarize_runs(runs, ledger)

    total_harm = sum(o.latent_harm_minor for o in outcomes) / 100
    assert summary["protected_value_by_denial_inr"] + summary["realized_harm_inr"] == pytest.approx(
        total_harm
    )


@SLOW
@given(
    events=st.lists(recovery_events(), min_size=1, max_size=6),
    arm=st.sampled_from(ARM_ORDER),
    flags=st.lists(st.tuples(st.booleans(), st.booleans()), min_size=6, max_size=6),
)
def test_recoverable_value_is_conserved_between_forgone_and_attempted(events, arm, flags):
    """Recoverable value is either forgone or attempted at the provider. No third bucket."""
    outcomes = []
    prepared = []
    for index, event in enumerate(events):
        recoverable, harmful = flags[index % len(flags)]
        cased = type(event)(**{**event.__dict__, "recovery_case_id": f"case_{index}"})
        prepared.append(cased)
        outcomes.append(
            CommonOutcome(
                case_id=cased.recovery_case_id,
                latent_customer_state="willing",
                latent_bank_state="available",
                latent_consent_state=cased.consent,
                latent_recovery_window="non_peak",
                latent_outcome_seed=index,
                latent_recoverable_minor=cased.amount_minor if recoverable else 0,
                latent_harm_minor=cased.amount_minor if harmful else 0,
            )
        )
    ledger = CommonOutcomeLedger(outcomes)
    runs = annotate_runs(
        [run_policy_case(arm=arm, event=event, ledger=ledger) for event in prepared], ledger
    )
    summary = summarize_runs(runs, ledger)

    attempted_on_recoverable = sum(
        run.event.amount_minor
        for run in runs
        if ledger.get(run.event.recovery_case_id).latent_recoverable_minor > 0
        and run.provider_result is not None
    ) / 100
    total_recoverable = sum(o.latent_recoverable_minor for o in outcomes) / 100
    assert summary["legitimate_recovery_forgone_inr"] + attempted_on_recoverable == pytest.approx(
        total_recoverable
    )


@SLOW
@given(event=recovery_events(), arm=st.sampled_from(ARM_ORDER))
def test_metrics_are_never_negative(event, arm):
    """A negative recovered, forgone, protected or harm figure is a sign error."""
    ledger = _ledger(event, True, True)
    runs = annotate_runs([run_policy_case(arm=arm, event=event, ledger=ledger)], ledger)
    summary = summarize_runs(runs, ledger)
    for metric in (
        "recovered_inr",
        "legitimate_recovery_forgone_inr",
        "protected_value_by_denial_inr",
        "realized_harm_inr",
        "violations",
    ):
        assert summary[metric] >= 0, f"{metric} went negative"
