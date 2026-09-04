from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .hardening import interpreter_ablation


class ClaimStatus(str, Enum):
    HELD = "HELD"
    REFUTED = "REFUTED"
    UNRESOLVED = "UNRESOLVED"
    MISSING = "MISSING"


@dataclass(frozen=True)
class ClaimResult:
    claim_id: str
    statement: str
    status: ClaimStatus
    evidence: str
    observed: Any
    required_for_release: bool = True

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _missing(claim_id: str, statement: str, evidence: str, *, required: bool) -> ClaimResult:
    return ClaimResult(
        claim_id=claim_id,
        statement=statement,
        status=ClaimStatus.MISSING,
        evidence=evidence,
        observed=None,
        required_for_release=required,
    )


def evaluate_claims(root: str | Path) -> list[ClaimResult]:
    """Resolve judge-facing claims from artifacts, never from prose.

    Required claims are part of the frozen offline proof. Provider-backed Test
    Mode claims are optional until sanitized evidence artifacts are present;
    once present their status is still derived mechanically from those files.
    """
    root = Path(root)
    outputs = root / "outputs"
    results: list[ClaimResult] = []

    aggregate_path = outputs / "aggregate.json"
    if not aggregate_path.exists():
        results.append(
            _missing(
                "offline.guarded-zero-harm",
                "B2 and B3 execute zero prohibited value in every frozen regime.",
                "outputs/aggregate.json",
                required=True,
            )
        )
    else:
        aggregate = _json(aggregate_path)
        guarded = [row for row in aggregate if row.get("arm") in {"B2", "B3"}]
        held = bool(guarded) and all(
            float((row.get("realized_harm_inr") or {}).get("mean", 0.0)) == 0.0
            and float((row.get("prohibited_execution_rate") or {}).get("mean", 0.0)) == 0.0
            and float((row.get("violations") or {}).get("mean", 0.0)) == 0.0
            for row in guarded
        )
        results.append(
            ClaimResult(
                "offline.guarded-zero-harm",
                "B2 and B3 execute zero prohibited value in every frozen regime.",
                ClaimStatus.HELD if held else ClaimStatus.REFUTED,
                "outputs/aggregate.json",
                {
                    "rows_checked": len(guarded),
                    "violating_rows": sum(
                        1
                        for row in guarded
                        if float((row.get("realized_harm_inr") or {}).get("mean", 0.0)) != 0.0
                        or float((row.get("prohibited_execution_rate") or {}).get("mean", 0.0)) != 0.0
                        or float((row.get("violations") or {}).get("mean", 0.0)) != 0.0
                    ),
                },
            )
        )

        ambiguous = next(
            (
                row
                for row in aggregate
                if row.get("regime") == "R3_AMBIGUOUS" and row.get("arm") == "B3"
            ),
            None,
        )
        abstention = 0.0 if ambiguous is None else float((ambiguous.get("abstention_rate") or {}).get("mean", 0.0))
        influence = 0.0 if ambiguous is None else float(
            (ambiguous.get("bounded_interpreter_influence_count") or {}).get("mean", 0.0)
        )
        results.append(
            ClaimResult(
                "offline.b3-ambiguity-abstention",
                "B3 actually uses bounded interpretation on ambiguity and abstains rather than guessing.",
                ClaimStatus.HELD if abstention > 0.0 and influence > 0.0 else ClaimStatus.REFUTED,
                "outputs/aggregate.json:R3_AMBIGUOUS/B3",
                {"abstention_rate": abstention, "interpreter_influence_count": influence},
            )
        )

        ablation = interpreter_ablation(aggregate)
        safety_held = bool(ablation) and all(row["safety_bound_unchanged"] for row in ablation)
        recovery_wins = sum(1 for row in ablation if row["interpreter_adds_recovery"])
        results.append(
            ClaimResult(
                "offline.interpreter-ablation",
                "Adding B3 interpretation does not widen the zero-harm execution bound; its recovery effect is reported rather than assumed.",
                ClaimStatus.HELD if safety_held else ClaimStatus.REFUTED,
                "outputs/aggregate.json:B2-vs-B3",
                {"regimes": len(ablation), "recovery_wins": recovery_wins, "rows": ablation},
            )
        )

    evidence_manifest_path = outputs / "evidence_manifest.json"
    evidence_path = outputs / "evidence_ledger.json"
    if not evidence_manifest_path.exists() or not evidence_path.exists():
        results.append(
            _missing(
                "offline.sample-evidence-hash",
                "The shipped sampled evidence ledger matches its frozen SHA-256 manifest.",
                "outputs/evidence_manifest.json + outputs/evidence_ledger.json",
                required=True,
            )
        )
    else:
        manifest = _json(evidence_manifest_path)
        observed_hash = sha256(evidence_path.read_bytes()).hexdigest()
        expected_hash = str(manifest.get("sampled_evidence_sha256") or "")
        results.append(
            ClaimResult(
                "offline.sample-evidence-hash",
                "The shipped sampled evidence ledger matches its frozen SHA-256 manifest.",
                ClaimStatus.HELD if observed_hash == expected_hash else ClaimStatus.REFUTED,
                "outputs/evidence_manifest.json + outputs/evidence_ledger.json",
                {"expected": expected_hash, "observed": observed_hash},
            )
        )

    evidence_dir = root / "docs" / "testmode_evidence"
    safe_path = evidence_dir / "testmode_safe_block_zero_write.json"
    if not safe_path.exists():
        results.append(
            _missing(
                "testmode.already-paid-zero-write",
                "An already-paid Razorpay Test Mode order is SAFE_BLOCKED with zero new fallback writes.",
                "docs/testmode_evidence/testmode_safe_block_zero_write.json",
                required=False,
            )
        )
    else:
        safe = _json(safe_path)
        held = (
            safe.get("order_status") == "paid"
            and safe.get("recoverytruth_result") == "SAFE_BLOCK_ALREADY_PAID"
            and safe.get("executed") is False
            and int(safe.get("payment_links_before", -1)) == 0
            and int(safe.get("payment_links_after", -1)) == 0
            and safe.get("zero_new_fallback_writes") is True
        )
        results.append(
            ClaimResult(
                "testmode.already-paid-zero-write",
                "An already-paid Razorpay Test Mode order is SAFE_BLOCKED with zero new fallback writes.",
                ClaimStatus.HELD if held else ClaimStatus.REFUTED,
                str(safe_path.relative_to(root)),
                safe,
                required_for_release=False,
            )
        )

    proof_path = evidence_dir / "testmode_recovery_proof.json"
    if not proof_path.exists():
        results.append(
            _missing(
                "testmode.recovery-proof",
                "A successful fallback is independently verified as a captured payment and bound into RecoveryProof.",
                "docs/testmode_evidence/testmode_recovery_proof.json",
                required=False,
            )
        )
    else:
        proof_blob = _json(proof_path)
        held = proof_blob.get("recovery_verified") is True and bool(proof_blob.get("recovery_proof_hash"))
        proof = proof_blob.get("proof") if isinstance(proof_blob.get("proof"), dict) else {}
        held = held and str(proof.get("provider_action_id") or "").startswith("plink_")
        held = held and str(proof.get("payment_id") or "").startswith("pay_")
        results.append(
            ClaimResult(
                "testmode.recovery-proof",
                "A successful fallback is independently verified as a captured payment and bound into RecoveryProof.",
                ClaimStatus.HELD if held else ClaimStatus.REFUTED,
                str(proof_path.relative_to(root)),
                {
                    "recovery_verified": proof_blob.get("recovery_verified"),
                    "recovery_proof_hash": proof_blob.get("recovery_proof_hash"),
                    "provider_action_id": proof.get("provider_action_id"),
                    "payment_id": proof.get("payment_id"),
                },
                required_for_release=False,
            )
        )

    return results


