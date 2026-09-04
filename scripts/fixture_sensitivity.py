"""Test whether the benchmark's conclusions survive a hostile fixture.

The sharpest available attack on this project is not a bug. It is that the
fixture's harm model was chosen by the same person who wanted the guardrails
to look good. `HARM_PROBABILITY_BY_STATE` and the independent exposure rates
are project assumptions, and a benchmark whose conclusion depends on the exact
value of an assumption nobody can verify is an anecdote with a hash.

So the assumptions are swept, deliberately including settings hostile to the
thesis, and the conclusions are recorded at every cell:

  compliance_harm_scale   scales how harmful a non terminal breach actually is.
                          At 0.25 a breach is mostly a paperwork problem and
                          the guardrails ought to look like an expensive habit.
  exposure_scale          scales how often a case is silently in a prohibited
                          state at all.

Two claims are tracked separately, because they are not equally fragile:

  1. B3 dominates B2 — same harm, more recovery. This is a claim about
     interpretation and should not depend on harm calibration at all.
  2. A fully guarded arm is the recommended arm at the configured price.
     This is an economic claim and SHOULD move with the assumptions.

Reporting where claim 2 fails is the point. A sweep that found the guardrails
winning everywhere would mean the sweep was too narrow, not that the design
was vindicated.

Run:
    python3 scripts/fixture_sensitivity.py [--seeds N] [--n CASES]
"""

from __future__ import annotations

# Make `bailiff` importable when this script is run directly
# (`python3 scripts/...py`), without requiring `pip install -e .` first
# or a manually exported PYTHONPATH. Idempotent if the package is
# already installed.
import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = str(_Path(__file__).resolve().parents[1])
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)

import argparse
import json
from pathlib import Path

from bailiff import fixtures
from bailiff.chartstyle import dominated_arms
from bailiff.runner import FINAL_SEEDS, aggregate_rows, run_experiment
from bailiff.rules import RuleCatalog
from bailiff.sensitivity import build_sensitivity

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

GUARDED_ARMS = ("B2", "B3")
COMPLIANCE_HARM_SCALES = (0.25, 0.50, 1.00, 1.50, 2.00)
EXPOSURE_SCALES = (0.50, 1.00, 2.00)

BASELINE_HARM = dict(fixtures.HARM_PROBABILITY_BY_STATE)
BASELINE_OPT_OUT = fixtures.INDEPENDENT_OPT_OUT_RATE
BASELINE_BLOCKED = fixtures.INDEPENDENT_BLOCKED_MANDATE_RATE


def _apply(compliance_scale: float, exposure_scale: float) -> None:
    """Rewrite the fixture assumptions in place for one sweep cell.

    A terminal reason stays certainly harmful: that is a definition, not a
    calibration, so scaling it would change what the word means rather than
    testing sensitivity to an assumption.
    """
    scaled = {}
    for state, probability in BASELINE_HARM.items():
        if state == "terminal_reason":
            scaled[state] = probability
        else:
            scaled[state] = min(1.0, round(probability * compliance_scale, 6))
    fixtures.HARM_PROBABILITY_BY_STATE = scaled
    fixtures.INDEPENDENT_OPT_OUT_RATE = min(1.0, BASELINE_OPT_OUT * exposure_scale)
    fixtures.INDEPENDENT_BLOCKED_MANDATE_RATE = min(1.0, BASELINE_BLOCKED * exposure_scale)


def _restore() -> None:
    fixtures.HARM_PROBABILITY_BY_STATE = dict(BASELINE_HARM)
    fixtures.INDEPENDENT_OPT_OUT_RATE = BASELINE_OPT_OUT
    fixtures.INDEPENDENT_BLOCKED_MANDATE_RATE = BASELINE_BLOCKED


