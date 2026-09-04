from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Iterable, Mapping


class TruthState(str, Enum):
    PAID = "PAID"
    FAILED = "FAILED"
    RECOVERABLE = "RECOVERABLE"
    IN_FLIGHT = "IN_FLIGHT"
    TERMINAL = "TERMINAL"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class ProviderEvidence:
    source: str
    entity_type: str
    entity_id: str
    status: str | None
    amount_minor: int | None = None
    currency: str | None = None
    reference_id: str | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))
    raw_hash: str = ""
    authoritative: bool = True

    def fingerprint(self) -> str:
        body = {
            "source": self.source,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "status": self.status,
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "reference_id": self.reference_id,
            "raw_hash": self.raw_hash,
            "authoritative": self.authoritative,
        }
        return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class TruthResolution:
    state: TruthState
    reason_codes: tuple[str, ...]
    evidence_fingerprints: tuple[str, ...]
    resolved_at: datetime

    @property
    def executable(self) -> bool:
        return self.state == TruthState.RECOVERABLE


_PAYMENT_CAPTURED = {"captured", "paid"}
_PAYMENT_FAILED = {"failed"}
_PAYMENT_IN_FLIGHT = {"created", "authorized", "pending"}
_PAYMENT_TERMINAL = {"refunded"}
_ORDER_KNOWN = {"created", "attempted", "paid"}
_MANDATE_ACTIVE = {"active", "enabled", "authenticated"}
_MANDATE_TERMINAL = {"revoked", "cancelled", "canceled", "paused", "expired", "halted"}


def _status(row: ProviderEvidence) -> str:
    return str(row.status or "").strip().lower()


def _collapse_latest(rows: Iterable[ProviderEvidence]) -> tuple[tuple[ProviderEvidence, ...], bool]:
    latest: dict[tuple[str, str, str], ProviderEvidence] = {}
    conflict = False
    for row in rows:
        if not row.authoritative:
            continue
        key = (row.source, row.entity_type.lower(), row.entity_id)
        current = latest.get(key)
        if current is None or row.observed_at > current.observed_at:
            latest[key] = row
        elif row.observed_at == current.observed_at and row.fingerprint() != current.fingerprint():
            conflict = True
    return tuple(latest.values()), conflict


def resolve_financial_truth(evidence: Iterable[ProviderEvidence]) -> TruthResolution:
    all_rows = tuple(evidence)
    now = datetime.now(timezone.utc)
    if not all_rows:
        return TruthResolution(TruthState.UNKNOWN, ("NO_PROVIDER_EVIDENCE",), (), now)

    current_rows, same_entity_conflict = _collapse_latest(all_rows)
    fingerprints = tuple(sorted(row.fingerprint() for row in all_rows))
    if same_entity_conflict:
        return TruthResolution(TruthState.CONFLICT, ("SAME_ENTITY_CURRENT_STATE_CONFLICT",), fingerprints, now)
    if not current_rows:
        return TruthResolution(TruthState.UNKNOWN, ("NO_AUTHORITATIVE_CURRENT_EVIDENCE",), fingerprints, now)

    payment_rows = tuple(row for row in current_rows if row.entity_type.lower() == "payment")
    order_rows = tuple(row for row in current_rows if row.entity_type.lower() == "order")
    mandate_rows = tuple(row for row in current_rows if row.entity_type.lower() in {"mandate", "subscription"})

    if any(_status(row) == "paid" for row in order_rows):
        return TruthResolution(TruthState.PAID, ("CURRENT_RAZORPAY_ORDER_PAID",), fingerprints, now)

    if any(_status(row) in _PAYMENT_CAPTURED for row in payment_rows):
        return TruthResolution(TruthState.PAID, ("CURRENT_CAPTURED_PAYMENT_OBSERVED",), fingerprints, now)

    if order_rows and any(_status(row) not in _ORDER_KNOWN for row in order_rows):
        return TruthResolution(TruthState.UNKNOWN, ("UNRECOGNIZED_CURRENT_ORDER_STATE",), fingerprints, now)

    if mandate_rows:
        mandate_statuses = {_status(row) for row in mandate_rows}
        if mandate_statuses & _MANDATE_TERMINAL:
            return TruthResolution(TruthState.TERMINAL, ("CURRENT_MANDATE_NOT_EXECUTABLE",), fingerprints, now)
        if not mandate_statuses.issubset(_MANDATE_ACTIVE):
            return TruthResolution(TruthState.UNKNOWN, ("UNRECOGNIZED_CURRENT_MANDATE_STATE",), fingerprints, now)

    known_payment_states = _PAYMENT_CAPTURED | _PAYMENT_FAILED | _PAYMENT_IN_FLIGHT | _PAYMENT_TERMINAL
    if any(_status(row) not in known_payment_states for row in payment_rows):
        return TruthResolution(TruthState.UNKNOWN, ("UNRECOGNIZED_CURRENT_PAYMENT_STATE",), fingerprints, now)

    if any(_status(row) in _PAYMENT_IN_FLIGHT for row in payment_rows):
        return TruthResolution(
            TruthState.IN_FLIGHT,
            ("CURRENT_PAYMENT_MAY_STILL_CAPTURE", "PARALLEL_RECOVERY_BLOCKED"),
            fingerprints,
            now,
        )

    if any(_status(row) in _PAYMENT_TERMINAL for row in payment_rows):
        return TruthResolution(TruthState.TERMINAL, ("CURRENT_PAYMENT_TERMINAL",), fingerprints, now)

    if payment_rows and all(_status(row) in _PAYMENT_FAILED for row in payment_rows):
        return TruthResolution(
            TruthState.RECOVERABLE,
            ("ALL_CURRENT_PAYMENT_ATTEMPTS_FAILED", "NO_CAPTURED_OR_INFLIGHT_PAYMENT"),
            fingerprints,
            now,
        )

    return TruthResolution(TruthState.UNKNOWN, ("INCOMPLETE_CURRENT_FINANCIAL_STATE",), fingerprints, now)