def assert_required_claims(root: str | Path) -> list[ClaimResult]:
    results = evaluate_claims(root)
    failures = [
        result
        for result in results
        if result.status is ClaimStatus.REFUTED
        or (result.required_for_release and result.status is not ClaimStatus.HELD)
    ]
    if failures:
        summary = ", ".join(f"{item.claim_id}={item.status.value}" for item in failures)
        raise AssertionError(f"evidence claims failed: {summary}")
    return results


def render_markdown(results: list[ClaimResult]) -> str:
    lines = [
        "# Evidence claims registry",
        "",
        "Statuses are derived from artifacts. This file is not the source of truth; the referenced evidence is.",
        "",
        "| Claim | Status | Required | Evidence |",
        "|---|---|---:|---|",
    ]
    for item in results:
        lines.append(
            f"| `{item.claim_id}` — {item.statement} | **{item.status.value}** | "
            f"{'yes' if item.required_for_release else 'no'} | `{item.evidence}` |"
        )
    lines.extend(["", "## Machine-readable observations", "", "```json"])
    lines.append(json.dumps([item.as_dict() for item in results], indent=2, sort_keys=True, default=str))
    lines.append("```")
    return "\n".join(lines) + "\n"


def write_registry(root: str | Path) -> list[ClaimResult]:
    root = Path(root)
    results = evaluate_claims(root)
    (root / "CLAIMS.md").write_text(render_markdown(results), encoding="utf-8")
    (root / "claims.json").write_text(
        json.dumps([item.as_dict() for item in results], indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return results
