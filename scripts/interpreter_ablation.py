from __future__ import annotations

import argparse
import json
from pathlib import Path

from bailiff.hardening import interpreter_ablation


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare B2 and B3 on the frozen aggregate.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the derived JSON to outputs/generated/ (excluded from shipped checksums)",
    )
    args = parser.parse_args()

    aggregate = json.loads((OUTPUTS / "aggregate.json").read_text(encoding="utf-8"))
    rows = interpreter_ablation(aggregate)
    if not rows:
        raise SystemExit("no B2/B3 aggregate rows found")

    print("B2 -> B3 bounded-interpreter ablation")
    print("same frozen aggregate, same guardrails, same execution boundary")
    print()
    print(
        f"{'regime':<15}{'B2 rec':>12}{'B3 rec':>12}{'delta':>12}"
        f"{'B3 abstain':>13}{'safe?':>8}{'adds rec?':>11}"
    )
    print("-" * 83)
    for row in rows:
        print(
            f"{row['regime']:<15}"
            f"{row['b2_incremental_recovered_inr']:>12,.2f}"
            f"{row['b3_incremental_recovered_inr']:>12,.2f}"
            f"{row['delta_recovered_inr']:>12,.2f}"
            f"{row['b3_abstention_rate']:>13.4f}"
            f"{str(row['safety_bound_unchanged']):>8}"
            f"{str(row['interpreter_adds_recovery']):>11}"
        )

    if args.write:
        payload = {
            "comparison": "B2 deterministic guardrails vs B3 same guardrails plus bounded interpreter",
            "source": "outputs/aggregate.json",
            "rows": rows,
            "safety_bound_unchanged_all_regimes": all(row["safety_bound_unchanged"] for row in rows),
            "recovery_wins": sum(1 for row in rows if row["interpreter_adds_recovery"]),
            "regimes": len(rows),
        }
        generated = OUTPUTS / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        out = generated / "interpreter_ablation.json"
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print()
        print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
