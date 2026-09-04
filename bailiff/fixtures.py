from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from hashlib import sha256
import random
from typing import Iterable

from .domain import CommonOutcome, ConsentState, FailureReason, RecoveryEvent
from .replay import CommonOutcomeLedger


DECLINE_TAXONOMY = tuple(reason.value for reason in FailureReason)

REGIMES: dict[str, dict[FailureReason, float]] = {
    "R1_TRANSIENT": {
        FailureReason.INSUFFICIENT_FUNDS: 0.45,
        FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE: 0.25,
        FailureReason.MANDATE_REVOKED_OR_CANCELLED: 0.08,
        FailureReason.ACCOUNT_CLOSED_OR_BLOCKED: 0.05,
        FailureReason.RISK_OR_FRAUD_REJECTED: 0.04,
        FailureReason.CUSTOMER_OPTED_OUT: 0.05,
        FailureReason.UNKNOWN_OR_CONFLICTING: 0.08,
    },
    "R2_TERMINAL": {
        FailureReason.INSUFFICIENT_FUNDS: 0.18,
        FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE: 0.12,
        FailureReason.MANDATE_REVOKED_OR_CANCELLED: 0.22,
        FailureReason.ACCOUNT_CLOSED_OR_BLOCKED: 0.16,
        FailureReason.RISK_OR_FRAUD_REJECTED: 0.12,
        FailureReason.CUSTOMER_OPTED_OUT: 0.12,
        FailureReason.UNKNOWN_OR_CONFLICTING: 0.08,
    },
    "R3_AMBIGUOUS": {
        FailureReason.INSUFFICIENT_FUNDS: 0.18,
        FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE: 0.14,
        FailureReason.MANDATE_REVOKED_OR_CANCELLED: 0.10,
        FailureReason.ACCOUNT_CLOSED_OR_BLOCKED: 0.08,
        FailureReason.RISK_OR_FRAUD_REJECTED: 0.06,
        FailureReason.CUSTOMER_OPTED_OUT: 0.04,
        FailureReason.UNKNOWN_OR_CONFLICTING: 0.40,
    },
}

AMOUNTS_MINOR = (9900, 14900, 19900, 49900, 99900, 249900)

# Independent compliance exposure rates. These are deliberately NOT conditioned
# on the failure reason. See the comment inside generate_fixture.
INDEPENDENT_OPT_OUT_RATE = 0.07
INDEPENDENT_BLOCKED_MANDATE_RATE = 0.10
BLOCKED_MANDATE_STATES = ("revoked", "cancelled", "paused", "expired")
PDN_EXEMPT_MCC = frozenset({"4784", "7412"})
ATTEMPT_CAP = 4
PEAK_WINDOWS_IST = ((10.0, 13.0), (17.0, 21.5))

# Conditional probability that a money action on a case in this state is
# actually harmful. These are PROJECT ASSUMPTIONS about severity, not observed
# rates, and they are reported as such. The ordering is the claim: executing
# against a dead mandate or an opted out customer is near certainly harmful,
# while a peak window breach is mostly an operational rule.
HARM_PROBABILITY_BY_STATE = {
    "terminal_reason": 1.00,
    "blocked_mandate_state": 0.95,
    "customer_opted_out": 0.90,
    "attempt_cap_exceeded": 0.60,
    "pre_debit_notice_invalid": 0.45,
    "peak_window_execution": 0.15,
}


def _is_peak_ist(execution_at: datetime | None) -> bool:
    """Return whether a proposed execution time falls in a configured peak window."""
    if execution_at is None:
        return False
    local = execution_at.astimezone(ZoneInfo("Asia/Kolkata"))
    hour = local.hour + local.minute / 60 + local.second / 3600
    return any(start <= hour < end for start, end in PEAK_WINDOWS_IST)


def latent_harm_states(
    *,
    terminal: bool,
    mandate_state: str,
    opted_out: bool,
    attempt_count: int,
    pre_debit_valid: bool,
    mcc: str,
    peak: bool,
) -> tuple[str, ...]:
    """Return every harm bearing state present on a case.

    Only the first entry is derivable from the normalized failure reason. Every
    other entry is visible solely to the full guardrail profile, which is what
    makes the benchmark able to separate reason awareness from policy control.
    """
    states: list[str] = []
    if terminal:
        states.append("terminal_reason")
    if mandate_state.lower() in set(BLOCKED_MANDATE_STATES):
        states.append("blocked_mandate_state")
    if opted_out:
        states.append("customer_opted_out")
    if attempt_count >= ATTEMPT_CAP:
        states.append("attempt_cap_exceeded")
    if not pre_debit_valid and mcc not in PDN_EXEMPT_MCC:
        states.append("pre_debit_notice_invalid")
    if peak:
        states.append("peak_window_execution")
    return tuple(states)