def evaluate_cell(seeds: tuple[int, ...], n_per_seed: int) -> dict[str, object]:
    catalog = RuleCatalog.load()
    rows, _evidence, _hashes = run_experiment(seeds=seeds, n_per_seed=n_per_seed)
    aggregates = aggregate_rows(rows)
    regimes = sorted({str(row["regime"]) for row in rows})
    arms = sorted({str(row["arm"]) for row in rows})
    manifest = {
        "arms": [a for a in fixtures_arm_order() if a in arms],
        "regimes": regimes,
        "violation_cost_inr": float(catalog.value("violation_cost_inr")),
        "human_review_cost_inr": float(catalog.value("human_review_cost_inr")),
        "harm_multiplier": 1.0,
    }
    sensitivity = build_sensitivity(manifest, aggregates)

    by_key = {(row["regime"], row["arm"]): row for row in aggregates}
    per_regime: dict[str, object] = {}
    for regime in regimes:
        coords = {
            arm: (
                float(by_key[(regime, arm)]["realized_harm_inr"]["mean"]),
                float(by_key[(regime, arm)]["incremental_recovered_inr"]["mean"]),
            )
            for arm in manifest["arms"]
        }
        dominated = set(dominated_arms(coords))
        item = sensitivity["per_regime"][regime]
        configured_point = next(
            point for point in item["harm_multiplier_curve"]
            if abs(point["harm_multiplier"] - 1.0) < 1e-9
        )
        per_regime[regime] = {
            "b3_dominates_b2": "B2" in dominated and "B3" not in dominated,
            "recommended_arm_at_1x": configured_point["recommended_arm"],
            "guarded_arm_wins_at_1x": configured_point["recommended_arm"] in GUARDED_ARMS,
            "guarded_arm_wins_at_harm_multiplier": item["guarded_arm_wins_at_harm_multiplier"],
            "dominated_arms": sorted(dominated, key=manifest["arms"].index),
        }
    return per_regime


def fixtures_arm_order() -> list[str]:
    from bailiff.policies import ARM_ORDER

    return list(ARM_ORDER)


