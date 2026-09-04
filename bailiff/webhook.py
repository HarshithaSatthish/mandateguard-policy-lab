"""Authenticate the Razorpay webhook before any policy is allowed to read it.

This module closes a hole in the project's own argument. Everything downstream
proves that an *action* was authorised: the authority envelope cannot widen, a
denied retry never reaches the provider, every decision carries a receipt. None
of that is worth anything if the *input* is unauthenticated, because an attacker
who can post a payload to the endpoint can manufacture a failure event and drive
the recovery agent with it. Authority control that begins after the event has
been trusted begins one step too late.

So the boundary is here, before the adapter, before the policy engine, and
before anything is written to a case. A payload that fails verification is not
normalised, not diagnosed, and not scored. It is recorded as a rejected
delivery and dropped.

The contract implemented is Razorpay's published one:

- the signature arrives in the ``X-Razorpay-Signature`` header;
- it is ``HMAC-SHA256`` over the **raw** request body, keyed by the webhook
  secret;
- the body must be hashed exactly as received, never re-serialised;
- ``x-razorpay-event-id`` is unique per event and is how a redelivery is
  recognised;
- during a secret rotation, a retried delivery may still be signed with the
  previous secret, so more than one secret may be live at once.

See https://razorpay.com/docs/webhooks/validate-test/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hmac
import json
from hashlib import sha256
from typing import Iterable, Mapping

SIGNATURE_HEADER = "X-Razorpay-Signature"
EVENT_ID_HEADER = "x-razorpay-event-id"

# Events after which a subscription is permanently done: nothing arriving
# later, of any kind, reopens it. Razorpay's own webhook payload reference
# lists no event that reverses `cancelled` or `completed`.
PERMANENTLY_ENDED_EVENTS = frozenset({
    "subscription.cancelled",
    "subscription.completed",
})

# Events that stop automated recovery on a subscription without ending it.
# Razorpay's webhook payload reference documents `subscription.resumed` as a
# distinct event that reverses both of these, so neither is permanent — a
# runtime that treated `halted` or `paused` as terminal would refuse to ever
# retry a subscription the merchant or customer had simply paused for a
# month and then resumed.
RETRY_BLOCKING_EVENTS = frozenset({
    "subscription.halted",
    "subscription.paused",
})

RESUME_EVENT = "subscription.resumed"

# Kept for callers that only need "no further automated action right now",
# without the permanent/reversible distinction the two sets above carry.
TERMINAL_EVENTS = PERMANENTLY_ENDED_EVENTS | RETRY_BLOCKING_EVENTS


def _subscription_id(parsed: Mapping[str, object]) -> str | None:
    """Pull the subscription identity out of a Razorpay webhook envelope."""
    payload = parsed.get("payload")
    if not isinstance(payload, Mapping):
        return None
    subscription = payload.get("subscription")
    if isinstance(subscription, Mapping):
        entity = subscription.get("entity")
        if isinstance(entity, Mapping) and entity.get("id"):
            return str(entity["id"])
    payment = payload.get("payment")
    if isinstance(payment, Mapping):
        entity = payment.get("entity")
        if isinstance(entity, Mapping):
            notes = entity.get("notes")
            if isinstance(notes, Mapping) and notes.get("subscription_id"):
                return str(notes["subscription_id"])
    return None

# A redelivery of a genuine event can lag. A delivery far outside this window is
# treated as a replay rather than as ordinary provider retry behaviour.
DEFAULT_MAX_AGE = timedelta(hours=24)


class WebhookRejected(ValueError):
    """Raised when a delivery must not be processed."""


@dataclass(frozen=True)
class WebhookVerdict:
    """The outcome of authenticating one delivery."""

    accepted: bool
    reason_code: str
    event_id: str | None = None
    event_name: str | None = None
    duplicate: bool = False
    secret_generation: str | None = None
    body_sha256: str | None = None
    subscription_id: str | None = None
    superseded: bool = False

    @property
    def should_process(self) -> bool:
        """Authentic is not the same as actionable.

        Three separate things can be true of a delivery that verified perfectly:
        it is a redelivery of something already handled, it is an older event
        that lost a race with a newer one, or the subscription it concerns has
        already ended. In each case the payload is genuine and the right
        response is to record it and do nothing.
        """
        return self.accepted and not self.duplicate and not self.superseded


@dataclass
class WebhookGate:
    """Verify, deduplicate and record Razorpay webhook deliveries.

    ``secrets`` is ordered: the current secret first, then any previous secrets
    still inside their rotation window. Every secret is tried so that a delivery
    signed before a rotation still verifies, and the generation that matched is
    recorded so an operator can see when an old secret is still in use.
    """

    secrets: tuple[str, ...]
    max_age: timedelta = DEFAULT_MAX_AGE
    _seen_event_ids: set[str] = field(default_factory=set)
    # The HMAC covers only the body, so the event-id header is not
    # authenticated: a captured delivery replayed under a fresh header id is
    # the same signed bytes. Dedup therefore also keys on the body hash.
    _seen_body_hashes: set[str] = field(default_factory=set)
    _rejections: list[dict[str, object]] = field(default_factory=list)
    # Highest `created_at` observed per subscription, the subscriptions known
    # to have permanently ended, and the subscriptions currently blocked by a
    # pause or halt (reversible — removed again on `subscription.resumed`).
    # All three exist because Razorpay does not guarantee webhook delivery
    # order and because paused/halted are not the same thing as ended.
    _subscription_clock: dict[str, int] = field(default_factory=dict)
    _ended_subscriptions: set[str] = field(default_factory=set)
    _blocked_subscriptions: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.secrets:
            raise ValueError("at least one webhook secret is required")
        if any(not isinstance(secret, str) or not secret for secret in self.secrets):
            raise ValueError("webhook secrets must be non empty strings")

    # -- signature ---------------------------------------------------------

    @staticmethod
    def expected_signature(raw_body: bytes, secret: str) -> str:
        return hmac.new(secret.encode("utf-8"), raw_body, sha256).hexdigest()

    def _matching_generation(self, raw_body: bytes, signature: str) -> str | None:
        """Return which secret verified the body, in constant time per candidate.

        ``hmac.compare_digest`` is used rather than ``==`` so that a failed
        comparison does not leak, through its timing, how many leading
        characters of the signature were correct.
        """
        try:
            # A hex digest is always ASCII. `hmac.compare_digest` raises
            # TypeError on a non-ASCII str argument, and the header is
            # attacker controlled, so a non-ASCII signature must be an
            # ordinary mismatch rather than an unhandled exception.
            signature_bytes = signature.encode("ascii")
        except UnicodeEncodeError:
            return None
        for index, secret in enumerate(self.secrets):
            candidate = self.expected_signature(raw_body, secret).encode("ascii")
            if hmac.compare_digest(candidate, signature_bytes):
                return "current" if index == 0 else f"previous_{index}"
        return None

    # -- verification ------------------------------------------------------

    def verify(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
        received_at: datetime | None = None,
    ) -> WebhookVerdict:
        """Authenticate one delivery. Never raises for an untrusted payload.

        A hostile caller controls the body and the headers, so every failure
        path returns a verdict rather than an exception: an endpoint that
        crashes on a malformed delivery is itself a denial of service surface.
        The one exception is a caller error, passing something other than raw
        bytes, which is a bug in this repository rather than an attack.
        """
        if not isinstance(raw_body, (bytes, bytearray)):
            raise TypeError(
                "raw_body must be the exact bytes received; re-serialising a parsed "
                "payload changes key order and whitespace and will not verify"
            )
        raw_body = bytes(raw_body)
        received_at = received_at or datetime.now(timezone.utc)

        lookup = {str(key).lower(): value for key, value in headers.items()}
        signature = lookup.get(SIGNATURE_HEADER.lower())
        event_id = lookup.get(EVENT_ID_HEADER)

        if not signature:
            return self._reject("MISSING_SIGNATURE_HEADER", event_id, raw_body)

        generation = self._matching_generation(raw_body, str(signature))
        if generation is None:
            return self._reject("SIGNATURE_MISMATCH", event_id, raw_body)

        # Only now is the body trusted enough to parse.
        try:
            parsed = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._reject("SIGNED_BODY_IS_NOT_JSON", event_id, raw_body)
        if not isinstance(parsed, Mapping):
            return self._reject("SIGNED_BODY_IS_NOT_AN_OBJECT", event_id, raw_body)

        if not event_id:
            return self._reject("MISSING_EVENT_ID_HEADER", None, raw_body)

        stale = self._staleness_reason(parsed, received_at)
        if stale is not None:
            return self._reject(stale, event_id, raw_body)

        body_hash = sha256(raw_body).hexdigest()
        duplicate = event_id in self._seen_event_ids or body_hash in self._seen_body_hashes
        self._seen_event_ids.add(event_id)
        self._seen_body_hashes.add(body_hash)

        event_name = str(parsed.get("event")) if parsed.get("event") else None
        subscription_id = _subscription_id(parsed)
        superseded_reason = None
        if not duplicate:
            superseded_reason = self._ordering_reason(parsed, subscription_id, event_name)

        reason_code = "VERIFIED"
        if duplicate:
            reason_code = "DUPLICATE_DELIVERY_IGNORED"
        elif superseded_reason is not None:
            reason_code = superseded_reason

        return WebhookVerdict(
            accepted=True,
            reason_code=reason_code,
            event_id=event_id,
            event_name=event_name,
            duplicate=duplicate,
            secret_generation=generation,
            body_sha256=body_hash,
            subscription_id=subscription_id,
            superseded=superseded_reason is not None,
        )

    def _ordering_reason(
        self,
        parsed: Mapping[str, object],
        subscription_id: str | None,
        event_name: str | None,
    ) -> str | None:
        """Decide whether a genuine delivery has been overtaken by another.

        Razorpay states that webhook ordering is not guaranteed, so arrival
        order cannot be trusted as event order. For a recovery runtime the
        consequence is specific and expensive: a `payment.failed` for a cycle
        can arrive *after* the `subscription.charged` that already settled it,
        or after the subscription was cancelled outright. Acting on arrival
        order would retry a debit that already succeeded, or debit a mandate
        the customer has since cancelled — which is precisely the class of
        duplicate and unwanted charge this project exists to prevent.

        So order is taken from the event's own `created_at`, not from when it
        turned up. A subscription that has permanently ended closes for good.
        A subscription that is only paused or halted blocks further
        automated action without closing — `subscription.resumed` lifts the
        block, and nothing else does.
        """
        if subscription_id is None:
            return None

        if subscription_id in self._ended_subscriptions and event_name not in PERMANENTLY_ENDED_EVENTS:
            return "SUPERSEDED_BY_TERMINAL_EVENT"

        if (
            subscription_id in self._blocked_subscriptions
            and event_name != RESUME_EVENT
            and event_name not in PERMANENTLY_ENDED_EVENTS
        ):
            return "BLOCKED_SUBSCRIPTION_PAUSED_OR_HALTED"

        created_at = parsed.get("created_at")
        stamp: int | None
        try:
            stamp = int(created_at) if created_at is not None else None
        except (TypeError, ValueError):
            stamp = None

        superseded = False
        if stamp is not None:
            latest = self._subscription_clock.get(subscription_id)
            if latest is not None and stamp < latest:
                superseded = True
            if not superseded:
                self._subscription_clock[subscription_id] = stamp

        # A permanent ending closes the subscription no matter where it lands
        # in the delivery order: an out-of-order cancellation is still a
        # cancellation, and nothing that arrives later may reopen it. The
        # reversible pause/resume pair, by contrast, stays strictly ordered —
        # applying a superseded pause or resume would let an older event
        # overrule a newer one.
        if event_name in PERMANENTLY_ENDED_EVENTS:
            self._ended_subscriptions.add(subscription_id)
        if superseded:
            return "SUPERSEDED_BY_NEWER_EVENT"
        if event_name in RETRY_BLOCKING_EVENTS:
            self._blocked_subscriptions.add(subscription_id)
        elif event_name == RESUME_EVENT:
            self._blocked_subscriptions.discard(subscription_id)
        return None

    def _staleness_reason(self, parsed: Mapping[str, object], received_at: datetime) -> str | None:
        created_at = parsed.get("created_at")
        if created_at is None:
            return "MISSING_CREATED_AT"
        try:
            created = datetime.fromtimestamp(int(created_at), tz=timezone.utc)
        except (OverflowError, OSError, ValueError, TypeError):
            return "UNREADABLE_CREATED_AT"
        if created - received_at > timedelta(minutes=5):
            return "CREATED_IN_THE_FUTURE"
        if received_at - created > self.max_age:
            return "DELIVERY_OUTSIDE_REPLAY_WINDOW"
        return None

    def _reject(self, reason_code: str, event_id: str | None, raw_body: bytes) -> WebhookVerdict:
        """Record a refused delivery. A rejection is evidence, not silence."""
        self._rejections.append(
            {
                "reason_code": reason_code,
                "event_id": event_id,
                "body_sha256": sha256(raw_body).hexdigest(),
                "body_bytes": len(raw_body),
            }
        )
        return WebhookVerdict(accepted=False, reason_code=reason_code, event_id=event_id)

    # -- evidence ----------------------------------------------------------

    @property
    def rejections(self) -> tuple[dict[str, object], ...]:
        return tuple(self._rejections)

    @property
    def accepted_event_ids(self) -> frozenset[str]:
        return frozenset(self._seen_event_ids)


def sign_payload(raw_body: bytes, secret: str) -> str:
    """Produce a valid signature. For fixtures and tests only, never for verification."""
    return WebhookGate.expected_signature(raw_body, secret)


def build_signed_delivery(
    payload: Mapping[str, object],
    *,
    secret: str,
    event_id: str,
) -> tuple[bytes, dict[str, str]]:
    """Serialise a payload once and sign exactly those bytes.

    The body is serialised a single time and both signed and returned, because
    signing one serialisation and transmitting another is the most common way
    this verification is broken in practice.
    """
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return raw, {
        SIGNATURE_HEADER: sign_payload(raw, secret),
        EVENT_ID_HEADER: event_id,
    }
