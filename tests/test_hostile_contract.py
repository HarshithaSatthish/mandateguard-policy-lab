from datetime import datetime, timezone

from fastapi.testclient import TestClient

from bailiff.api import EXPERIMENTS, app
from bailiff.domain import ConsentState, FailureReason, RecoveryEvent
from bailiff.fixtures import generate_fixture
from bailiff.metrics import annotate_runs, summarize_runs
from bailiff.policies import ARM_ORDER, default_policy, run_policy_case
from bailiff.replay import CommonOutcomeLedger
from bailiff.runner import _event_row, run_experiment


client = TestClient(app)


def make_ambiguous() -> RecoveryEvent:
    return RecoveryEvent(
        event_id="evt_hostile",
        merchant_id="merchant",
        customer_id="customer",
        mandate_id="mandate",
        scheduled_execution_id="scheduled",
        recovery_case_id="case_hostile",
        correlation_id="cid_hostile",
        amount_minor=10000,
        currency="INR",
        failure_code="XX99",
        mandate_state="active",
        attempt_count=1,
        pre_debit_state="valid",
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        failure_payload={"code": "XX99", "description": "conflicting bank signals"},
        mcc="5817",
        consent=ConsentState(email=True),
        normalized_failure_reason=FailureReason.UNKNOWN_OR_CONFLICTING.value,
    )


def test_all_arms_have_verified_audit_and_evidence_contract():
    events, ledger = generate_fixture("R3_AMBIGUOUS", 1701, 6)
    for arm in ARM_ORDER:
        raw = [run_policy_case(arm=arm, event=event, ledger=ledger) for event in events]
        runs = annotate_runs(raw, ledger)
        summary = summarize_runs(runs, ledger)
        assert summary["audit_incomplete_rows"] == 0
        assert all(run.audit_verified and len(run.audit_events) >= 2 for run in runs)
        evidence = [_event_row(run, ledger.sha256()) for run in runs]
        assert all(row["ledger_sha256"] == ledger.sha256() for row in evidence)
        assert all("legitimate_recovery_forgone_inr" in row for row in evidence)
        assert all("protected_value_by_denial_inr" in row for row in evidence)
        assert sum(row["legitimate_recovery_forgone_inr"] for row in evidence) == summary["legitimate_recovery_forgone_inr"]
        assert sum(row["protected_value_by_denial_inr"] for row in evidence) == summary["protected_value_by_denial_inr"]


def test_event_validity_expiry_denies_before_provider():
    events, ledger = generate_fixture("R1_TRANSIENT", 1701, 1)
    expired = events[0].__class__(
        **{
            **events[0].__dict__,
            "valid_until": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "mandate_state": "active",
            "proposed_execution_at": None,
        }
    )
    run = run_policy_case(arm="B2", event=expired, ledger=ledger)
    assert "EVENT_EXPIRED" in run.decision.reason_codes
    assert run.provider_result is None


def test_mcc_exemption_and_retry_gap_are_real_runtime_rules():
    events, ledger = generate_fixture("R1_TRANSIENT", 1701, 1)
    exempt_event = events[0].__class__(
        **{
            **events[0].__dict__,
            "pre_debit_state": "invalid",
            "mcc": "4784",
            "last_attempt_at": None,
            "proposed_execution_at": None,
        }
    )
    exempt_run = run_policy_case(arm="B2", event=exempt_event, ledger=ledger)
    assert "PRE_DEBIT_NOTICE_INVALID" not in exempt_run.decision.reason_codes

    gap_event = events[0].__class__(
        **{
            **events[0].__dict__,
            "pre_debit_state": "valid",
            "last_attempt_at": events[0].event_time,
            "proposed_execution_at": events[0].event_time + __import__("datetime").timedelta(hours=12),
        }
    )
    gap_run = run_policy_case(arm="B2", event=gap_event, ledger=ledger)
    assert "RETRY_GAP_TOO_SHORT" in gap_run.decision.reason_codes
    assert gap_run.provider_result is None


def test_b3_uses_injected_interpreter_and_records_influence():
    event = make_ambiguous()
    ledger = CommonOutcomeLedger.from_seed(seed=19, case_ids=[event.recovery_case_id])
    calls = []

    def injected(_event):
        calls.append(_event.event_id)
        return FailureReason.MANDATE_REVOKED_OR_CANCELLED.value, 0.91

    run = run_policy_case(arm="B3", event=event, ledger=ledger, interpreter=injected)
    assert calls == [event.event_id]
    assert run.decision.bounded_interpreter_influence is True
    assert run.decision.diagnosed_reason == FailureReason.MANDATE_REVOKED_OR_CANCELLED.value
    assert run.provider_result is None
    assert run.audit_verified is True


def test_b3_does_not_interpret_nonambiguous_payloads():
    events, ledger = generate_fixture("R1_TRANSIENT", 1701, 1)
    calls = []

    def unexpected(_event):
        calls.append(_event.event_id)
        return FailureReason.UNKNOWN_OR_CONFLICTING.value, 0.1

    run = run_policy_case(arm="B3", event=events[0], ledger=ledger, interpreter=unexpected)
    assert calls == []
    assert run.decision.diagnosed_reason == events[0].normalized_failure_reason
    assert run.decision.bounded_interpreter_influence is False


