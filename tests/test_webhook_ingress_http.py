"""HTTP-level proof that the webhook boundary is actually wired to the route.

`tests/test_webhook_ingress.py` proves `WebhookGate` correctly authenticates
and orders a delivery as an isolated module. That is not the same claim as
"the FastAPI application uses it" — a strong, well tested library that no
route imports would pass every one of those tests and still leave the real
`/webhooks/razorpay` endpoint wide open. This file sends raw bytes over HTTP,
through `bailiff.api.app`, and checks the same properties end to end:
signature rejection, duplicate and stale-ordering handling, the paused/halted
block and its resume, and — for a genuine actionable delivery — that the
guardrail decision underneath is real, not a stub: a revoked mandate makes
zero provider calls, and an active one makes exactly one.
"""

from __future__ import annotations

import dataclasses
import json
import time

from fastapi.testclient import TestClient

from bailiff.api import WEBHOOK_GATE, _DEMO_WEBHOOK_SECRET, app
from bailiff.demo import _raw_event
from bailiff.razorpay_adapter import to_razorpay_test_payload
from bailiff.webhook import build_signed_delivery

client = TestClient(app)


def _payload(case_id: str, *, event_name: str = "payment.failed", **kwargs) -> dict:
    raw_event = _raw_event(case_id, **kwargs)
    payload = to_razorpay_test_payload(raw_event)
    payload["event"] = event_name
    # bailiff.demo anchors event_time in the past relative to a fixed demo
    # clock; the webhook gate's replay window is relative to wall clock time,
    # so a delivery needs a fresh created_at to land inside it here.
    payload["created_at"] = int(time.time())
    return payload


def _post(payload: dict, *, event_id: str, secret: str = _DEMO_WEBHOOK_SECRET):
    raw_body, headers = build_signed_delivery(payload, secret=secret, event_id=event_id)
    return client.post("/webhooks/razorpay", content=raw_body, headers=headers)


def setup_function(_):
    # WEBHOOK_GATE is a module level singleton so state (seen event ids,
    # per-subscription clocks) persists across tests unless cleared.
    WEBHOOK_GATE._seen_event_ids.clear()
    WEBHOOK_GATE._seen_body_hashes.clear()
    WEBHOOK_GATE._rejections.clear()
    WEBHOOK_GATE._subscription_clock.clear()
    WEBHOOK_GATE._ended_subscriptions.clear()
    WEBHOOK_GATE._blocked_subscriptions.clear()


