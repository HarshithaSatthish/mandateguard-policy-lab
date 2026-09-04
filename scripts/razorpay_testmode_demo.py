from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from bailiff.recovery_runtime import RecoveryActionReceipt, RecoveryRequest, RecoveryTruthRuntime
from bailiff.razorpay_testmode import RazorpayTestModeClient


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Run RecoveryTruth against Razorpay TEST MODE only. The execute command creates a "
            "customer-initiated Payment Link fallback; it is not an AutoPay debit retry."
        )
    )
    sub = p.add_subparsers(dest="command", required=True)

    execute = sub.add_parser("execute", help="Resolve truth, re-read at the write boundary and create one Test Mode fallback")
    execute.add_argument("--order-id", required=True, help="Razorpay Test Mode order id (order_...)")
    execute.add_argument("--case-id", required=True)
    execute.add_argument("--mandate-id", required=True)
    execute.add_argument("--mandate-status", default="active", help="Current merchant-side mandate state")
    execute.add_argument("--amount-minor", required=True, type=int, help="Expected INR amount in paise")
    execute.add_argument("--max-authorized-amount-minor", type=int, help="Amount ceiling from the policy decision; defaults to amount-minor")
    execute.add_argument("--decision-id", required=True)
    execute.add_argument("--decision-evidence-hash", required=True, help="Hash of the exact MandateGuard decision/audit evidence")
    execute.add_argument("--policy-version", default="mandateguard_policy_0.2")
    execute.add_argument("--authority-ttl-seconds", type=int, default=300, help="Short-lived execution authority TTL")
    execute.add_argument(
        "--receipt-out",
        type=Path,
        help="Write the exact execution receipt required by the later verify step",
    )

    verify = sub.add_parser("verify", help="Verify the exact captured payment using a previously emitted execution receipt")
    verify.add_argument("--receipt", required=True, type=Path)
    return p


def _load_receipt(path: Path) -> RecoveryActionReceipt:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("receipt file must contain a JSON object")
    expected = set(RecoveryActionReceipt.__dataclass_fields__)
    if set(data) != expected:
        missing = sorted(expected - set(data))
        extra = sorted(set(data) - expected)
        raise ValueError(f"receipt schema mismatch; missing={missing}, extra={extra}")
    return RecoveryActionReceipt(**data)


def main() -> int:
    args = parser().parse_args()
    client = RazorpayTestModeClient.from_env()
    runtime = RecoveryTruthRuntime(client)

    if args.command == "verify":
        receipt = _load_receipt(args.receipt)
        proof = runtime.verify_recovery(receipt)
        print(
            json.dumps(
                {
                    "mode": "razorpay_test_mode_verify",
                    "recovery_verified": True,
                    "proof": asdict(proof),
                    "recovery_proof_hash": proof.hash(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.authority_ttl_seconds <= 0 or args.authority_ttl_seconds > 3600:
        raise ValueError("authority-ttl-seconds must be between 1 and 3600")
    max_amount = args.max_authorized_amount_minor or args.amount_minor
    request = RecoveryRequest(
        case_id=args.case_id,
        decision_id=args.decision_id,
        decision_evidence_hash=args.decision_evidence_hash,
        policy_version=args.policy_version,
        order_id=args.order_id,
        mandate_id=args.mandate_id,
        mandate_status=args.mandate_status,
        amount_minor=args.amount_minor,
        max_authorized_amount_minor=max_amount,
        authority_expires_at=datetime.now(timezone.utc) + timedelta(seconds=args.authority_ttl_seconds),
    )
    attempt = runtime.execute_customer_fallback(request)
    output: dict[str, object] = {
        "mode": "razorpay_test_mode_execute",
        "execution_state": attempt.execution_state.value,
        "executed": attempt.executed,
        "write_outcome_unknown": attempt.write_outcome_unknown,
        "reason_code": attempt.reason_code,
        "financial_truth": attempt.truth.state.value,
        "truth_reason_codes": list(attempt.truth.reason_codes),
    }
    if attempt.receipt is not None:
        receipt_dict = asdict(attempt.receipt)
        output["receipt"] = receipt_dict
        if args.receipt_out is not None:
            args.receipt_out.write_text(json.dumps(receipt_dict, indent=2, sort_keys=True) + "\n")
            output["receipt_file"] = str(args.receipt_out)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
