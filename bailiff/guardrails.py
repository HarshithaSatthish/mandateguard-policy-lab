from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

from .domain import (
    ActionType,
    FailureReason,
    AuthorityEnvelope,
    CaseState,
    Decision,
    PolicyConfig,
    PolicyDecision,
    RecoveryEvent,
)
from .replay import ReplayProvider
from .state import CaseRecord, CaseStore


@dataclass(frozen=True)
class EvaluationContext:
    event: RecoveryEvent
    policy: PolicyConfig
    proposed_action: ActionType
    authority: AuthorityEnvelope
    diagnosed_reason: str = FailureReason.UNKNOWN_OR_CONFLICTING.value
    confidence: float = 1.0
    model_used: bool = False
    interpreter_reason_source: str | None = None
    model_calls: int = 0
    model_tokens: int = 0
    model_cost_inr: float = 0.0
    interpreter_model: str | None = None


class AuditChain:
    """Append only hash chain for local decision receipts."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self._previous_hash = "GENESIS"

    def append(
        self,
        *,
        correlation_id: str,
        event_type: str,
        entity_id: str,
        decision: str | None,
        reasons: tuple[str, ...],
        provider_call_made: bool,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        body = {
            "sequence": len(self.events) + 1,
            "correlation_id": correlation_id,
            "event_type": event_type,
            "entity_id": entity_id,
            "decision": decision,
            "reason_codes": reasons,
            "provider_call_made": provider_call_made,
            "previous_hash": self._previous_hash,
            "metadata": metadata or {},
        }
        canonical = json.dumps(body, sort_keys=True, default=str).encode()
        current_hash = sha256(canonical).hexdigest()
        body["event_hash"] = current_hash
        self.events.append(body)
        self._previous_hash = current_hash
        return body

    def verify(self) -> bool:
        previous = "GENESIS"
        for event in self.events:
            actual_hash = event.get("event_hash")
            body = {key: value for key, value in event.items() if key != "event_hash"}
            expected = sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
            if event.get("previous_hash") != previous or actual_hash != expected:
                return False
            previous = expected
        return True


class GuardrailEngine:
    def __init__(self, *, cases: CaseStore, provider: ReplayProvider, audit: AuditChain) -> None:
        self.cases = cases
        self.provider = provider
        self.audit = audit
        self._decision_sequence = 0

    @staticmethod
    def _in_window(execution_at: datetime, policy: PolicyConfig) -> bool:
        local = execution_at.astimezone(ZoneInfo(policy.timezone))
        hour = local.hour + local.minute / 60 + local.second / 3600
        return any(start <= hour < end for start, end in policy.non_peak_windows)

    @staticmethod
    def _reason_sources(reasons: list[str]) -> tuple[str, ...]:
        if not reasons:
            return ("PROJECT_POLICY",)
        runtime_reasons = {
            "MANDATE_ACTIVE",
            "PRE_DEBIT_VALID",
            "ATTEMPT_AVAILABLE",
            "CHANNEL_CONSENT_VALID",
            "CHANNEL_ALLOWLISTED",
        }
        return tuple(
            "RUNTIME_STATE" if reason in runtime_reasons else "PROJECT_POLICY"
            for reason in reasons
        )

    @staticmethod
    def _authority_identity_reasons(context: EvaluationContext) -> tuple[str, ...]:
        event = context.event
        authority = context.authority
        policy = context.policy
        checks = (
            (authority.correlation_id == event.correlation_id, "AUTHORITY_CORRELATION_ID_MISMATCH"),
            (authority.policy_id == policy.policy_id, "AUTHORITY_POLICY_ID_MISMATCH"),
            (authority.mandate_id == event.mandate_id, "AUTHORITY_MANDATE_ID_MISMATCH"),
            (
                authority.scheduled_execution_id == event.scheduled_execution_id,
                "AUTHORITY_SCHEDULED_EXECUTION_ID_MISMATCH",
            ),
            (authority.recovery_case_id == event.recovery_case_id, "AUTHORITY_RECOVERY_CASE_ID_MISMATCH"),
        )
        return tuple(reason for ok, reason in checks if not ok)

    def evaluate(self, context: EvaluationContext) -> PolicyDecision:
        event = context.event
        policy = context.policy
        profile = policy.guardrail_profile
        full_guardrails = profile == "full"
        attempt_guardrails = profile in {"full", "timing_attempts", "timing_attempts_consent"}
        consent_guardrails = profile in {"full", "timing_attempts_consent"}
        record = self.cases.get(event.recovery_case_id)
        reasons: list[str] = []
        decision = Decision.ALLOW
        final_action: ActionType | None = context.proposed_action

        identity_reasons = self._authority_identity_reasons(context)
        if not identity_reasons:
            self._ensure_classified(record)

        if identity_reasons:
            decision = Decision.DENY
            final_action = None
            reasons.extend(identity_reasons)
        elif context.proposed_action not in policy.allow_actions:
            decision = Decision.DENY
            final_action = None
            reasons.append("ACTION_NOT_ALLOWLISTED")
        elif context.proposed_action not in context.authority.allowed_actions:
            decision = Decision.DENY
            final_action = None
            reasons.append("AUTHORITY_ACTION_NOT_ALLOWED")
        elif record.state in {CaseState.RECOVERED, CaseState.TERMINAL_STOP}:
            decision = Decision.STOP
            final_action = None
            reasons.append("CASE_TERMINAL")
        elif full_guardrails and event.mandate_state.lower() not in {"active", "enabled"}:
            decision = Decision.STOP
            final_action = None
            reasons.append("MANDATE_NOT_ACTIVE")
        elif full_guardrails and event.valid_until is not None and datetime.now(timezone.utc) >= event.valid_until:
            decision = Decision.STOP
            final_action = None
            reasons.append("EVENT_EXPIRED")
        elif datetime.now(timezone.utc) >= context.authority.expires_at:
            decision = Decision.DENY
            final_action = None
            reasons.append("AUTHORITY_EXPIRED")
        elif context.model_used and context.confidence < policy.minimum_interpreter_confidence:
            decision = Decision.ABSTAIN
            final_action = ActionType.ESCALATE_TO_HUMAN
            reasons.extend(["ABSTAIN", "INTERPRETER_CONFIDENCE_BELOW_THRESHOLD"])
        elif consent_guardrails and event.consent.opted_out and context.proposed_action in {
            ActionType.SCHEDULE_RETRY,
            ActionType.SEND_WHATSAPP,
            ActionType.SEND_SMS,
            ActionType.SEND_EMAIL,
        }:
            decision = Decision.STOP
            final_action = None
            reasons.append("CUSTOMER_OPTED_OUT")
        elif consent_guardrails and not event.consent.allows(context.proposed_action):
            decision = Decision.DENY
            final_action = None
            reasons.append("CHANNEL_CONSENT_MISSING")
        elif context.proposed_action == ActionType.SCHEDULE_RETRY:
            if (
                full_guardrails
                and event.pre_debit_state.lower() != "valid"
                and policy.requires_pre_debit_notice
                and event.mcc not in policy.pre_debit_exempt_mcc
            ):
                decision = Decision.DENY
                final_action = None
                reasons.append("PRE_DEBIT_NOTICE_INVALID")
            elif attempt_guardrails and (event.attempt_count >= policy.max_attempts or context.authority.attempts_remaining <= 0):
                decision = Decision.STOP
                final_action = None
                reasons.append("ATTEMPT_POLICY_EXHAUSTED")
            elif full_guardrails and event.amount_minor > context.authority.max_amount_minor:
                decision = Decision.DENY
                final_action = None
                reasons.append("AUTHORITY_AMOUNT_EXCEEDED")
            elif (
                attempt_guardrails
                and event.last_attempt_at is not None
                and event.proposed_execution_at is not None
                and (event.proposed_execution_at - event.last_attempt_at).total_seconds() / 3600 < policy.minimum_retry_gap_hours
            ):
                decision = Decision.DENY
                final_action = None
                reasons.append("RETRY_GAP_TOO_SHORT")
            elif event.proposed_execution_at is not None and not self._in_window(
                event.proposed_execution_at, policy
            ):
                decision = Decision.DENY
                final_action = None
                reasons.append("EXECUTION_OUTSIDE_NON_PEAK_WINDOW")
            elif (
                full_guardrails
                and event.pre_debit_sent_at is not None
                and event.proposed_execution_at is not None
                and policy.requires_pre_debit_notice
                and (event.proposed_execution_at - event.pre_debit_sent_at).total_seconds() / 3600 < 24
            ):
                decision = Decision.DENY
                final_action = None
                reasons.append("PRE_DEBIT_LEAD_TIME_INSUFFICIENT")
            elif full_guardrails and event.amount_minor >= policy.amount_review_threshold_minor:
                decision = Decision.ESCALATE
                final_action = ActionType.ESCALATE_TO_HUMAN
                reasons.append("AMOUNT_REQUIRES_REVIEW")
            else:
                reasons.extend(["MANDATE_ACTIVE", "PRE_DEBIT_VALID", "ATTEMPT_AVAILABLE"])
        elif context.proposed_action == ActionType.ESCALATE_TO_HUMAN:
            decision = Decision.ESCALATE
            final_action = ActionType.ESCALATE_TO_HUMAN
            reasons.append("HUMAN_REVIEW_REQUIRED")
        elif context.proposed_action == ActionType.STOP_RECOVERY:
            decision = Decision.STOP
            final_action = ActionType.STOP_RECOVERY
            reasons.append("RECOVERY_STOP_REQUESTED")
        elif context.proposed_action in {
            ActionType.SEND_EMAIL,
            ActionType.SEND_SMS,
            ActionType.SEND_WHATSAPP,
        }:
            reasons.extend(["CHANNEL_CONSENT_VALID", "CHANNEL_ALLOWLISTED"])
        else:
            reasons.append("POLICY_ALLOWLISTED")

        if decision == Decision.ALLOW and not reasons:
            reasons.append("POLICY_ALLOWLISTED")
        self._decision_sequence += 1
        reason_sources = list(self._reason_sources(reasons))
        if context.model_used and context.interpreter_reason_source:
            reason_sources.append(context.interpreter_reason_source)
        reason_sources = list(dict.fromkeys(reason_sources))
        decision_record = PolicyDecision(
            decision_id=f"dec_{self._decision_sequence:06d}",
            correlation_id=event.correlation_id,
            policy_id=policy.policy_id,
            recovery_case_id=event.recovery_case_id,
            decision=decision,
            proposed_action=context.proposed_action,
            final_action=final_action,
            reason_codes=tuple(reasons),
            diagnosed_reason=context.diagnosed_reason,
            confidence=context.confidence,
            provider_call_made=False,
            model_used=context.model_used,
            policy_version=policy.version,
            reason_sources=tuple(reason_sources),
            policy_provenance=policy.policy_provenance,
            model_calls=context.model_calls,
            model_tokens=context.model_tokens,
            model_cost_inr=context.model_cost_inr,
            bounded_interpreter_model=context.interpreter_model,
        )
        self.audit.append(
            correlation_id=event.correlation_id,
            event_type="policy_decision",
            entity_id=decision_record.decision_id,
            decision=decision.value,
            reasons=decision_record.reason_codes,
            provider_call_made=False,
            metadata={
                "proposed_action": context.proposed_action.value,
                "final_action": final_action.value if final_action else None,
                "reason_sources": decision_record.reason_sources,
                "event_source": event.source,
                "provider_payload_hash": event.payload_hash,
                "provider_signal": dict(event.failure_payload),
            },
        )
        return decision_record

    def execute(self, *, context: EvaluationContext, decision: PolicyDecision) -> ProviderResult | None:
        record = self.cases.get(context.event.recovery_case_id)
        action = decision.final_action

        if decision.final_action == ActionType.ESCALATE_TO_HUMAN:
            if record.state not in {CaseState.HUMAN_REVIEW, CaseState.RECOVERED, CaseState.TERMINAL_STOP}:
                record.transition(CaseState.HUMAN_REVIEW, "bounded_interpreter_escalation")
            self.audit.append(
                correlation_id=context.event.correlation_id,
                event_type="human_review_escalation",
                entity_id=decision.decision_id,
                decision=decision.decision.value,
                reasons=decision.reason_codes,
                provider_call_made=False,
            )
            return None

        if decision.final_action == ActionType.STOP_RECOVERY:
            if record.state not in {CaseState.RECOVERED, CaseState.TERMINAL_STOP}:
                record.transition(CaseState.TERMINAL_STOP, "policy_stop")
            self.audit.append(
                correlation_id=context.event.correlation_id,
                event_type="recovery_stopped_before_provider",
                entity_id=decision.decision_id,
                decision=decision.decision.value,
                reasons=decision.reason_codes,
                provider_call_made=False,
            )
            return None

        if decision.decision != Decision.ALLOW or action is None:
            self.audit.append(
                correlation_id=context.event.correlation_id,
                event_type="action_denied_before_provider",
                entity_id=decision.decision_id,
                decision=decision.decision.value,
                reasons=decision.reason_codes,
                provider_call_made=False,
            )
            return None

        idempotency_key = self.idempotency_key(context.event, action)
        existing = self.provider.result_for(idempotency_key)
        if existing is not None:
            self.audit.append(
                correlation_id=context.event.correlation_id,
                event_type="idempotent_replay",
                entity_id=existing.provider_call_id,
                decision=decision.decision.value,
                reasons=("IDEMPOTENT_RESULT_REUSED",),
                provider_call_made=False,
                metadata={"idempotency_key": idempotency_key},
            )
            return existing

        if action == ActionType.SCHEDULE_RETRY:
            record.transition(CaseState.RETRY_SCHEDULED, "policy_allowed_retry")
        elif action in {ActionType.SEND_EMAIL, ActionType.SEND_SMS, ActionType.SEND_WHATSAPP}:
            record.transition(CaseState.MESSAGE_SENT, "policy_allowed_message")

        result = self.provider.execute(
            event=context.event,
            action=action,
            idempotency_key=idempotency_key,
        )
        if result.timed_out:
            postcondition = self.provider.read_case_state(context.event.recovery_case_id)
            if postcondition in {None, "UNKNOWN_POSTCONDITION"}:
                record.transition(CaseState.HUMAN_REVIEW, "provider_timeout_postcondition_unknown")
                self.audit.append(
                    correlation_id=context.event.correlation_id,
                    event_type="provider_postcondition_unknown",
                    entity_id=result.provider_call_id,
                    decision=decision.decision.value,
                    reasons=("PROVIDER_TIMEOUT", "POSTCONDITION_UNKNOWN"),
                    provider_call_made=True,
                    metadata={"idempotency_key": idempotency_key},
                )
                return result
        elif result.recovered:
            record.transition(CaseState.RECOVERED, "provider_recovered")

        self.audit.append(
            correlation_id=context.event.correlation_id,
            event_type="provider_action",
            entity_id=result.provider_call_id,
            decision=decision.decision.value,
            reasons=decision.reason_codes,
            provider_call_made=True,
            metadata={
                "action": action.value,
                "idempotency_key": idempotency_key,
                "status": result.status,
                "postcondition_state": result.postcondition_state,
            },
        )
        return result

    @staticmethod
    def idempotency_key(event: RecoveryEvent, action: ActionType) -> str:
        return f"{event.correlation_id}:{event.scheduled_execution_id}:{action.value}"

    @staticmethod
    def _ensure_classified(record: CaseRecord) -> None:
        if record.state == CaseState.SCHEDULED:
            record.transition(CaseState.FAILED, "failure_event_ingested")
            record.transition(CaseState.CLASSIFIED, "deterministic_diagnosis")
        elif record.state == CaseState.FAILED:
            record.transition(CaseState.CLASSIFIED, "deterministic_diagnosis")