@dataclass(frozen=True)
class WriteFence:
    diagnosis_fingerprint: str

    @classmethod
    def from_evidence(cls, evidence: Iterable[ProviderEvidence]) -> "WriteFence":
        rows = tuple(evidence)
        resolution = resolve_financial_truth(rows)
        if resolution.state != TruthState.RECOVERABLE:
            raise ValueError(f"write fence can only be armed from RECOVERABLE state, got {resolution.state.value}")
        return cls(_set_fingerprint(rows))

    def check(self, fresh_evidence: Iterable[ProviderEvidence]) -> tuple[bool, str]:
        fresh = tuple(fresh_evidence)
        resolution = resolve_financial_truth(fresh)
        if resolution.state == TruthState.PAID:
            return False, "SAFE_BLOCK_ALREADY_PAID"
        if resolution.state != TruthState.RECOVERABLE:
            return False, f"SAFE_BLOCK_{resolution.state.value}"
        if _set_fingerprint(fresh) != self.diagnosis_fingerprint:
            return False, "SAFE_BLOCK_STATE_CHANGED_BEFORE_WRITE"
        return True, "WRITE_FENCE_PASSED"


def evidence_set_hash(evidence: Iterable[ProviderEvidence]) -> str:
    return _set_fingerprint(tuple(evidence))


def _set_fingerprint(evidence: Iterable[ProviderEvidence]) -> str:
    values = sorted(row.fingerprint() for row in evidence if row.authoritative)
    return sha256("|".join(values).encode()).hexdigest()


@dataclass(frozen=True)
class CapturedPaymentProof:
    payment_id: str
    amount_minor: int
    currency: str
    reference_id: str
    captured: bool


def verify_captured_payment(
    payment: Mapping[str, object], *, expected_amount_minor: int, expected_currency: str, expected_reference_id: str
) -> CapturedPaymentProof:
    payment_id = str(payment.get("id") or payment.get("payment_id") or "")
    status = str(payment.get("status") or "").lower()
    amount = int(payment.get("amount") or 0)
    currency = str(payment.get("currency") or "")
    notes = payment.get("notes")
    note_reference = notes.get("recovery_reference", "") if isinstance(notes, Mapping) else ""
    reference = str(payment.get("reference_id") or note_reference)
    if not payment_id:
        raise ValueError("payment id missing")
    if status != "captured":
        raise ValueError("payment is not captured")
    if amount != expected_amount_minor:
        raise ValueError("captured payment amount mismatch")
    if currency != expected_currency:
        raise ValueError("captured payment currency mismatch")
    if reference != expected_reference_id:
        raise ValueError("captured payment reference mismatch")
    return CapturedPaymentProof(payment_id, amount, currency, reference, True)


@dataclass(frozen=True)
class RecoveryProof:
    case_id: str
    mandate_id: str
    original_order_id: str
    decision_id: str
    decision_evidence_hash: str
    policy_version: str
    authority_expires_at: str
    prewrite_resolution: str
    prewrite_evidence_hash: str
    provider_action_type: str
    provider_action_id: str
    postcondition_evidence_hash: str
    payment_id: str
    amount_minor: int
    currency: str
    reference_id: str
    previous_proof_hash: str = "GENESIS"
    proof_version: str = "recoveryproof_v1"

    def hash(self) -> str:
        body = asdict(self)
        return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
