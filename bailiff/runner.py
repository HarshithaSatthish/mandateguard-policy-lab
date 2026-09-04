from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import argparse
import json
from pathlib import Path
from typing import Iterable

from .benchmark import canonical_json, freeze_dataset
from .checker import self_test
from .fixtures import REGIMES, generate_fixture
from .metrics import annotate_runs, summarize_runs, summarize_seed_values
from .policies import ARM_ORDER, PolicyRun, bounded_interpreter_diagnosis, run_policy_case
from .rules import RuleCatalog
from .interpreter import RealBoundedInterpreter
from .razorpay_adapter import normalize_razorpay_autopay_payload, to_razorpay_test_payload
from ._version import RELEASE_VERSION

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"
FINAL_SEEDS = (1701, 2029, 3313, 4157, 5011, 6073, 7127, 8191, 9227, 10267, 11003, 12011, 13007, 14009, 15013, 16033, 17027, 18041, 19013, 20011)


def _event_row(run: PolicyRun, ledger_hash: str) -> dict[str, object]:
    d = run.decision
    result = run.provider_result
    return {
        "case_id": run.event.recovery_case_id,
        "arm": run.arm,
        "policy_id": d.policy_id,
        "decision_id": d.decision_id,
        "correlation_id": d.correlation_id,
        "failure_code": run.event.failure_code,
        "normalized_failure_reason": run.event.normalized_failure_reason,
        "event_source": run.event.source,
        "provider_payload_hash": run.event.payload_hash,
        "provider_event": run.event.failure_payload.get("provider_event"),
        "provider_error_source": run.event.failure_payload.get("error_source"),
        "provider_error_reason": run.event.failure_payload.get("error_reason"),
        "provider_error_description": run.event.failure_payload.get("error_description"),
        "diagnosed_reason": d.diagnosed_reason,
        "confidence": d.confidence,
        "proposed_action": d.proposed_action.value if d.proposed_action else None,
        "final_action": d.final_action.value if d.final_action else None,
        "decision": d.decision.value,
        "reason_codes": list(d.reason_codes),
        "reason_sources": list(d.reason_sources),
        "policy_provenance": dict(d.policy_provenance),
        "bounded_interpreter_model": d.bounded_interpreter_model,
        "bounded_interpreter_influence": d.bounded_interpreter_influence,
        "provider_call_made": bool(result),
        "provider_call_id": result.provider_call_id if result else None,
        "provider_status": result.status if result else None,
        "provider_postcondition_state": result.postcondition_state if result else None,
        "provider_timed_out": result.timed_out if result else False,
        "legitimate_recovery_forgone_inr": d.legitimate_recovery_forgone_inr_minor / 100,
        "protected_value_by_denial_inr": d.protected_value_inr_minor / 100,
        "realized_harm_inr": d.realized_harm_inr_minor / 100,
        "audit_event_count": len(run.audit_events),
        "audit_event_hashes": [str(item.get("event_hash")) for item in run.audit_events],
        "audit_verified": run.audit_verified,
        "ledger_sha256": ledger_hash,
    }


def _dataset_rows(events: list, ledger) -> list[dict[str, object]]:
    return [
        {
            "case_id": event.recovery_case_id,
            "event_id": event.event_id,
            "amount_minor": event.amount_minor,
            "failure_code": event.failure_code,
            "normalized_failure_reason": event.normalized_failure_reason,
            "event_source": event.source,
            "provider_payload_hash": event.payload_hash,
            "provider_signal": dict(event.failure_payload),
            "mandate_state": event.mandate_state,
            "attempt_count": event.attempt_count,
            "mcc": event.mcc,
            "proposed_execution_at": event.proposed_execution_at.isoformat() if event.proposed_execution_at else None,
            "outcome": asdict(ledger.get(event.recovery_case_id)),
        }
        for event in events
    ]


