from fastapi.testclient import TestClient

from bailiff.api import app, EXPERIMENTS
from bailiff.policies import CANONICAL_ARM_ORDER


client = TestClient(app)
# Derived, not retyped. A hand maintained copy of the arm list in the test file
# drifts silently the moment an arm is added, and then asserts the wrong thing.
CANONICAL_ARMS = list(CANONICAL_ARM_ORDER)
CANONICAL_POLICY_IDS = [f"pid_{arm.replace('.', '_').lower()}" for arm in CANONICAL_ARM_ORDER]


def test_health_exposes_canonical_arms():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["arms"] == CANONICAL_ARMS


def test_create_requires_canonical_frontier_policy_ids_and_run_is_reproducible():
    response = client.post(
        "/experiments",
        json={
            "regime": "R1_TRANSIENT",
            "seed": 1701,
            "n": 8,
            "policy_ids": CANONICAL_POLICY_IDS,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    experiment_id = payload["experiment_id"]
    assert payload["policy_ids"] == CANONICAL_POLICY_IDS
    assert payload["ledger_sha256"]

    too_few = client.post(
        f"/experiments/{experiment_id}/run",
        json={"seeds": [1701, 2029, 3313, 4157], "n_per_seed": 8},
    )
    assert too_few.status_code == 400

    run = client.post(
        f"/experiments/{experiment_id}/run",
        json={"seeds": [1701, 2029, 3313, 4157, 5011], "n_per_seed": 8},
    )
    assert run.status_code == 200
    assert len(run.json()["aggregate"]) == len(CANONICAL_ARMS)
    assert all(item["seeds"] == 5 for item in run.json()["aggregate"])

    metrics = client.get(f"/experiments/{experiment_id}/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["arms"] == CANONICAL_ARMS

    case_id = next(iter(EXPERIMENTS[experiment_id].ledger.cases()))
    case = client.get(f"/experiments/{experiment_id}/cases/{case_id}")
    assert case.status_code == 200
    assert case.json()["latent_outcome_hidden_from_policy"] is True

    verification = client.post(f"/experiments/{experiment_id}/verify")
    assert verification.status_code == 200
    assert verification.json()["arms_canonical"] is True


def test_api_cost_inputs_are_recorded_and_change_net_value():
    response = client.post(
        "/experiments",
        json={
            "regime": "R1_TRANSIENT",
            "seed": 1701,
            "n": 20,
            "policy_ids": CANONICAL_POLICY_IDS,
        },
    )
    assert response.status_code == 200
    experiment_id = response.json()["experiment_id"]
    run = client.post(
        f"/experiments/{experiment_id}/run",
        json={
            "seeds": [1701, 2029, 3313, 4157, 5011],
            "n_per_seed": 20,
            "violation_cost_inr": 123.0,
            "human_review_cost_inr": 17.0,
        },
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["violation_cost_inr"] == 123.0
    assert payload["human_review_cost_inr"] == 17.0
    b1 = next(row for row in payload["aggregate"] if row["arm"] == "B1")
    assert b1["net_value_inr"]["mean"] != b1["incremental_recovered_inr"]["mean"]
    assert b1["violation_cost_inr"]["mean"] > 0
