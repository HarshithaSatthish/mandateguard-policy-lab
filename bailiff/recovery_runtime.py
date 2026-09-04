from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Mapping, Protocol

import httpx

from .recovery_truth import ProviderEvidence, RecoveryProof, TruthResolution, TruthState, WriteFence, resolve_financial_truth


FALLBACK_ACTION = "CREATE_PAYMENT_LINK_FALLBACK"


class ExecutionState(str, Enum):
    NOT_EXECUTED = "NOT_EXECUTED"
    EXECUTED = "EXECUTED"
    WRITE_OUTCOME_UNKNOWN = "WRITE_OUTCOME_UNKNOWN"


class RecoveryProvider(Protocol):
    def order_evidence(
        self,
        *,
        order_id: str,
        mandate_id: str | None = None,
        mandate_status: str | None = None,
        expected_amount_minor: int | None = None,
        expected_currency: str | None = None,
    ): ...

    def create_payment_link_once(
        self, *, amount_minor: int, currency: str, reference_id: str, description: str
    ): ...

    def verify_payment_link_capture(
        self, *, payment_link_id: str, expected_amount_minor: int, expected_currency: str, expected_reference_id: str
    ): ...


@dataclass(frozen=True)
class RecoveryRequest:
    case_id: str
    decision_id: str
    decision_evidence_hash: str
    policy_version: str
    order_id: str
    mandate_id: str
    mandate_status: str
    amount_minor: int
    max_authorized_amount_minor: int
    authority_expires_at: datetime
    authorized_action_type: str = FALLBACK_ACTION
    currency: str = "INR"
    description: str = "RecoveryTruth customer-initiated fallback"

    def __post_init__(self) -> None:
        if not self.case_id or not self.decision_id or not self.policy_version or not self.decision_evidence_hash:
            raise ValueError("case_id, decision_id, decision_evidence_hash and policy_version are required")
        if not self.order_id.startswith("order_"):
            raise ValueError("RecoveryTruth requires a Razorpay order id")
        if not self.mandate_id:
            raise ValueError("mandate_id is required")
        if self.amount_minor <= 0 or self.max_authorized_amount_minor <= 0:
            raise ValueError("amount ceilings must be positive")
        if self.amount_minor > self.max_authorized_amount_minor:
            raise ValueError("requested recovery exceeds decision authority amount ceiling")
        if self.currency != "INR":
            raise ValueError("RecoveryTruth fallback currently supports INR only")
        if self.authorized_action_type != FALLBACK_ACTION:
            raise ValueError("decision authority does not allow the fallback action")
        if self.authority_expires_at.tzinfo is None:
            raise ValueError("authority_expires_at must be timezone-aware")


@dataclass(frozen=True)
class RecoveryActionReceipt:
    case_id: str
    decision_id: str
    decision_evidence_hash: str
    policy_version: str
    action_type: str
    authority_expires_at: str
    order_id: str
    mandate_id: str
    reference_id: str
    payment_link_id: str
    short_url: str
    amount_minor: int
    currency: str
    prewrite_resolution: str
    prewrite_evidence_hash: str


@dataclass(frozen=True)
class RecoveryAttempt:
    execution_state: ExecutionState
    reason_code: str
    truth: TruthResolution
    receipt: RecoveryActionReceipt | None = None

    @property
    def executed(self) -> bool:
        return self.execution_state == ExecutionState.EXECUTED

    @property
    def write_outcome_unknown(self) -> bool:
        return self.execution_state == ExecutionState.WRITE_OUTCOME_UNKNOWN


def recovery_reference(case_id: str) -> str:
    return "rt_" + sha256(case_id.encode()).hexdigest()[:32]


def _resolution_hash(resolution: TruthResolution) -> str:
    return sha256("|".join(sorted(resolution.evidence_fingerprints)).encode()).hexdigest()


