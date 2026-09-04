from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .domain import ActionType, CONTACT_ACTIONS, FailureReason, PolicyDecision, RecoveryEvent

# Deliberately transcribed independently from the runtime policy. Drift is a finding.
BLOCKED_STATES = {"revoked", "cancelled", "paused", "expired"}
TERMINAL_REASONS = {
    FailureReason.MANDATE_REVOKED_OR_CANCELLED.value,
    FailureReason.ACCOUNT_CLOSED_OR_BLOCKED.value,
    FailureReason.RISK_OR_FRAUD_REJECTED.value,
    FailureReason.CUSTOMER_OPTED_OUT.value,
}
PEAK_WINDOWS = ((10.0, 13.0), (17.0, 21.5))
ATTEMPT_CAP = 4
PDN_MIN_HOURS = 24.0
MIN_RETRY_GAP_HOURS = 24.0
PDN_EXEMPT_MCC = {"4784", "7412"}
MIN_CONFIDENCE = 0.70


def _peak(execution_at: datetime | None) -> bool:
    if execution_at is None:
        return False
    local = execution_at.astimezone(ZoneInfo("Asia/Kolkata"))
    hour = local.hour + local.minute / 60 + local.second / 3600
    return any(start <= hour < end for start, end in PEAK_WINDOWS)


def violations(event: RecoveryEvent, decision: PolicyDecision) -> tuple[str, ...]:
    """Return every policy rule breached by the action that was actually selected."""
    action = decision.final_action
    if action is None:
        return ()
    money = action == ActionType.SCHEDULE_RETRY
    contact = action in CONTACT_ACTIONS
    found: list[str] = []
    state = event.mandate_state.lower()
    if (money or contact) and (state in BLOCKED_STATES or event.consent.opted_out):
        found.append("P1")
    if money and event.valid_until is not None and datetime.now(timezone.utc) >= event.valid_until:
        found.append("P2")
    if money and event.attempt_count >= ATTEMPT_CAP:
        found.append("P3")
    if money and _peak(event.proposed_execution_at):
        found.append("P4")
    if money and event.last_attempt_at is not None and event.proposed_execution_at is not None:
        gap_hours = (event.proposed_execution_at - event.last_attempt_at).total_seconds() / 3600
        if gap_hours < MIN_RETRY_GAP_HOURS:
            found.append("P9")
    if money and event.pre_debit_state.lower() != "valid" and event.mcc not in PDN_EXEMPT_MCC:
        found.append("P5")
    if (money or contact) and decision.diagnosed_reason in TERMINAL_REASONS:
        found.append("P6")
    if contact and event.consent.opted_out:
        found.append("P7_CONSENT")
    if (money or contact) and (
        decision.diagnosed_reason == FailureReason.UNKNOWN_OR_CONFLICTING.value
        or (0.0 < decision.confidence < MIN_CONFIDENCE)
    ):
        found.append("P8")
    if money and decision.diagnosed_reason in {
        FailureReason.RISK_OR_FRAUD_REJECTED.value,
    }:
        found.append("P10")
    return tuple(found)


def positive_controls() -> tuple[tuple[str, RecoveryEvent, PolicyDecision], ...]:
    """Return compact cases that must trigger independent violation detection."""
    from datetime import timedelta
    from .domain import ConsentState

    base = dict(
        event_id="checker_evt",
        merchant_id="merchant",
        customer_id="customer",
        mandate_id="mandate",
        scheduled_execution_id="scheduled",
        recovery_case_id="case",
        correlation_id="cid",
        amount_minor=1000,
        currency="INR",
        failure_code="BANK_TIMEOUT",
        mandate_state="active",
        attempt_count=0,
        pre_debit_state="valid",
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        mcc="5817",
        consent=ConsentState(email=True),
        valid_until=datetime(2027, 1, 1, tzinfo=timezone.utc),
        proposed_execution_at=datetime(2026, 1, 1, 3, tzinfo=timezone.utc),
    )
    decision = PolicyDecision(
        decision_id="dec",
        correlation_id="cid",
        policy_id="pid",
        recovery_case_id="case",
        decision="allow",  # type: ignore[arg-type]
        proposed_action=ActionType.SCHEDULE_RETRY,
        final_action=ActionType.SCHEDULE_RETRY,
        reason_codes=("test",),
        diagnosed_reason=FailureReason.INSUFFICIENT_FUNDS.value,
        confidence=0.95,
    )
    controls = []
    for rule, changes in (
        ("P1", {"mandate_state": "expired"}),
        ("P3", {"attempt_count": 4}),
        ("P4", {"proposed_execution_at": datetime(2026, 1, 1, 5, tzinfo=timezone.utc)}),
        ("P5", {"pre_debit_state": "invalid"}),
        ("P8", {}),
    ):
        event = RecoveryEvent(**{**base, **changes})
        d = decision if rule != "P8" else PolicyDecision(**{**decision.__dict__, "diagnosed_reason": FailureReason.UNKNOWN_OR_CONFLICTING.value, "confidence": 0.2})
        controls.append((rule, event, d))
    return tuple(controls)


def self_test() -> None:
    for rule, event, decision in positive_controls():
        assert rule in violations(event, decision), f"checker missed {rule}"
    clean_event = RecoveryEvent(**{
        **positive_controls()[0][1].__dict__,
        "mandate_state": "active",
        "attempt_count": 0,
        "pre_debit_state": "valid",
        "proposed_execution_at": datetime(2026, 1, 1, 3, tzinfo=timezone.utc),
    })
    clean_decision = positive_controls()[0][2]
    assert violations(clean_event, clean_decision) == ()


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("checker self test requires assertions; do not run with -O")
    self_test()
    print("independent checker positive controls passed")
