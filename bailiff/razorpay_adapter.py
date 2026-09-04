"""Razorpay shaped input and output boundaries for the local Track 03 demo.

This module deliberately does not call Razorpay APIs or hold credentials. It accepts
Razorpay shaped webhook or test payloads, preserves the provider signal, and maps it
to the project's scheduled UPI AutoPay RecoveryEvent contract. The normalized reason
is a project taxonomy, not an official Razorpay or NPCI taxonomy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from .domain import ConsentState, FailureReason, RecoveryEvent


class RazorpayPayloadError(ValueError):
    """Raised when a payload is not sufficient for the scheduled AutoPay contract."""


_REASON_MAP = {
    "insufficient_funds": FailureReason.INSUFFICIENT_FUNDS.value,
    "bank_technical_error": FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE.value,
    "payment_timed_out": FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE.value,
    "server_error": FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE.value,
    "upi_app_technical_error": FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE.value,
    "mandate_revoked": FailureReason.MANDATE_REVOKED_OR_CANCELLED.value,
    "mandate_cancelled": FailureReason.MANDATE_REVOKED_OR_CANCELLED.value,
    "account_closed": FailureReason.ACCOUNT_CLOSED_OR_BLOCKED.value,
    "account_blocked": FailureReason.ACCOUNT_CLOSED_OR_BLOCKED.value,
    "payment_risk_check_failed": FailureReason.RISK_OR_FRAUD_REJECTED.value,
    "risk_rejected": FailureReason.RISK_OR_FRAUD_REJECTED.value,
    "customer_opted_out": FailureReason.CUSTOMER_OPTED_OUT.value,
    # An explicitly ambiguous provider reason must stay ambiguous through the
    # round trip. Before this entry existed, the keyword fallback quietly
    # relabelled a large share of the ambiguous regime's recorded reasons
    # (the fixture's conflicting descriptions matched retryable keywords),
    # so the shipped evidence understated the ambiguity mix the regime is
    # named for. Arm behaviour was unaffected — diagnosis is driven by the
    # payload conflict flag — but recorded evidence must not disagree with
    # the fixture that generated it.
    "unknown_or_conflicting": FailureReason.UNKNOWN_OR_CONFLICTING.value,
}


def _as_mapping(value: object, label: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RazorpayPayloadError(f"{label} must be an object")
    return value


def _entity(container: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    direct = container.get(name)
    if isinstance(direct, Mapping) and isinstance(direct.get("entity"), Mapping):
        return _as_mapping(direct["entity"], f"{name}.entity")
    return _as_mapping(direct, name)


def _nested_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = payload.get("payload")
    return _as_mapping(nested, "payload") if nested is not None else payload


def _first(*values: object, default: object = None) -> object:
    for value in values:
        if value is not None and value != "":
            return value
    return default


def _required_text(notes: Mapping[str, Any], name: str, *fallbacks: object) -> str:
    value = _first(notes.get(name), *fallbacks)
    if value is None or str(value) == "":
        raise RazorpayPayloadError(f"missing required scheduled AutoPay note: {name}")
    return str(value)


def _int_value(value: object, name: str, default: int | None = None) -> int:
    if value is None or value == "":
        if default is not None:
            return default
        raise RazorpayPayloadError(f"missing required numeric field: {name}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RazorpayPayloadError(f"{name} must be an integer") from exc


def _bool_value(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _datetime_value(value: object, name: str, default: datetime | None = None) -> datetime:
    if value is None or value == "":
        if default is not None:
            return default
        raise RazorpayPayloadError(f"missing required time field: {name}")
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)):
        result = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            result = datetime.fromisoformat(text)
        except ValueError as exc:
            raise RazorpayPayloadError(f"{name} must be ISO 8601 or epoch seconds") from exc
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _normalized_reason(error_reason: object, error_code: object, description: object) -> str:
    reason_text = str(error_reason or "").strip().lower()
    if reason_text in _REASON_MAP:
        return _REASON_MAP[reason_text]
    # Keyword fallback for payloads whose provider reason is not exact-mapped.
    # Terminal readings are checked before retryable ones: a description that
    # mentions both a closed account and an insufficient balance must land on
    # the reading that stops recovery, because the cost of the two mistakes is
    # not symmetric.
    text = " ".join(str(value).lower() for value in (error_reason, error_code, description) if value)
    if "mandate" in text and ("revok" in text or "cancel" in text):
        return FailureReason.MANDATE_REVOKED_OR_CANCELLED.value
    if "account" in text and ("closed" in text or "block" in text):
        return FailureReason.ACCOUNT_CLOSED_OR_BLOCKED.value
    if "risk" in text or "fraud" in text:
        return FailureReason.RISK_OR_FRAUD_REJECTED.value
    if "insufficient" in text or "balance" in text:
        return FailureReason.INSUFFICIENT_FUNDS.value
    if "timeout" in text or "technical" in text or "server" in text or "unavailable" in text:
        return FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE.value
    return FailureReason.UNKNOWN_OR_CONFLICTING.value


def _canonical_payload(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RazorpayPayloadError("Razorpay payload is not JSON serializable") from exc


def normalize_razorpay_autopay_payload(payload: Mapping[str, Any]) -> RecoveryEvent:
    """Convert a Razorpay shaped subscription payment failure into a RecoveryEvent.

    Required merchant specific identifiers belong in the webhook entity's ``notes``
    object. This prevents the adapter from inventing customer, mandate, or authority
    identity. The original provider fields remain in ``failure_payload``.
    """
    if not isinstance(payload, Mapping):
        raise RazorpayPayloadError("Razorpay payload must be an object")

    root = _nested_payload(payload)
    subscription = _entity(root, "subscription")
    payment = _entity(root, "payment")
    notes = _as_mapping(_first(payment.get("notes"), subscription.get("notes"), default={}), "notes")

    event_name = str(payload.get("event") or "subscription.pending")
    if event_name not in {"subscription.pending", "subscription.charged", "payment.failed", "subscription.payment_failed"}:
        raise RazorpayPayloadError(f"unsupported Razorpay event for this adapter: {event_name}")

    amount_minor = _int_value(_first(payment.get("amount"), notes.get("amount_minor")), "payment.amount")
    currency = str(_first(payment.get("currency"), notes.get("currency"), default="INR")).upper()
    if currency != "INR":
        raise RazorpayPayloadError("this adapter accepts INR scheduled AutoPay payloads only")

    error_code = str(_first(payment.get("error_code"), payment.get("code"), default="RAZORPAY_PAYMENT_FAILURE"))
    error_reason = _first(payment.get("error_reason"), payment.get("reason"))
    description = _first(payment.get("error_description"), payment.get("description"), default="")
    normalized = _normalized_reason(error_reason, error_code, description)
    created_at = _datetime_value(_first(payload.get("created_at"), payment.get("created_at"), notes.get("event_time")), "created_at")
    proposed = _datetime_value(notes.get("proposed_execution_at"), "proposed_execution_at", default=created_at)

    provider_signal = {
        "provider": "razorpay",
        "provider_event": event_name,
        "subscription_id": _first(subscription.get("id"), notes.get("subscription_id")),
        "payment_id": _first(payment.get("id"), notes.get("payment_id")),
        "error_code": error_code,
        "error_reason": error_reason,
        "error_source": _first(payment.get("error_source"), notes.get("error_source")),
        "error_step": _first(payment.get("error_step"), notes.get("error_step")),
        "error_description": description,
        "conflict": _first(payment.get("conflict"), notes.get("conflict")),
        "method": payment.get("method", "upi"),
        "recurring": payment.get("recurring", True),
    }
    provider_signal = {key: value for key, value in provider_signal.items() if value is not None}
    provider_signal["normalized_reason"] = normalized
    payload_hash = "sha256:" + sha256(_canonical_payload(payload)).hexdigest()

    event_id = _required_text(notes, "event_id", payment.get("id"), subscription.get("id"))
    return RecoveryEvent(
        event_id=event_id,
        merchant_id=_required_text(notes, "merchant_id"),
        customer_id=_required_text(notes, "customer_id"),
        mandate_id=_required_text(notes, "mandate_id", subscription.get("id")),
        scheduled_execution_id=_required_text(notes, "scheduled_execution_id", payment.get("id")),
        recovery_case_id=_required_text(notes, "recovery_case_id", event_id),
        correlation_id=_required_text(notes, "correlation_id", event_id),
        amount_minor=amount_minor,
        currency=currency,
        failure_code=error_code,
        mandate_state=str(_first(notes.get("mandate_state"), subscription.get("status"), default="active")),
        attempt_count=_int_value(_first(notes.get("attempt_count"), subscription.get("paid_count"), default=0), "attempt_count"),
        pre_debit_state=str(notes.get("pre_debit_state", "valid")),
        event_time=created_at,
        failure_payload=provider_signal,
        mcc=str(notes.get("mcc", "0000")),
        consent=ConsentState(
            whatsapp=_bool_value(notes.get("consent_whatsapp")),
            sms=_bool_value(notes.get("consent_sms")),
            email=_bool_value(notes.get("consent_email"), default=True),
            opted_out=_bool_value(notes.get("opted_out")),
        ),
        source="razorpay_test_payload",
        payload_hash=payload_hash,
        is_scheduled_autopay=_bool_value(_first(notes.get("is_scheduled_autopay"), payment.get("recurring"), default=True), default=True),
        normalized_failure_reason=normalized,
        scheduled_execution_at=_datetime_value(notes.get("scheduled_execution_at"), "scheduled_execution_at", default=created_at),
        proposed_execution_at=proposed,
        last_attempt_at=_datetime_value(notes.get("last_attempt_at"), "last_attempt_at", default=created_at),
        pre_debit_sent_at=_datetime_value(notes.get("pre_debit_sent_at"), "pre_debit_sent_at", default=created_at),
        valid_until=(
            _datetime_value(notes.get("valid_until"), "valid_until")
            if notes.get("valid_until") not in (None, "")
            else None
        ),
    )


def to_razorpay_test_payload(event: RecoveryEvent) -> dict[str, Any]:
    """Wrap a canonical event in a deterministic Razorpay shaped test payload."""
    provider_reasons = {
        FailureReason.INSUFFICIENT_FUNDS.value: "insufficient_funds",
        FailureReason.BANK_TIMEOUT_OR_TEMPORARY_FAILURE.value: "bank_technical_error",
        FailureReason.MANDATE_REVOKED_OR_CANCELLED.value: "mandate_revoked",
        FailureReason.ACCOUNT_CLOSED_OR_BLOCKED.value: "account_closed",
        FailureReason.RISK_OR_FRAUD_REJECTED.value: "payment_risk_check_failed",
        FailureReason.CUSTOMER_OPTED_OUT.value: "customer_opted_out",
        FailureReason.UNKNOWN_OR_CONFLICTING.value: "unknown_or_conflicting",
    }
    payload = {
        "event": "subscription.pending",
        "created_at": int(event.event_time.timestamp()),
        "payload": {
            "subscription": {
                "entity": {
                    "id": event.mandate_id,
                    "status": event.mandate_state,
                    "paid_count": event.attempt_count,
                    "notes": {
                        "merchant_id": event.merchant_id,
                        "customer_id": event.customer_id,
                        "mandate_id": event.mandate_id,
                        "scheduled_execution_id": event.scheduled_execution_id,
                        "recovery_case_id": event.recovery_case_id,
                        "correlation_id": event.correlation_id,
                        "event_id": event.event_id,
                        "attempt_count": event.attempt_count,
                        "pre_debit_state": event.pre_debit_state,
                        "mcc": event.mcc,
                        "consent_whatsapp": event.consent.whatsapp,
                        "consent_sms": event.consent.sms,
                        "consent_email": event.consent.email,
                        "opted_out": event.consent.opted_out,
                        "is_scheduled_autopay": event.is_scheduled_autopay,
                        "scheduled_execution_at": event.scheduled_execution_at.isoformat() if event.scheduled_execution_at else None,
                        "proposed_execution_at": event.proposed_execution_at.isoformat() if event.proposed_execution_at else None,
                        "last_attempt_at": event.last_attempt_at.isoformat() if event.last_attempt_at else None,
                        "pre_debit_sent_at": event.pre_debit_sent_at.isoformat() if event.pre_debit_sent_at else None,
                        "valid_until": event.valid_until.isoformat() if event.valid_until else None,
                    },
                }
            },
            "payment": {
                "entity": {
                    "id": f"pay_{event.event_id}",
                    "amount": event.amount_minor,
                    "currency": event.currency,
                    "method": "upi",
                    "recurring": True,
                    "error_code": event.failure_code,
                    "error_reason": event.failure_payload.get("error_reason") or provider_reasons[event.normalized_failure_reason],
                    "error_source": event.failure_payload.get("error_source") or "bank",
                    "error_step": event.failure_payload.get("error_step"),
                    "error_description": event.failure_payload.get("error_description") or event.failure_payload.get("description") or event.failure_code,
                    "conflict": event.failure_payload.get("conflict"),
                }
            },
        },
    }
    return payload
