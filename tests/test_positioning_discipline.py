"""Keep the competitive positioning and its honesty markers from rotting.

The positioning is load bearing for this submission: it concedes, in the first
line of the README, that Razorpay already ships recovery for UPI AutoPay, and
it stakes the project on the evaluation layer instead. That concession is the
part most likely to be quietly deleted during a late edit, because it reads as
a weakness. It is not a weakness, it is the reason the rest of the argument is
credible, and these tests fail if it disappears.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Claims this project must never make. Each would be either false or
# unsupportable, and any one of them invites a judge to discard the rest.
FORBIDDEN_CLAIMS = [
    "razorpay lacks",
    "razorpay does not have subscription recovery",
    "razorpay has no recovery",
    "the only solution",
    "first ever",
    "world's first",
    "guaranteed recovery",
    "production revenue recovered",
    # Absolute claims about a self-selected complaint sample. The evidence
    # supports a statement about what the sampled sources contained; it does
    # not support a statement about every customer everywhere, and a judge
    # who spots the overreach is right to discount the rest.
    "nobody is filing complaints",
    "no one is filing complaints",
    # Design inspiration is not integration. Any of these would be false.
    "rillet integration",
    "integrates with rillet",
    "powered by rillet",
    "built on rillet",
    "rillet mcp",
]

SHIPPED_DOCS = [
    "README.md",
    "FINDINGS.md",
    "ARCHITECTURE.md",
    "VIDEO_SCRIPT.md",
    "docs/competitive_position.md",
    "docs/problem_evidence.md",
    "docs/submission_checklist.md",
    "docs/system_spec.md",
    "docs/panel_qa.md",
]

# Stale arm/test/mutation counts a hostile reviewer actually caught in this
# repository: the arm count went 8 -> 9 when RZP was added, the test count
# drifted through 120 -> 189 -> 198 -> 209 -> 210 as coverage grew, and the
# mutation count went 8 -> 13 -> 14. Any of these strings reappearing means
# someone hand-typed a count instead of checking it, which is exactly the
# mistake that made a judge distrust the rest of a submission's numbers.
STALE_COUNT_STRINGS = [
    "eight arm",
    "eight polic",
    "eight recovery polic",
    "eight rows of receipts",
    "eight columns of captions",
    "all eight arms",
    "120 tests",
    "135 tests",
    "189 test",
    "198 test",
    "209 test",
    "210 test",
    "8/8 mutation",
    "eight deliberately reintroduced",
    "eight known defects",
    "13/13 mutation",
    # 283 -> 292 when the ingress replay, non-ASCII signature, out-of-order
    # cancellation, route reason-gating, and live-credential fixes landed
    # with regression tests.
    "283 test",
    "283-test",
]

STALE_COUNT_SURFACE = SHIPPED_DOCS + [
    "docs/system_spec_review.md",
    "docs/panel_qa.md",
    "app.py",
    "scripts/demo60.py",
    "scripts/demo.sh",
]


@pytest.mark.parametrize("needle", STALE_COUNT_STRINGS)
def test_no_shipped_surface_states_a_known_stale_count(needle):
    offenders = []
    for name in STALE_COUNT_SURFACE:
        path = ROOT / name
        if not path.exists():
            continue
        text = _normalise(path.read_text(encoding="utf-8"))
        if needle in text:
            offenders.append(name)
    assert not offenders, f"stale count {needle!r} found in {offenders}"


# A document may legitimately QUOTE a forbidden claim in order to forbid it.
# The claims discipline sections do exactly that, so a line that is itself a
# prohibition is not an assertion of the claim it names.
PROHIBITION_MARKERS = (
    "do not",
    "don't",
    "never",
    "must not",
    "cannot say",
    "it does not lack",
    "does not claim",
    "does not say",
    "not claim that",
)


def _normalise(text: str) -> str:
    """Lowercase and strip markdown emphasis so a bolded word still matches."""
    return text.lower().replace("**", "").replace("*", "").replace("`", "")


def _shipped_lines() -> list[tuple[str, str]]:
    out = []
    for name in SHIPPED_DOCS:
        path = ROOT / name
        if path.exists():
            for line in _normalise(path.read_text(encoding="utf-8")).splitlines():
                out.append((name, line))
    return out


@pytest.mark.parametrize("claim", FORBIDDEN_CLAIMS)
def test_no_shipped_document_asserts_a_forbidden_claim(claim):
    offenders = [
        f"{name}: {line.strip()[:90]}"
        for name, line in _shipped_lines()
        if claim in line and not any(marker in line for marker in PROHIBITION_MARKERS)
    ]
    assert not offenders, f"forbidden claim {claim!r} is asserted in {offenders}"


def test_the_negative_result_is_locked_not_smoothed():
    """The rival arm must be shown winning where it actually wins.

    FINDINGS.md states that reason gating alone is competitive under the flat
    per-breach charge. That is the honest negative result of this benchmark,
    and it would be easy to lose in a rewrite that only kept the flattering
    half. This test asserts, from the shipped economics, that a non-guarded
    arm is the flat-cost recommendation in at least one regime AND a guarded
    arm is the harm-priced recommendation in at least one regime — both sides
    of the crossover, locked.
    """
    import json

    breakeven_path = ROOT / "outputs" / "breakeven.json"
    if not breakeven_path.exists():
        pytest.skip("outputs/breakeven.json is generated by scripts/evaluate.sh")
    analysis = json.loads(breakeven_path.read_text())
    guarded = {"B2", "B3"}
    flat_recommendations = {
        regime: item["recommended_arm_at_configured_cost"]
        for regime, item in analysis["per_regime"].items()
    }
    harm_recommendations = {
        regime: item["recommended_arm_at_harm_price"]
        for regime, item in analysis["per_regime"].items()
    }
    assert any(arm not in guarded for arm in flat_recommendations.values()), (
        f"no regime recommends a non-guarded arm at flat cost ({flat_recommendations}); "
        "either the fixture regressed or the negative result was smoothed away"
    )
    assert any(arm in guarded for arm in harm_recommendations.values()), (
        f"no regime recommends a guarded arm at harm price ({harm_recommendations}); "
        "the substantive crossover claim no longer holds on the shipped outputs"
    )


def test_the_competitive_position_document_exists():
    assert (ROOT / "docs" / "competitive_position.md").exists()


def test_the_problem_evidence_document_exists():
    assert (ROOT / "docs" / "problem_evidence.md").exists()


def test_readme_concedes_razorpay_already_ships_recovery():
    """The concession is the credibility. Losing it costs more than it saves."""
    text = _normalise((ROOT / "README.md").read_text())
    assert "razorpay already ships recovery" in text
    assert "not a recovery engine" in text


def test_competitive_position_states_what_would_weaken_it():
    """A position with no stated failure condition is marketing, not analysis."""
    text = _normalise((ROOT / "docs" / "competitive_position.md").read_text())
    assert "what would weaken this position" in text
    assert "revenue-protect" in text


def test_problem_evidence_states_its_sampling_caveat_before_its_numbers():
    """Self-selected samples must be labelled as such, above the figures."""
    lowered = _normalise((ROOT / "docs" / "problem_evidence.md").read_text())
    assert "self-selected" in lowered
    caveat_at = lowered.find("self-selected")
    first_figure_at = lowered.find("3,556")
    assert caveat_at != -1 and first_figure_at != -1
    assert caveat_at < first_figure_at, "the sampling caveat must precede the figures"


def test_problem_evidence_disclaims_feeding_the_benchmark():
    """Complaint data must never be mistaken for an input to the ledger."""
    text = _normalise((ROOT / "docs" / "problem_evidence.md").read_text())
    assert "not an input to any number" in text
    assert "does not establish" in text


def test_video_script_does_not_open_on_a_recovery_number():
    """The ungated arms beat the guarded arms on recovery. Leading with it loses."""
    text = _normalise((ROOT / "VIDEO_SCRIPT.md").read_text(encoding="utf-8"))
    assert "do not open with a recovery number" in text


def test_the_webhook_attack_count_matches_the_real_suite():
    """The same rot that hit demo60.py, one document over.

    README and docs/panel_qa.md both state how many ways the webhook boundary
    is attacked. That number was written by hand and drifted: both said 37
    while tests/test_webhook_ingress.py actually collected 39. A reviewer who
    checks one number and finds it wrong stops believing the rest, so the
    claim is re-derived from the real suite on every run instead of trusted.
    """
    import re as _re
    import subprocess
    import sys as _sys

    collected = subprocess.run(
        [_sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_webhook_ingress.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    real = _re.search(r"(\d+) tests? collected", collected)
    assert real, "could not determine the real webhook test count"
    real_count = int(real.group(1))

    claims = {
        "README.md": r"attacks this boundary (\d+) ways",
        "docs/panel_qa.md": r"attacked (\d+) ways in tests",
    }
    for name, pattern in claims.items():
        text = (ROOT / name).read_text()
        found = _re.search(pattern, text)
        assert found, f"{name} must state the webhook attack count in a matchable form"
        assert int(found.group(1)) == real_count, (
            f"{name} claims {found.group(1)} webhook attacks but "
            f"tests/test_webhook_ingress.py collects {real_count}"
        )
