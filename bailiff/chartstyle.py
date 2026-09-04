"""One visual system for every generated chart.

The project's argument is that a refusal is a product feature and that
every decision leaves a receipt. The charts are drawn to carry that
argument rather than to decorate it, so the system is an audit document:
warm ink on warm paper, hairline rules instead of boxed panels, tabular
figures, and colour spent only where it means something.

Colour discipline
-----------------
Two accents, derived in OKLCH at identical lightness and chroma so they
carry equal visual weight and differ only in hue. One marks the fully
guarded arms, one marks the ungated baselines. Everything else is
neutral ink. A reader's eye therefore lands on the comparison the
benchmark exists to make, and no arm is flattered by being brighter.

Type
----
Three families, each with a job and none of them a default UI face:

- TeX Gyre Pagella carries titles. It is a Palatino cut: a document
  voice rather than a dashboard voice.
- TeX Gyre Heros carries labels and recedes behind the data.
- DejaVu Sans Mono carries every number. Monospace figures are tabular
  by construction, so columns of rupee values line up on the decimal,
  and it is the only family installed here that actually contains the
  rupee sign. Setting a rupee value in the serif would silently render
  a missing glyph box, so anything containing the sign is set in mono
  explicitly.
"""

from __future__ import annotations

import logging
from math import cos, radians, sin
from typing import Iterable, Sequence

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

SERIF = ["TeX Gyre Pagella", "Palatino", "DejaVu Serif", "serif"]
GROTESK = ["TeX Gyre Heros", "Helvetica", "DejaVu Sans", "sans-serif"]
MONO = ["DejaVu Sans Mono", "Liberation Mono", "monospace"]


def oklch(lightness: float, chroma: float, hue_degrees: float) -> str:
    """Convert an OKLCH colour to an sRGB hex string.

    Working in OKLCH rather than picking hex by eye is what makes the two
    accents genuinely equal in weight: they are specified at the same
    lightness and chroma, so neither can shout louder than the other.
    """
    hue = radians(hue_degrees)
    a = chroma * cos(hue)
    b = chroma * sin(hue)

    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3

    linear = (
        +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )

    def encode(channel: float) -> int:
        channel = max(0.0, min(1.0, channel))
        srgb = 12.92 * channel if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055
        return round(max(0.0, min(1.0, srgb)) * 255)

    return "#{:02x}{:02x}{:02x}".format(*(encode(c) for c in linear))


# Paper and ink. Warm, and desaturated well below the 0.02 ceiling so the
# ground never reads as a colour of its own.
PAPER = oklch(0.988, 0.004, 85)
INK = oklch(0.245, 0.010, 60)
INK_MID = oklch(0.530, 0.010, 60)
INK_SOFT = oklch(0.700, 0.008, 60)
RULE = oklch(0.895, 0.006, 75)
RULE_FAINT = oklch(0.945, 0.005, 75)

# The two accents: same lightness, same chroma, opposed hues.
GUARD = oklch(0.460, 0.105, 255)
RISK = oklch(0.460, 0.105, 35)

ARM_ROLE = {
    "B0": "control",
    "B1": "ungated",
    "B1.5": "ungated",
    "RZP": "documented",
    "B2.25": "diagnostic",
    "B2.5": "diagnostic",
    "B2.75": "diagnostic",
    "B2": "guarded",
    "B3": "guarded",
}
ROLE_COLOR = {
    "control": INK_SOFT,
    "ungated": RISK,
    "documented": INK,
    "diagnostic": INK_MID,
    "guarded": GUARD,
}
ROLE_LABEL = {
    "control": "No intervention control",
    "ungated": "Ungated baselines",
    "documented": "Razorpay documented retry model",
    "diagnostic": "Diagnostic frontier arms",
    "guarded": "Fully guarded arms",
}


def arm_color(arm: str) -> str:
    return ROLE_COLOR[ARM_ROLE[arm]]


def is_emphasised(arm: str) -> bool:
    return ARM_ROLE[arm] == "guarded"


def apply_style() -> None:
    # The stacks name Helvetica and Palatino ahead of the TeX Gyre clones so a
    # machine that has the real faces uses them. Machines that do not would
    # otherwise emit one findfont warning per text object, which buries real
    # warnings in the release output, so that logger is quieted rather than
    # the fallbacks removed.
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    plt.rcParams.update(
        {
            "font.family": GROTESK,
            "font.size": 9,
            "figure.dpi": 120,
            "savefig.dpi": 200,
            "figure.facecolor": PAPER,
            "axes.facecolor": PAPER,
            "savefig.facecolor": PAPER,
            "text.color": INK,
            "axes.labelcolor": INK_MID,
            "xtick.color": INK_MID,
            "ytick.color": INK_MID,
            "axes.titlesize": 10,
            "axes.labelsize": 8.5,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8.5,
            "axes.linewidth": 0.6,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "xtick.major.size": 3,
            "ytick.major.size": 3,
            "lines.solid_capstyle": "round",
        }
    )


