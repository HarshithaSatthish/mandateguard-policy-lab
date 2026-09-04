from __future__ import annotations

if not __debug__:
    raise SystemExit(
        "this release gate is built on assert statements; running it with "
        "PYTHONOPTIMIZE or -O would silently disable every check"
    )

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os

import httpx

from bailiff.recovery_runtime import (
    FALLBACK_ACTION,
    ExecutionState,
    RecoveryRequest,
    RecoveryTruthRuntime,
    recovery_reference,
)
from bailiff.recovery_truth import ProviderEvidence, TruthState, WriteFence, resolve_financial_truth
from bailiff.razorpay_testmode import RazorpayConfigurationError, RazorpayTestModeClient


def evidence(
    status: str,
    entity_id: str = "pay_1",
    *,
    entity_type: str = "payment",
    authoritative: bool = True,
    observed_at: datetime | None = None,
) -> ProviderEvidence:
    return ProviderEvidence(
        source="razorpay_test_mode" if entity_type == "payment" else "merchant_current_state",
        entity_type=entity_type,
        entity_id=entity_id,
        status=status,
        amount_minor=1000 if entity_type == "payment" else None,
        currency="INR" if entity_type == "payment" else None,
        reference_id="order_1",
        observed_at=observed_at or datetime.now(timezone.utc),
        authoritative=authoritative,
    )


@contextmanager
def env(**values: str):
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeProvider:
    def __init__(self) -> None:
        self.phase = 0
        self.write_attempts = 0
        self.create_method_calls = 0
        self.link = None
        self.evidence_reads = 0
        self.fail_read_at: int | None = None
        self.ambiguous_write = False
        self.malformed_write_response = False

    def order_evidence(
        self,
        *,
        order_id: str,
        mandate_id: str | None = None,
        mandate_status: str | None = None,
        expected_amount_minor: int | None = None,
        expected_currency: str | None = None,
    ):
        assert order_id == "order_1"
        assert expected_amount_minor == 1000
        assert expected_currency == "INR"
        self.evidence_reads += 1
        if self.fail_read_at == self.evidence_reads:
            raise httpx.ReadTimeout("provider read timed out")
        mandate = evidence(mandate_status or "active", mandate_id or "mandate_1", entity_type="mandate")
        if self.phase == 2:
            return (evidence("captured", "pay_late"), mandate)
        if self.phase == 3:
            return (evidence("authorized", "pay_inflight"), mandate)
        return (evidence("failed"), mandate)

    def create_payment_link_once(self, *, amount_minor: int, currency: str, reference_id: str, description: str):
        self.create_method_calls += 1
        if self.ambiguous_write:
            self.write_attempts += 1
            raise httpx.WriteTimeout("provider write timed out after send")
        if self.malformed_write_response:
            self.write_attempts += 1
            return {"id": "not-a-payment-link", "reference_id": reference_id, "amount": amount_minor, "currency": currency}
        if self.link is None:
            self.write_attempts += 1
            self.link = {
                "id": "plink_test_1",
                "short_url": "https://rzp.io/i/test",
                "amount": amount_minor,
                "currency": currency,
                "reference_id": reference_id,
                "accept_partial": False,
            }
        return self.link

    def verify_payment_link_capture(self, *, payment_link_id: str, expected_amount_minor: int, expected_currency: str, expected_reference_id: str):
        from bailiff.recovery_truth import verify_captured_payment

        payment = {
            "id": "pay_captured_1",
            "status": "captured",
            "amount": expected_amount_minor,
            "currency": expected_currency,
            "reference_id": expected_reference_id,
        }
        proof = verify_captured_payment(
            payment,
            expected_amount_minor=expected_amount_minor,
            expected_currency=expected_currency,
            expected_reference_id=expected_reference_id,
        )
        return proof, "postcondition_hash_1"


