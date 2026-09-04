"""MandateGuard Drop-In ASGI / FastAPI Middleware.

Integrate enterprise-grade AutoPay guardrails into any FastAPI or Starlette
application with 3 lines of code:

    from bailiff.middleware import MandateGuardMiddleware

    app = FastAPI()
    app.add_middleware(
        MandateGuardMiddleware,
        webhook_secret=os.environ["RAZORPAY_WEBHOOK_SECRET"],
        policy="B2",
    )

Every incoming webhook to the protected path is authenticated via constant-time
HMAC-SHA256, normalized into project taxonomy, evaluated against deterministic
guardrails, and enriched into request.state.mandateguard before route execution.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .webhook import WebhookGate, SIGNATURE_HEADER, EVENT_ID_HEADER
from .razorpay_adapter import normalize_razorpay_autopay_payload
from .policies import default_policy, run_policy_case
from .domain import RecoveryEvent


class MandateGuardMiddleware(BaseHTTPMiddleware):
    """Protects webhook endpoints against forged, stale, and illegal recurring debits."""

    def __init__(
        self,
        app,
        webhook_secret: str,
        webhook_path: str = "/webhook/razorpay",
        policy: str = "B2",
        fail_closed: bool = True,
    ):
        super().__init__(app)
        self.webhook_path = webhook_path
        self.policy_id = f"pid_{policy.lower().replace('.', '_')}"
        self.policy = default_policy(self.policy_id)
        self.fail_closed = fail_closed
        self.gate = WebhookGate(secrets=(webhook_secret,))

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path != self.webhook_path or request.method != "POST":
            return await call_next(request)

        raw_body = await request.body()
        headers = dict(request.headers)
        now = datetime.now(timezone.utc)

        # 1. Ingress HMAC constant-time verification
        verdict = self.gate.verify(raw_body=raw_body, headers=headers, received_at=now)
        if not verdict.accepted:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "WEBHOOK_AUTHENTICATION_FAILED",
                    "reason": verdict.reason_code,
                    "provider_calls": 0,
                    "protected": True,
                },
            )

        if not verdict.should_process:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "IGNORED_NON_ACTIONABLE",
                    "reason": verdict.reason_code,
                    "duplicate": verdict.duplicate,
                    "superseded": verdict.superseded,
                    "provider_calls": 0,
                },
            )

        # 2. Parse and normalize
        try:
            parsed = json.loads(raw_body.decode())
            event = normalize_razorpay_autopay_payload(parsed)
        except Exception as err:
            return JSONResponse(
                status_code=400,
                content={"error": "PAYLOAD_NORMALIZATION_FAILED", "detail": str(err)},
            )

        # 3. Guardrail evaluation
        policy_result = run_policy_case(arm=self.policy.arm, event=event)
        decision = policy_result.decision

        # Attach to request state for downstream handler
        request.state.mandateguard = {
            "verdict": verdict,
            "decision": decision.decision.value,
            "final_action": decision.final_action.value if decision.final_action else None,
            "reason_codes": list(decision.reason_codes),
            "audit_hash": policy_result.audit_events[-1].current_hash if policy_result.audit_events else None,
            "provider_calls_allowed": bool(policy_result.provider_result),
        }

        # 4. Fail-closed refusal enforcement
        if decision.decision.value in {"stop", "deny"}:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "REFUSED_BEFORE_PROVIDER_BOUNDARY",
                    "decision": decision.decision.value,
                    "reasons": list(decision.reason_codes),
                    "provider_calls": 0,
                    "audit_hash": request.state.mandateguard["audit_hash"],
                },
            )

        return await call_next(request)
