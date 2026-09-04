"""Guard the verification tooling itself against silent rot.

A mutation check whose anchor text has drifted reports success while testing
nothing, and a sweep that crashes is discovered at the worst possible moment.
These tests keep both honest without paying their full runtime.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    """Import a script by path.

    The module must be registered in sys.modules before it executes: dataclasses
    resolves a class's module during decoration, and an unregistered module makes
    that lookup fail.
    """
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def test_every_mutation_anchor_still_exists_in_the_source():
    """A drifted anchor makes the mutation check silently vacuous."""
    mutation_check = _load("mutation_check")
    missing = []
    for mutation in mutation_check.MUTATIONS:
        text = (ROOT / mutation.path).read_text()
        if mutation.old not in text:
            missing.append(f"{mutation.name} -> {mutation.path}")
    assert not missing, (
        "Mutation anchors no longer match the source, so the mutation check is "
        f"not testing what it claims: {missing}"
    )


def test_mutations_actually_change_the_source():
    """An anchor equal to its replacement would be a no-op mutation."""
    mutation_check = _load("mutation_check")
    for mutation in mutation_check.MUTATIONS:
        assert mutation.old != mutation.new, f"{mutation.name} is a no-op"


def test_mutation_check_covers_the_safety_critical_modules():
    """Each module carrying a safety claim must have at least one mutation."""
    mutation_check = _load("mutation_check")
    covered = {mutation.path for mutation in mutation_check.MUTATIONS}
    for required in (
        "bailiff/guardrails.py",
        "bailiff/domain.py",
        "bailiff/policies.py",
        "bailiff/metrics.py",
        "bailiff/fixtures.py",
        "bailiff/webhook.py",
    ):
        assert required in covered, f"no mutation exercises {required}"


def test_mutation_scratch_copy_carries_everything_the_suite_needs(tmp_path):
    """The scratch copy must be able to go green with no mutation applied.

    An earlier revision excluded `outputs/` from the copy while keeping
    `SHA256SUMS.txt`, so the chart checksum tests failed in every scratch
    copy and every mutation was reported "caught" whether or not any test
    could detect it. The baseline control run in `main()` is the full
    defence; this test keeps its precondition from silently regressing.
    """
    mutation_check = _load("mutation_check")
    target = mutation_check.copy_tree(tmp_path)
    for required in (
        "SHA256SUMS.txt",
        "outputs/manifest.json",
        "outputs/aggregate.json",
        "outputs/architecture.png",
        "outputs/frontier.png",
        "outputs/sensitivity.png",
        "tests/test_chart_checksum_policy.py",
    ):
        assert (target / required).exists(), (
            f"{required} is missing from the mutation scratch copy, so the "
            "suite cannot pass unmutated and every mutation verdict is vacuous"
        )
    assert "def main" in (ROOT / "scripts" / "mutation_check.py").read_text()
    source = (ROOT / "scripts" / "mutation_check.py").read_text()
    assert "BASELINE FAILED" in source, (
        "mutation_check.py must run a baseline control: without it a scratch "
        "copy that fails for an unrelated reason marks every mutation caught"
    )


def test_fixture_sweep_restores_the_baseline_assumptions():
    """The sweep mutates module globals. Leaking them would corrupt later runs."""
    from bailiff import fixtures

    sweep = _load("fixture_sensitivity")
    before = dict(fixtures.HARM_PROBABILITY_BY_STATE)
    before_opt_out = fixtures.INDEPENDENT_OPT_OUT_RATE
    before_blocked = fixtures.INDEPENDENT_BLOCKED_MANDATE_RATE

    sweep._apply(0.25, 3.0)
    assert fixtures.HARM_PROBABILITY_BY_STATE != before
    sweep._restore()

    assert fixtures.HARM_PROBABILITY_BY_STATE == before
    assert fixtures.INDEPENDENT_OPT_OUT_RATE == before_opt_out
    assert fixtures.INDEPENDENT_BLOCKED_MANDATE_RATE == before_blocked


def test_sweep_never_rescales_a_terminal_reason():
    """Terminal harm is a definition, not a calibration. Scaling it is a category error."""
    from bailiff import fixtures

    sweep = _load("fixture_sensitivity")
    try:
        sweep._apply(0.25, 1.0)
        assert fixtures.HARM_PROBABILITY_BY_STATE["terminal_reason"] == 1.00
        sweep._apply(2.00, 1.0)
        assert fixtures.HARM_PROBABILITY_BY_STATE["terminal_reason"] == 1.00
    finally:
        sweep._restore()


def test_robustness_document_is_present_and_generated():
    """The shipped robustness claims must exist and say they were generated."""
    path = ROOT / "ROBUSTNESS.md"
    if not path.exists():
        pytest.skip("ROBUSTNESS.md is generated by scripts/fixture_sensitivity.py")
    text = path.read_text()
    assert "scripts/fixture_sensitivity.py" in text
    assert "Falsification" in text