def hairline_axes(axis, *, ygrid: bool = True) -> None:
    """Strip the panel to two hairlines and, at most, faint horizontal rules.

    A boxed panel on a tinted ground is dashboard furniture. A document
    rules only where a rule carries information.
    """
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axis.spines[side].set_color(RULE)
        axis.spines[side].set_linewidth(0.7)
    if ygrid:
        axis.grid(True, axis="y", color=RULE_FAINT, linewidth=0.7, zorder=0)
    axis.set_axisbelow(True)
    axis.tick_params(length=3, pad=4)


def compact_inr(value: float, _pos: int = 0) -> str:
    """Axis figures without a currency glyph, which the axis label carries instead."""
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1000:
        thousands = value / 1000
        text = f"{thousands:,.0f}k" if abs(thousands - round(thousands)) < 0.05 else f"{thousands:,.1f}k"
    else:
        text = f"{value:,.0f}"
    return text


def sqrt_money_scale(axis, *, ticks: Sequence[float]) -> None:
    """Put money on a square-root axis and tick it at round rupee values.

    One arm in this benchmark moves prohibited value on every harm bearing
    case while the guarded arms move none, so a linear axis spends four
    fifths of its width on empty space and crushes every arm a merchant
    would actually consider into the first tenth. A square root scale is the
    mildest fix that stays honest: it is monotone, it maps zero to zero, and
    unlike a log scale it needs no invented threshold to handle the arms
    sitting exactly at zero. Order and zero are preserved, so no arm can be
    made to look better than it is; only the spacing between them changes,
    and the axis says so.
    """
    axis.set_xscale(
        "function",
        functions=(lambda v: np.sqrt(np.clip(v, 0, None)), lambda v: np.square(v)),
    )
    axis.set_xticks(list(ticks))
    axis.xaxis.set_major_formatter(FuncFormatter(compact_inr))
    for label in axis.get_xticklabels():
        label.set_fontfamily(MONO)


def money_ticks(maximum: float) -> list[float]:
    """Round rupee gridlines that reach just past the largest value."""
    candidates = [0, 1_000, 2_500, 5_000, 10_000, 20_000, 35_000, 50_000, 75_000, 100_000]
    ticks = [tick for tick in candidates if tick <= maximum * 1.08]
    # Near the origin a square-root axis packs the small ticks together. Drop
    # the finest one once the axis is long enough for it to collide.
    if maximum > 20_000 and 1_000 in ticks:
        ticks.remove(1_000)
    return ticks


def money(value: float) -> str:
    """Rupee figures for annotations. Always set this in MONO."""
    return f"₹{value:,.0f}"


def use_money_axis(axis, which: str = "y") -> None:
    formatter = FuncFormatter(compact_inr)
    target = axis.yaxis if which == "y" else axis.xaxis
    target.set_major_formatter(formatter)
    for label in (axis.get_yticklabels() if which == "y" else axis.get_xticklabels()):
        label.set_fontfamily(MONO)


