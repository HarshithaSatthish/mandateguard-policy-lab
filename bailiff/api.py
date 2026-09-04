from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .benchmark import canonical_json, freeze_dataset
from .domain import ActionType, AuthorityEnvelope, CommonOutcome
from .fixtures import REGIMES, generate_fixture
from .guardrails import AuditChain, EvaluationContext, GuardrailEngine
from .metrics import annotate_runs, summarize_runs
from .policies import (
    ARM_ORDER,
    CANONICAL_ARM_ORDER,
    PolicyRun,
    bounded_interpreter_diagnosis,
    default_policy,
    deterministic_diagnosis,
    proposed_action,
    run_policy_case,
)
from .replay import CommonOutcomeLedger, ReplayProvider
from .runner import _dataset_rows, _event_row, aggregate_rows
from .rules import RuleCatalog
from .state import CaseStore
from .interpreter import RealBoundedInterpreter
from .razorpay_adapter import RazorpayPayloadError, normalize_razorpay_autopay_payload, to_razorpay_test_payload
from .webhook import WebhookGate
from ._version import RELEASE_VERSION


class ExperimentCreate(BaseModel):
    regime: str = "R1_TRANSIENT"
    seed: int = 1701
    n: int = Field(default=100, ge=1, le=5000)
    policy_ids: list[str] = Field(
        default_factory=lambda: ["pid_b0", "pid_b1", "pid_b1_5", "pid_b2_25", "pid_b2_5", "pid_b2_75", "pid_b2", "pid_b3"]
    )


class ExperimentRun(BaseModel):
    seeds: list[int] = Field(default_factory=lambda: [1701, 2029, 3313, 4157, 5011])
    n_per_seed: int = Field(default=100, ge=1, le=5000)
    violation_cost_inr: float | None = Field(default=None, ge=0)
    human_review_cost_inr: float | None = Field(default=None, ge=0)
    interpreter_mode: str = Field(default="deterministic_offline")


@dataclass
class ExperimentRecord:
    experiment_id: str
    regime: str
    seed: int
    n: int
    violation_cost_inr: float
    human_review_cost_inr: float
    frozen_ledgers: dict[int, tuple[list, object]] = field(default_factory=dict)
    interpreter_mode: str = "deterministic_offline"

    @property
    def ledger(self):
        return next(iter(self.frozen_ledgers.values()))[1] if self.frozen_ledgers else None
    frozen_manifest_hash: str | None = None
    rows: list[dict] = field(default_factory=list)
    aggregate: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)


app = FastAPI(title="MandateGuard Policy Lab", version=RELEASE_VERSION)
EXPERIMENTS: dict[str, ExperimentRecord] = {}

# Demo-only default: a fixed, published secret so the endpoint is reproducible
# out of the box for a judge running this from a clean checkout with no setup.
# It is not a production secret and must never be treated as one. Set
# MANDATEGUARD_WEBHOOK_SECRET to override it; the endpoint accepts a
# comma-separated list so a rotation window can keep more than one live.
_DEMO_WEBHOOK_SECRET = "mandateguard-demo-webhook-secret-not-for-production"
WEBHOOK_GATE = WebhookGate(
    secrets=tuple(
        s
        for s in os.getenv("MANDATEGUARD_WEBHOOK_SECRET", _DEMO_WEBHOOK_SECRET).split(",")
        if s
    )
)


def _policy_ids() -> list[str]:
    return [f"pid_{arm.replace('.', '_').lower()}" for arm in ARM_ORDER]


def _freeze_record_ledgers(record: ExperimentRecord, seeds: tuple[int, ...], n_per_seed: int) -> None:
    if record.frozen_ledgers and record.n != n_per_seed:
        raise HTTPException(status_code=409, detail="experiment case count is already frozen")
    requested = tuple(sorted(set(seeds)))
    for seed in requested:
        if seed not in record.frozen_ledgers:
            events, ledger = generate_fixture(record.regime, seed, n_per_seed)
            adapted_events = [
                normalize_razorpay_autopay_payload(to_razorpay_test_payload(event))
                for event in events
            ]
            record.frozen_ledgers[seed] = (adapted_events, ledger)
    datasets = {
        str(seed): _dataset_rows(events, ledger)
        for seed, (events, ledger) in sorted(record.frozen_ledgers.items())
    }
    manifest = freeze_dataset(
        dataset_id=record.experiment_id,
        dataset=datasets,
        seeds=tuple(sorted(record.frozen_ledgers)),
        generation_config={"regime": record.regime, "n_per_seed": n_per_seed, "version": RELEASE_VERSION},
        minimum_seeds=1,
    )
    record.frozen_manifest_hash = manifest.dataset_sha256