def test_missing_signature_is_rejected_at_the_real_endpoint():
    payload = _payload("http_missing_sig")
    raw_body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    response = client.post(
        "/webhooks/razorpay", content=raw_body, headers={"x-razorpay-event-id": "e_missing"}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["reason_code"] == "MISSING_SIGNATURE_HEADER"


def test_wrong_signature_is_rejected_at_the_real_endpoint():
    payload = _payload("http_wrong_sig")
    response = _post(payload, event_id="e_wrong_sig", secret="not-the-configured-secret")
    assert response.status_code == 400
    assert response.json()["detail"]["reason_code"] == "SIGNATURE_MISMATCH"


def test_tampered_body_under_a_valid_signature_is_rejected():
    payload = _payload("http_tamper")
    raw_body, headers = build_signed_delivery(payload, secret=_DEMO_WEBHOOK_SECRET, event_id="e_tamper")
    tampered = raw_body.replace(b'"amount":99900', b'"amount":9990000')
    if tampered == raw_body:
        tampered = raw_body + b" "
    response = client.post("/webhooks/razorpay", content=tampered, headers=headers)
    assert response.status_code == 400
    assert response.json()["detail"]["reason_code"] == "SIGNATURE_MISMATCH"


def test_a_verified_active_mandate_failure_is_allowed_and_calls_the_provider_once():
    payload = _payload("http_allow", attempt_count=1)
    response = _post(payload, event_id="e_allow")
    assert response.status_code == 200
    body = response.json()
    assert body["should_process"] is True
    decision = body["decision"]
    assert decision["decision"] == "allow"
    assert decision["provider_call_made"] is True
    assert decision["provider_call_count"] == 1
    assert decision["audit_verified"] is True


def test_a_verified_revoked_mandate_failure_is_denied_with_zero_provider_calls():
    raw_event = _raw_event("http_deny", attempt_count=1)
    revoked = dataclasses.replace(raw_event, mandate_state="revoked")
    payload = to_razorpay_test_payload(revoked)
    payload["event"] = "payment.failed"
    payload["created_at"] = int(time.time())
    response = _post(payload, event_id="e_deny")
    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["decision"] == "stop"
    assert decision["provider_call_made"] is False
    assert decision["provider_call_count"] == 0


def test_a_provider_signalled_terminal_failure_is_not_retried_even_when_state_lags():
    """The route must gate on the diagnosed reason, not only the state field.

    A mandate the customer revoked can arrive with `mandate_state` still
    reading `active` because the caller's record lags the provider's. The
    benchmark B2 arm stops on the normalized terminal reason; the route runs
    the same policy, so it must stop here too — this exact seam once
    hardcoded a retry proposal and dropped the arm's reason gating entirely.
    """
    raw_event = _raw_event(
        "http_terminal_reason",
        attempt_count=1,
        failure_code="U31",
        description="mandate revoked by customer",
        normalized_reason="MANDATE_REVOKED_OR_CANCELLED",
    )
    payload = to_razorpay_test_payload(raw_event)
    payload["event"] = "payment.failed"
    payload["created_at"] = int(time.time())
    response = _post(payload, event_id="e_terminal_reason")
    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["decision"] == "stop"
    assert decision["provider_call_made"] is False
    assert decision["provider_call_count"] == 0


def test_a_redelivered_event_id_is_reported_as_a_duplicate_and_not_redecided():
    payload = _payload("http_dup")
    first = _post(payload, event_id="e_dup_http")
    assert first.json()["should_process"] is True
    second = _post(payload, event_id="e_dup_http")
    body = second.json()
    assert body["should_process"] is False
    assert body["reason_code"] == "DUPLICATE_DELIVERY_IGNORED"
    assert "decision" not in body


def test_a_stale_out_of_order_failure_is_superseded_and_not_redecided():
    subscription = "http_ordering_sub"
    charged = _payload("http_ordering", event_name="subscription.charged")
    charged["payload"]["subscription"]["entity"]["id"] = subscription
    charged["created_at"] = int(time.time())
    _post(charged, event_id="e_charged_http")

    stale_failure = _payload("http_ordering", event_name="payment.failed")
    stale_failure["payload"]["subscription"]["entity"]["id"] = subscription
    stale_failure["created_at"] = charged["created_at"] - 3600
    response = _post(stale_failure, event_id="e_stale_http")
    body = response.json()
    assert body["should_process"] is False
    assert body["reason_code"] == "SUPERSEDED_BY_NEWER_EVENT"


def test_a_paused_subscription_blocks_a_later_failure_until_resumed():
    subscription = "http_pause_sub"
    now = int(time.time())

    paused = _payload("http_pause", event_name="subscription.paused")
    paused["payload"]["subscription"]["entity"]["id"] = subscription
    paused["created_at"] = now
    _post(paused, event_id="e_pause_http")

    blocked_failure = _payload("http_pause", event_name="payment.failed")
    blocked_failure["payload"]["subscription"]["entity"]["id"] = subscription
    blocked_failure["created_at"] = now + 60
    blocked = _post(blocked_failure, event_id="e_pause_blocked_http")
    assert blocked.json()["should_process"] is False
    assert blocked.json()["reason_code"] == "BLOCKED_SUBSCRIPTION_PAUSED_OR_HALTED"

    resumed = _payload("http_pause", event_name="subscription.resumed")
    resumed["payload"]["subscription"]["entity"]["id"] = subscription
    resumed["created_at"] = now + 120
    resume_response = _post(resumed, event_id="e_resume_http")
    assert resume_response.json()["should_process"] is True

    after_resume = _payload("http_pause", event_name="payment.failed", attempt_count=1)
    after_resume["payload"]["subscription"]["entity"]["id"] = subscription
    after_resume["created_at"] = now + 180
    final = _post(after_resume, event_id="e_after_resume_http")
    assert final.json()["should_process"] is True
    assert final.json()["decision"]["decision"] in {"allow", "stop", "escalate"}


def test_a_verified_non_payment_failed_event_is_recorded_without_a_decision():
    payload = _payload("http_charged", event_name="subscription.charged")
    response = _post(payload, event_id="e_charged_only")
    body = response.json()
    assert body["should_process"] is True
    assert body["decision"] is None
