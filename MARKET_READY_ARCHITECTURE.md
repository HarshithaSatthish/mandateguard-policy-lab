# MandateGuard — Market-Ready Enterprise Architecture & Deployment Guide

This document outlines the production architecture, deployment topologies, security boundaries, and enterprise integration patterns for deploying **MandateGuard** as a real-world subscription recovery middleware.

---

## 1. Production Architecture Overview

```
                      ┌─────────────────────────────────────────┐
                      │            Razorpay Platform            │
                      └───────────────────┬─────────────────────┘
                                          │ Webhook Delivery
                                          │ (X-Razorpay-Signature)
                                          ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ MANDATEGUARD ENTERPRISE GATEWAY                                                        │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 1. INGRESS AUTHENTICATION & DEDUPLICATION (FastAPI / WebhookGate)                │  │
│  │    • Raw-byte HMAC-SHA256 signature verification (constant-time compare)          │  │
│  │    • Secret rotation support (primary & secondary keys)                          │  │
│  │    • Event ID & payload hash deduplication via Redis cache                       │  │
│  │    • Subscription sequence tracking (stale failure dropping)                      │  │
│  └──────────────────────────────────┬───────────────────────────────────────────────┘  │
│                                     │ Validated Event Envelope                         │
│                                     ▼                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 2. TAXONOMY NORMALIZER                                                           │  │
│  │    • Maps provider/bank error codes into canonical project taxonomy               │  │
│  │    • Enforces structured failure reasons                                         │  │
│  └──────────────────┬───────────────────────────────────────────────┬───────────────┘  │
│                     │ Deterministic Path                            │ Ambiguous Case   │
│                     ▼                                               ▼                  │
│  ┌─────────────────────────────────────────┐    ┌───────────────────────────────────┐  │
│  │ 3. POLICY & GUARDRAIL ENGINE            │    │ 4. BOUNDED AI INTERPRETER         │  │
│  │    • Active mandate check               │    │    • Diagnostic analysis only     │  │
│  │    • Customer opt-out / pause check     │◄───┤    • Confidence scoring           │  │
│  │    • 24h pre-debit notice validation    │    │    • Zero payment authority       │  │
│  │    • Non-peak window execution          │    │    • Low confidence -> Escalate   │  │
│  │    • Maximum attempt cap enforcement    │    └───────────────────────────────────┘  │
│  └──────────────────┬──────────────────────┘                                           │
│                     │ Decision: ALLOW / STOP / DENY / ESCALATE                         │
│                     ▼                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 5. RECOVERYTRUTH WRITE FENCE                                                     │  │
│  │    • Pre-write reread: query current financial truth from Razorpay API            │  │
│  │    • In-flight lock: blocks concurrent recovery on pending/authorized orders      │  │
│  │    • Already-paid safeguard: aborts execution with SAFE_BLOCK_ALREADY_PAID (0->0) │  │
│  └──────────────────┬───────────────────────────────────────────────┬───────────────┘  │
│                     │ Allowed & Pre-write Verified                  │ Refusal / Stop   │
│                     ▼                                               ▼                  │
│  ┌─────────────────────────────────────────┐    ┌───────────────────────────────────┐  │
│  │ 6. PROVIDER ADAPTER EXECUTION           │    │ 7. REFUSAL LOGGING (Zero Provider)│  │
│  │    • Idempotent Payment Link generation │    │    • Tamper-evident receipt hash  │  │
│  │    • Captures payment confirmation proof│    │    • No provider API touched      │  │
│  └──────────────────┬──────────────────────┘    └───────────────────┬───────────────┘  │
│                     │                                               │                  │
│                     └───────────────────────┬───────────────────────┘                  │
│                                             ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 8. CRYPTOGRAPHIC AUDIT LINEAGE                                                   │  │
│  │    • SHA-256 hash chaining linking Event -> Decision -> Pre-write -> Postcondition│  │
│  │    • Persisted to immutable PostgreSQL / Object Storage audit ledger             │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Deployment Models

### Option A: Merchant Microservice (Sidecar Gateway)
For merchants processing hundreds of thousands of recurring debits monthly:
- Deploy MandateGuard as a containerized FastAPI gateway behind an API Gateway (AWS API Gateway, Cloudflare, or NGINX).
- Webhook URL in Razorpay Dashboard points to: `https://recovery.merchant.com/api/v1/webhook/razorpay`.
- MandateGuard authenticates, evaluates policies, verifies write fences, and returns `200 OK` to Razorpay while queuing actions.

