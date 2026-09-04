from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class ScopeError(ValueError):
    """Raised when an event is outside the scheduled AutoPay scope."""


class CaseState(str, Enum):
    SCHEDULED = "SCHEDULED"
    FAILED = "FAILED"
    CLASSIFIED = "CLASSIFIED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    MESSAGE_SENT = "MESSAGE_SENT"
    RECOVERED = "RECOVERED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    TERMINAL_STOP = "TERMINAL_STOP"


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"
    STOP = "stop"


class ActionType(str, Enum):
    SCHEDULE_RETRY = "schedule_retry"
    SEND_EMAIL = "send_email"
    SEND_SMS = "send_sms"
    SEND_WHATSAPP = "send_whatsapp"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    STOP_RECOVERY = "stop_recovery"


class FailureReason(str, Enum):
    """Project taxonomy, not an official universal NPCI taxonomy."""

    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    BANK_TIMEOUT_OR_TEMPORARY_FAILURE = "BANK_TIMEOUT_OR_TEMPORARY_FAILURE"
    MANDATE_REVOKED_OR_CANCELLED = "MANDATE_REVOKED_OR_CANCELLED"
    ACCOUNT_CLOSED_OR_BLOCKED = "ACCOUNT_CLOSED_OR_BLOCKED"
    RISK_OR_FRAUD_REJECTED = "RISK_OR_FRAUD_REJECTED"
    CUSTOMER_OPTED_OUT = "CUSTOMER_OPTED_OUT"
    UNKNOWN_OR_CONFLICTING = "UNKNOWN_OR_CONFLICTING"


MONEY_ACTIONS = frozenset({ActionType.SCHEDULE_RETRY})
CONTACT_ACTIONS = frozenset(
    {
        ActionType.SEND_WHATSAPP,
        ActionType.SEND_SMS,
        ActionType.SEND_EMAIL,
    }
)
EXECUTABLE_ACTIONS = MONEY_ACTIONS | CONTACT_ACTIONS


@dataclass(frozen=True)
class ConsentState:
    whatsapp: bool = False
    sms: bool = False
    email: bool = False
    opted_out: bool = False

    def allows(self, action: ActionType) -> bool:
        if self.opted_out and action in CONTACT_ACTIONS:
            return False
        return {
            ActionType.SEND_WHATSAPP: self.whatsapp,
            ActionType.SEND_SMS: self.sms,
            ActionType.SEND_EMAIL: self.email,
        }.get(action, True)