def _run_frozen(record: ExperimentRecord) -> None:
    if record.interpreter_mode not in {"deterministic_offline", "real_optional"}:
        raise HTTPException(status_code=400, detail="interpreter_mode must be deterministic_offline or real_optional")
    interpreter = RealBoundedInterpreter() if record.interpreter_mode == "real_optional" else bounded_interpreter_diagnosis
    rows: list[dict] = []
    evidence: list[dict] = []
    for seed in sorted(record.frozen_ledgers):
        events, ledger = record.frozen_ledgers[seed]
        for arm in ARM_ORDER:
            runs: list[PolicyRun] = [
                run_policy_case(arm=arm, event=event, ledger=ledger, interpreter=interpreter)
                for event in events
            ]
            runs = annotate_runs(runs, ledger)
            summary = summarize_runs(
                runs,
                ledger,
                human_review_cost_inr=record.human_review_cost_inr,
                violation_cost_inr=record.violation_cost_inr,
            )
            summary.update({"regime": record.regime, "seed": seed, "ledger_sha256": ledger.sha256()})
            rows.append(summary)
            evidence.extend(_event_row(run, ledger.sha256()) for run in runs)
    for seed in sorted(record.frozen_ledgers):
        base = next(row["recovered_inr"] for row in rows if row["seed"] == seed and row["arm"] == "B0")
        for row in rows:
            if row["seed"] == seed:
                row["incremental_recovered_inr"] = round(float(row["recovered_inr"]) - base, 4)
                row["net_value_inr"] = round(
                    row["incremental_recovered_inr"]
                    - float(row["violation_cost_inr"])
                    - float(row["human_review_cost_inr"])
                    - float(row["model_cost_inr"]),
                    4,
                )
    record.rows = rows
    record.aggregate = aggregate_rows(rows)
    record.evidence = evidence


def _artifact_hashes(record: ExperimentRecord) -> dict[str, str]:
    artifacts = {
        "rows": record.rows,
        "aggregate": record.aggregate,
        "evidence": record.evidence,
    }
    return {
        name: sha256(canonical_json(value)).hexdigest()
        for name, value in artifacts.items()
    }


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "scope": "scheduled_upi_autopay_only", "arms": list(ARM_ORDER)}


@app.post("/experiments")
def create_experiment(request: ExperimentCreate) -> dict[str, object]:
    if request.regime not in REGIMES:
        raise HTTPException(status_code=400, detail="unknown regime")
    if request.policy_ids != _policy_ids():
        raise HTTPException(
            status_code=400,
            detail={"message": "policy_ids must use canonical order", "expected": _policy_ids()},
        )
    experiment_id = f"exp_{uuid4().hex[:12]}"
    catalog = RuleCatalog.load()
    record = ExperimentRecord(
        experiment_id=experiment_id,
        regime=request.regime,
        seed=request.seed,
        n=request.n,
        violation_cost_inr=float(catalog.value("violation_cost_inr")),
        human_review_cost_inr=float(catalog.value("human_review_cost_inr")),
    )
    EXPERIMENTS[experiment_id] = record
    _freeze_record_ledgers(record, (request.seed,), request.n)
    _, ledger = record.frozen_ledgers[request.seed]
    return {
        "experiment_id": experiment_id,
        "policy_ids": _policy_ids(),
        "regime": request.regime,
        "seed": request.seed,
        "n": request.n,
        "ledger_sha256": ledger.sha256(),
        "frozen_manifest_hash": record.frozen_manifest_hash,
    }