def pareto_front(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """Non-dominated points when minimising x and maximising y.

    On these charts x is harm and y is recovery, so the front is the set
    of arms for which no other arm recovers at least as much while causing
    no more harm. Everything off the front is dominated outright, which is
    a stronger statement than 'scored lower'.
    """
    # Collapse ties on x first. Two arms at identical harm are not both on
    # the front: the one recovering less is dominated outright, and saying so
    # is a stronger statement than saying it scored lower.
    best_at_x: dict[float, float] = {}
    for x, y in points:
        if x not in best_at_x or y > best_at_x[x]:
            best_at_x[x] = y

    front: list[tuple[float, float]] = []
    best_y = float("-inf")
    for x in sorted(best_at_x):
        y = best_at_x[x]
        if y > best_y:
            front.append((x, y))
            best_y = y
    return front


def dominated_arms(by_arm: dict[str, tuple[float, float]]) -> list[str]:
    """Arms for which another arm causes no more harm and recovers at least as much."""
    dominated = []
    for arm, (x, y) in by_arm.items():
        for other, (ox, oy) in by_arm.items():
            if other == arm:
                continue
            if ox <= x and oy >= y and (ox < x or oy > y):
                dominated.append(arm)
                break
    return dominated


def place_labels(
    axis,
    items: Iterable[tuple[float, float, str, str, bool]],
    *,
    x_pad_frac: float = 0.028,
    min_gap_frac: float = 0.075,
    near_frac: float = 0.30,
) -> None:
    """Label every point without letting two labels sit on top of each other.

    Fixed per arm offsets cannot work here: three arms land on exactly zero
    harm and two of them differ by a few hundred rupees on a twenty thousand
    rupee axis, so their labels collide at any zoom. Labels are pushed apart
    vertically, but only against neighbours close enough horizontally to
    actually overlap, and a leader line is drawn whenever a label has been
    moved far enough that its owner would otherwise be ambiguous.
    """
    entries = list(items)
    if not entries:
        return
    x_lo, x_hi = axis.get_xlim()
    y_lo, y_hi = axis.get_ylim()
    x_span = x_hi - x_lo or 1.0
    y_span = y_hi - y_lo or 1.0
    min_gap = y_span * min_gap_frac
    near = x_span * near_frac

    # A series can leave the frame entirely: the ungated baseline's net value
    # dives far below any useful y range. Its true value must not drag the
    # whole layout, so every anchor is first clamped into the visible band and
    # the clamped value is what both the layout and the leader line use.
    inner_lo = y_lo + y_span * 0.035
    inner_hi = y_hi - y_span * 0.035
    anchors = [min(max(entry[1], inner_lo), inner_hi) for entry in entries]

    order = sorted(range(len(entries)), key=lambda i: anchors[i])
    label_y = [anchors[i] for i in order]

    for _ in range(200):
        moved = False
        for k in range(1, len(order)):
            lower, upper = order[k - 1], order[k]
            if abs(entries[upper][0] - entries[lower][0]) > near:
                continue
            gap = label_y[k] - label_y[k - 1]
            if gap < min_gap:
                shift = (min_gap - gap) / 2
                label_y[k - 1] -= shift
                label_y[k] += shift
                moved = True
        if label_y[-1] > inner_hi:
            label_y = [y - (label_y[-1] - inner_hi) for y in label_y]
        if label_y[0] < inner_lo:
            label_y = [y + (inner_lo - label_y[0]) for y in label_y]
        if not moved:
            break

    for k, index in enumerate(order):
        x, _, text, color, emphasise = entries[index]
        y = anchors[index]
        target_y = label_y[k]
        label_x = x + x_span * x_pad_frac
        if abs(target_y - y) > y_span * 0.014:
            axis.plot(
                [x + x_span * 0.008, label_x - x_span * 0.006],
                [y, target_y],
                color=RULE,
                linewidth=0.6,
                zorder=2,
                solid_capstyle="butt",
            )
        axis.annotate(
            text,
            (label_x, target_y),
            va="center",
            ha="left",
            fontsize=8.4 if emphasise else 8,
            fontfamily=MONO,
            color=color,
            weight="bold" if emphasise else "normal",
            zorder=6,
        )


def role_legend(figure, roles: Sequence[str], *, y: float = 0.075) -> None:
    handles = [
        plt.Line2D(
            [],
            [],
            marker="o",
            linestyle="none",
            markersize=6 if role == "guarded" else 5,
            markerfacecolor=ROLE_COLOR[role] if role != "control" else PAPER,
            markeredgecolor=ROLE_COLOR[role],
            markeredgewidth=1.0,
            label=ROLE_LABEL[role],
        )
        for role in roles
    ]
    legend = figure.legend(
        handles=handles,
        loc="lower center",
        ncol=len(handles),
        frameon=False,
        bbox_to_anchor=(0.5, y),
        handletextpad=0.5,
        columnspacing=2.0,
    )
    for text in legend.get_texts():
        text.set_color(INK_MID)


def titleblock(figure, title: str, standfirst: str, *, y: float = 0.955) -> None:
    """A document style heading: a serif line, then one plain sentence."""
    figure.text(
        0.5,
        y,
        title,
        ha="center",
        va="top",
        fontsize=15,
        fontfamily=SERIF,
        color=INK,
    )
    figure.text(
        0.5,
        y - 0.052,
        standfirst,
        ha="center",
        va="top",
        fontsize=9,
        color=INK_MID,
    )


def colophon(figure, text: str, *, y: float = 0.022, color: str | None = None) -> None:
    figure.text(0.5, y, text, ha="center", va="bottom", fontsize=7.2, color=color or INK_SOFT)