@dataclass(frozen=True)
class RecoveryEvent:
    event_id: str
    merchant_id: str
    customer_id: str
    mandate_id: str
    scheduled_execution_id: str
    recovery_case_id: str
    correlation_id: str
    amount_minor: int
    currency: str
    failure_code: str
    mandate_state: str
    attempt_count: int
    pre_debit_state: str
    event_time: datetime
    failure_payload: Mapping[str, Any] = field(default_factory=dict)
    mcc: str = "0000"
    consent: ConsentState = field(default_factory=ConsentState)
    source: str = "replay_provider"
    payload_hash: str = ""
    is_scheduled_autopay: bool = True
    normalized_failure_reason: str = FailureReason.UNKNOWN_OR_CONFLICTING.value
    scheduled_execution_at: datetime | None = None
    proposed_execution_at: datetime | None = None
    last_attempt_at: datetime | None = None
    pre_debit_sent_at: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        if not self.is_scheduled_autopay:
            raise ScopeError("Bailiff accepts scheduled AutoPay events only")
        required = {
            "event_id": self.event_id,
            "merchant_id": self.merchant_id,
            "customer_id": self.customer_id,
            "mandate_id": self.mandate_id,
            "scheduled_execution_id": self.scheduled_execution_id,
            "recovery_case_id": self.recovery_case_id,
            "correlation_id": self.correlation_id,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required identifiers: {', '.join(missing)}")
        if self.amount_minor < 0:
            raise ValueError("amount_minor cannot be negative")
        if self.attempt_count < 0:
            raise ValueError("attempt_count cannot be negative")
        if self.currency != "INR":
            raise ScopeError("The MVP scope is INR scheduled AutoPay only")
        try:
            FailureReason(self.normalized_failure_reason)
        except ValueError as exc:
            raise ValueError("normalized_failure_reason is outside the project taxonomy") from exc


@dataclass(frozen=True)
class PolicyConfig:
    policy_id: str
    rail: str = "upi_autopay_scheduled"
    currency: str = "INR"
    max_attempts: int = 4
    minimum_retry_gap_hours: int = 24
    requires_pre_debit_notice: bool = True
    amount_review_threshold_minor: int = 1_500_000
    allow_actions: frozenset[ActionType] = frozenset(
        {
            ActionType.SCHEDULE_RETRY,
            ActionType.SEND_EMAIL,
            ActionType.SEND_SMS,
            ActionType.SEND_WHATSAPP,
            ActionType.ESCALATE_TO_HUMAN,
            ActionType.STOP_RECOVERY,
        }
    )
    bounded_interpreter_mode: str = "ambiguous_only"
    guardrail_profile: str = "full"
    minimum_interpreter_confidence: float = 0.70
    version: str = "mandateguard_policy_0.2"
    timezone: str = "Asia/Kolkata"
    non_peak_windows: tuple[tuple[float, float], ...] = ((0.0, 10.0), (13.0, 17.0), (21.5, 24.0))
    pre_debit_exempt_mcc: frozenset[str] = frozenset({"4784", "7412"})
    policy_provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.rail != "upi_autopay_scheduled":
            raise ValueError("The MVP policy rail must be upi_autopay_scheduled")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.minimum_retry_gap_hours < 0:
            raise ValueError("minimum_retry_gap_hours cannot be negative")
        if self.guardrail_profile not in {"full", "timing_only", "timing_attempts", "timing_attempts_consent"}:
            raise ValueError("guardrail_profile is not supported")
        if not 0.0 <= self.minimum_interpreter_confidence <= 1.0:
            raise ValueError("minimum_interpreter_confidence must be between zero and one")
        if not self.non_peak_windows:
            raise ValueError("At least one permitted non peak execution window is required")


@dataclass(frozen=True)
class AuthorityEnvelope:
    correlation_id: str
    policy_id: str
    mandate_id: str
    scheduled_execution_id: str
    recovery_case_id: str
    allowed_actions: frozenset[ActionType]
    max_amount_minor: int
    attempts_remaining: int
    consent_snapshot_hash: str
    expires_at: datetime
    parent_decision_id: str | None = None

    def attenuate(
        self,
        *,
        allowed_actions: frozenset[ActionType] | None = None,
        max_amount_minor: int | None = None,
        attempts_remaining: int | None = None,
        expires_at: datetime | None = None,
    ) -> "AuthorityEnvelope":
        next_actions = self.allowed_actions if allowed_actions is None else allowed_actions
        next_amount = self.max_amount_minor if max_amount_minor is None else max_amount_minor
        next_attempts = self.attempts_remaining if attempts_remaining is None else attempts_remaining
        next_expiry = self.expires_at if expires_at is None else expires_at
        if not next_actions.issubset(self.allowed_actions):
            raise ValueError("Authority attenuation cannot add actions")
        if next_amount > self.max_amount_minor:
            raise ValueError("Authority attenuation cannot increase amount")
        if next_attempts > self.attempts_remaining:
            raise ValueError("Authority attenuation cannot increase attempts")
        if next_expiry > self.expires_at:
            raise ValueError("Authority attenuation cannot extend expiry")
        return AuthorityEnvelope(
            correlation_id=self.correlation_id,
            policy_id=self.policy_id,
            mandate_id=self.mandate_id,
            scheduled_execution_id=self.scheduled_execution_id,
            recovery_case_id=self.recovery_case_id,
            allowed_actions=next_actions,
            max_amount_minor=next_amount,
            attempts_remaining=next_attempts,
            consent_snapshot_hash=self.consent_snapshot_hash,
            expires_at=next_expiry,
            parent_decision_id=self.parent_decision_id,
        )


@dataclass(frozen=True)
class CommonOutcome:
    case_id: str
    latent_customer_state: str
    latent_bank_state: str
    latent_consent_state: ConsentState
    latent_recovery_window: str
    latent_outcome_seed: int
    latent_recoverable_minor: int = 0
    latent_harm_minor: int = 0


@dataclass(frozen=True)
class PolicyDecision:
    decision_id: str
    correlation_id: str
    policy_id: str
    recovery_case_id: str
    decision: Decision
    proposed_action: ActionType | None
    final_action: ActionType | None
    reason_codes: tuple[str, ...]
    diagnosed_reason: str = FailureReason.UNKNOWN_OR_CONFLICTING.value
    confidence: float = 0.0
    provider_call_made: bool = False
    model_used: bool = False
    policy_version: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason_sources: tuple[str, ...] = ()
    policy_provenance: Mapping[str, str] = field(default_factory=dict)
    provider_call_id: str | None = None
    legitimate_recovery_forgone_inr_minor: int = 0
    protected_value_inr_minor: int = 0
    realized_harm_inr_minor: int = 0
    model_calls: int = 0
    model_tokens: int = 0
    model_cost_inr: float = 0.0
    bounded_interpreter_model: str | None = None
    bounded_interpreter_influence: bool = False


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    provider_call_id: str
    status: str
    provider_reference: str | None
    idempotency_key: str
    executed_at: datetime
    recovered: bool = False
    postcondition_state: str | None = None
    timed_out: bool = False
    error_code: str | None = None


@dataclass(frozen=True)
class AuditEvent:
    audit_event_id: str
    correlation_id: str
    event_type: str
    entity_id: str
    actor: str
    decision: str | None
    reason_codes: tuple[str, ...]
    provider_call_made: bool
    previous_hash: str
    event_hash: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