def run_experiment(
    *,
    seeds: Iterable[int],
    n_per_seed: int,
    regimes: Iterable[str] = REGIMES.keys(),
    human_review_cost_inr: float | None = None,
    violation_cost_inr: float | None = None,
    harm_multiplier: float | None = None,
    interpreter_mode: str = "deterministic_offline",
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, str]]:
    catalog = RuleCatalog.load()
    if human_review_cost_inr is None:
        human_review_cost_inr = float(catalog.value("human_review_cost_inr"))
    if violation_cost_inr is None:
        violation_cost_inr = float(catalog.value("violation_cost_inr"))
    if harm_multiplier is None:
        harm_multiplier = float(catalog.value("harm_multiplier"))
    if interpreter_mode not in {"deterministic_offline", "real_optional"}:
        raise ValueError("interpreter_mode must be deterministic_offline or real_optional")
    interpreter = RealBoundedInterpreter() if interpreter_mode == "real_optional" else bounded_interpreter_diagnosis
    rows: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    dataset_hashes: dict[str, str] = {}
    for regime in regimes:
        for seed in seeds:
            events, ledger = generate_fixture(regime, seed, n_per_seed)
            adapted_events = [
                normalize_razorpay_autopay_payload(to_razorpay_test_payload(event))
                for event in events
            ]
            dataset = _dataset_rows(adapted_events, ledger)
            # This freezes one regime-and-seed dataset, so its manifest must
            # record exactly the seed that generated it. The five-seed floor
            # belongs to the experiment-level protocol, not to a per-dataset
            # manifest; padding the list with unused seeds to clear that floor
            # would record false provenance.
            manifest = freeze_dataset(
                dataset_id=f"{regime}_{seed}",
                dataset=dataset,
                seeds=(seed,),
                minimum_seeds=1,
                generation_config={"regime": regime, "n_per_seed": n_per_seed, "version": RELEASE_VERSION},
            )
            dataset_hashes[f"{regime}:{seed}"] = manifest.dataset_sha256
            per_arm: dict[str, list[PolicyRun]] = {}
            for arm in ARM_ORDER:
                raw_runs = [
                    run_policy_case(
                        arm=arm,
                        event=event,
                        ledger=ledger,
                        interpreter=interpreter,
                    )
                    for event in adapted_events
                ]
                per_arm[arm] = annotate_runs(raw_runs, ledger)
                summary = summarize_runs(
                    per_arm[arm],
                    ledger,
                    human_review_cost_inr=human_review_cost_inr,
                    violation_cost_inr=violation_cost_inr,
                    harm_multiplier=harm_multiplier,
                )
                summary.update({
                    "regime": regime,
                    "seed": seed,
                    "ledger_sha256": ledger.sha256(),
                    "rules_sha256": RuleCatalog.load().sha256(),
                })
                rows.append(summary)
                evidence.extend(_event_row(run, ledger.sha256()) for run in per_arm[arm])

    for regime in sorted({str(row["regime"]) for row in rows}):
        for seed in sorted({int(row["seed"]) for row in rows if row["regime"] == regime}):
            base = next(
                row["recovered_inr"]
                for row in rows
                if row["regime"] == regime and row["seed"] == seed and row["arm"] == "B0"
            )
            for row in rows:
                if row["regime"] == regime and row["seed"] == seed:
                    row["incremental_recovered_inr"] = round(float(row["recovered_inr"]) - base, 4)
                    row["net_value_inr"] = round(
                        row["incremental_recovered_inr"]
                        - float(row["violation_cost_inr"])
                        - float(row["human_review_cost_inr"])
                        - float(row["model_cost_inr"]),
                        4,
                    )
                    row["net_value_harm_priced_inr"] = round(
                        row["incremental_recovered_inr"]
                        - float(row["harm_cost_inr"])
                        - float(row["human_review_cost_inr"])
                        - float(row["model_cost_inr"]),
                        4,
                    )
    return rows, evidence, dataset_hashes


def aggregate_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    aggregates: list[dict[str, object]] = []
    numeric = (
        "incremental_recovered_inr",
        "legitimate_recovery_forgone_inr",
        "protected_value_by_denial_inr",
        "realized_harm_inr",
        "harm_cost_inr",
        "prohibited_execution_rate",
        "violations",
        "recovered_per_permitted_action_inr",
        "abstention_rate",
        "human_review_cost_inr",
        "violation_cost_inr",
        "net_value_inr",
        "net_value_harm_priced_inr",
        "contacts_per_case",
        "provider_calls",
        "model_calls",
        "model_cost_inr",
        "bounded_interpreter_influence_count",
        "audit_incomplete_rows",
    )
    for regime in REGIMES:
        for arm in ARM_ORDER:
            selected = [row for row in rows if row["regime"] == regime and row["arm"] == arm]
            if not selected:
                continue
            aggregate: dict[str, object] = {"regime": regime, "arm": arm, "seeds": len(selected)}
            for metric in numeric:
                values = {int(row["seed"]): float(row[metric]) for row in selected}
                aggregate[metric] = summarize_seed_values(values, minimum_seeds=5)
            aggregates.append(aggregate)
    return aggregates


