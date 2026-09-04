from __future__ import annotations

if not __debug__:
    raise SystemExit(
        "this release gate is built on assert statements; running it with "
        "PYTHONOPTIMIZE or -O would silently disable every check"
    )

import hashlib
import json
import subprocess
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
ARMS = ["B0", "B1", "B1.5", "RZP", "B2.25", "B2.5", "B2.75", "B2", "B3"]


def load(name: str):
    return json.loads((OUTPUTS / name).read_text())


def main() -> int:
    manifest = load("manifest.json")
    assert manifest["final"] is True
    assert manifest["arms"] == ARMS
    assert len(manifest["seeds"]) >= 20
    assert manifest["dataset_count"] == len(manifest["seeds"]) * len(manifest["regimes"])
    assert manifest["violation_cost_inr"] >= 0
    assert manifest["human_review_cost_inr"] >= 0
    assert manifest["input_contract"] == "razorpay_shaped_test_payload_v1"
    assert manifest["provider_adapter"] == "bailiff.razorpay_adapter.normalize_razorpay_autopay_payload"
    assert manifest["interpreter_mode"] == "deterministic_offline"
    assert manifest["harm_multiplier"] >= 0
    assert manifest["harm_model"] == "compliance_exposure_independent_of_failure_reason"

    evidence_manifest = load("evidence_manifest.json")
    evidence_path = OUTPUTS / "evidence_ledger.json"
    evidence = json.loads(evidence_path.read_text())
    assert evidence_manifest["sampled_seed"] == min(manifest["seeds"])
    assert evidence_manifest["sampled_regime"] == manifest["regimes"][0]
    assert evidence_manifest["sampled_arms"] == ARMS
    assert evidence_manifest["sampled_row_count"] == len(evidence)
    assert evidence_manifest["sampled_case_count"] == manifest["n_per_seed"]
    assert len(evidence) == len(ARMS) * manifest["n_per_seed"]
    assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == evidence_manifest["sampled_evidence_sha256"]
    full_path = OUTPUTS / evidence_manifest["full_evidence_local_path"]
    assert full_path.exists()
    assert hashlib.sha256(full_path.read_bytes()).hexdigest() == evidence_manifest["full_evidence_sha256"]
    assert all(row["arm"] in ARMS for row in evidence)
    assert {row["arm"] for row in evidence} == set(ARMS)
    assert all(row["audit_verified"] for row in evidence)
    assert all(row["event_source"] == "razorpay_test_payload" for row in evidence)
    assert all(str(row["provider_payload_hash"]).startswith("sha256:") for row in evidence)
    assert any(row["provider_error_reason"] for row in evidence)

    if (ROOT / ".git").exists():
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
        assert "evidence_ledger_full.json" not in tracked
    assert not (OUTPUTS / "evidence_ledger_full.json").exists()

    anti = load("anti_gaming.json")
    assert anti["failures"] == []
    aggregate = load("aggregate.json")
    assert len(aggregate) == len(manifest["regimes"]) * len(ARMS)
    b3_ambiguous = next(row for row in aggregate if row["regime"] == "R3_AMBIGUOUS" and row["arm"] == "B3")
    assert b3_ambiguous["abstention_rate"]["mean"] > 0
    assert b3_ambiguous["bounded_interpreter_influence_count"]["mean"] > 0
    for row in aggregate:
        if row["arm"] in {"B2", "B3"}:
            assert row["violations"]["mean"] == 0
            assert row["audit_incomplete_rows"]["mean"] == 0
            # A fully guarded arm must never move prohibited money.
            assert row["realized_harm_inr"]["mean"] == 0
            assert row["prohibited_execution_rate"]["mean"] == 0

    # Metric comparability gates. These reject the two defects that made the
    # 0.3 benchmark unreadable: an arm dependent forgone definition, and a
    # latent harm model degenerate with the failure reason.
    strictness = ["B1", "B1.5", "B2.25", "B2.5", "B2.75", "B2"]
    by_key = {(row["regime"], row["arm"]): row for row in aggregate}
    for regime in manifest["regimes"]:
        forgone = [by_key[(regime, arm)]["legitimate_recovery_forgone_inr"]["mean"] for arm in strictness]
        assert forgone == sorted(forgone), (
            f"{regime}: legitimate recovery forgone is not monotone in strictness: "
            f"{dict(zip(strictness, forgone))}"
        )
        protected = {
            arm: by_key[(regime, arm)]["protected_value_by_denial_inr"]["mean"]
            for arm in ARMS
            if arm != "B1"
        }
        assert len(set(protected.values())) > 1, (
            f"{regime}: protected value by denial does not discriminate between arms: {protected}"
        )
        assert by_key[(regime, "B1.5")]["protected_value_by_denial_inr"]["mean"] < by_key[(regime, "B2")][
            "protected_value_by_denial_inr"
        ]["mean"], f"{regime}: reason gating alone protects as much as the full guardrail profile"
        assert by_key[(regime, "B1")]["realized_harm_inr"]["mean"] > 0, (
            f"{regime}: the ungated baseline records no prohibited execution, so the fixture "
            f"contains no harm for any control to prevent"
        )
    b1 = next(row for row in aggregate if row["regime"] == "R1_TRANSIENT" and row["arm"] == "B1")
    assert b1["violations"]["mean"] > 0
    assert b1["violation_cost_inr"]["mean"] > 0
    assert b1["net_value_inr"]["mean"] != b1["incremental_recovered_inr"]["mean"]

    assert (OUTPUTS / "breakeven.json").exists()
    sensitivity = load("sensitivity.json")
    for regime in manifest["regimes"]:
        item = sensitivity["per_regime"][regime]
        assert len(item["harm_multiplier_curve"]) == len(sensitivity["grids"]["harm_multiplier"])
        assert len(item["violation_cost_curve"]) == len(sensitivity["grids"]["violation_cost_inr"])
        # A recommendation that never changes across the whole swept price
        # range is not a recommendation, it is a constant.
        assert len(item["recommended_arm_span"]) > 1, (
            f"{regime}: the recommended arm is invariant across the entire swept harm price"
        )
    assert (OUTPUTS / "frontier.png").stat().st_size > 10_000
    assert (OUTPUTS / "architecture.png").stat().st_size > 10_000
    assert (OUTPUTS / "sensitivity.png").stat().st_size > 10_000
    findings = (ROOT / "FINDINGS.md").read_text().lower()
    report = (OUTPUTS / "report.md").read_text().lower()
    for text in ("abstention", "net value", "break even", "frontier", "harm priced", "realized harm"):
        assert text in report
    assert "falsification criteria" in findings

    demo = subprocess.run(
        [sys.executable, "-m", "bailiff.demo"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for text in (
        "allowed input: source=razorpay_test_payload",
        "allowed retry: decision=allow, provider_calls=1",
        "exhausted retry denial: decision=stop, provider_calls=0",
        "ambiguous B3: mode=deterministic_offline, decision=abstain",
        "timeout:",
        "audit tamper: before=True, after=False",
    ):
        assert text in demo, text

    real_evidence_path = OUTPUTS / "real_interpreter_evidence.json"
    if real_evidence_path.exists():
        real_evidence = json.loads(real_evidence_path.read_text())
        result = real_evidence["result"]
        assert result["reason_source"] == "MODEL_INTERPRETATION"
        assert result["model_calls"] == 1
        assert result["model_tokens"] > 0
        assert 0.0 <= result["confidence"] <= 1.0
        assert real_evidence["provider_base_url"] != "https://api.openai.com/v1", (
            "record which OpenAI-compatible host actually served this run, not the default"
        )
        print("real interpreter evidence present and well formed (optional, not gated)")
    else:
        print("real interpreter evidence not present (optional; run bailiff.demo --real-interpreter to add it)")

    print("release checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