def latent_harm_probability(**kwargs: object) -> float:
    """Severity of the worst harm bearing state on the case."""
    states = latent_harm_states(**kwargs)  # type: ignore[arg-type]
    if not states:
        return 0.0
    return max(HARM_PROBABILITY_BY_STATE[state] for state in states)


def _pick(rng: random.Random, distribution: dict[FailureReason, float]) -> FailureReason:
    target = rng.random()
    cumulative = 0.0
    for reason, probability in distribution.items():
        cumulative += probability
        if target <= cumulative:
            return reason
    return next(reversed(distribution))


def _payload(reason: FailureReason, rng: random.Random) -> tuple[str, dict[str, str]]:
    payloads = {
        FailureReason.INSUFFICIENT_FUNDS: [("U30", "insufficient balance"), ("51", "not sufficient funds")],
        FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE: [("U69", "bank unavailable"), ("BT", "timeout")],
        FailureReason.MANDATE_REVOKED_OR_CANCELLED: [("UM3", "mandate revoked"), ("M014", "standing instruction cancelled")],
        FailureReason.ACCOUNT_CLOSED_OR_BLOCKED: [("U16", "account closed"), ("14", "invalid account")],
        FailureReason.RISK_OR_FRAUD_REJECTED: [("U28", "risk rejected"), ("R01", "suspected fraud")],
        FailureReason.CUSTOMER_OPTED_OUT: [("OPT", "customer unsubscribed")],
        FailureReason.UNKNOWN_OR_CONFLICTING: [("U30", "mandate revoked"), ("UM3", "insufficient balance"), ("XX99", "unmapped error")],
    }
    code, description = rng.choice(payloads[reason])
    conflict = reason == FailureReason.UNKNOWN_OR_CONFLICTING or rng.random() < 0.03
    return code, {"code": code, "description": description, "conflict": str(conflict).lower()}