# Least to most constrained. Used by the metric comparability gate below.
STRICTNESS_ORDER = ("B1", "B1.5", "B2.25", "B2.5", "B2.75", "B2")

# Below this many cases per regime, a fixture level claim cannot be separated
# from an unlucky draw, so the pooled checks are skipped rather than guessed.
MINIMUM_CASES_FOR_FIXTURE_CHECKS = 300


def _metric_integrity_failures(rows: list[dict[str, object]]) -> list[str]:
    """Catch the metric defects that made the 0.3 benchmark unreadable.

    These are release gates, not unit tests. They run against the actual final
    aggregate so that a metric definition which is comparable in a fixture but
    not at scale still fails the release.

    The checks are applied at the granularity each claim actually lives at. Arm
    level invariants hold on any sample and are checked per seed. The claim that
    latent harm is not degenerate with respect to policy is a property of the
    fixture rather than of one seed, so it is pooled across seeds and skipped
    entirely on samples too small to distinguish a degenerate fixture from an
    unlucky draw.
    """
    failures: list[str] = []
    keys = sorted({(str(row["regime"]), int(row["seed"])) for row in rows})

    for regime, seed in keys:
        selected = {
            str(row["arm"]): row
            for row in rows
            if row["regime"] == regime and row["seed"] == seed
        }

        # A stricter arm executes a subset of the provider calls a looser one
        # executes, so it can never forgo less legitimate recovery. An arm
        # dependent forgone definition breaks this on any sample size.
        forgone = [
            float(selected[arm]["legitimate_recovery_forgone_inr"])
            for arm in STRICTNESS_ORDER
            if arm in selected
        ]
        if forgone != sorted(forgone):
            failures.append(
                f"{regime} seed {seed}: legitimate recovery forgone is not monotone in policy "
                f"strictness ({dict(zip(STRICTNESS_ORDER, forgone))}); the metric is not "
                f"comparable across arms"
            )

        # A fully guarded arm must never move prohibited money, on any sample.
        for arm in ("B2", "B3"):
            if arm in selected and float(selected[arm]["realized_harm_inr"]) != 0.0:
                failures.append(
                    f"{regime} seed {seed}: {arm} executed a prohibited action worth "
                    f"{selected[arm]['realized_harm_inr']} INR"
                )

    # Pooled fixture level checks.
    for regime in sorted({str(row["regime"]) for row in rows}):
        regime_rows = [row for row in rows if row["regime"] == regime]
        cases = sum(int(row["n"]) for row in regime_rows if row["arm"] == "B0")
        if cases < MINIMUM_CASES_FOR_FIXTURE_CHECKS:
            continue

        pooled: dict[str, float] = {}
        harm_pooled: dict[str, float] = {}
        for arm in ARM_ORDER:
            arm_rows = [row for row in regime_rows if row["arm"] == arm]
            if not arm_rows:
                continue
            pooled[arm] = sum(float(row["protected_value_by_denial_inr"]) for row in arm_rows)
            harm_pooled[arm] = sum(float(row["realized_harm_inr"]) for row in arm_rows)

        # Only the reason-gated arms can reveal the degeneracy. B0 protects
        # everything by never executing, and B1 and RZP are reason-blind, so
        # including any of them makes this set unequal on every fixture and
        # the check can never fire.
        reason_gated_arms = ("B1.5", "B2.25", "B2.5", "B2.75", "B2", "B3")
        gated = {arm: pooled[arm] for arm in reason_gated_arms if arm in pooled}
        if gated and len(set(gated.values())) <= 1:
            failures.append(
                f"{regime}: protected value by denial is identical for every reason-gated arm "
                f"({next(iter(gated.values()), 0.0)} over {cases} cases); latent harm is "
                f"degenerate with respect to policy, so reason gating alone captures all harm "
                f"avoidance by construction"
            )
        if "B1.5" in pooled and "B2" in pooled and pooled["B1.5"] >= pooled["B2"]:
            failures.append(
                f"{regime}: deterministic reason gating protects as much value as the full "
                f"guardrail profile ({pooled['B1.5']} versus {pooled['B2']}); no control above "
                f"the reason code can be shown to be worth its cost on this fixture"
            )
        if harm_pooled.get("B1", 0.0) <= 0.0:
            failures.append(
                f"{regime}: the ungated baseline executed no prohibited action over {cases} "
                f"cases, so the fixture contains no harm for any control to prevent"
            )

    return failures