class StubRazorpayClient(RazorpayTestModeClient):
    """Exercise the real adapter contract without network or credentials."""

    def __init__(self, *, post_mode: str = "normal") -> None:
        super().__init__(key_id="rzp_test_contract", key_secret="not-a-real-secret")
        self.post_mode = post_mode
        self.link: dict[str, object] | None = None
        self.post_writes = 0
        self.paid = False
        self.order_status = "attempted"
        self.wrong_order_payment = False

    def _request(self, method: str, path: str, **kwargs: object):
        if method == "GET" and path == "/orders/order_1":
            return {
                "id": "order_1",
                "amount": 1000,
                "amount_paid": 1000 if self.order_status == "paid" else 0,
                "amount_due": 0 if self.order_status == "paid" else 1000,
                "currency": "INR",
                "status": self.order_status,
                "receipt": "case_1",
            }
        if method == "GET" and path == "/orders/order_1/payments":
            return {
                "items": [
                    {
                        "id": "pay_failed_1",
                        "order_id": "order_wrong" if self.wrong_order_payment else "order_1",
                        "amount": 1000,
                        "currency": "INR",
                        "status": "failed",
                    }
                ]
            }
        if method == "GET" and path == "/payment_links/":
            links = [] if self.link is None else [dict(self.link)]
            return {"payment_links": links}
        if method == "POST" and path == "/payment_links":
            payload = kwargs.get("json")
            assert isinstance(payload, dict)
            self.post_writes += 1
            self.link = {
                "id": "plink_contract_1",
                "short_url": "https://rzp.io/i/contract",
                "amount": payload["amount"],
                "currency": payload["currency"],
                "reference_id": payload["reference_id"],
                "accept_partial": payload["accept_partial"],
                "status": "created",
                "payments": None,
                "notes": dict(payload["notes"]),
            }
            request = httpx.Request("POST", "https://api.razorpay.com/v1/payment_links")
            if self.post_mode == "timeout_after_create":
                raise httpx.WriteTimeout("simulated timeout after provider accepted write", request=request)
            if self.post_mode == "duplicate_after_create":
                response = httpx.Response(400, request=request)
                raise httpx.HTTPStatusError("duplicate reference", request=request, response=response)
            return dict(self.link)
        if method == "GET" and path == "/payment_links/plink_contract_1":
            assert self.link is not None
            link = dict(self.link)
            if self.paid:
                link["status"] = "paid"
                link["amount_paid"] = 1000
                link["payments"] = [
                    {
                        "payment_id": "pay_captured_1",
                        "payment_link_id": "plink_contract_1",
                        "amount": 1000,
                        "status": "captured",
                    }
                ]
            return link
        if method == "GET" and path == "/payments/pay_captured_1":
            # Razorpay propagates the notes set at Payment Link creation onto
            # the payment made through the link; the recovery reference on the
            # payment is how capture verification binds without injecting the
            # expectation into its own check.
            assert self.link is not None
            return {
                "id": "pay_captured_1",
                "order_id": None,
                "amount": 1000,
                "currency": "INR",
                "status": "captured",
                "notes": dict(self.link.get("notes", {})),
            }
        raise AssertionError(f"unexpected adapter request: {method} {path} {kwargs}")


def request(*, expires_at: datetime | None = None) -> RecoveryRequest:
    return RecoveryRequest(
        case_id="case_1",
        decision_id="dec_1",
        decision_evidence_hash="decision_hash_1",
        policy_version="mandateguard_policy_0.2",
        order_id="order_1",
        mandate_id="mandate_1",
        mandate_status="active",
        amount_minor=1000,
        max_authorized_amount_minor=1000,
        authority_expires_at=expires_at or datetime.now(timezone.utc) + timedelta(minutes=5),
        authorized_action_type=FALLBACK_ACTION,
    )


