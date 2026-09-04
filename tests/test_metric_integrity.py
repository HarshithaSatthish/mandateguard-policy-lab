"""Regression tests for the three defects found in the 0.3 benchmark.

Every test in this file fails against the pre 0.4 implementation. They are
written as invariants rather than as golden numbers so that they keep their
meaning when the fixture, the rules, or the arm set changes.
"""

from __future__ import annotations

import pytest

from bailiff.fixtures import (
    HARM_PROBABILITY_BY_STATE,
    REGIMES,
    generate_fixture,
    latent_harm_states,
)
from bailiff.metrics import annotate_runs, summarize_runs
from bailiff.policies import ARM_ORDER, run_policy_case

SEED = 1701
N = 120

# Ordered from least to most constrained. Only the fully guarded arms are
# expected to reach zero realized harm.
STRICTNESS_ORDER = ("B1", "B1.5", "B2.25", "B2.5", "B2.75", "B2")


def _summaries(regime: str) -> dict[str, dict]:
    events, ledger = generate_fixture(regime, SEED, N)
    out = {}
    for arm in ARM_ORDER:
        runs = annotate_runs(
            [run_policy_case(arm=arm, event=event, ledger=ledger) for event in events],
            ledger,
        )
        out[arm] = summarize_runs(runs, ledger, violation_cost_inr=50.0)
    return out


# ---------------------------------------------------------------------------
# Defect 1: legitimate_recovery_forgone_inr was not comparable across arms.
#
# The old implementation only counted forgone value when `final_action is
# None`. The baseline path spells a stop as None and the guardrail path spells
# it as STOP_RECOVERY or ESCALATE_TO_HUMAN, so guarded arms silently dropped
# their stops and escalations out of the metric. That produced the impossible
# reading where B1.5 recovered more than B2 and also reported more than double
# the legitimate recovery forgone.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", sorted(REGIMES))
def test_forgone_plus_attempted_equals_total_recoverable(regime: str) -> None:
    """Every recoverable rupee is either attempted or forgone. Never both, never neither."""
    events, ledger = generate_fixture(regime, SEED, N)
    for arm in ARM_ORDER:
        runs = annotate_runs(
            [run_policy_case(arm=arm, event=event, ledger=ledger) for event in events],
            ledger,
        )
        total_recoverable = 0
        forgone = 0
        attempted = 0
        for run in runs:
            if ledger.get(run.event.recovery_case_id).latent_recoverable_minor <= 0:
                continue
            total_recoverable += run.event.amount_minor
            if run.provider_result is None:
                forgone += run.event.amount_minor
            else:
                attempted += run.event.amount_minor
        assert forgone + attempted == total_recoverable, arm
        assert forgone == sum(r.decision.legitimate_recovery_forgone_inr_minor for r in runs), arm


@pytest.mark.parametrize("regime", sorted(REGIMES))
def test_forgone_is_monotone_in_strictness(regime: str) -> None:
    """A stricter arm can never forgo less legitimate recovery than a looser one.

    This is the invariant the old metric violated. It held for the baseline
    arms and broke for the guarded arms, which is exactly what an arm dependent
    definition looks like from the outside.
    """
    summaries = _summaries(regime)
    values = [summaries[arm]["legitimate_recovery_forgone_inr"] for arm in STRICTNESS_ORDER]
    assert values == sorted(values), dict(zip(STRICTNESS_ORDER, values))


@pytest.mark.parametrize("regime", sorted(REGIMES))
def test_stops_and_escalations_are_counted_identically(regime: str) -> None:
    """Forgone value must not depend on how an arm spells 'did not act'."""
    events, ledger = generate_fixture(regime, SEED, N)
    seen_symbolic_stop = False
    for arm in ("B2", "B3"):
        runs = annotate_runs(
            [run_policy_case(arm=arm, event=event, ledger=ledger) for event in events],
            ledger,
        )
        for run in runs:
            if run.decision.final_action is None or run.provider_result is not None:
                continue
            # A non None final action with no provider call: stop_recovery or
            # escalate_to_human. The old code scored these as zero forgone.
            seen_symbolic_stop = True
            if ledger.get(run.event.recovery_case_id).latent_recoverable_minor > 0:
                assert run.decision.legitimate_recovery_forgone_inr_minor == run.event.amount_minor
    assert seen_symbolic_stop, "fixture no longer exercises symbolic stops"