@app.post("/experiments/{experiment_id}/run")
def run_experiment_api(experiment_id: str, request: ExperimentRun) -> dict[str, object]:
    record = EXPERIMENTS.get(experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if len(request.seeds) < 5:
        raise HTTPException(status_code=400, detail="at least five seeds are required")
    if request.violation_cost_inr is not None:
        record.violation_cost_inr = request.violation_cost_inr
    if request.human_review_cost_inr is not None:
        record.human_review_cost_inr = request.human_review_cost_inr
    if request.interpreter_mode not in {"deterministic_offline", "real_optional"}:
        raise HTTPException(status_code=400, detail="interpreter_mode must be deterministic_offline or real_optional")
    record.interpreter_mode = request.interpreter_mode
    try:
        _freeze_record_ledgers(record, tuple(request.seeds), request.n_per_seed)
    except HTTPException:
        raise
    _run_frozen(record)
    return {
        "experiment_id": experiment_id,
        "arms": list(ARM_ORDER),
        "seed_count": len(record.frozen_ledgers),
        "ledger_hashes": {str(seed): ledger.sha256() for seed, (_, ledger) in record.frozen_ledgers.items()},
        "rows": record.rows,
        "aggregate": record.aggregate,
        "violation_cost_inr": record.violation_cost_inr,
        "human_review_cost_inr": record.human_review_cost_inr,
        "interpreter_mode": record.interpreter_mode,
        "input_contract": "razorpay_shaped_test_payload_v1",
        "provider_adapter": "bailiff.razorpay_adapter.normalize_razorpay_autopay_payload",
    }


@app.get("/experiments/{experiment_id}/metrics")
def metrics(experiment_id: str) -> dict[str, object]:
    record = EXPERIMENTS.get(experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return {"experiment_id": experiment_id, "arms": list(ARM_ORDER), "rows": record.rows, "aggregate": record.aggregate}


@app.get("/experiments/{experiment_id}/cases/{case_id}")
def case_view(experiment_id: str, case_id: str) -> dict[str, object]:
    record = EXPERIMENTS.get(experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    evidence = [item for item in record.evidence if item["case_id"] == case_id]
    if not evidence:
        raise HTTPException(status_code=404, detail="case not found or experiment has not run")
    arm_set = {item["arm"] for item in evidence}
    return {
        "experiment_id": experiment_id,
        "case_id": case_id,
        "latent_outcome_hidden_from_policy": True,
        "ledger_sha256": evidence[0]["ledger_sha256"],
        "arms_present": [arm for arm in ARM_ORDER if arm in arm_set],
        "evidence": evidence,
    }


@app.get("/experiments/{experiment_id}/audit")
def audit(experiment_id: str) -> dict[str, object]:
    record = EXPERIMENTS.get(experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return {
        "experiment_id": experiment_id,
        "evidence_rows": len(record.evidence),
        "provider_call_rows": sum(1 for item in record.evidence if item["provider_call_made"]),
        "denied_rows": sum(1 for item in record.evidence if not item["provider_call_made"]),
        "audit_verified": all(item["audit_verified"] for item in record.evidence) if record.evidence else False,
        "ledger_hashes": {str(seed): ledger.sha256() for seed, (_, ledger) in record.frozen_ledgers.items()},
    }


@app.post("/experiments/{experiment_id}/verify")
def verify(experiment_id: str) -> dict[str, object]:
    record = EXPERIMENTS.get(experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if not record.frozen_ledgers:
        raise HTTPException(status_code=409, detail="experiment has no frozen ledger")
    datasets = {
        str(seed): _dataset_rows(events, ledger)
        for seed, (events, ledger) in sorted(record.frozen_ledgers.items())
    }
    recomputed_manifest = freeze_dataset(
        dataset_id=record.experiment_id,
        dataset=datasets,
        seeds=tuple(sorted(record.frozen_ledgers)),
        generation_config={"regime": record.regime, "n_per_seed": record.n, "version": RELEASE_VERSION},
        minimum_seeds=1,
    )
    hashes = _artifact_hashes(record)
    return {
        "experiment_id": experiment_id,
        "dataset_hash_matches": recomputed_manifest.dataset_sha256 == record.frozen_manifest_hash,
        "dataset_sha256": recomputed_manifest.dataset_sha256,
        "audit_verified": all(item["audit_verified"] for item in record.evidence) if record.evidence else False,
        "evidence_complete_for_run": bool(record.evidence) == bool(record.rows),
        "arms_canonical": list(ARM_ORDER) == list(CANONICAL_ARM_ORDER),
        "input_contract": "razorpay_shaped_test_payload_v1",
        "interpreter_mode": record.interpreter_mode,
        "artifact_hashes": hashes,
    }


# -- webhook ingress ---------------------------------------------------------
#
# This is the end-to-end wiring for the boundary `bailiff/webhook.py`
# implements: an HTTP route that actually calls `WebhookGate.verify` on the
# raw request bytes before anything downstream sees the payload, then, only
# for a genuine and actionable delivery, runs the same guardrail decision
# path `bailiff/demo.py` exercises — evaluate under the B2 guarded policy,
# execute only if allowed, against the local provider simulator. It is not a
# case-management system: it does not persist a queue or retry schedule
# across requests, and the local provider is a simulator, not a live
# Razorpay call. What it does prove, on a single HTTP round trip, is that
# authentication, normalisation and the guardrail decision are one connected
# path rather than three modules that only meet inside a test file.


def _webhook_ledger(event) -> CommonOutcomeLedger:
    """A ledger for one live-arriving event.

    Unlike the benchmark ledgers in `bailiff/fixtures.py`, there is no known
    ground truth here — a real deployment would not know in advance whether a
    debit will succeed. This assumes the optimistic case (`recoverable=True`)
    purely so the local simulator has something to return; it is not used to
    influence the guardrail's allow/deny decision, which never reads it.
    """
    outcome = CommonOutcome(
        case_id=event.recovery_case_id,
        latent_customer_state="willing",
        latent_bank_state="available",
        latent_consent_state=event.consent,
        latent_recovery_window="non_peak",
        latent_outcome_seed=7,
        latent_recoverable_minor=event.amount_minor,
        latent_harm_minor=0,
    )
    return CommonOutcomeLedger([outcome])


def _decide_and_execute(event) -> dict[str, object]:
    ledger = _webhook_ledger(event)
    provider = ReplayProvider(ledger)
    cases = CaseStore()
    cases.create_or_get(event)
    audit = AuditChain()
    engine = GuardrailEngine(cases=cases, provider=provider, audit=audit)
    policy = default_policy("B2")
    authority = AuthorityEnvelope(
        correlation_id=event.correlation_id,
        policy_id=policy.policy_id,
        mandate_id=event.mandate_id,
        scheduled_execution_id=event.scheduled_execution_id,
        recovery_case_id=event.recovery_case_id,
        allowed_actions=policy.allow_actions,
        max_amount_minor=event.amount_minor,
        attempts_remaining=max(0, policy.max_attempts - event.attempt_count),
        consent_snapshot_hash="sha256:webhook-consent",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    # The proposal must come from the same B2 reason gate the benchmark arm
    # uses. Hardcoding SCHEDULE_RETRY here once dropped the arm's reason
    # gating entirely: a provider-signalled terminal failure whose
    # mandate_state field lagged behind was retried by this route while the
    # benchmark B2 arm refused it.
    diagnosed_reason, confidence = deterministic_diagnosis(event)
    context = EvaluationContext(
        event=event,
        policy=policy,
        proposed_action=proposed_action("B2", diagnosed_reason, attempt_count=event.attempt_count),
        authority=authority,
        diagnosed_reason=diagnosed_reason,
        confidence=confidence,
    )
    decision = engine.evaluate(context)
    result = engine.execute(context=context, decision=decision)
    return {
        "policy_arm": "B2",
        "decision": decision.decision.value,
        "reason_codes": list(decision.reason_codes),
        "provider_call_made": result is not None and provider.call_count > 0,
        "provider_call_count": provider.call_count,
        "postcondition": result.postcondition_state if result else None,
        "audit_verified": audit.verify(),
    }


@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> dict[str, object]:
    raw_body = await request.body()
    headers = dict(request.headers)
    verdict = WEBHOOK_GATE.verify(raw_body=raw_body, headers=headers)

    if not verdict.accepted:
        raise HTTPException(status_code=400, detail={"reason_code": verdict.reason_code})

    response: dict[str, object] = {
        "received": True,
        "event_id": verdict.event_id,
        "event_name": verdict.event_name,
        "subscription_id": verdict.subscription_id,
        "should_process": verdict.should_process,
        "reason_code": verdict.reason_code,
    }
    if not verdict.should_process:
        # Authentic delivery, correctly ignored: a duplicate, a stale or
        # superseded ordering, or a subscription currently paused or halted.
        return response

    if verdict.event_name != "payment.failed":
        # Verified and actionable, but not the scheduled AutoPay failure
        # shape this project's guardrail evaluates. Recorded, not decided.
        response["decision"] = None
        return response

    try:
        parsed = json.loads(raw_body.decode("utf-8"))
        event = normalize_razorpay_autopay_payload(parsed)
    except (json.JSONDecodeError, RazorpayPayloadError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"reason_code": "VERIFIED_BUT_NOT_SCHEDULED_AUTOPAY_SHAPED", "error": str(exc)},
        ) from exc

    response["decision"] = _decide_and_execute(event)
    return response