def check_real_adapter_contract() -> None:
    client = StubRazorpayClient()
    rows = client.order_evidence(
        order_id="order_1",
        expected_amount_minor=1000,
        expected_currency="INR",
    )
    assert resolve_financial_truth(rows).state == TruthState.RECOVERABLE

    reference = recovery_reference("case_1")
    link = client.create_payment_link_once(
        amount_minor=1000,
        currency="INR",
        reference_id=reference,
        description="contract test",
    )
    assert link["id"] == "plink_contract_1"
    assert client.post_writes == 1
    reused = client.create_payment_link_once(
        amount_minor=1000,
        currency="INR",
        reference_id=reference,
        description="contract test",
    )
    assert reused["id"] == "plink_contract_1" and client.post_writes == 1

    client.paid = True
    proof, evidence_hash = client.verify_payment_link_capture(
        payment_link_id="plink_contract_1",
        expected_amount_minor=1000,
        expected_currency="INR",
        expected_reference_id=reference,
    )
    assert proof.payment_id == "pay_captured_1"
    assert proof.captured and len(evidence_hash) == 64

    timeout_client = StubRazorpayClient(post_mode="timeout_after_create")
    reconciled = timeout_client.create_payment_link_once(
        amount_minor=1000,
        currency="INR",
        reference_id=reference,
        description="timeout reconciliation",
    )
    assert reconciled["id"] == "plink_contract_1" and timeout_client.post_writes == 1

    duplicate_client = StubRazorpayClient(post_mode="duplicate_after_create")
    reconciled = duplicate_client.create_payment_link_once(
        amount_minor=1000,
        currency="INR",
        reference_id=reference,
        description="duplicate reconciliation",
    )
    assert reconciled["id"] == "plink_contract_1" and duplicate_client.post_writes == 1

    paid_order = StubRazorpayClient()
    paid_order.order_status = "paid"
    rows = paid_order.order_evidence(order_id="order_1", expected_amount_minor=1000, expected_currency="INR")
    assert resolve_financial_truth(rows).state == TruthState.PAID

    mismatched = StubRazorpayClient()
    mismatched.wrong_order_payment = True
    try:
        mismatched.order_evidence(order_id="order_1", expected_amount_minor=1000, expected_currency="INR")
    except ValueError as exc:
        assert "another order" in str(exc)
    else:
        raise AssertionError("adapter accepted a payment bound to a different Razorpay order")