def _unknown_truth(reason: str, fingerprints: tuple[str, ...] = ()) -> TruthResolution:
    return TruthResolution(TruthState.UNKNOWN, (reason,), fingerprints, datetime.now(timezone.utc))


def _block(reason: str, truth: TruthResolution | None = None) -> RecoveryAttempt:
    return RecoveryAttempt(ExecutionState.NOT_EXECUTED, reason, truth or _unknown_truth(reason))


def _unknown_write(reason: str, truth: TruthResolution) -> RecoveryAttempt:
    return RecoveryAttempt(
        ExecutionState.WRITE_OUTCOME_UNKNOWN,
        "PROVIDER_WRITE_OUTCOME_UNKNOWN",
        _unknown_truth(reason, truth.evidence_fingerprints),
    )


class RecoveryTruthRuntime:
    """Financial-truth and write-authority boundary for provider execution.

    Provider read faults fail closed. A network-ambiguous or malformed
    post-write provider result is represented separately from both success and
    non-execution so callers are never encouraged to repeat an unresolved
    financial write.
    """

    def __init__(self, provider: RecoveryProvider) -> None:
        self.provider = provider

    def _read_bound_evidence(self, request: RecoveryRequest) -> tuple[ProviderEvidence, ...]:
        return tuple(
            self.provider.order_evidence(
                order_id=request.order_id,
                mandate_id=request.mandate_id,
                mandate_status=request.mandate_status,
                expected_amount_minor=request.amount_minor,
                expected_currency=request.currency,
            )
        )

    def _safe_read_bound_evidence(self, request: RecoveryRequest) -> tuple[tuple[ProviderEvidence, ...] | None, str | None]:
        try:
            return self._read_bound_evidence(request), None
        except (httpx.HTTPError, OSError, TimeoutError, ValueError, RuntimeError) as exc:
            return None, type(exc).__name__

    def execute_customer_fallback(self, request: RecoveryRequest) -> RecoveryAttempt:
        if datetime.now(timezone.utc) >= request.authority_expires_at.astimezone(timezone.utc):
            return _block("SAFE_BLOCK_AUTHORITY_EXPIRED")
        if request.authorized_action_type != FALLBACK_ACTION:
            return _block("SAFE_BLOCK_ACTION_NOT_AUTHORIZED")
        if request.amount_minor > request.max_authorized_amount_minor:
            return _block("SAFE_BLOCK_AMOUNT_EXCEEDS_AUTHORITY")

        initial_evidence, read_error = self._safe_read_bound_evidence(request)
        if initial_evidence is None:
            return _block("SAFE_BLOCK_PROVIDER_READ_ERROR", _unknown_truth(read_error or "PROVIDER_READ_ERROR"))
        initial_truth = resolve_financial_truth(initial_evidence)
        if initial_truth.state == TruthState.PAID:
            return _block("SAFE_BLOCK_ALREADY_PAID", initial_truth)
        if not initial_truth.executable:
            return _block(f"SAFE_BLOCK_{initial_truth.state.value}", initial_truth)

        fence = WriteFence.from_evidence(initial_evidence)

        fresh_evidence, read_error = self._safe_read_bound_evidence(request)
        if fresh_evidence is None:
            return _block("SAFE_BLOCK_PREWRITE_PROVIDER_READ_ERROR", _unknown_truth(read_error or "PROVIDER_READ_ERROR"))
        allowed, reason = fence.check(fresh_evidence)
        fresh_truth = resolve_financial_truth(fresh_evidence)
        if not allowed:
            return _block(reason, fresh_truth)

        if datetime.now(timezone.utc) >= request.authority_expires_at.astimezone(timezone.utc):
            return _block("SAFE_BLOCK_AUTHORITY_EXPIRED_AT_WRITE", fresh_truth)
        if request.amount_minor > request.max_authorized_amount_minor:
            return _block("SAFE_BLOCK_AMOUNT_EXCEEDS_AUTHORITY", fresh_truth)

        reference_id = recovery_reference(request.case_id)
        try:
            link = self.provider.create_payment_link_once(
                amount_minor=request.amount_minor,
                currency=request.currency,
                reference_id=reference_id,
                description=request.description,
            )
        except (httpx.TimeoutException, httpx.NetworkError, TimeoutError, OSError):
            return _unknown_write("AMBIGUOUS_PROVIDER_WRITE", fresh_truth)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                return _unknown_write("PROVIDER_5XX_AFTER_WRITE_ATTEMPT", fresh_truth)
            return _block("PROVIDER_WRITE_REJECTED", fresh_truth)

        if not isinstance(link, Mapping):
            return _unknown_write("POST_WRITE_PROVIDER_RESPONSE_NOT_OBJECT", fresh_truth)
        link_id = str(link.get("id") or "")
        short_url = str(link.get("short_url") or "")
        if not link_id.startswith("plink_"):
            return _unknown_write("POST_WRITE_PROVIDER_ID_INVALID", fresh_truth)
        if str(link.get("reference_id") or "") != reference_id:
            return _unknown_write("POST_WRITE_PROVIDER_REFERENCE_MISMATCH", fresh_truth)
        try:
            returned_amount = int(link.get("amount") or 0)
        except (TypeError, ValueError):
            return _unknown_write("POST_WRITE_PROVIDER_AMOUNT_INVALID", fresh_truth)
        if returned_amount != request.amount_minor:
            return _unknown_write("POST_WRITE_PROVIDER_AMOUNT_MISMATCH", fresh_truth)
        if str(link.get("currency") or "") != request.currency:
            return _unknown_write("POST_WRITE_PROVIDER_CURRENCY_MISMATCH", fresh_truth)

        receipt = RecoveryActionReceipt(
            case_id=request.case_id,
            decision_id=request.decision_id,
            decision_evidence_hash=request.decision_evidence_hash,
            policy_version=request.policy_version,
            action_type=FALLBACK_ACTION,
            authority_expires_at=request.authority_expires_at.astimezone(timezone.utc).isoformat(),
            order_id=request.order_id,
            mandate_id=request.mandate_id,
            reference_id=reference_id,
            payment_link_id=link_id,
            short_url=short_url,
            amount_minor=request.amount_minor,
            currency=request.currency,
            prewrite_resolution=fresh_truth.state.value,
            prewrite_evidence_hash=_resolution_hash(fresh_truth),
        )
        return RecoveryAttempt(ExecutionState.EXECUTED, "FALLBACK_PAYMENT_LINK_CREATED", fresh_truth, receipt)

    def verify_recovery(self, receipt: RecoveryActionReceipt) -> RecoveryProof:
        if receipt.action_type != FALLBACK_ACTION:
            raise ValueError("receipt action type is outside RecoveryTruth proof contract")
        captured, postcondition_hash = self.provider.verify_payment_link_capture(
            payment_link_id=receipt.payment_link_id,
            expected_amount_minor=receipt.amount_minor,
            expected_currency=receipt.currency,
            expected_reference_id=receipt.reference_id,
        )
        return RecoveryProof(
            case_id=receipt.case_id,
            mandate_id=receipt.mandate_id,
            original_order_id=receipt.order_id,
            decision_id=receipt.decision_id,
            decision_evidence_hash=receipt.decision_evidence_hash,
            policy_version=receipt.policy_version,
            authority_expires_at=receipt.authority_expires_at,
            prewrite_resolution=receipt.prewrite_resolution,
            prewrite_evidence_hash=receipt.prewrite_evidence_hash,
            provider_action_type=receipt.action_type,
            provider_action_id=receipt.payment_link_id,
            postcondition_evidence_hash=postcondition_hash,
            payment_id=captured.payment_id,
            amount_minor=captured.amount_minor,
            currency=captured.currency,
            reference_id=captured.reference_id,
        )
