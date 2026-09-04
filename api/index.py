"""Vercel Serverless entrypoint for MandateGuard Policy Lab.

Exposes REST endpoints for live webhook verification, policy evaluation,
and cryptographic evidence inspection.
"""

from __future__ import annotations

import json
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from bailiff.core import (
    WebhookEvent,
    PolicyContext,
    evaluate_decision,
    verify_webhook_signature,
    compute_canonical_hash,
)
from bailiff.middleware import MandateGuardMiddleware

app = FastAPI(
    title="MandateGuard Policy Lab API",
    description="Deterministic Auto-Debit Recovery with Zero Regulatory Breach",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ROOT = Path(__file__).resolve().parent.parent


class WebhookVerificationRequest(BaseModel):
    payload: dict = Field(..., description="Raw or parsed webhook payload")
    signature: str = Field(..., description="X-Razorpay-Signature header value")
    secret: str = Field(..., description="Webhook secret configured in Razorpay dashboard")


class PolicyEvaluationRequest(BaseModel):
    merchant_id: str
    mandate_id: str
    amount_inr: float
    attempt_count: int
    has_pre_debit_notification: bool = True
    within_idempotency_window: bool = True
    policy_arm: str = "B1.5"


@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "service": "mandateguard-policy-lab",
        "version": "1.0.0",
        "live_mode_isolated": True,
        "policy_arm_recommended": "B1.5",
    }


@app.post("/api/verify-webhook")
def verify_webhook(req: WebhookVerificationRequest):
    raw_bytes = json.dumps(req.payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    is_valid = verify_webhook_signature(raw_bytes, req.signature, req.secret)
    canonical_hash = compute_canonical_hash(raw_bytes)
    return {
        "valid": is_valid,
        "canonical_sha256": canonical_hash,
        "length_bytes": len(raw_bytes),
    }


@app.post("/api/simulate-policy")
def simulate_policy(req: PolicyEvaluationRequest):
    # Guardrail rules
    if req.policy_arm in ("B1", "B1.5") and not req.has_pre_debit_notification:
        return {
            "decision": "QUARANTINE_FOR_REVIEW",
            "reason": "RBI_MANDATE_PRE_DEBIT_NOTIFICATION_MISSING",
            "penalty_avoidance_inr": 500000.0,
            "can_retry_auto_debit": False,
        }

    if req.attempt_count >= 3:
        return {
            "decision": "DROP_FRAUD",
            "reason": "RETRY_CAP_EXCEEDED",
            "penalty_avoidance_inr": 100000.0,
            "can_retry_auto_debit": False,
        }

    return {
        "decision": "PERMIT_RETRY",
        "reason": "COMPLIANT_WITHIN_GUARDRAIL_BOUNDS",
        "policy_arm": req.policy_arm,
        "can_retry_auto_debit": True,
    }


@app.get("/api/manifest")
def get_manifest():
    manifest_path = ROOT / "outputs" / "manifest.json"
    if manifest_path.is_file():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"status": "manifest_not_found"}
