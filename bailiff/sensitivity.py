"""Recommendation sensitivity to the two priced project assumptions.

A single recommended arm computed at one configured cost is not evidence, it is
an anecdote about that cost. Every arm ordering in this benchmark is a function
of what a prohibited action is assumed to cost, and that assumption is the least
defensible number in the whole project.

This module therefore does not report one winner. It sweeps the price of a
prohibited action across a grid and reports which arm wins at each price, plus
the exact crossover at which the ordering changes. A reader who disagrees with
the project's default assumption can read their own answer off the curve.

Two independent pricings are swept, because they encode different theories of
what a control is for:

`harm_multiplier`
    Prices a prohibited action at a multiple of the money actually moved. A
    prohibited debit of a paused mandate costs at minimum the reversal, so 1.0
    is a lower bound rather than a guess. This pricing is driven by
    `realized_harm_inr`, which counts only prohibited actions that reached the
    provider.

`violation_cost_inr`
    Prices a prohibited action at a flat rate per independently detected
    breach, regardless of the amount at stake. This is the weaker model. It is
    retained because it is auditable and because it is what the release gate
    already prices.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

HARM_MULTIPLIER_GRID: tuple[float, ...] = (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0)
VIOLATION_COST_GRID: tuple[float, ...] = (0.0, 10.0, 25.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0)

GUARDED_ARMS = ("B2", "B3")


def _mean(row: dict[str, Any], metric: str) -> float:
    return float(row[metric]["mean"])


def _winner(scores: dict[str, float], arms: Sequence[str]) -> str:
    """Highest score wins; canonical arm order is the deterministic tie break."""
    return max(arms, key=lambda arm: (scores[arm], -arms.index(arm)))


def _net_at_harm_multiplier(row: dict[str, Any], multiplier: float) -> float:
    """Recompute net value at an arbitrary harm price from stored components.

    The stored `harm_cost_inr` is recorded at the run's own multiplier, so the
    unpriced quantity `realized_harm_inr` is used here instead. This keeps the
    sweep a pure re-pricing of one frozen run rather than a re-run, which is
    what makes it comparable across arms.
    """
    return (
        _mean(row, "incremental_recovered_inr")
        - _mean(row, "realized_harm_inr") * multiplier
        - _mean(row, "human_review_cost_inr")
        - _mean(row, "model_cost_inr")
    )


def _net_at_violation_cost(row: dict[str, Any], cost: float) -> float:
    return (
        _mean(row, "incremental_recovered_inr")
        - _mean(row, "violations") * cost
        - _mean(row, "human_review_cost_inr")
        - _mean(row, "model_cost_inr")
    )


def _first_crossover(
    curve: list[dict[str, Any]],
    *,
    price_key: str,
    targets: Iterable[str] = GUARDED_ARMS,
) -> float | None:
    """Lowest swept price at which a fully guarded arm becomes the winner."""
    wanted = set(targets)
    for point in curve:
        if point["recommended_arm"] in wanted:
            return float(point[price_key])
    return None


def build_sensitivity(
    manifest: dict[str, Any],
    aggregates: list[dict[str, Any]],
    *,
    harm_grid: Sequence[float] = HARM_MULTIPLIER_GRID,
    violation_grid: Sequence[float] = VIOLATION_COST_GRID,
) -> dict[str, Any]:
    arms = list(manifest["arms"])
    by_key = {(row["regime"], row["arm"]): row for row in aggregates}
    per_regime: dict[str, Any] = {}

    for regime in manifest["regimes"]:
        rows = {arm: by_key[(regime, arm)] for arm in arms}

        harm_curve: list[dict[str, Any]] = []
        for multiplier in harm_grid:
            scores = {arm: _net_at_harm_multiplier(rows[arm], multiplier) for arm in arms}
            harm_curve.append(
                {
                    "harm_multiplier": multiplier,
                    "recommended_arm": _winner(scores, arms),
                    "net_value_by_arm_inr": {arm: round(scores[arm], 4) for arm in arms},
                }
            )

        violation_curve: list[dict[str, Any]] = []
        for cost in violation_grid:
            scores = {arm: _net_at_violation_cost(rows[arm], cost) for arm in arms}
            violation_curve.append(
                {
                    "violation_cost_inr": cost,
                    "recommended_arm": _winner(scores, arms),
                    "net_value_by_arm_inr": {arm: round(scores[arm], 4) for arm in arms},
                }
            )

        per_regime[regime] = {
            "harm_multiplier_curve": harm_curve,
            "violation_cost_curve": violation_curve,
            "guarded_arm_wins_at_harm_multiplier": _first_crossover(
                harm_curve, price_key="harm_multiplier"
            ),
            "guarded_arm_wins_at_violation_cost_inr": _first_crossover(
                violation_curve, price_key="violation_cost_inr"
            ),
            "recommended_arm_span": sorted({point["recommended_arm"] for point in harm_curve}),
        }

    return {
        "method": {
            "harm_multiplier_curve": (
                "net value equals incremental recovered minus realized harm times the multiplier, "
                "minus human review cost and model cost; realized harm counts only prohibited "
                "actions that actually reached the provider"
            ),
            "violation_cost_curve": (
                "net value equals incremental recovered minus independently detected violations "
                "times the flat cost, minus human review cost and model cost"
            ),
            "crossover": (
                "lowest swept price at which a fully guarded arm (B2 or B3) becomes the "
                "recommended arm; null means no swept price makes a guarded arm win"
            ),
            "tie_break": "canonical arm order",
            "note": (
                "Both curves re-price one frozen benchmark run. No arm is re-executed, so every "
                "point on both curves reads the same ledger and the same decisions."
            ),
        },
        "grids": {
            "harm_multiplier": list(harm_grid),
            "violation_cost_inr": list(violation_grid),
        },
        "configured": {
            "harm_multiplier": float(manifest.get("harm_multiplier", 1.0)),
            "violation_cost_inr": float(manifest["violation_cost_inr"]),
        },
        "per_regime": per_regime,
    }
