"""Keep the sixty second demo from rotting into a false proof.

An earlier version of `scripts/demo60.py` pinned a fixed demo date. Once the
wall clock passed it every mandate expired, so the runtime refused everything —
including the case the demo narrates as permitted — while the script cheerfully
printed a hardcoded "1 provider call" beside it. That is the worst failure mode
available to a demo: confidently asserting a proof it is no longer producing.

These tests execute the demo's own code paths and assert the outcomes it claims
on screen, so the claims and the runtime cannot drift apart again.
"""

from __future__ import annotations

import importlib.util
import io
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_demo():
    spec = importlib.util.spec_from_file_location("demo60", ROOT / "scripts" / "demo60.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo60"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("demo60", None)
        raise
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


def test_the_permitted_case_really_makes_exactly_one_provider_call(demo):
    """The claim on screen in step 5. If this fails the demo is lying."""
    run = demo.decide(demo.build_event("t_allowed"))
    assert run.provider_result is not None, (
        f"the demo's permitted case was refused: {run.decision.reason_codes}"
    )
    assert run.decision.final_action is not None
    assert run.provider_result.postcondition_state == "RECOVERED"


def test_the_refused_case_really_makes_zero_provider_calls(demo):
    """The claim on screen in step 4, and the whole thesis of the project."""
    run = demo.decide(
        demo.build_event(
            "t_revoked",
            mandate_state="revoked",
            normalized_failure_reason="MANDATE_REVOKED_OR_CANCELLED",
        ),
        harmful=True,
    )
    assert run.provider_result is None
    assert run.audit_verified


def test_no_demo_case_is_refused_merely_because_it_expired(demo):
    """The exact rot that broke this demo before. EVENT_EXPIRED is never the point."""
    run = demo.decide(demo.build_event("t_fresh"))
    assert "EVENT_EXPIRED" not in run.decision.reason_codes


def test_the_demo_retry_lands_in_a_non_peak_window(demo):
    """A retry refused on timing would tell the wrong story in step 5."""
    run = demo.decide(demo.build_event("t_timing"))
    assert "RETRY_OUTSIDE_NON_PEAK_WINDOW" not in run.decision.reason_codes
    assert "PEAK_WINDOW" not in " ".join(run.decision.reason_codes)


def test_the_ambiguous_case_really_abstains_with_zero_provider_calls(demo):
    """The claim on screen in step 6."""
    run = demo.decide(
        demo.build_event(
            "t_ambiguous",
            failure_code="XX99",
            failure_payload={"code": "XX99", "description": "unmapped error", "conflict": "true"},
            normalized_failure_reason="UNKNOWN_OR_CONFLICTING",
        ),
        arm="B3",
    )
    assert "ABSTAIN" in run.decision.reason_codes
    assert run.provider_result is None


def test_the_demo_runs_end_to_end_and_states_its_scope(demo):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        assert demo.main() == 0
    plain = re.sub(r"\x1b\[[0-9]*m", "", buffer.getvalue())

    # The proof beats a judge is told to look for.
    assert "SIGNATURE_MISMATCH" in plain
    assert "VERIFIED" in plain
    assert "DUPLICATE_DELIVERY_IGNORED" in plain
    assert "ABSTAIN" in plain
    assert "before=True after=False" in plain

    # The scope disclaimer must survive every edit.
    assert "No Razorpay API is called" in plain
    assert "not an official NPCI taxonomy" in plain


def test_the_demo_never_prints_a_hardcoded_provider_call_count():
    """Guard the specific dishonesty that occurred: an asserted count."""
    source = (ROOT / "scripts" / "demo60.py").read_text()
    assert 'line("provider calls", "1"' not in source
    assert 'line("provider calls", "0"' not in source


def test_the_closing_test_and_mutation_count_matches_reality():
    """The exact class of bug a hostile reviewer caught: `demo60.py` claimed

    135 tests and 8/8 mutations while the suite actually had 189 (then 209)
    tests and 14 mutations. A wrong number here does not just embarrass one
    line, it makes a judge distrust every other number in the submission. So
    the printed line is checked against the real, live count on every run
    rather than trusted as prose.
    """
    import subprocess
    import sys as _sys

    source = (ROOT / "scripts" / "demo60.py").read_text()
    match = re.search(r'"\s*(\d+) tests, (\d+) red team attacks, (\d+)/(\d+) mutations caught"', source)
    assert match, "demo60.py must state its closing counts as a single matchable line"
    claimed_tests, claimed_attacks, claimed_caught, claimed_total = (int(g) for g in match.groups())

    collected = subprocess.run(
        [_sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    total_match = re.search(r"(\d+) tests? collected", collected)
    assert total_match, "could not determine the real collected test count"
    assert claimed_tests == int(total_match.group(1)), (
        f"demo60.py claims {claimed_tests} tests but the suite actually collects "
        f"{total_match.group(1)} — update the printed line"
    )

    attack_collected = subprocess.run(
        [_sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_adversarial.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    attack_match = re.search(r"(\d+) tests? collected", attack_collected)
    assert attack_match and claimed_attacks == int(attack_match.group(1)), (
        "demo60.py's red-team attack count must match tests/test_adversarial.py's real size"
    )

    spec = importlib.util.spec_from_file_location(
        "mutation_check_for_demo60_test", ROOT / "scripts" / "mutation_check.py"
    )
    mutation_module = importlib.util.module_from_spec(spec)
    # Registering in sys.modules before exec matters: the dataclass in this
    # module resolves its own type hints via sys.modules[cls.__module__] at
    # import time, and crashes if the module cannot find itself there.
    sys.modules[spec.name] = mutation_module
    try:
        spec.loader.exec_module(mutation_module)
    finally:
        sys.modules.pop(spec.name, None)
    real_total = len(mutation_module.MUTATIONS)
    assert claimed_total == real_total, (
        f"demo60.py claims {claimed_total} mutations but scripts/mutation_check.py "
        f"defines {real_total} — update the printed line"
    )
    assert claimed_caught == claimed_total, (
        "demo60.py must only ever claim every defined mutation was caught; "
        "run scripts/mutation_check.py to confirm before changing this line"
    )
