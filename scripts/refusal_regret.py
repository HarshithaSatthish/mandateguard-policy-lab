from __future__ import annotations

import argparse
import json
from pathlib import Path

from bailiff.hardening import refusal_regret


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"


def main() -> int:
    parser = argparse.ArgumentParser(description="Price every non-provider refusal on the frozen evidence ledger.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the derived JSON to outputs/generated/ (excluded from shipped checksums)",
    )
    args = parser.parse_args()

    evidence = json.loads((OUTPUTS / "evidence_ledger.json").read_text(encoding="utf-8"))
    report = refusal_regret(evidence)

    print("REFUSAL REGRET")
    print("Every non-provider row is priced on both sides: safety protected and legitimate recovery forgone.")
    print()
    print(f"non-provider rows                 {report['non_provider_rows']}")
    print(f"legitimate recovery forgone INR  {report['legitimate_recovery_forgone_inr']:,.2f}")
    print(f"protected value by denial INR    {report['protected_value_by_denial_inr']:,.2f}")
    print(f"protection minus regret INR      {report['net_protection_minus_regret_inr']:,.2f}")
    print()
    print(
        f"{'decision':<12}{'primary reason':<42}{'rows':>7}"
        f"{'forgone':>13}{'protected':>13}{'net':>13}"
    )
    print("-" * 100)
    for row in report["breakdown"]:
        print(
            f"{row['decision']:<12}{row['primary_reason']:<42}{row['rows']:>7}"
            f"{row['legitimate_recovery_forgone_inr']:>13,.2f}"
            f"{row['protected_value_by_denial_inr']:>13,.2f}"
            f"{row['net_protection_minus_regret_inr']:>13,.2f}"
        )

    if args.write:
        generated = OUTPUTS / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        out = generated / "refusal_regret.json"
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print()
        print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
