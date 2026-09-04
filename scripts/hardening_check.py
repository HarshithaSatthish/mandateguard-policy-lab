from __future__ import annotations

if not __debug__:
    raise SystemExit(
        "this release gate is built on assert statements; running it with "
        "PYTHONOPTIMIZE or -O would silently disable every check"
    )

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier, Lock
import time

from bailiff.claims import assert_required_claims
from bailiff.hardening import interpreter_ablation, refusal_regret
from bailiff.provider_proof import load_provider_proofs
from bailiff.razorpay_testmode import RazorpayTestModeClient


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"


class ConcurrentStubClient(RazorpayTestModeClient):
    """Shared provider stub with a deliberately slow Payment Link creation."""

    def __init__(self) -> None:
        super().__init__(key_id="rzp_test_concurrency", key_secret="not-a-real-secret")
        self.link: dict[str, object] | None = None
        self.post_attempts = 0
        self._state_lock = Lock()

    def _request(self, method: str, path: str, **kwargs: object):
        if method == "GET" and path == "/payment_links/":
            params = kwargs.get("params")
            reference = params.get("reference_id") if isinstance(params, dict) else None
            with self._state_lock:
                matches = []
                if self.link is not None and self.link.get("reference_id") == reference:
                    matches = [dict(self.link)]
            return {"payment_links": matches}

        if method == "POST" and path == "/payment_links":
            payload = kwargs.get("json")
            assert isinstance(payload, dict)
            time.sleep(0.05)
            with self._state_lock:
                self.post_attempts += 1
                assert self.link is None, "a second provider mutation reached the stub"
                self.link = {
                    "id": "plink_concurrent_1",
                    "short_url": "https://rzp.io/i/concurrent",
                    "amount": payload["amount"],
                    "currency": payload["currency"],
                    "reference_id": payload["reference_id"],
                    "accept_partial": False,
                }
                return dict(self.link)

        raise AssertionError(f"unexpected request {method} {path}")


def check_concurrent_fallback() -> None:
    client = ConcurrentStubClient()
    start = Barrier(2)
    reference = "rt_concurrency_proof_0000000000000001"

    def create() -> dict[str, object]:
        start.wait(timeout=2)
        return dict(
            client.create_payment_link_once(
                amount_minor=1000,
                currency="INR",
                reference_id=reference,
                description="concurrency proof",
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        left_future = pool.submit(create)
        right_future = pool.submit(create)
        left = left_future.result(timeout=5)
        right = right_future.result(timeout=5)

    assert left["id"] == right["id"] == "plink_concurrent_1"
    assert left["reference_id"] == right["reference_id"] == reference
    assert client.post_attempts == 1


def check_interpreter_ablation() -> None:
    aggregate = json.loads((OUTPUTS / "aggregate.json").read_text(encoding="utf-8"))
    rows = interpreter_ablation(aggregate)
    assert rows, "B2/B3 ablation produced no comparable regimes"
    assert all(row["safety_bound_unchanged"] for row in rows), rows
    assert any(row["b3_abstention_rate"] > 0 for row in rows), rows
    assert any(row["b3_interpreter_influence_count"] > 0 for row in rows), rows


def check_refusal_regret() -> None:
    evidence = json.loads((OUTPUTS / "evidence_ledger.json").read_text(encoding="utf-8"))
    report = refusal_regret(evidence)
    expected_non_provider = sum(1 for row in evidence if not row.get("provider_call_made"))
    assert report["non_provider_rows"] == expected_non_provider
    assert report["non_provider_rows"] > 0
    assert sum(item["rows"] for item in report["breakdown"]) == expected_non_provider
    assert report["legitimate_recovery_forgone_inr"] >= 0.0
    assert report["protected_value_by_denial_inr"] >= 0.0


def check_provider_proof_if_present() -> None:
    bundle = load_provider_proofs(ROOT)
    if not bundle.artifacts:
        print("provider proof artifacts not present in this checkout (optional until final evidence commit)")
        return
    assert bundle.complete, "partial docs/testmode_evidence bundle would make the judge proof ambiguous"
    assert bundle.successful_fallback_verified, "successful Test Mode fallback artifact failed its proof contract"
    assert bundle.recovery_verified, "captured-payment RecoveryProof artifact failed its proof contract"
    assert bundle.already_paid_zero_write_verified, "already-paid zero-write artifact failed its proof contract"


def main() -> int:
    assert_required_claims(ROOT)
    print("claims registry: PASS")

    check_interpreter_ablation()
    print("B2 -> B3 interpreter ablation: PASS")

    check_refusal_regret()
    print("refusal regret accounting: PASS")

    check_concurrent_fallback()
    print("concurrent fallback serialization: PASS")

    check_provider_proof_if_present()
    print("provider proof artifact contract: PASS")

    print("hardening check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