def generate_fixture(regime: str, seed: int, n: int = 100) -> tuple[list[RecoveryEvent], CommonOutcomeLedger]:
    """Generate one immutable event ledger and its latent outcomes.

    The returned ledger is created once. Every arm must receive the exact same
    event list and ledger; no arm may call this function independently.
    """
    if regime not in REGIMES:
        raise ValueError(f"Unknown regime: {regime}")
    rng = random.Random(seed)
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events: list[RecoveryEvent] = []
    outcomes: list[CommonOutcome] = []

    for index in range(n):
        reason = _pick(rng, REGIMES[regime])
        amount = rng.choice(AMOUNTS_MINOR)
        case_id = f"{regime}_{seed}_case_{index:05d}"
        event_time = base_time + timedelta(minutes=index)
        code, payload = _payload(reason, rng)
        terminal = reason in {
            FailureReason.MANDATE_REVOKED_OR_CANCELLED,
            FailureReason.ACCOUNT_CLOSED_OR_BLOCKED,
            FailureReason.RISK_OR_FRAUD_REJECTED,
            FailureReason.CUSTOMER_OPTED_OUT,
        }
        bank_state = {
            FailureReason.INSUFFICIENT_FUNDS: "available" if rng.random() < 0.55 else "temporary_failure",
            FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE: "available" if rng.random() < 0.75 else "temporary_failure",
            FailureReason.MANDATE_REVOKED_OR_CANCELLED: "mandate_revoked",
            FailureReason.ACCOUNT_CLOSED_OR_BLOCKED: "account_closed",
            FailureReason.RISK_OR_FRAUD_REJECTED: "risk_rejected",
            FailureReason.CUSTOMER_OPTED_OUT: "available",
            FailureReason.UNKNOWN_OR_CONFLICTING: "unknown",
        }[reason]
        customer_state = "unwilling" if reason == FailureReason.CUSTOMER_OPTED_OUT else rng.choice(("willing", "willing", "unknown"))
        recoverable = reason in {
            FailureReason.INSUFFICIENT_FUNDS,
            FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE,
            FailureReason.UNKNOWN_OR_CONFLICTING,
        } and not terminal and customer_state == "willing"
        # ------------------------------------------------------------------
        # Compliance exposure is drawn INDEPENDENTLY of the failure reason.
        #
        # This is the load bearing property of the fixture. If latent harm were
        # a pure function of `reason`, then an arm that gates on the reason code
        # alone (B1.5) would capture every unit of harm avoidance by
        # construction, and every control above it could only destroy recovery.
        # A benchmark built that way cannot answer the question the project is
        # asking, because the answer is fixed before any policy runs.
        #
        # Real scheduled AutoPay exposure does not work that way. A bank can
        # return "insufficient funds" on a mandate the customer separately
        # paused, on a customer who separately opted out, on an attempt that is
        # already over the authority cap, or without a valid pre debit notice.
        # Those are exactly the states that only the full guardrail profile
        # inspects, so they are drawn here from their own independent draws.
        # ------------------------------------------------------------------
        independent_opt_out = rng.random() < INDEPENDENT_OPT_OUT_RATE
        independent_blocked_mandate = rng.random() < INDEPENDENT_BLOCKED_MANDATE_RATE

        opted_out = reason == FailureReason.CUSTOMER_OPTED_OUT or independent_opt_out
        consent = ConsentState(email=True, sms=rng.random() < 0.6, whatsapp=rng.random() < 0.5, opted_out=opted_out)
        if reason == FailureReason.MANDATE_REVOKED_OR_CANCELLED and rng.random() < 0.8:
            mandate_state = "revoked"
        elif independent_blocked_mandate:
            mandate_state = rng.choice(BLOCKED_MANDATE_STATES)
        else:
            mandate_state = "active"
        attempt_count = rng.choice((0, 1, 1, 2, 3, 4))
        pre_debit_valid = rng.random() >= 0.20
        pre_debit_sent_at = event_time - timedelta(hours=48 if pre_debit_valid else 2)
        proposed_execution_at = event_time + timedelta(hours=rng.choice((2, 14, 22, 26)))
        mcc_value = rng.choice(("5817", "5968", "4784", "7412", "6300"))
        events.append(
            RecoveryEvent(
                event_id=f"evt_{case_id}",
                merchant_id="merchant_demo",
                customer_id=f"customer_{index:05d}",
                mandate_id=f"mandate_{seed}_{index:05d}",
                scheduled_execution_id=f"scheduled_{seed}_{index:05d}",
                recovery_case_id=case_id,
                correlation_id=f"cid_{case_id}",
                amount_minor=amount,
                currency="INR",
                failure_code=code,
                mandate_state=mandate_state,
                attempt_count=attempt_count,
                pre_debit_state="valid" if pre_debit_valid else "invalid",
                event_time=event_time,
                failure_payload=payload,
                mcc=mcc_value,
                consent=consent,
                source="synthetic_fixture",
                is_scheduled_autopay=True,
                normalized_failure_reason=reason.value,
                scheduled_execution_at=event_time + timedelta(days=1),
                proposed_execution_at=proposed_execution_at,
                last_attempt_at=event_time - timedelta(hours=12),
                pre_debit_sent_at=pre_debit_sent_at,
            )
        )
        digest = sha256(f"{seed}:{case_id}".encode()).digest()
        peak = _is_peak_ist(proposed_execution_at)
        harm_probability = latent_harm_probability(
            terminal=terminal,
            mandate_state=mandate_state,
            opted_out=opted_out,
            attempt_count=attempt_count,
            pre_debit_valid=pre_debit_valid,
            mcc=mcc_value,
            peak=peak,
        )
        harmful = rng.random() < harm_probability
        outcomes.append(
            CommonOutcome(
                case_id=case_id,
                latent_customer_state=customer_state,
                latent_bank_state=bank_state,
                latent_consent_state=consent,
                latent_recovery_window="peak" if peak else "non_peak",
                latent_outcome_seed=int.from_bytes(digest[:8], "big"),
                latent_recoverable_minor=amount if recoverable else 0,
                latent_harm_minor=amount if harmful else 0,
            )
        )
    return events, CommonOutcomeLedger(outcomes)