def main() -> int:
    now = datetime.now(timezone.utc)

    stale = evidence("failed", authoritative=False, observed_at=now - timedelta(minutes=5))
    captured = evidence("captured", "pay_2", observed_at=now)
    result = resolve_financial_truth([stale, captured])
    assert result.state == TruthState.PAID and not result.executable

    failed = evidence("failed")
    active = evidence("active", "mandate_1", entity_type="mandate")
    result = resolve_financial_truth([failed, active])
    assert result.state == TruthState.RECOVERABLE and result.executable
    assert resolve_financial_truth([evidence("authorized", "pay_3"), active]).state == TruthState.IN_FLIGHT
    assert resolve_financial_truth([evidence("pending", "pay_4"), active]).state == TruthState.IN_FLIGHT
    assert resolve_financial_truth([evidence("mystery")]).state == TruthState.UNKNOWN
    assert resolve_financial_truth([failed, evidence("revoked", "mandate_1", entity_type="mandate")]).state == TruthState.TERMINAL

    fence = WriteFence.from_evidence([failed, active])
    allowed, reason = fence.check([captured, active])
    assert not allowed and reason == "SAFE_BLOCK_ALREADY_PAID"
    allowed, reason = fence.check([evidence("authorized", "pay_inflight"), active])
    assert not allowed and reason == "SAFE_BLOCK_IN_FLIGHT"

    provider = FakeProvider()
    expired = request(expires_at=now - timedelta(seconds=1))
    attempt = RecoveryTruthRuntime(provider).execute_customer_fallback(expired)
    assert not attempt.executed and attempt.reason_code == "SAFE_BLOCK_AUTHORITY_EXPIRED"
    assert provider.write_attempts == 0 and provider.evidence_reads == 0

    try:
        RecoveryRequest(
            case_id="case_1",
            decision_id="dec_1",
            decision_evidence_hash="decision_hash_1",
            policy_version="v1",
            order_id="order_1",
            mandate_id="mandate_1",
            mandate_status="active",
            amount_minor=1001,
            max_authorized_amount_minor=1000,
            authority_expires_at=now + timedelta(minutes=5),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("recovery request widened the policy amount authority")

    provider = FakeProvider()
    provider.fail_read_at = 1
    attempt = RecoveryTruthRuntime(provider).execute_customer_fallback(request())
    assert attempt.execution_state == ExecutionState.NOT_EXECUTED
    assert attempt.reason_code == "SAFE_BLOCK_PROVIDER_READ_ERROR"
    assert provider.write_attempts == 0

    provider = FakeProvider()
    provider.fail_read_at = 2
    attempt = RecoveryTruthRuntime(provider).execute_customer_fallback(request())
    assert attempt.execution_state == ExecutionState.NOT_EXECUTED
    assert attempt.reason_code == "SAFE_BLOCK_PREWRITE_PROVIDER_READ_ERROR"
    assert provider.write_attempts == 0

    provider = FakeProvider()
    runtime = RecoveryTruthRuntime(provider)
    req = request()
    attempt = runtime.execute_customer_fallback(req)
    assert attempt.executed and attempt.receipt is not None
    assert provider.evidence_reads == 2
    assert provider.write_attempts == 1
    assert len(attempt.receipt.reference_id) <= 40
    assert attempt.receipt.reference_id == recovery_reference("case_1")
    assert attempt.receipt.decision_evidence_hash == "decision_hash_1"
    assert attempt.receipt.order_id == "order_1"

    second = runtime.execute_customer_fallback(req)
    assert second.executed and second.receipt is not None
    assert second.receipt.payment_link_id == attempt.receipt.payment_link_id
    assert provider.create_method_calls == 2
    assert provider.write_attempts == 1

    proof = runtime.verify_recovery(attempt.receipt)
    assert proof.payment_id == "pay_captured_1"
    assert proof.provider_action_id == "plink_test_1"
    assert proof.provider_action_type == FALLBACK_ACTION
    assert proof.decision_evidence_hash == "decision_hash_1"
    assert proof.postcondition_evidence_hash == "postcondition_hash_1"
    assert proof.hash() == proof.hash()

    provider = FakeProvider()
    original = provider.order_evidence
    calls = {"n": 0}

    def changing_to_paid(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            provider.phase = 2
        return original(**kwargs)

    provider.order_evidence = changing_to_paid  # type: ignore[method-assign]
    attempt = RecoveryTruthRuntime(provider).execute_customer_fallback(req)
    assert not attempt.executed and attempt.reason_code == "SAFE_BLOCK_ALREADY_PAID"
    assert provider.write_attempts == 0

    provider = FakeProvider()
    original = provider.order_evidence
    calls = {"n": 0}

    def changing_to_inflight(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            provider.phase = 3
        return original(**kwargs)

    provider.order_evidence = changing_to_inflight  # type: ignore[method-assign]
    attempt = RecoveryTruthRuntime(provider).execute_customer_fallback(req)
    assert not attempt.executed and attempt.reason_code == "SAFE_BLOCK_IN_FLIGHT"
    assert provider.write_attempts == 0

    provider = FakeProvider()
    provider.ambiguous_write = True
    attempt = RecoveryTruthRuntime(provider).execute_customer_fallback(req)
    assert attempt.execution_state == ExecutionState.WRITE_OUTCOME_UNKNOWN
    assert attempt.write_outcome_unknown
    assert attempt.reason_code == "PROVIDER_WRITE_OUTCOME_UNKNOWN"
    assert attempt.receipt is None
    assert provider.write_attempts == 1

    provider = FakeProvider()
    provider.malformed_write_response = True
    attempt = RecoveryTruthRuntime(provider).execute_customer_fallback(req)
    assert attempt.execution_state == ExecutionState.WRITE_OUTCOME_UNKNOWN
    assert attempt.reason_code == "PROVIDER_WRITE_OUTCOME_UNKNOWN"
    assert attempt.receipt is None
    assert provider.write_attempts == 1

    check_real_adapter_contract()

    with env(RAZORPAY_TEST_KEY_ID="rzp_live_forbidden", RAZORPAY_TEST_KEY_SECRET="secret"):
        try:
            RazorpayTestModeClient.from_env()
        except RazorpayConfigurationError:
            pass
        else:
            raise AssertionError("live Razorpay key was not refused")

    print(
        "RecoveryTruth acceptance checks passed: financial truth, exact order binding, actual Test Mode adapter "
        "contract, provider-read fail-closed, in-flight block, expiring authority, write fence, logical "
        "exactly-once, timeout/duplicate reconciliation, ambiguous/malformed post-write state, captured-payment proof"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