# ---------------------------------------------------------------------------
# Defect 2: latent harm was a pure function of the normalized failure reason,
# so an arm gating on the reason code alone captured all harm avoidance by
# construction and every control above it could only destroy recovery. The
# giveaway was that protected_value_by_denial was numerically identical for B0
# and for the full guardrail arms.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", sorted(REGIMES))
def test_harm_is_not_determined_by_the_failure_reason(regime: str) -> None:
    """Within at least one reason class, harm must vary case by case."""
    events, ledger = generate_fixture(regime, SEED, N * 4)
    by_reason: dict[str, set[bool]] = {}
    for event in events:
        harmful = ledger.get(event.recovery_case_id).latent_harm_minor > 0
        by_reason.setdefault(event.normalized_failure_reason, set()).add(harmful)
    mixed = [reason for reason, outcomes in by_reason.items() if len(outcomes) > 1]
    assert mixed, (
        "latent harm is fully predictable from the reason code; "
        "reason gating alone would capture all harm avoidance by construction"
    )


def test_retryable_reasons_carry_genuine_hidden_harm() -> None:
    """The reasons B1.5 retries must contain harm it cannot see.

    Without this the benchmark cannot distinguish reason awareness from policy
    control, which was the whole point of separating B1.5 from B2.
    """
    retryable = {"INSUFFICIENT_FUNDS", "BANK_TIMEOUT_OR_TEMPORARY_FAILURE"}
    for regime in REGIMES:
        events, ledger = generate_fixture(regime, SEED, N * 4)
        selected = [e for e in events if e.normalized_failure_reason in retryable]
        assert selected, regime
        harmful = sum(1 for e in selected if ledger.get(e.recovery_case_id).latent_harm_minor > 0)
        rate = harmful / len(selected)
        assert 0.05 < rate < 0.95, f"{regime}: hidden harm rate among retryable reasons is {rate:.2%}"


@pytest.mark.parametrize("regime", sorted(REGIMES))
def test_protected_value_discriminates_between_arms(regime: str) -> None:
    """Protected value must separate 'did nothing' from 'gated correctly'.

    In the old fixture this column was byte identical for B0, B1.5, B2.25,
    B2.5, B2.75, B2 and B3 in every regime. A column with no discriminating
    power between doing nothing and applying the full guardrail stack is not
    evidence of anything.
    """
    summaries = _summaries(regime)
    protected = {arm: summaries[arm]["protected_value_by_denial_inr"] for arm in ARM_ORDER}
    assert protected["B1"] == 0.0
    assert protected["B1.5"] < protected["B2"], protected
    assert protected["B2"] == protected["B0"], "full guardrails should protect everything B0 does"
    assert len({protected[arm] for arm in STRICTNESS_ORDER}) > 1, protected


@pytest.mark.parametrize("regime", sorted(REGIMES))
def test_protected_and_realized_harm_partition_latent_harm(regime: str) -> None:
    summaries = _summaries(regime)
    events, ledger = generate_fixture(regime, SEED, N)
    total_harm = sum(
        event.amount_minor
        for event in events
        if ledger.get(event.recovery_case_id).latent_harm_minor > 0
    ) / 100
    for arm in ARM_ORDER:
        s = summaries[arm]
        assert s["protected_value_by_denial_inr"] + s["realized_harm_inr"] == pytest.approx(total_harm), arm


@pytest.mark.parametrize("regime", sorted(REGIMES))
def test_guarded_arms_execute_no_prohibited_action(regime: str) -> None:
    summaries = _summaries(regime)
    for arm in ("B2", "B3"):
        assert summaries[arm]["realized_harm_inr"] == 0.0, arm
        assert summaries[arm]["prohibited_execution_rate"] == 0.0, arm
        assert summaries[arm]["violations"] == 0, arm


def test_harm_states_are_mostly_invisible_to_reason_gating() -> None:
    """Only one of the harm bearing states is derivable from the reason code."""
    states = latent_harm_states(
        terminal=False,
        mandate_state="paused",
        opted_out=True,
        attempt_count=9,
        pre_debit_valid=False,
        mcc="5817",
        peak=True,
    )
    assert "terminal_reason" not in states
    assert set(states) == {
        "blocked_mandate_state",
        "customer_opted_out",
        "attempt_cap_exceeded",
        "pre_debit_notice_invalid",
        "peak_window_execution",
    }
    assert set(states) <= set(HARM_PROBABILITY_BY_STATE)
