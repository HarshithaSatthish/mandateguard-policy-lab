from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


EVIDENCE_FILES = {
    "success": "testmode_success_execute.json",
    "recovery_proof": "testmode_recovery_proof.json",
    "safe_block": "testmode_safe_block.json",
    "safe_block_zero_write": "testmode_safe_block_zero_write.json",
}


@dataclass(frozen=True)
class ProviderProofBundle:
    evidence_dir: Path
    artifacts: Mapping[str, Mapping[str, Any]]

    @property
    def complete(self) -> bool:
        return all(name in self.artifacts for name in EVIDENCE_FILES)

    @property
    def recovery_verified(self) -> bool:
        proof = self.artifacts.get("recovery_proof", {})
        return proof.get("recovery_verified") is True and bool(proof.get("recovery_proof_hash"))

    @property
    def already_paid_zero_write_verified(self) -> bool:
        row = self.artifacts.get("safe_block_zero_write", {})
        return (
            row.get("order_status") == "paid"
            and row.get("recoverytruth_result") == "SAFE_BLOCK_ALREADY_PAID"
            and row.get("executed") is False
            and int(row.get("payment_links_before", -1)) == 0
            and int(row.get("payment_links_after", -1)) == 0
            and row.get("zero_new_fallback_writes") is True
        )

    @property
    def successful_fallback_verified(self) -> bool:
        row = self.artifacts.get("success", {})
        receipt = row.get("receipt") if isinstance(row.get("receipt"), Mapping) else {}
        return (
            row.get("executed") is True
            and row.get("execution_state") == "EXECUTED"
            and row.get("financial_truth") == "RECOVERABLE"
            and row.get("reason_code") == "FALLBACK_PAYMENT_LINK_CREATED"
            and str(receipt.get("payment_link_id") or "").startswith("plink_")
        )

    def summary(self) -> dict[str, Any]:
        success = self.artifacts.get("success", {})
        receipt = success.get("receipt") if isinstance(success.get("receipt"), Mapping) else {}
        proof_blob = self.artifacts.get("recovery_proof", {})
        proof = proof_blob.get("proof") if isinstance(proof_blob.get("proof"), Mapping) else {}
        blocked = self.artifacts.get("safe_block_zero_write", {})
        return {
            "complete": self.complete,
            "successful_fallback_verified": self.successful_fallback_verified,
            "recovery_verified": self.recovery_verified,
            "already_paid_zero_write_verified": self.already_paid_zero_write_verified,
            "payment_link_id": receipt.get("payment_link_id"),
            "recovered_payment_id": proof.get("payment_id"),
            "recovery_proof_hash": proof_blob.get("recovery_proof_hash"),
            "safe_block_order_id": blocked.get("order_id"),
            "payment_links_before": blocked.get("payment_links_before"),
            "payment_links_after": blocked.get("payment_links_after"),
        }


def load_provider_proofs(root: str | Path) -> ProviderProofBundle:
    """Load sanitized Test Mode proof artifacts without any provider access.

    This function is intentionally read-only: no network calls, no environment
    credentials and no writes. Missing or malformed files are simply absent so
    the UI can say "not captured" rather than inventing proof.
    """
    root = Path(root)
    evidence_dir = root / "docs" / "testmode_evidence"
    artifacts: dict[str, Mapping[str, Any]] = {}
    for key, filename in EVIDENCE_FILES.items():
        path = evidence_dir / filename
        if not path.exists():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, Mapping):
            artifacts[key] = value
    return ProviderProofBundle(evidence_dir=evidence_dir, artifacts=artifacts)
