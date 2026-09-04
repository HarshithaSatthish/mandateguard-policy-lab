"""Plot the recovery/harm frontier for every policy arm.

The chart answers one question: what does an arm's extra recovery cost in
prohibited debits? Harm is on the horizontal axis because harm is the
thing the guardrails exist to prevent, and it is drawn in rupees rather
than in violation counts because a flat count is indifferent to the size
of the debit it is counting.

The front is the set of arms no other arm beats on both axes at once.
Naming an arm dominated is a stronger and more falsifiable claim than
saying it scored lower, so dominated arms are drawn hollow and called out.
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

import json
from pathlib import Path

from bailiff.chartstyle import (
    GROTESK,
    GUARD,
    INK,
    INK_SOFT,
    RULE,
    apply_style,
    arm_color,
    colophon,
    dominated_arms,
    hairline_axes,
    is_emphasised,
    money_ticks,
    pareto_front,
    place_labels,
    role_legend,
    sqrt_money_scale,
    titleblock,
    use_money_axis,
)
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"


def main() -> int:
    manifest = json.loads((OUTPUTS / "manifest.json").read_text())
    aggregates = json.loads((OUTPUTS / "aggregate.json").read_text())
    arms = list(manifest["arms"])
    regimes = list(manifest["regimes"])
    by_key = {(row["regime"], row["arm"]): row for row in aggregates}

    apply_style()
    figure, axes = plt.subplots(1, len(regimes), figsize=(14.5, 5.9))
    if len(regimes) == 1:
        axes = [axes]

    dominated_everywhere: set[str] | None = None

    for axis, regime in zip(axes, regimes):
        coords = {
            arm: (
                float(by_key[(regime, arm)]["realized_harm_inr"]["mean"]),
                float(by_key[(regime, arm)]["incremental_recovered_inr"]["mean"]),
            )
            for arm in arms
        }
        dominated = set(dominated_arms(coords))
        dominated_everywhere = dominated if dominated_everywhere is None else dominated_everywhere & dominated

        xs = [x for x, _ in coords.values()]
        ys = [y for _, y in coords.values()]
        y_span = max(ys) - min(ys) or 1.0

        hairline_axes(axis)
        sqrt_money_scale(axis, ticks=money_ticks(max(xs)))
        # Headroom on the right is label room: the zero harm arms stack their
        # labels beside the axis and must not run into the diagnostic arms.
        axis.set_xlim(-max(xs) * 0.012, max(xs) * 1.34)
        axis.set_ylim(min(ys) - y_span * 0.11, max(ys) + y_span * 0.17)

        # The zero harm line is the whole point of the guarded arms, so it is
        # marked rather than left to coincide with the axis.
        axis.axvline(0, color=RULE, linewidth=0.8, linestyle=(0, (2, 3)), zorder=1)

        front = pareto_front(list(coords.values()))
        axis.plot(
            [x for x, _ in front],
            [y for _, y in front],
            color=INK_SOFT,
            linewidth=1.0,
            zorder=2,
            solid_capstyle="round",
        )

        for arm, (x, y) in coords.items():
            color = arm_color(arm)
            on_front = arm not in dominated
            # Two arms can sit at the same coordinates: the guarded arms both
            # reach exactly zero harm and differ only in recovery. Dominated
            # markers are drawn larger and on top so their ring encircles the
            # arm that dominates them instead of disappearing underneath it.
            axis.scatter(
                x,
                y,
                s=(96 if is_emphasised(arm) else 68) if not on_front else (64 if is_emphasised(arm) else 40),
                facecolor=color if on_front else "none",
                edgecolor=color if on_front else color,
                linewidths=1.3 if on_front else 1.2,
                zorder=5 if on_front else 6,
            )

        place_labels(
            axis,
            [
                (x, y, arm, arm_color(arm), is_emphasised(arm))
                for arm, (x, y) in coords.items()
            ],
        )

        if regime == regimes[0]:
            guarded_y = max(coords[arm][1] for arm in coords if is_emphasised(arm))
            axis.annotate(
                "B3 dominates B2:\nsame zero harm,\nmore recovery",
                xy=(0, guarded_y),
                xytext=(0.54, 0.17),
                textcoords="axes fraction",
                fontsize=7.8,
                color=GUARD,
                linespacing=1.5,
                arrowprops=dict(
                    arrowstyle="-",
                    color=GUARD,
                    linewidth=0.7,
                    shrinkA=2,
                    shrinkB=9,
                    alpha=0.55,
                ),
                zorder=7,
            )

        axis.set_title(
            regime.replace("_", " ").title(),
            fontfamily=GROTESK,
            color=INK,
            pad=12,
            loc="left",
        )
        axis.set_xlabel("Prohibited value actually moved  (INR, square-root scale)")
        use_money_axis(axis, "y")

    axes[0].set_ylabel("Incremental recovered  (INR)")

    dominated_note = "Hollow markers are dominated: another arm recovers more while moving no more prohibited value."
    if dominated_everywhere:
        ordered = sorted(dominated_everywhere, key=arms.index)
        listed = (
            ", ".join(ordered[:-1]) + " and " + ordered[-1] if len(ordered) > 1 else ordered[0]
        )
        dominated_note = (
            f"Hollow markers are dominated in every regime ({listed}): another arm recovers "
            f"more while moving no more prohibited value."
        )

    titleblock(
        figure,
        "Extra recovery is bought with prohibited debits",
        "Every arm on the same frozen ledger. The line is the front: arms no other arm beats on both axes at once.",
    )
    role_legend(figure, ["control", "ungated", "documented", "diagnostic", "guarded"], y=0.085)
    figure.tight_layout(rect=(0.02, 0.15, 0.98, 0.855))
    colophon(figure, dominated_note, y=0.043)
    colophon(
        figure,
        "Generated from aggregate.json. Simulated counterfactual values from a synthetic ledger, not production revenue. "
        "The square-root horizontal scale preserves order and zero; only the spacing between arms changes.",
        y=0.016,
    )

    output = OUTPUTS / "frontier.png"
    figure.savefig(output, metadata={"Software": "MandateGuard Policy Lab", "Date": None})
    plt.close(figure)
    print(output)
    if dominated_everywhere:
        print(f"dominated in every regime: {sorted(dominated_everywhere, key=arms.index)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