### Option B: Razorpay Platform Integration (Native App / Marketplace Extension)
- Integrated directly into Razorpay's App Store / Subscription Settings as an enterprise guardrail plugin.
- Merchants configure their policy envelope directly from the Razorpay dashboard, while MandateGuard acts as the safety gatekeeper before any retry or recovery link is triggered.

---

## 3. Production Technology Stack

| Layer | Recommended Technology | MandateGuard Implementation |
|---|---|---|
| **Runtime** | Python 3.11+ / Docker | `Dockerfile`, `pyproject.toml` |
| **API Server** | FastAPI + Uvicorn (async) | `bailiff/api.py` |
| **Idempotency & Deduplication** | Redis Cluster | `WebhookGate` cache (event ID, body hash, delivery window) |
| **Audit Storage** | PostgreSQL + S3 (WORM bucket) | `AuditChain` SHA-256 hash-chained receipts |
| **AI Diagnosis (Ambiguous codes)** | Self-hosted LLM / OpenAI API | `RealBoundedInterpreter` (read-only, diagnostic) |
| **Evidence Dashboard** | Streamlit | `app.py` & `provider_proof_app.py` |
| **Containerization** | Docker / Kubernetes (Helm chart) | `Dockerfile`, `docker-compose.yml` |

---

## 4. Environment Configuration (`.env`)

```bash
# Server & Environment
MANDATEGUARD_ENV=production
PORT=8000
HOST=0.0.0.0
LOG_LEVEL=info

# Razorpay Webhook Ingress (Required)
RAZORPAY_WEBHOOK_SECRET=whsec_prod_xxxxxxxxxxxx
RAZORPAY_WEBHOOK_OLD_SECRET=whsec_prev_xxxxxxxxxxxx   # Optional for smooth secret rotation
RAZORPAY_MAX_REPLAY_WINDOW_SEC=300

# Razorpay API Credentials (Test Mode for simulation, Live for fallback links)
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx

# Bounded Interpreter (Optional - if omitted, runs in deterministic offline mode)
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxx
INTERPRETER_MODEL=gpt-4o-mini
INTERPRETER_CONFIDENCE_THRESHOLD=0.85

# State & Audit Backend
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=postgresql://user:password@localhost:5432/mandateguard
```

---

## 5. Security Posture & RBI Compliance Safeguards

1. **Zero Raw Credentials in State**:
   - Webhook secrets and API keys are read from environment variables; they are never persisted to databases or written into audit receipts.
2. **Timing-Attack Proof**:
   - Signatures are verified strictly with `hmac.compare_digest` to prevent byte-by-byte timing analysis.
3. **RBI UPI AutoPay Rules Baked In**:
   - **24-Hour Pre-Debit Notice**: Retries without a verified pre-debit notice are refused.
   - **Customer Revocation Priority**: If a customer pauses or cancels a subscription in the merchant app or banking app, all subsequent failure retries are instantly blocked (`MANDATE_NOT_ACTIVE`).
   - **Non-Peak Processing**: High-volume retries outside banking settlement non-peak windows are denied to avoid systemic grid stress.
4. **Idempotency & Race-Condition Defense**:
   - Redis distributed locking prevents concurrent workers from processing duplicate events for the same subscription or order simultaneously.
   - Pre-write fence performs an immediate read of current provider truth before emitting any write call.

---

## 6. Docker Deployment

### Single-Command Production Run:
```bash
docker build -t mandateguard:latest .
docker run -d \
  -p 8000:8000 \
  -p 8501:8501 \
  --env-file .env \
  --name mandateguard-prod \
  mandateguard:latest
```

The container exposes:
- Port `8000`: FastAPI Webhook Ingress & Verification REST API
- Port `8501`: Streamlit Evidence & Policy Comparison UI