def anti_gaming(rows: list[dict[str, object]]) -> list[str]:
    failures: list[str] = []
    failures.extend(_metric_integrity_failures(rows))
    for row in rows:
        if row["arm"] != "B0" and float(row["abstention_rate"]) > 0.60:
            failures.append(f"{row['arm']} {row['regime']} seed {row['seed']} abstains above 60%")
        if int(row["audit_incomplete_rows"]) != 0:
            failures.append(f"{row['arm']} {row['regime']} seed {row['seed']} has incomplete audit evidence")
    try:
        self_test()
    except AssertionError as exc:
        failures.append(f"independent checker positive controls failed: {exc}")
    ambiguous_b3 = [
        row for row in rows
        if row["arm"] == "B3" and row["regime"] == "R3_AMBIGUOUS" and int(row["bounded_interpreter_influence_count"]) > 0
    ]
    if not ambiguous_b3:
        failures.append("B3 has no recorded bounded interpreter influence on R3_AMBIGUOUS")
    return failures


def write_outputs(
    *,
    seeds: tuple[int, ...],
    n_per_seed: int,
    final: bool = False,
    human_review_cost_inr: float | None = None,
    violation_cost_inr: float | None = None,
    harm_multiplier: float | None = None,
    output_dir: Path | None = None,
    interpreter_mode: str = "deterministic_offline",
) -> dict[str, object]:
    catalog = RuleCatalog.load()
    if human_review_cost_inr is None:
        human_review_cost_inr = float(catalog.value("human_review_cost_inr"))
    if violation_cost_inr is None:
        violation_cost_inr = float(catalog.value("violation_cost_inr"))
    if harm_multiplier is None:
        harm_multiplier = float(catalog.value("harm_multiplier"))
    rows, evidence, dataset_hashes = run_experiment(
        seeds=seeds,
        n_per_seed=n_per_seed,
        human_review_cost_inr=human_review_cost_inr,
        violation_cost_inr=violation_cost_inr,
        harm_multiplier=harm_multiplier,
        interpreter_mode=interpreter_mode,
    )
    aggregates = aggregate_rows(rows)
    manifest_dataset = {"datasets": dataset_hashes, "seeds": seeds, "regimes": list(REGIMES), "n_per_seed": n_per_seed}
    manifest = {
        "version": RELEASE_VERSION,
        "arms": list(ARM_ORDER),
        "seeds": list(seeds),
        "regimes": list(REGIMES),
        "n_per_seed": n_per_seed,
        "final": final,
        "dataset_sha256": sha256(canonical_json(manifest_dataset)).hexdigest(),
        "dataset_count": len(dataset_hashes),
        "rules_sha256": RuleCatalog.load().sha256(),
        "policy_contract": "scheduled_upi_autopay_only",
        "input_contract": "razorpay_shaped_test_payload_v1",
        "provider_adapter": "bailiff.razorpay_adapter.normalize_razorpay_autopay_payload",
        "interpreter_mode": interpreter_mode,
        "rules_provenance": "project_policy_with_source_tiers",
        "human_review_cost_inr": human_review_cost_inr,
        "violation_cost_inr": violation_cost_inr,
        "harm_multiplier": harm_multiplier,
        "harm_model": "compliance_exposure_independent_of_failure_reason",
    }
    failures = anti_gaming(rows)
    target = output_dir or OUTPUTS
    target.mkdir(parents=True, exist_ok=True)
    generated = target / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    per_seed_bytes = json.dumps(rows, indent=2, sort_keys=True).encode()
    aggregate_bytes = json.dumps(aggregates, indent=2, sort_keys=True).encode()
    full_evidence_bytes = json.dumps(evidence, indent=2, sort_keys=True, default=str).encode()
    sample_seed = min(seeds)
    sample_regime = next(iter(REGIMES))
    sample_prefix = f"{sample_regime}_{sample_seed}_"
    sample_evidence = [row for row in evidence if str(row["case_id"]).startswith(sample_prefix)]
    sample_evidence_bytes = json.dumps(sample_evidence, indent=2, sort_keys=True, default=str).encode()
    full_evidence_sha256 = sha256(full_evidence_bytes).hexdigest()
    sample_evidence_sha256 = sha256(sample_evidence_bytes).hexdigest()
    (target / "per_seed.json").write_bytes(per_seed_bytes)
    (target / "aggregate.json").write_bytes(aggregate_bytes)
    (target / "evidence_ledger.json").write_bytes(sample_evidence_bytes)
    (generated / "evidence_ledger_full.json").write_bytes(full_evidence_bytes)
    evidence_manifest = {
        "sampled_regime": sample_regime,
        "sampled_seed": sample_seed,
        "sampled_arms": list(ARM_ORDER),
        "sampled_case_count": n_per_seed,
        "sampled_row_count": len(sample_evidence),
        "sampled_evidence_sha256": sample_evidence_sha256,
        "full_evidence_sha256": full_evidence_sha256,
        "full_evidence_local_path": str((generated / "evidence_ledger_full.json").relative_to(target)),
        "note": "The full ledger is generated for local verification. The shipped evidence ledger is a deterministic one seed and one regime sample.",
    }
    evidence_manifest_bytes = json.dumps(evidence_manifest, indent=2, sort_keys=True).encode()
    (target / "evidence_manifest.json").write_bytes(evidence_manifest_bytes)
    (target / "anti_gaming.json").write_text(json.dumps({"failures": failures}, indent=2, sort_keys=True) + "\n")
    artifact_hash_input = {
        "per_seed_sha256": sha256(per_seed_bytes).hexdigest(),
        "aggregate_sha256": sha256(aggregate_bytes).hexdigest(),
        "evidence_sha256": sample_evidence_sha256,
        "evidence_manifest_sha256": sha256(evidence_manifest_bytes).hexdigest(),
        "anti_gaming": failures,
    }
    manifest["outputs_sha256"] = sha256(canonical_json(artifact_hash_input)).hexdigest()
    manifest["evidence"] = {
        "shipped_file": "evidence_ledger.json",
        "sample_manifest": "evidence_manifest.json",
        "full_local_path": str((generated / "evidence_ledger_full.json").relative_to(target)),
        "shipped_row_count": len(sample_evidence),
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {"rows": rows, "aggregates": aggregates, "manifest": manifest, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--violation-cost-inr", type=float, default=None)
    parser.add_argument("--human-review-cost-inr", type=float, default=None)
    parser.add_argument("--harm-multiplier", type=float, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--real-interpreter", action="store_true", help="use the optional model path for ambiguous B3 cases")
    args = parser.parse_args()
    seeds = FINAL_SEEDS if args.final else FINAL_SEEDS[: args.seeds]
    result = write_outputs(
        seeds=tuple(seeds),
        n_per_seed=args.n,
        final=args.final,
        violation_cost_inr=args.violation_cost_inr,
        human_review_cost_inr=args.human_review_cost_inr,
        harm_multiplier=args.harm_multiplier,
        output_dir=args.output_dir,
        interpreter_mode="real_optional" if args.real_interpreter else "deterministic_offline",
    )
    print("regime         arm     incremental  forgone     protected   realized_harm  violations   net_harm_priced")
    for row in result["aggregates"]:
        incr = row["incremental_recovered_inr"]["mean"]
        forgone = row["legitimate_recovery_forgone_inr"]["mean"]
        protected = row["protected_value_by_denial_inr"]["mean"]
        harm = row["realized_harm_inr"]["mean"]
        violations = row["violations"]["mean"]
        net = row["net_value_harm_priced_inr"]["mean"]
        print(
            f"{row['regime']:<14}{row['arm']:<7}{incr:>12,.2f}{forgone:>12,.2f}"
            f"{protected:>12,.2f}{harm:>15,.2f}{violations:>12,.2f}{net:>18,.2f}"
        )
    if result["failures"]:
        print("ANTI_GAMING_FAILURES")
        for failure in result["failures"]:
            print(f"  {failure}")
        return 1
    print(f"wrote {OUTPUTS}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