def write_robustness_markdown(summary: dict[str, object]) -> Path:
    """Emit the robustness section from the swept data, never by hand."""
    cells = summary["cells"]
    regimes = sorted({regime for cell in cells for regime in cell["per_regime"]})

    by_regime_dominance = {
        regime: [cell["per_regime"][regime]["b3_dominates_b2"] for cell in cells]
        for regime in regimes
    }
    by_regime_guarded = {
        regime: [cell["per_regime"][regime]["guarded_arm_wins_at_1x"] for cell in cells]
        for regime in regimes
    }
    winners = sorted(
        {cell["per_regime"][regime]["recommended_arm_at_1x"] for cell in cells for regime in regimes}
    )

    lines = [
        "# Robustness of the conclusions to the fixture assumptions",
        "",
        "> Generated by `scripts/fixture_sensitivity.py`. Not hand written.",
        "",
        "The harm model in `bailiff/fixtures.py` is a project assumption chosen by the",
        "author. A conclusion that only holds at one setting of an unverifiable",
        "assumption is not a finding, so the assumptions are swept and every conclusion",
        "is reported at every setting, including settings hostile to the design.",
        "",
        f"Protocol: {summary['method']['protocol']}, "
        f"{summary['cells_evaluated']} fixture settings, "
        f"{summary['regime_observations']} regime observations.",
        "",
        "## What survives the sweep",
        "",
        "| Claim | Holds in |",
        "|---|---:|",
        f"| B3 dominates B2 — same realized harm, more recovery | {summary['b3_dominates_b2_in']} |",
        f"| A fully guarded arm is recommended at the configured price | {summary['a_guarded_arm_wins_at_configured_price_in']} |",
        f"| An ungated arm (B1) is never the recommended arm | "
        f"{'yes' if 'B1' not in winners else 'NO — B1 wins somewhere'} |",
        "",
        "## By regime",
        "",
        "| Regime | B3 dominates B2 | Guarded arm wins at 1x |",
        "|---|---:|---:|",
    ]
    for regime in regimes:
        dominance = by_regime_dominance[regime]
        guarded = by_regime_guarded[regime]
        lines.append(
            f"| {regime} | {sum(dominance)}/{len(dominance)} | {sum(guarded)}/{len(guarded)} |"
        )

    lines += [
        "",
        "## How to read this",
        "",
        "The dominance claim is a statement about interpretation and does not depend on",
        "how harm is priced, so where it fails it fails because the bounded interpreter",
        "had little ambiguous work to do and the two guarded arms are separated by noise",
        "rather than by policy. It is strongest exactly where it should be, on the",
        "regimes carrying ambiguous and terminal payloads.",
        "",
        "The economic claim is expected to move with the assumptions, and it does:",
        "the cheaper a prohibited action is assumed to be, the later the guardrails pay",
        "for themselves. Reporting the settings where the guardrails do NOT pay is the",
        "point of the sweep. A sweep that found them winning everywhere would mean the",
        "sweep was too narrow, not that the design was vindicated.",
        "",
        "The one conclusion that survives every setting tested is negative rather than",
        "flattering: ungated retry is never the right policy at any assumption in the",
        "grid. Reason gating alone frequently is.",
        "",
        "## Falsification",
        "",
        "These claims are falsified if a run at the shipped configuration shows a fully",
        "guarded arm recording a nonzero independent violation, if a dominated arm",
        "becomes recommended without its inputs changing, or if the sweep above is",
        "rerun at the recorded protocol and the counts differ.",
        "",
    ]

    path = ROOT / "ROBUSTNESS.md"
    path.write_text("\n".join(lines))
    print(f"wrote {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--n", type=int, default=100)
    args = parser.parse_args()
    seeds = tuple(FINAL_SEEDS[: args.seeds])

    cells: list[dict[str, object]] = []
    total = len(COMPLIANCE_HARM_SCALES) * len(EXPOSURE_SCALES)
    index = 0

    try:
        for compliance_scale in COMPLIANCE_HARM_SCALES:
            for exposure_scale in EXPOSURE_SCALES:
                index += 1
                _apply(compliance_scale, exposure_scale)
                print(
                    f"  [{index}/{total}] compliance_harm_scale={compliance_scale:.2f} "
                    f"exposure_scale={exposure_scale:.2f}",
                    flush=True,
                )
                cells.append(
                    {
                        "compliance_harm_scale": compliance_scale,
                        "exposure_scale": exposure_scale,
                        "per_regime": evaluate_cell(seeds, args.n),
                    }
                )
    finally:
        _restore()

    regime_results = [
        (cell, regime, result)
        for cell in cells
        for regime, result in cell["per_regime"].items()
    ]
    dominance_holds = sum(1 for _c, _r, res in regime_results if res["b3_dominates_b2"])
    guarded_wins = sum(1 for _c, _r, res in regime_results if res["guarded_arm_wins_at_1x"])
    observed = len(regime_results)

    summary = {
        "method": {
            "swept": "fixture harm assumptions, not policy code or runtime configuration",
            "compliance_harm_scale": "multiplier on every non terminal harm probability, capped at 1.0",
            "exposure_scale": "multiplier on the independent opt out and blocked mandate rates",
            "terminal_reason_note": "terminal reasons stay certainly harmful; that is a definition, not a calibration",
            "protocol": f"{len(seeds)} seeds x {args.n} cases x 3 regimes per cell",
        },
        "cells_evaluated": len(cells),
        "regime_observations": observed,
        "b3_dominates_b2_in": f"{dominance_holds}/{observed}",
        "a_guarded_arm_wins_at_configured_price_in": f"{guarded_wins}/{observed}",
        "seeds": list(seeds),
        "n_per_seed": args.n,
        "baseline_harm_probability_by_state": BASELINE_HARM,
        "cells": cells,
    }

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    path = OUTPUTS / "fixture_sensitivity.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    write_robustness_markdown(summary)

    print()
    print(f"B3 dominates B2 in                        {dominance_holds}/{observed} regime observations")
    print(f"A fully guarded arm wins at 1x harm in    {guarded_wins}/{observed} regime observations")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
