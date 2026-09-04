"""Attacks against the webhook ingress boundary.

Everything else in this project proves an ACTION was authorised. This file
proves the INPUT was authentic, which has to come first: an attacker who can
post to the endpoint and be believed does not need to defeat a single guardrail
downstream, because the recovery agent will be driven by a failure they wrote.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import json
import pytest

from bailiff.webhook import (
    EVENT_ID_HEADER,
    SIGNATURE_HEADER,
    WebhookGate,
    build_signed_delivery,
    sign_payload,
)

SECRET = "whsec_live_example"
OLD_SECRET = "whsec_rotated_out"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

PAYLOAD = {
    "event": "subscription.pending",
    "created_at": int(NOW.timestamp()),
    "payload": {
        "payment": {"entity": {"id": "pay_test", "error_reason": "insufficient_funds"}},
        "subscription": {"entity": {"id": "sub_test", "status": "active"}},
    },
}


def _gate(**kwargs) -> WebhookGate:
    return WebhookGate(secrets=kwargs.pop("secrets", (SECRET,)), **kwargs)


def _delivery(event_id: str = "evt_001", secret: str = SECRET):
    return build_signed_delivery(PAYLOAD, secret=secret, event_id=event_id)


# -- the happy path exists only to make the failures meaningful ------------


def test_a_correctly_signed_delivery_is_accepted():
    raw, headers = _delivery()
    verdict = _gate().verify(raw_body=raw, headers=headers, received_at=NOW)
    assert verdict.accepted and verdict.should_process
    assert verdict.event_name == "subscription.pending"
    assert verdict.secret_generation == "current"


# -- forgery ---------------------------------------------------------------


def test_an_unsigned_delivery_is_refused():
    raw, headers = _delivery()
    headers.pop(SIGNATURE_HEADER)
    verdict = _gate().verify(raw_body=raw, headers=headers, received_at=NOW)
    assert not verdict.accepted
    assert verdict.reason_code == "MISSING_SIGNATURE_HEADER"


@pytest.mark.parametrize(
    "forged",
    [
        "0" * 64,
        "",
        "not-a-signature",
        "deadbeef",
        sign_payload(json.dumps(PAYLOAD).encode(), "the-wrong-secret"),
    ],
)
def test_a_forged_signature_is_refused(forged):
    raw, headers = _delivery()
    headers[SIGNATURE_HEADER] = forged
    verdict = _gate().verify(raw_body=raw, headers=headers, received_at=NOW)
    assert not verdict.accepted


def test_a_body_tampered_after_signing_is_refused():
    """The attack this defends against: a genuine signature on an altered amount."""
    raw, headers = _delivery()
    tampered = raw.replace(b'"status":"active"', b'"status":"halted"')
    assert tampered != raw
    verdict = _gate().verify(raw_body=tampered, headers=headers, received_at=NOW)
    assert not verdict.accepted
    assert verdict.reason_code == "SIGNATURE_MISMATCH"


def test_even_a_single_appended_byte_is_refused():
    raw, headers = _delivery()
    verdict = _gate().verify(raw_body=raw + b" ", headers=headers, received_at=NOW)
    assert not verdict.accepted


def test_a_signature_valid_for_a_different_body_does_not_transfer():
    """Signature reuse across deliveries must not authenticate a new payload."""
    raw_a, headers_a = _delivery(event_id="evt_a")
    other = dict(PAYLOAD)
    other["event"] = "subscription.charged"
    raw_b, _ = build_signed_delivery(other, secret=SECRET, event_id="evt_b")
    verdict = _gate().verify(raw_body=raw_b, headers=headers_a, received_at=NOW)
    assert not verdict.accepted


# -- replay and duplicates -------------------------------------------------


def test_a_redelivered_event_is_authentic_but_must_not_be_processed_twice():
    """Razorpay may redeliver. Authentic is not the same as actionable."""
    raw, headers = _delivery()
    gate = _gate()
    first = gate.verify(raw_body=raw, headers=headers, received_at=NOW)
    second = gate.verify(raw_body=raw, headers=headers, received_at=NOW + timedelta(minutes=5))
    assert first.should_process
    assert second.accepted
    assert second.duplicate
    assert not second.should_process
    assert second.reason_code == "DUPLICATE_DELIVERY_IGNORED"


def test_a_captured_body_replayed_under_a_fresh_event_id_is_still_a_duplicate():
    """The HMAC covers only the body, so the event-id header is unauthenticated.

    An attacker who observed one genuine delivery does not need to forge a
    signature to replay it — only to change the unsigned header id. The same
    signed bytes are the same event, whatever the header claims.
    """
    raw, headers = _delivery(event_id="evt_original")
    gate = _gate()
    assert gate.verify(raw_body=raw, headers=headers, received_at=NOW).should_process
    replayed = dict(headers)
    replayed[EVENT_ID_HEADER] = "evt_attacker_minted"
    second = gate.verify(raw_body=raw, headers=replayed, received_at=NOW + timedelta(minutes=2))
    assert second.accepted
    assert second.duplicate
    assert not second.should_process
    assert second.reason_code == "DUPLICATE_DELIVERY_IGNORED"


def test_a_non_ascii_signature_header_is_a_mismatch_not_a_crash():
    """`hmac.compare_digest` raises TypeError on non-ASCII str input.

    The header is attacker controlled, and the gate's contract is that no
    untrusted payload can crash it, so a non-ASCII signature must land on the
    ordinary mismatch path.
    """
    raw, headers = _delivery(event_id="evt_non_ascii")
    headers[SIGNATURE_HEADER] = "sig\u00ff\u0100nature"
    verdict = _gate().verify(raw_body=raw, headers=headers, received_at=NOW)
    assert not verdict.accepted
    assert verdict.reason_code == "SIGNATURE_MISMATCH"


def test_a_delivery_without_an_event_id_cannot_be_deduplicated_and_is_refused():
    raw, headers = _delivery()
    headers.pop(EVENT_ID_HEADER)
    verdict = _gate().verify(raw_body=raw, headers=headers, received_at=NOW)
    assert not verdict.accepted
    assert verdict.reason_code == "MISSING_EVENT_ID_HEADER"


def test_a_delivery_replayed_long_after_the_fact_is_refused():
    raw, headers = _delivery()
    verdict = _gate().verify(
        raw_body=raw, headers=headers, received_at=NOW + timedelta(days=9)
    )
    assert not verdict.accepted
    assert verdict.reason_code == "DELIVERY_OUTSIDE_REPLAY_WINDOW"


def test_a_delivery_stamped_in_the_future_is_refused():
    payload = dict(PAYLOAD)
    payload["created_at"] = int((NOW + timedelta(days=2)).timestamp())
    raw, headers = build_signed_delivery(payload, secret=SECRET, event_id="evt_future")
    verdict = _gate().verify(raw_body=raw, headers=headers, received_at=NOW)
    assert not verdict.accepted
    assert verdict.reason_code == "CREATED_IN_THE_FUTURE"


# -- secret rotation -------------------------------------------------------


def test_a_retry_signed_with_the_previous_secret_still_verifies_during_rotation():
    raw, headers = _delivery(secret=OLD_SECRET)
    gate = _gate(secrets=(SECRET, OLD_SECRET))
    verdict = gate.verify(raw_body=raw, headers=headers, received_at=NOW)
    assert verdict.accepted
    assert verdict.secret_generation == "previous_1"


def test_a_retired_secret_no_longer_verifies_once_rotation_completes():
    raw, headers = _delivery(secret=OLD_SECRET)
    verdict = _gate(secrets=(SECRET,)).verify(raw_body=raw, headers=headers, received_at=NOW)
    assert not verdict.accepted


# -- malformed input -------------------------------------------------------


@pytest.mark.parametrize("body", [b"", b"{", b"not json", b"[]", b"null", b"\xff\xfe"])
def test_a_signed_but_malformed_body_is_refused_without_crashing(body):
    """A correct signature over garbage is still garbage. It must not raise."""
    headers = {SIGNATURE_HEADER: sign_payload(body, SECRET), EVENT_ID_HEADER: "evt_bad"}
    verdict = _gate().verify(raw_body=body, headers=headers, received_at=NOW)
    assert not verdict.accepted


def test_passing_a_parsed_payload_instead_of_raw_bytes_is_a_caller_error():
    """Re-serialising changes key order and whitespace, so it must be refused loudly."""
    _, headers = _delivery()
    with pytest.raises(TypeError):
        _gate().verify(raw_body=PAYLOAD, headers=headers, received_at=NOW)  # type: ignore[arg-type]


def test_header_names_are_matched_case_insensitively():
    """Real gateways and proxies normalise header case unpredictably."""
    raw, headers = _delivery()
    shouted = {key.upper(): value for key, value in headers.items()}
    assert _gate().verify(raw_body=raw, headers=shouted, received_at=NOW).accepted


# -- evidence --------------------------------------------------------------


def test_every_refused_delivery_is_recorded_as_evidence():
    """A silent drop is indistinguishable from a bug. Rejections are receipts too."""
    raw, headers = _delivery()
    headers[SIGNATURE_HEADER] = "0" * 64
    gate = _gate()
    gate.verify(raw_body=raw, headers=headers, received_at=NOW)
    assert len(gate.rejections) == 1
    record = gate.rejections[0]
    assert record["reason_code"] == "SIGNATURE_MISMATCH"
    assert record["body_sha256"]


def test_a_refused_delivery_is_never_recorded_as_accepted():
    raw, headers = _delivery(event_id="evt_refused")
    headers[SIGNATURE_HEADER] = "0" * 64
    gate = _gate()
    gate.verify(raw_body=raw, headers=headers, received_at=NOW)
    assert "evt_refused" not in gate.accepted_event_ids


def test_a_gate_cannot_be_constructed_without_a_secret():
    with pytest.raises(ValueError):
        WebhookGate(secrets=())


# -- delivery order --------------------------------------------------------
#
# Razorpay states that webhook ordering is not guaranteed. For a recovery
# runtime that is not a nuisance, it is a correctness problem: acting on
# arrival order can retry a debit that already succeeded, or debit a mandate
# the customer has since cancelled. Both are the duplicate and unwanted
# charges this project exists to prevent.


def _ordered(name: str, *, created_at: datetime, event_id: str, subscription: str = "sub_test"):
    payload = {
        "event": name,
        "created_at": int(created_at.timestamp()),
        "payload": {
            "payment": {"entity": {"id": f"pay_{event_id}", "error_reason": "insufficient_funds"}},
            "subscription": {"entity": {"id": subscription, "status": "active"}},
        },
    }
    raw, headers = build_signed_delivery(payload, secret=SECRET, event_id=event_id)
    return {"raw_body": raw, "headers": headers}


def test_events_arriving_in_order_are_all_actionable():
    gate = _gate()
    first = gate.verify(**_ordered("subscription.pending", created_at=NOW, event_id="e1"), received_at=NOW)
    second = gate.verify(
        **_ordered("subscription.pending", created_at=NOW + timedelta(hours=1), event_id="e2"),
        received_at=NOW + timedelta(hours=1),
    )
    assert first.should_process and second.should_process


def test_a_failure_event_that_lost_a_race_to_a_newer_event_is_not_acted_on():
    """The expensive case: a stale `payment.failed` overtaking a settled cycle."""
    gate = _gate()
    gate.verify(
        **_ordered("subscription.charged", created_at=NOW + timedelta(hours=2), event_id="e_charged"),
        received_at=NOW + timedelta(hours=2),
    )
    verdict = gate.verify(
        **_ordered("payment.failed", created_at=NOW, event_id="e_failed"),
        received_at=NOW + timedelta(hours=3),
    )
    assert verdict.accepted, "the delivery is genuine"
    assert verdict.superseded and not verdict.should_process
    assert verdict.reason_code == "SUPERSEDED_BY_NEWER_EVENT"


def test_nothing_is_actionable_after_the_subscription_has_ended():
    """A cancelled mandate closes for good, whatever turns up afterwards."""
    gate = _gate()
    assert gate.verify(
        **_ordered("subscription.cancelled", created_at=NOW, event_id="e_cancel"), received_at=NOW
    ).should_process
    verdict = gate.verify(
        **_ordered("payment.failed", created_at=NOW + timedelta(hours=4), event_id="e_late"),
        received_at=NOW + timedelta(hours=4),
    )
    assert verdict.accepted
    assert verdict.superseded
    assert verdict.reason_code == "SUPERSEDED_BY_TERMINAL_EVENT"


def test_an_out_of_order_cancellation_still_closes_the_subscription():
    """A cancellation that lost a delivery race is still a cancellation.

    Order is taken from `created_at`, so a cancellation stamped earlier than
    an already-seen event is superseded as an *action* — but its terminal
    fact must still be recorded, or every later failure on that subscription
    stays actionable against a mandate the customer ended.
    """
    gate = _gate()
    assert gate.verify(
        **_ordered("payment.failed", created_at=NOW + timedelta(hours=1), event_id="e_newer_failure"),
        received_at=NOW + timedelta(hours=1),
    ).should_process
    late_cancel = gate.verify(
        **_ordered("subscription.cancelled", created_at=NOW, event_id="e_late_cancel"),
        received_at=NOW + timedelta(hours=1, minutes=5),
    )
    assert late_cancel.accepted and not late_cancel.should_process
    after = gate.verify(
        **_ordered("payment.failed", created_at=NOW + timedelta(hours=2), event_id="e_after_cancel"),
        received_at=NOW + timedelta(hours=2),
    )
    assert not after.should_process
    assert after.reason_code == "SUPERSEDED_BY_TERMINAL_EVENT"


@pytest.mark.parametrize("permanent", ["subscription.cancelled", "subscription.completed"])
def test_every_permanently_ended_event_closes_the_subscription_for_good(permanent):
    """Cancelled and completed are the only two Razorpay never reverses.

    No later event, including `subscription.resumed`, reopens either one —
    Razorpay's webhook payload reference documents no event that does.
    """
    gate = _gate()
    gate.verify(**_ordered(permanent, created_at=NOW, event_id=f"e_{permanent}"), received_at=NOW)
    later = gate.verify(
        **_ordered("payment.failed", created_at=NOW + timedelta(hours=1), event_id="e_after"),
        received_at=NOW + timedelta(hours=1),
    )
    assert not later.should_process
    assert later.reason_code == "SUPERSEDED_BY_TERMINAL_EVENT"
    # Even an (anomalous) resume does not reopen a permanently ended subscription.
    resumed = gate.verify(
        **_ordered("subscription.resumed", created_at=NOW + timedelta(hours=2), event_id="e_resume"),
        received_at=NOW + timedelta(hours=2),
    )
    assert not resumed.should_process


@pytest.mark.parametrize("blocking", ["subscription.paused", "subscription.halted"])
def test_paused_or_halted_blocks_action_without_ending_the_subscription(blocking):
    """Paused and halted are reversible: Razorpay's own payload reference

    documents `subscription.resumed` as the event that reverses both. A
    runtime that treated either as permanent would refuse forever to retry a
    subscription a customer merely paused for a month.
    """
    gate = _gate()
    gate.verify(**_ordered(blocking, created_at=NOW, event_id=f"e_{blocking}"), received_at=NOW)

    blocked = gate.verify(
        **_ordered("payment.failed", created_at=NOW + timedelta(hours=1), event_id="e_blocked"),
        received_at=NOW + timedelta(hours=1),
    )
    assert not blocked.should_process
    assert blocked.reason_code == "BLOCKED_SUBSCRIPTION_PAUSED_OR_HALTED"

    resumed = gate.verify(
        **_ordered("subscription.resumed", created_at=NOW + timedelta(hours=2), event_id="e_resumed"),
        received_at=NOW + timedelta(hours=2),
    )
    assert resumed.should_process

    after_resume = gate.verify(
        **_ordered("payment.failed", created_at=NOW + timedelta(hours=3), event_id="e_after_resume"),
        received_at=NOW + timedelta(hours=3),
    )
    assert after_resume.should_process


def test_permanently_ended_takes_priority_over_a_prior_pause_or_halt():
    """A cancellation after a pause must close the subscription for good, not

    leave it merely blocked-and-resumable.
    """
    gate = _gate()
    gate.verify(**_ordered("subscription.paused", created_at=NOW, event_id="e_pause"), received_at=NOW)
    gate.verify(
        **_ordered("subscription.cancelled", created_at=NOW + timedelta(hours=1), event_id="e_cancel"),
        received_at=NOW + timedelta(hours=1),
    )
    resumed = gate.verify(
        **_ordered("subscription.resumed", created_at=NOW + timedelta(hours=2), event_id="e_resume_after_cancel"),
        received_at=NOW + timedelta(hours=2),
    )
    assert not resumed.should_process
    assert resumed.reason_code == "SUPERSEDED_BY_TERMINAL_EVENT"


def test_ordering_state_is_kept_per_subscription_and_does_not_leak():
    """One customer's cancellation must not silence another's recovery."""
    gate = _gate()
    gate.verify(
        **_ordered("subscription.cancelled", created_at=NOW, event_id="e_a", subscription="sub_a"),
        received_at=NOW,
    )
    verdict = gate.verify(
        **_ordered(
            "payment.failed", created_at=NOW + timedelta(hours=1), event_id="e_b", subscription="sub_b"
        ),
        received_at=NOW + timedelta(hours=1),
    )
    assert verdict.should_process
    assert verdict.subscription_id == "sub_b"


def test_two_events_stamped_at_the_same_instant_are_both_actionable():
    """Equal timestamps are a tie, not an inversion. Refusing both would drop work."""
    gate = _gate()
    assert gate.verify(
        **_ordered("payment.failed", created_at=NOW, event_id="e_same_1"), received_at=NOW
    ).should_process
    assert gate.verify(
        **_ordered("payment.failed", created_at=NOW, event_id="e_same_2"), received_at=NOW
    ).should_process


def test_a_redelivery_is_reported_as_a_duplicate_rather_than_as_superseded():
    """Both mean 'do nothing', but the reason recorded must be the true one."""
    gate = _gate()
    delivery = _ordered("payment.failed", created_at=NOW, event_id="e_dup")
    gate.verify(**delivery, received_at=NOW)
    again = gate.verify(**delivery, received_at=NOW + timedelta(minutes=1))
    assert again.duplicate
    assert again.reason_code == "DUPLICATE_DELIVERY_IGNORED"


def test_an_envelope_without_a_subscription_is_never_treated_as_out_of_order():
    """Ordering is per subscription. With no identity there is nothing to order."""
    bare = {
        "event": "payment.failed",
        "created_at": int(NOW.timestamp()),
        "payload": {"payment": {"entity": {"id": "pay_bare"}}},
    }
    raw, headers = build_signed_delivery(bare, secret=SECRET, event_id="evt_no_sub")
    verdict = _gate().verify(raw_body=raw, headers=headers, received_at=NOW)
    assert verdict.should_process
    assert verdict.subscription_id is None
