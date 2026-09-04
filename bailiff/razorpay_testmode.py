from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from threading import Lock
from typing import ClassVar, Mapping

import httpx

from .recovery_truth import CapturedPaymentProof, ProviderEvidence, verify_captured_payment


class RazorpayConfigurationError(RuntimeError):
    pass


@dataclass
class RazorpayTestModeClient:
    key_id: str
    key_secret: str
    base_url: str = "https://api.razorpay.com/v1"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        # The live-credential refusal must be structural, not a property of
        # one factory: a caller constructing the client directly gets the
        # same boundary as `from_env`.
        if not self.key_id.startswith("rzp_test_"):
            raise RazorpayConfigurationError("RecoveryTruth refuses non-test Razorpay credentials")

    # Process-local serialization closes the common double-click/two-thread
    # race before the provider boundary. It is intentionally not presented as
    # distributed exactly-once: separate processes can still race, so the
    # deterministic Razorpay reference_id remains the cross-process fence and
    # duplicate/ambiguous writes are reconciled by provider lookup below.
    _reference_locks: ClassVar[dict[str, Lock]] = {}
    _reference_locks_guard: ClassVar[Lock] = Lock()

    @classmethod
    def from_env(cls) -> "RazorpayTestModeClient":
        key_id = os.getenv("RAZORPAY_TEST_KEY_ID", "")
        key_secret = os.getenv("RAZORPAY_TEST_KEY_SECRET", "")
        if not key_id or not key_secret:
            raise RazorpayConfigurationError("RAZORPAY_TEST_KEY_ID and RAZORPAY_TEST_KEY_SECRET are required")
        if not key_id.startswith("rzp_test_"):
            raise RazorpayConfigurationError("RecoveryTruth refuses non-test Razorpay credentials")
        return cls(key_id=key_id, key_secret=key_secret)

    @classmethod
    def _lock_for_reference(cls, reference_id: str) -> Lock:
        with cls._reference_locks_guard:
            lock = cls._reference_locks.get(reference_id)
            if lock is None:
                lock = Lock()
                cls._reference_locks[reference_id] = lock
            return lock

    def _request(self, method: str, path: str, **kwargs: object) -> Mapping[str, object]:
        with httpx.Client(auth=(self.key_id, self.key_secret), timeout=self.timeout_seconds) as client:
            response = client.request(method, f"{self.base_url}{path}", **kwargs)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, Mapping):
            raise ValueError("Razorpay response must be an object")
        return data

    @staticmethod
    def _raw_hash(value: Mapping[str, object]) -> str:
        raw = json.dumps(dict(value), sort_keys=True, default=str, separators=(",", ":")).encode()
        return sha256(raw).hexdigest()

    def fetch_order(self, order_id: str) -> Mapping[str, object]:
        if not order_id.startswith("order_"):
            raise ValueError("invalid Razorpay order id")
        order = self._request("GET", f"/orders/{order_id}")
        if str(order.get("id") or "") != order_id:
            raise ValueError("Razorpay returned a different order id")
        return order

    def fetch_payment(self, payment_id: str) -> Mapping[str, object]:
        if not payment_id.startswith("pay_"):
            raise ValueError("invalid Razorpay payment id")
        payment = self._request("GET", f"/payments/{payment_id}")
        if str(payment.get("id") or "") != payment_id:
            raise ValueError("Razorpay returned a different payment id")
        return payment

    def fetch_order_payments(self, order_id: str) -> tuple[Mapping[str, object], ...]:
        if not order_id.startswith("order_"):
            raise ValueError("invalid Razorpay order id")
        data = self._request("GET", f"/orders/{order_id}/payments")
        items = data.get("items", [])
        if not isinstance(items, list):
            raise ValueError("Razorpay order payments response has invalid items")
        payments = tuple(item for item in items if isinstance(item, Mapping))
        for payment in payments:
            if str(payment.get("order_id") or "") != order_id:
                raise ValueError("Razorpay order-payments response contains a payment for another order")
        return payments

    def fetch_payment_link(self, payment_link_id: str) -> Mapping[str, object]:
        if not payment_link_id.startswith("plink_"):
            raise ValueError("invalid Razorpay payment link id")
        link = self._request("GET", f"/payment_links/{payment_link_id}")
        if str(link.get("id") or "") != payment_link_id:
            raise ValueError("Razorpay returned a different payment link id")
        return link

    def find_payment_link_by_reference(self, reference_id: str) -> Mapping[str, object] | None:
        if not reference_id or len(reference_id) > 40:
            raise ValueError("payment link reference_id must contain 1 to 40 characters")
        data = self._request("GET", "/payment_links/", params={"reference_id": reference_id})
        links = data.get("payment_links", [])
        if not isinstance(links, list):
            raise ValueError("Razorpay payment links response has invalid payment_links")
        matches = [link for link in links if isinstance(link, Mapping) and link.get("reference_id") == reference_id]
        if len(matches) > 1:
            raise RuntimeError("multiple payment links found for unique recovery reference")
        return matches[0] if matches else None

    def create_payment_link_once(
        self, *, amount_minor: int, currency: str, reference_id: str, description: str
    ) -> Mapping[str, object]:
        """Create a customer-initiated fallback collection link exactly once logically.

        This is not an AutoPay debit retry. Calls for the same reference are
        serialized inside one process. Across processes, the deterministic
        unique reference is the provider reconciliation key. Network ambiguity
        and duplicate-reference races are resolved by lookup before the caller
        is allowed to consider another provider write.
        """
        if amount_minor <= 0:
            raise ValueError("amount_minor must be positive")
        if currency != "INR":
            raise ValueError("RecoveryTruth Test Mode fallback is INR only")

        with self._lock_for_reference(reference_id):
            existing = self.find_payment_link_by_reference(reference_id)
            if existing is not None:
                return existing
            payload = {
                "amount": amount_minor,
                "currency": currency,
                "reference_id": reference_id,
                "description": description,
                "accept_partial": False,
                "notify": {"sms": False, "email": False},
                "reminder_enable": False,
                "notes": {"recovery_reference": reference_id, "system": "RecoveryTruth"},
            }
            try:
                return self._request("POST", "/payment_links", json=payload)
            except (httpx.TimeoutException, httpx.NetworkError):
                reconciled = self.find_payment_link_by_reference(reference_id)
                if reconciled is not None:
                    return reconciled
                raise
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {400, 409}:
                    reconciled = self.find_payment_link_by_reference(reference_id)
                    if reconciled is not None:
                        return reconciled
                raise

    @staticmethod
    def payment_evidence(payment: Mapping[str, object], *, authoritative: bool = True) -> ProviderEvidence:
        return ProviderEvidence(
            source="razorpay_test_mode",
            entity_type="payment",
            entity_id=str(payment.get("id") or ""),
            status=str(payment.get("status") or ""),
            amount_minor=int(payment.get("amount") or 0),
            currency=str(payment.get("currency") or ""),
            reference_id=str(payment.get("order_id") or ""),
            observed_at=datetime.now(timezone.utc),
            raw_hash=RazorpayTestModeClient._raw_hash(payment),
            authoritative=authoritative,
        )

    @staticmethod
    def order_state_evidence(order: Mapping[str, object]) -> ProviderEvidence:
        return ProviderEvidence(
            source="razorpay_test_mode",
            entity_type="order",
            entity_id=str(order.get("id") or ""),
            status=str(order.get("status") or ""),
            amount_minor=int(order.get("amount") or 0),
            currency=str(order.get("currency") or ""),
            reference_id=str(order.get("receipt") or ""),
            observed_at=datetime.now(timezone.utc),
            raw_hash=RazorpayTestModeClient._raw_hash(order),
            authoritative=True,
        )

    def order_evidence(
        self,
        *,
        order_id: str,
        mandate_id: str | None = None,
        mandate_status: str | None = None,
        expected_amount_minor: int | None = None,
        expected_currency: str | None = None,
    ) -> tuple[ProviderEvidence, ...]:
        """Fetch and bind fresh Razorpay order + payment evidence.

        Caller-supplied mandate state is intentionally ignored as provider
        truth. Mandate/consent permission is carried by the expiring
        MandateGuard decision authority unless a separate authoritative source
        is actually queried.
        """
        del mandate_id, mandate_status
        order = self.fetch_order(order_id)
        if expected_amount_minor is not None and int(order.get("amount") or 0) != expected_amount_minor:
            raise ValueError("Razorpay order amount does not match recovery authority")
        if expected_currency is not None and str(order.get("currency") or "") != expected_currency:
            raise ValueError("Razorpay order currency does not match recovery authority")

        payments = self.fetch_order_payments(order_id)
        for payment in payments:
            if expected_amount_minor is not None and int(payment.get("amount") or 0) != expected_amount_minor:
                raise ValueError("Razorpay payment amount does not match recovery order")
            if expected_currency is not None and str(payment.get("currency") or "") != expected_currency:
                raise ValueError("Razorpay payment currency does not match recovery order")
        return (self.order_state_evidence(order), *(self.payment_evidence(payment) for payment in payments))

    def verify_payment_link_capture(
        self, *, payment_link_id: str, expected_amount_minor: int, expected_currency: str, expected_reference_id: str
    ) -> tuple[CapturedPaymentProof, str]:
        link = self.fetch_payment_link(payment_link_id)
        link_raw_hash = self._raw_hash(link)
        if str(link.get("reference_id") or "") != expected_reference_id:
            raise ValueError("payment link reference mismatch")
        if int(link.get("amount") or 0) != expected_amount_minor:
            raise ValueError("payment link amount mismatch")
        if str(link.get("currency") or "") != expected_currency:
            raise ValueError("payment link currency mismatch")
        if bool(link.get("accept_partial", False)):
            raise ValueError("partial payment link is outside RecoveryTruth proof contract")
        if str(link.get("status") or "").lower() != "paid":
            raise ValueError("payment link is not in paid state")

        payments = link.get("payments")
        if not isinstance(payments, list) or not payments:
            raise ValueError("no captured payment attached to payment link")
        if len(payments) != 1:
            raise ValueError("expected exactly one captured payment for non-partial recovery link")

        link_payment = payments[0]
        if not isinstance(link_payment, Mapping):
            raise ValueError("invalid captured payment entry on payment link")
        payment_id = str(link_payment.get("payment_id") or link_payment.get("id") or "")
        if not payment_id:
            raise ValueError("captured payment entry has no payment id")
        linked_plink = str(link_payment.get("payment_link_id") or "")
        if linked_plink and linked_plink != payment_link_id:
            raise ValueError("captured payment is bound to a different payment link")
        link_payment_status = str(link_payment.get("status") or "").lower()
        if link_payment_status and link_payment_status != "captured":
            raise ValueError("payment link entry is not captured")
        link_payment_amount = link_payment.get("amount")
        if link_payment_amount is not None and int(link_payment_amount) != expected_amount_minor:
            raise ValueError("payment link captured payment amount mismatch")

        provider_payment = dict(self.fetch_payment(payment_id))
        payment_raw_hash = self._raw_hash(provider_payment)
        # The payment must carry the recovery reference itself, via the notes
        # Razorpay propagates from the link at creation. Injecting the
        # expected reference here before verifying it would turn the
        # reference check into a comparison of the expectation with itself.
        proof = verify_captured_payment(
            provider_payment,
            expected_amount_minor=expected_amount_minor,
            expected_currency=expected_currency,
            expected_reference_id=expected_reference_id,
        )
        if proof.payment_id != payment_id:
            raise ValueError("captured payment proof identity mismatch")
        binding = f"{link_raw_hash}:{payment_raw_hash}:{payment_link_id}:{payment_id}:{expected_reference_id}"
        postcondition_evidence_hash = sha256(binding.encode()).hexdigest()
        return proof, postcondition_evidence_hash
