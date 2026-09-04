"""Verify the test suite actually catches the bugs it claims to prevent.

A green suite proves nothing on its own: tests that assert the wrong thing,
or that never reach the branch they name, pass just as happily as tests that
work. This script answers the only question that matters about a safety
suite — if the safety property were broken, would anything go red?

Each mutation below reintroduces a specific defect into a scratch copy of the
package, runs the suite against that copy, and records whether the suite
failed. A mutation that SURVIVES is a hole in the tests, not a success.

Two of these mutations are not hypothetical. `forgone_branches_on_final_action`
and `stop_uses_a_symbolic_action` together are the metric comparability bug
this project actually shipped and later fixed; they are kept here so the suite
can never silently lose the ability to detect them again.

Run:
    python3 scripts/mutation_check.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutation:
    name: str
    path: str
    old: str
    new: str
    breaks: str


MUTATIONS = [
    Mutation(
        name="mandate_state_gate_removed",
        path="bailiff/guardrails.py",
        old='elif full_guardrails and event.mandate_state.lower() not in {"active", "enabled"}:',
        new='elif False and event.mandate_state.lower() not in {"active", "enabled"}:',
        breaks="a revoked or paused mandate could be debited",
    ),
    Mutation(
        name="interpreter_reason_not_validated",
        path="bailiff/policies.py",
        old="    FailureReason(reason)\n    if not isinstance(confidence, (int, float))",
        new="    if not isinstance(confidence, (int, float))",
        breaks="an interpreter could return a reason outside the taxonomy",
    ),
    Mutation(
        name="attenuation_may_raise_the_amount",
        path="bailiff/domain.py",
        old='if next_amount > self.max_amount_minor:\n            raise ValueError("Authority attenuation cannot increase amount")',
        new='if False:\n            raise ValueError("Authority attenuation cannot increase amount")',
        breaks="a child envelope could grant itself a larger ceiling",
    ),
    Mutation(
        name="attenuation_may_add_actions",
        path="bailiff/domain.py",
        old='if not next_actions.issubset(self.allowed_actions):\n            raise ValueError("Authority attenuation cannot add actions")',
        new='if False:\n            raise ValueError("Authority attenuation cannot add actions")',
        breaks="a child envelope could grant itself new actions",
    ),
    Mutation(
        name="forgone_branches_on_final_action",
        path="bailiff/metrics.py",
        old="recoverable_forgone = run.event.amount_minor if recoverable and not executed else 0",
        new=(
            "recoverable_forgone = (\n"
            "            run.event.amount_minor\n"
            "            if recoverable and not executed and run.decision.final_action is None\n"
            "            else 0\n"
            "        )"
        ),
        breaks="the forgone metric stops being comparable across arms",
    ),
    Mutation(
        name="confidence_threshold_ignored",
        path="bailiff/guardrails.py",
        old="context.confidence < policy.minimum_interpreter_confidence",
        new="False",
        breaks="a low confidence reading could authorise money movement",
    ),
    Mutation(
        name="consent_gate_removed",
        path="bailiff/guardrails.py",
        old="elif consent_guardrails and event.consent.opted_out and context.proposed_action in {",
        new="elif False and event.consent.opted_out and context.proposed_action in {",
        breaks="an opted out customer could be contacted",
    ),
    Mutation(
        name="webhook_signature_not_verified",
        path="bailiff/webhook.py",
        old="            if hmac.compare_digest(candidate, signature_bytes):",
        new="            if True or hmac.compare_digest(candidate, signature):",
        breaks="a forged webhook could drive the recovery agent",
    ),
    Mutation(
        name="webhook_duplicate_not_detected",
        path="bailiff/webhook.py",
        old="        duplicate = event_id in self._seen_event_ids or body_hash in self._seen_body_hashes",
        new="        duplicate = False",
        breaks="a redelivered event could be acted on twice",
    ),
    Mutation(
        name="webhook_accepts_reserialised_body",
        path="bailiff/webhook.py",
        old="        if not isinstance(raw_body, (bytes, bytearray)):",
        new="        if False:",
        breaks="a re-serialised payload could be verified against the wrong bytes",
    ),
    Mutation(
        name="webhook_ordering_ignored",
        path="bailiff/webhook.py",
        old="            if latest is not None and stamp < latest:",
        new="            if False:",
        breaks="a stale failure could retry a cycle that already settled",
    ),
    Mutation(
        name="terminal_subscription_not_closed",
        path="bailiff/webhook.py",
        old="        if subscription_id in self._ended_subscriptions and event_name not in PERMANENTLY_ENDED_EVENTS:",
        new="        if False:",
        breaks="a cancelled or completed mandate could still be debited by a late event",
    ),
    Mutation(
        name="paused_subscription_not_blocked",
        path="bailiff/webhook.py",
        old=(
            "        if (\n"
            "            subscription_id in self._blocked_subscriptions\n"
            "            and event_name != RESUME_EVENT\n"
            "            and event_name not in PERMANENTLY_ENDED_EVENTS\n"
            "        ):\n"
            "            return \"BLOCKED_SUBSCRIPTION_PAUSED_OR_HALTED\""
        ),
        new="        if False:\n            return \"BLOCKED_SUBSCRIPTION_PAUSED_OR_HALTED\"",
        breaks="a paused or halted subscription could still be debited before it is resumed",
    ),
    Mutation(
        name="harm_conditioned_on_reason_only",
        path="bailiff/fixtures.py",
        old="    if mandate_state.lower() in set(BLOCKED_MANDATE_STATES):\n        states.append(\"blocked_mandate_state\")",
        new="    if False:\n        states.append(\"blocked_mandate_state\")",
        breaks="latent harm becomes predictable from the failure reason alone",
    ),
]


def run_suite(target: Path) -> tuple[bool, str]:
    if os.name == "nt":
        env = dict(os.environ)
        env["PYTHONPATH"] = str(target)
        env["PYTHONUTF8"] = "1"
    else:
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "PYTHONPATH": str(target)}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-x", "-q", "--no-header"],
        cwd=target,
        capture_output=True,
        text=True,
        env=env,
    )
    combined = (result.stdout + result.stderr).strip()
    tail = combined.splitlines()[-1] if combined else ""
    return result.returncode == 0, tail


def copy_tree(destination: Path) -> Path:
    # outputs/ must be present in the scratch copy: the chart checksum tests
    # verify shipped artefacts against SHA256SUMS.txt, and a copy without them
    # fails the suite before any mutation is applied. Only the local-only
    # generated evidence is excluded.
    target = destination / "repo"
    shutil.copytree(
        ROOT,
        target,
        ignore=shutil.ignore_patterns(
            "generated", ".git", "__pycache__", "*.egg-info", ".pytest_cache",
            "recovered_minimax_artifacts", "build", "dist", ".venv", "venv", ".hypothesis",
        ),
    )
    return target


def main() -> int:
    # Baseline control: a mutation is only proven caught if the identical
    # scratch copy passes with no mutation applied. Without this control a
    # copy that fails for an unrelated reason marks every mutation "caught".
    with tempfile.TemporaryDirectory() as tmp:
        baseline = copy_tree(Path(tmp))
        passed, tail = run_suite(baseline)
        if not passed:
            print("BASELINE FAILED: the unmutated scratch copy does not pass the suite,")
            print("so no mutation verdict below would mean anything.")
            print(f"  last line: {tail}")
            return 1
    print("Baseline control passed: the unmutated scratch copy is green.")

    print(f"Checking {len(MUTATIONS)} mutations against the test suite.\n")
    survivors: list[Mutation] = []
    unapplied: list[Mutation] = []

    for mutation in MUTATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            target = copy_tree(Path(tmp))
            source = target / mutation.path
            text = source.read_text()
            if mutation.old not in text:
                unapplied.append(mutation)
                print(f"  UNAPPLIED  {mutation.name}: anchor text not found in {mutation.path}")
                continue
            source.write_text(text.replace(mutation.old, mutation.new, 1))

            passed, _ = run_suite(target)
            if passed:
                survivors.append(mutation)
                print(f"  SURVIVED   {mutation.name}  ->  {mutation.breaks}")
            else:
                print(f"  caught     {mutation.name}")

    print()
    if unapplied:
        print(f"{len(unapplied)} mutation(s) could not be applied. Their anchors have drifted;")
        print("update scripts/mutation_check.py so the check keeps testing what it claims.")
    if survivors:
        print(f"{len(survivors)} mutation(s) SURVIVED. The suite does not detect:")
        for mutation in survivors:
            print(f"  - {mutation.breaks}")
        return 1
    if unapplied:
        return 1
    print(f"All {len(MUTATIONS)} mutations were caught. The suite has teeth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
