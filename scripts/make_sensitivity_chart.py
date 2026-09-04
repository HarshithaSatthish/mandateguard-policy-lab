"""Plot how the recommended arm depends on the price of a prohibited action.

The single most contestable number in this project is what a prohibited
action costs. This chart refuses to hide that behind one configured value:
it sweeps the price and draws where the ordering flips.

Arms are labelled at the end of their own line rather than in a legend.
With eight series, a legend forces the reader to match colour to name
eight times before they can read anything; a label on the line is read
once, in place.
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

import matplotlib.pyplot as plt

from bailiff.chartstyle import (
    GROTESK,
    GUARD,
    INK,
    INK_MID,
    MONO,
    RULE,
    apply_style,
    arm_color,
    colophon,
    hairline_axes,
    is_emphasised,
    place_labels,
    role_legend,
    titleblock,
    use_money_axis,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

# The decision boundary lives in the low multiplier region. The full grid
# stays in sensitivity.json; drawing to 10x would flatten every line that
# matters into the axis.
PLOT_MULTIPLIER_LIMIT = 3.0


def main() -> int:
    manifest = json.loads((OUTPUTS / "manifest.json").read_text())
    sensitivity = json.loads((OUTPUTS / "sensitivity.json").read_text())
    regimes = list(manifest["regimes"])
    arms = list(manifest["arms"])
    full_grid = sensitivity["grids"]["harm_multiplier"]
    configured = float(sensitivity["configured"]["harm_multiplier"])

    keep = [index for index, value in enumerate(full_grid) if value <= PLOT_MULTIPLIER_LIMIT]
    grid = [full_grid[index] for index in keep]

    apply_style()
    figure, axes = plt.subplots(1, len(regimes), figsize=(14.5, 5.9))
    if len(regimes) == 1:
        axes = [axes]

    for axis, regime in zip(axes, regimes):
        item = sensitivity["per_regime"][regime]
        curve = item["harm_multiplier_curve"]
        crossover = item["guarded_arm_wins_at_harm_multiplier"]

        series = {
            arm: [curve[index]["net_value_by_arm_inr"][arm] for index in keep]
            for arm in arms
        }

        # Frame the region where the lines actually cross each other, which is
        # the only part of the chart that carries a decision. The ungated
        # baseline falls away so steeply that framing it whole would flatten
        # every crossing into a single band; it leaves the frame and the
        # colophon says so.
        band = [value for arm, values in series.items() if arm != "B1" for value in values]
        headroom = max(band) or 1.0
        axis.set_ylim(-0.95 * headroom, 1.28 * headroom)
        axis.set_xlim(grid[0] - 0.10, grid[-1] + 0.55)

        hairline_axes(axis)
        use_money_axis(axis, "y")

        if crossover is not None and crossover <= PLOT_MULTIPLIER_LIMIT:
            axis.axvspan(crossover, grid[-1], color=GUARD, alpha=0.05, zorder=0)
            axis.axvline(crossover, color=GUARD, linewidth=0.8, alpha=0.5, zorder=1)

        axis.axhline(0, color=RULE, linewidth=0.8, zorder=1)
        axis.axvline(configured, color=INK_MID, linewidth=0.7, linestyle=(0, (2, 3)), zorder=1)

        for arm in arms:
            emphasise = is_emphasised(arm)
            axis.plot(
                grid,
                series[arm],
                color=arm_color(arm),
                linewidth=2.0 if emphasise else 1.1,
                alpha=1.0 if emphasise else 0.85,
                zorder=4 if emphasise else 3,
                solid_capstyle="round",
            )

        place_labels(
            axis,
            [
                (grid[-1], series[arm][-1], arm, arm_color(arm), is_emphasised(arm))
                for arm in arms
            ],
            x_pad_frac=0.030,
            min_gap_frac=0.050,
            near_frac=1.0,
        )

        axis.annotate(
            f"configured {configured:.2f}×",
            (configured, axis.get_ylim()[1]),
            xytext=(4, -10),
            textcoords="offset points",
            fontsize=7.4,
            color=INK_MID,
            va="top",
        )
        if crossover is not None and crossover <= PLOT_MULTIPLIER_LIMIT:
            axis.annotate(
                f"a guarded arm wins from {crossover:.2f}×",
                (crossover, axis.get_ylim()[0]),
                xytext=(6, 12),
                textcoords="offset points",
                fontsize=7.8,
                color=GUARD,
                va="bottom",
            )

        axis.set_title(
            regime.replace("_", " ").title(),
            fontfamily=GROTESK,
            color=INK,
            pad=12,
            loc="left",
        )
        axis.set_xlabel("Cost of a prohibited action, as a multiple of the amount it moved")
        axis.set_xticks([value for value in grid if value in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)])
        axis.xaxis.set_major_formatter(lambda value, _pos: f"{value:g}×")
        for label in axis.get_xticklabels():
            label.set_fontfamily(MONO)

    axes[0].set_ylabel("Mean net value  (INR)")

    titleblock(
        figure,
        "Whether the guardrails are worth it depends on one price",
        "The same frozen run, re-priced. No arm is re-executed, so every point reads the same ledger and the same decisions.",
    )
    role_legend(figure, ["control", "ungated", "documented", "diagnostic", "guarded"], y=0.085)
    figure.tight_layout(rect=(0.02, 0.15, 0.98, 0.855))
    colophon(
        figure,
        f"Drawn to {PLOT_MULTIPLIER_LIMIT:g}× and clipped so the crossover stays legible; the ungated baseline B1 continues below the frame "
        f"and the full grid to {full_grid[-1]:g}× is in sensitivity.json.",
        y=0.043,
    )
    colophon(
        figure,
        "Generated from sensitivity.json. Simulated counterfactual values from a synthetic ledger, not production revenue.",
        y=0.016,
    )

    output = OUTPUTS / "sensitivity.png"
    figure.savefig(output, metadata={"Software": "MandateGuard Policy Lab", "Date": None})
    plt.close(figure)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
