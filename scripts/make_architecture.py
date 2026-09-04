"""Draw the one thing the prose keeps asserting: where the refusal happens.

Every claim in this repository reduces to a position on a line. A denial is
worth something because it occurs *before* the provider boundary, not after it
in a log. That is a spatial fact, and prose is a poor way to carry a spatial
fact, so this draws it.

The diagram uses the same visual system as the charts: warm ink on warm paper,
hairlines instead of boxes-on-tint, and colour spent only where it means
something — blue for a path that refuses, oxblood for the one path that can
move money.
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

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from bailiff.chartstyle import (
    GROTESK,
    GUARD,
    INK,
    INK_MID,
    INK_SOFT,
    MONO,
    PAPER,
    RISK,
    RULE,
    SERIF,
    apply_style,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

STAGES = [
    ("Razorpay\nwebhook", "signed delivery", 6.6, 0.6),
    ("Ingress gate", "HMAC · duplicate\ndelivery order", 6.6, 3.35),
    ("Adapter", "provider signal\n→ project taxonomy", 6.6, 6.1),
    ("Policy arm", "B0 · B1 · B1.5 · RZP\nB2.25 · B2.5 · B2.75\nB2 · B3", 6.2, 8.85),
    ("Guardrail engine", "authority envelope\nconsent · mandate\ntiming · attempts\npre-debit · amount", 6.0, 11.6),
]
BOUNDARY_X = 13.45
PROVIDER_X = 14.75

BOX_W = 2.35
BOX_H = 1.0
MID_Y = 3.5
REFUSED_Y = 1.45
AUDIT_Y = 0.35


def box(ax, x, y, title, subtitle, *, edge, width=BOX_W, height=BOX_H,
        title_color=None, subtitle_size=6.6):
    ax.add_patch(
        FancyBboxPatch(
            (x - width / 2, y - height / 2), width, height,
            boxstyle="round,pad=0.06,rounding_size=0.06",
            linewidth=1.0, edgecolor=edge, facecolor=PAPER, zorder=3,
        )
    )
    ax.text(x, y + 0.20, title, ha="center", va="center", fontsize=9.2,
            fontfamily=GROTESK, color=title_color or INK, zorder=4)
    ax.text(x, y - 0.22, subtitle, ha="center", va="center", fontsize=subtitle_size,
            fontfamily=MONO, color=INK_SOFT, linespacing=1.5, zorder=4)


def arrow(ax, start, end, *, color=INK_MID, style="-|>", dashed=False, width=1.0):
    ax.add_patch(
        FancyArrowPatch(
            start, end, arrowstyle=style, mutation_scale=11,
            linewidth=width, color=color, zorder=2,
            linestyle=(0, (3, 3)) if dashed else "solid",
            shrinkA=3, shrinkB=3,
        )
    )


def main() -> int:
    apply_style()
    figure, ax = plt.subplots(figsize=(15.2, 6.4))
    ax.set_xlim(-0.7, 16.3)
    ax.set_ylim(-0.2, 5.6)
    ax.axis("off")

    figure.text(0.5, 0.955, "Where the refusal happens", ha="center", va="top",
                fontsize=16, fontfamily=SERIF, color=INK)
    figure.text(0.5, 0.902,
                "A denial is evidence only if it occurs before the provider boundary. "
                "Everything left of the dotted line moves no money.",
                ha="center", va="top", fontsize=9, color=INK_MID)

    # The stages, and the arrows between them.
    for index, (title, subtitle, subtitle_size, x) in enumerate(STAGES):
        edge = GUARD if index in (1, 4) else RULE
        box(ax, x, MID_Y, title, subtitle, edge=edge, subtitle_size=subtitle_size,
            title_color=GUARD if index in (1, 4) else INK)
        if index:
            arrow(ax, (STAGES[index - 1][3] + BOX_W / 2, MID_Y), (x - BOX_W / 2, MID_Y))

    # The bounded interpreter sits above the policy arm: consulted only for
    # ambiguity, and holding no provider tools.
    box(ax, 8.85, MID_Y + 1.45, "Bounded interpreter", "ambiguous payloads only\nno provider tools",
        edge=RULE, height=0.9)
    arrow(ax, (8.85, MID_Y + BOX_H / 2), (8.85, MID_Y + 1.45 - 0.45), dashed=True, color=INK_SOFT)
    ax.text(9.10, MID_Y + 0.72, "B3 only", fontsize=6.6, fontfamily=MONO, color=INK_SOFT, va="center")

    # The provider boundary.
    ax.plot([BOUNDARY_X, BOUNDARY_X], [0.75, 5.05], linestyle=(0, (2, 3)),
            color=INK_MID, linewidth=1.1, zorder=1)
    ax.text(BOUNDARY_X, 5.18, "PROVIDER BOUNDARY", ha="center", va="bottom",
            fontsize=7.4, fontfamily=GROTESK, color=INK_MID)

    box(ax, PROVIDER_X, MID_Y, "Provider", "one idempotent call\npostcondition recorded",
        edge=RISK, title_color=RISK, width=1.85)
    arrow(ax, (STAGES[-1][3] + BOX_W / 2, MID_Y), (PROVIDER_X - 1.85 / 2, MID_Y),
          color=RISK, width=1.3)
    ax.text((STAGES[-1][3] + PROVIDER_X) / 2, MID_Y + 0.30, "allow",
            ha="center", fontsize=7, fontfamily=MONO, color=RISK)

    # The two refusal paths, both terminating before the boundary.
    box(ax, 3.35, REFUSED_Y, "Delivery refused", "reason · body hash\nzero provider calls",
        edge=GUARD, title_color=GUARD, height=0.9)
    arrow(ax, (3.35, MID_Y - BOX_H / 2), (3.35, REFUSED_Y + 0.45), color=GUARD)

    box(ax, 11.6, REFUSED_Y, "Action refused", "deny · stop · abstain\nzero provider calls",
        edge=GUARD, title_color=GUARD, height=0.9)
    arrow(ax, (11.6, MID_Y - BOX_H / 2), (11.6, REFUSED_Y + 0.45), color=GUARD)
    ax.text(11.85, (MID_Y + REFUSED_Y) / 2 + 0.05, "deny", fontsize=7,
            fontfamily=MONO, color=GUARD, va="center")

    # Escalation is a real destination, not a synonym for stopping.
    ax.text(11.6, REFUSED_Y - 0.72, "escalate → human review",
            ha="center", fontsize=6.8, fontfamily=MONO, color=INK_SOFT)

    # The audit chain underneath everything.
    ax.add_patch(
        FancyBboxPatch((0.6 - BOX_W / 2, AUDIT_Y - 0.28), PROVIDER_X + 0.9 - (0.6 - BOX_W / 2), 0.56,
                       boxstyle="round,pad=0.04,rounding_size=0.05",
                       linewidth=0.9, edgecolor=RULE, facecolor=PAPER, zorder=1)
    )
    ax.text((0.6 + PROVIDER_X) / 2, AUDIT_Y, "hash-chained audit  ·  every path above writes a receipt, refusals included",
            ha="center", va="center", fontsize=7.6, fontfamily=GROTESK, color=INK_MID, zorder=2)

    figure.text(0.5, 0.028,
                "Razorpay shaped input, local provider simulator, synthetic ledger. "
                "No Razorpay API is called.",
                ha="center", va="bottom", fontsize=7.2, color=INK_SOFT)

    output = OUTPUTS / "architecture.png"
    figure.savefig(output, bbox_inches="tight", pad_inches=0.28,
                   metadata={"Software": "MandateGuard Policy Lab", "Date": None})
    plt.close(figure)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
