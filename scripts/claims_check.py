from __future__ import annotations

import argparse
from pathlib import Path

from bailiff.claims import ClaimStatus, assert_required_claims, evaluate_claims, write_registry


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve evidence-backed submission claims.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="write CLAIMS.md and claims.json from current artifacts",
    )
    args = parser.parse_args()

    results = write_registry(ROOT) if args.write else evaluate_claims(ROOT)
    assert_required_claims(ROOT)

    for result in results:
        marker = "PASS" if result.status is ClaimStatus.HELD else result.status.value
        required = "required" if result.required_for_release else "optional"
        print(f"{marker:10} {required:8} {result.claim_id} -> {result.evidence}")

    print("required evidence claims passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