def test_low_confidence_bounded_interpreter_cannot_authorize_retry():
    event = make_ambiguous().__class__(
        **{
            **make_ambiguous().__dict__,
            "normalized_failure_reason": FailureReason.INSUFFICIENT_FUNDS.value,
            "failure_payload": {"description": "insufficient balance but conflicting signal"},
        }
    )
    ledger = CommonOutcomeLedger.from_seed(seed=21, case_ids=[event.recovery_case_id])

    def low_confidence(_event):
        return FailureReason.INSUFFICIENT_FUNDS.value, 0.10

    run = run_policy_case(arm="B3", event=event, ledger=ledger, interpreter=low_confidence)
    assert run.decision.decision.value == "abstain"
    assert "ABSTAIN" in run.decision.reason_codes
    assert "INTERPRETER_CONFIDENCE_BELOW_THRESHOLD" in run.decision.reason_codes
    assert run.decision.final_action is not None
    assert run.decision.final_action.value == "escalate_to_human"
    assert run.provider_result is None


def test_malformed_bounded_interpreter_output_abstains_safely():
    event = make_ambiguous()
    ledger = CommonOutcomeLedger.from_seed(seed=22, case_ids=[event.recovery_case_id])

    def malformed(_event):
        return {"action": "schedule_retry", "confidence": 2.0}

    run = run_policy_case(arm="B3", event=event, ledger=ledger, interpreter=malformed)
    assert run.decision.diagnosed_reason == FailureReason.UNKNOWN_OR_CONFLICTING.value
    assert run.decision.decision.value == "abstain"
    assert "ABSTAIN" in run.decision.reason_codes
    assert run.decision.final_action is not None
    assert run.decision.final_action.value == "escalate_to_human"
    assert run.provider_result is None


def test_generated_ambiguous_regime_emits_b3_abstentions_without_provider_calls():
    events, ledger = generate_fixture("R3_AMBIGUOUS", 1701, 40)
    runs = annotate_runs([run_policy_case(arm="B3", event=event, ledger=ledger) for event in events], ledger)
    summary = summarize_runs(runs, ledger)
    assert summary["abstention_rate"] > 0
    abstained = [run for run in runs if "ABSTAIN" in run.decision.reason_codes]
    assert abstained
    assert all(run.provider_result is None for run in abstained)
    assert all(run.decision.final_action.value == "escalate_to_human" for run in abstained)


def test_rule_catalog_provenance_is_present_in_policy_decisions():
    policy = default_policy("B2")
    assert policy.policy_provenance
    assert "attempt_cap" in policy.policy_provenance
    assert policy.version.startswith("mandateguard_rules_")


def test_api_reuses_created_seed_and_returns_all_arm_case_evidence():
    response = client.post(
        "/experiments",
        json={
            "regime": "R3_AMBIGUOUS",
            "seed": 1701,
            "n": 5,
            "policy_ids": [f"pid_{arm.replace('.', '_').lower()}" for arm in ARM_ORDER],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    experiment_id = payload["experiment_id"]
    original_hash = payload["ledger_sha256"]
    run = client.post(
        f"/experiments/{experiment_id}/run",
        json={"seeds": [1701, 2029, 3313, 4157, 5011], "n_per_seed": 5},
    )
    assert run.status_code == 200
    assert run.json()["ledger_hashes"]["1701"] == original_hash
    case_id = next(iter(EXPERIMENTS[experiment_id].ledger.cases()))
    case = client.get(f"/experiments/{experiment_id}/cases/{case_id}")
    assert case.status_code == 200
    assert case.json()["arms_present"] == list(ARM_ORDER)

    original_amount = EXPERIMENTS[experiment_id].frozen_ledgers[1701][0][0].amount_minor
    EXPERIMENTS[experiment_id].frozen_ledgers[1701] = (
        [EXPERIMENTS[experiment_id].frozen_ledgers[1701][0][0].__class__(
            **{
                **EXPERIMENTS[experiment_id].frozen_ledgers[1701][0][0].__dict__,
                "amount_minor": original_amount + 1,
            }
        )] + EXPERIMENTS[experiment_id].frozen_ledgers[1701][0][1:],
        EXPERIMENTS[experiment_id].frozen_ledgers[1701][1],
    )
    verification = client.post(f"/experiments/{experiment_id}/verify")
    assert verification.status_code == 200
    assert verification.json()["dataset_hash_matches"] is False


def test_runner_evidence_has_same_ledger_hash_for_every_arm():
    rows, evidence, hashes = run_experiment(seeds=(1701, 2029, 3313, 4157, 5011), n_per_seed=4, regimes=("R1_TRANSIENT",))
    assert len(hashes) == 5
    for seed in (1701, 2029, 3313, 4157, 5011):
        seed_hashes = {row["ledger_sha256"] for row in evidence if row["case_id"].startswith(f"R1_TRANSIENT_{seed}_")}
        assert len(seed_hashes) == 1
    assert all(row["audit_verified"] for row in evidence)
