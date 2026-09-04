from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from bailiff.fixtures import generate_fixture
from bailiff.interpreter import InterpreterOutput, RealBoundedInterpreter
from bailiff.policies import run_policy_case
from bailiff.razorpay_adapter import RazorpayPayloadError, normalize_razorpay_autopay_payload, to_razorpay_test_payload
from bailiff.razorpay_testmode import RazorpayConfigurationError, RazorpayTestModeClient
from bailiff.replay import CommonOutcomeLedger


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeUsage:
    prompt_tokens: int = 100
    completion_tokens: int = 20
    total_tokens: int = 120


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]
    usage: _FakeUsage = field(default_factory=_FakeUsage)


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse([_FakeChoice(_FakeMessage(self.content))])


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.completions = _FakeCompletions(content)
        self.chat = SimpleNamespace(completions=self.completions)


def test_razorpay_shaped_payload_round_trip_preserves_provider_signal():
    events, ledger = generate_fixture("R1_TRANSIENT", 1701, 1)
    original = events[0]
    payload = to_razorpay_test_payload(original)
    adapted = normalize_razorpay_autopay_payload(payload)

    assert adapted.source == "razorpay_test_payload"
    assert adapted.payload_hash.startswith("sha256:")
    assert adapted.failure_payload["provider"] == "razorpay"
    assert adapted.failure_payload["provider_event"] == "subscription.pending"
    assert adapted.normalized_failure_reason == original.normalized_failure_reason
    assert adapted.amount_minor == original.amount_minor
    assert adapted.recovery_case_id == original.recovery_case_id
    assert ledger.get(adapted.recovery_case_id).case_id == original.recovery_case_id


def test_every_fixture_reason_survives_the_adapter_round_trip_exactly():
    """The recorded reason mix must be the fixture's reason mix.

    Before `unknown_or_conflicting` was exact-mapped, the keyword fallback
    relabelled over a quarter of the ambiguous regime's recorded reasons —
    the regime nominally 40% ambiguous shipped evidence showing 13%. Arm
    behaviour never drifted (the payload conflict flag drives diagnosis),
    but evidence that disagrees with the fixture that generated it is the
    kind of defect this project exists to refuse.
    """
    for regime in ("R1_TRANSIENT", "R2_TERMINAL", "R3_AMBIGUOUS"):
        events, _ = generate_fixture(regime, 1701, 50)
        for event in events:
            adapted = normalize_razorpay_autopay_payload(to_razorpay_test_payload(event))
            assert adapted.normalized_failure_reason == event.normalized_failure_reason, (
                f"{regime}: adapter relabelled {event.normalized_failure_reason} "
                f"to {adapted.normalized_failure_reason} for {event.failure_code}"
            )


def test_adapter_keyword_fallback_prefers_the_terminal_reading():
    """A description matching both readings must stop recovery, not retry it.

    The two mistakes are not symmetric: misreading a terminal failure as
    retryable debits an account that must not be debited; the reverse only
    forgoes one retry.
    """
    from bailiff.razorpay_adapter import _normalized_reason

    both = _normalized_reason(
        "some_unmapped_code", "XX01", "insufficient balance after account closed"
    )
    assert both == "ACCOUNT_CLOSED_OR_BLOCKED"
    revoked = _normalized_reason(None, None, "balance low and mandate revoked by customer")
    assert revoked == "MANDATE_REVOKED_OR_CANCELLED"


def test_razorpay_adapter_rejects_non_inr_payload():
    events, _ = generate_fixture("R1_TRANSIENT", 1701, 1)
    payload = to_razorpay_test_payload(events[0])
    payload["payload"]["payment"]["entity"]["currency"] = "USD"
    with pytest.raises(RazorpayPayloadError, match="INR"):
        normalize_razorpay_autopay_payload(payload)


@pytest.mark.parametrize("key_id", ["rzp_live_abc123", "rzp_partner_abc", ""])
def test_testmode_client_refuses_non_test_credentials_at_construction(key_id):
    """The live-key refusal is structural, not a property of one factory.

    `from_env` already refuses non-test keys; a caller constructing the
    client directly must hit the same boundary, or the refusal is only as
    strong as the discipline of whoever writes the next call site.
    """
    with pytest.raises(RazorpayConfigurationError):
        RazorpayTestModeClient(key_id=key_id, key_secret="secret")


def test_testmode_client_accepts_test_credentials_at_construction():
    client = RazorpayTestModeClient(key_id="rzp_test_abc123", key_secret="secret")
    assert client.key_id.startswith("rzp_test_")


# -- structural proof that the interpreter cannot reach the provider --------
#
# "The bounded interpreter has no provider tools" is asserted in prose all
# over this repository. These two tests turn the assertion into a property:
# the interpreter module's import graph mechanically cannot reach any module
# that talks to a provider, and the wire request it builds carries no tool,
# function, or credential field. A future edit that gives the interpreter a
# provider path fails here before it passes review.

_PROVIDER_MODULES = {
    "replay",            # local provider simulator
    "razorpay_testmode",  # real Test Mode client
    "recovery_runtime",  # RecoveryTruth execution runtime
    "recovery_truth",    # provider evidence and write fence
    "guardrails",        # execution engine that owns the provider handle
    "state",             # case store the engine mutates
    "webhook",           # ingress gate
    "api",               # HTTP surface
    "policies",          # policy arms that construct providers
}


def _bailiff_imports(module_name: str) -> set[str]:
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "bailiff" / f"{module_name}.py").read_text()
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0:
                found.add((node.module or "").split(".")[0])
            elif (node.module or "").startswith("bailiff"):
                parts = node.module.split(".")
                found.add(parts[1] if len(parts) > 1 else "")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("bailiff."):
                    found.add(alias.name.split(".")[1])
    return {name for name in found if name}


def test_the_interpreter_import_graph_cannot_reach_a_provider():
    seen: set[str] = set()
    frontier = ["interpreter"]
    while frontier:
        module = frontier.pop()
        if module in seen:
            continue
        seen.add(module)
        for imported in _bailiff_imports(module):
            assert imported not in _PROVIDER_MODULES, (
                f"bailiff/{module}.py imports bailiff/{imported}.py, which gives the "
                "bounded interpreter a structural path to provider execution"
            )
            frontier.append(imported)


def test_the_interpreter_wire_request_carries_no_tools_or_credentials():
    events, _ = generate_fixture("R3_AMBIGUOUS", 1701, 1)
    fake = _FakeClient('{"reason": "UNKNOWN_OR_CONFLICTING", "confidence": 0.4}')
    interpreter = RealBoundedInterpreter(model="test-model", client=fake)
    interpreter(events[0])

    (request,) = fake.completions.calls
    for forbidden in ("tools", "tool_choice", "functions", "function_call"):
        assert forbidden not in request, f"interpreter request must never carry {forbidden}"
    serialized = str(request).lower()
    for leak in ("key_secret", "rzp_test_", "rzp_live_", "authorization"):
        assert leak not in serialized, f"interpreter request must never carry {leak}"
    schema = request["response_format"]["json_schema"]["schema"]
    assert set(schema["properties"]) == {"reason", "confidence"}
    assert schema["additionalProperties"] is False


def test_real_interpreter_uses_schema_and_returns_cost_metadata():
    events, _ = generate_fixture("R3_AMBIGUOUS", 1701, 1)
    event = normalize_razorpay_autopay_payload(to_razorpay_test_payload(events[0]))
    client = _FakeClient('{"reason":"UNKNOWN_OR_CONFLICTING","confidence":0.61}')
    interpreter = RealBoundedInterpreter(client=client, model="test-model", usd_to_inr=85)

    output = interpreter(event)

    assert isinstance(output, InterpreterOutput)
    assert output.reason == "UNKNOWN_OR_CONFLICTING"
    assert output.confidence == 0.61
    assert output.model == "test-model"
    assert output.model_calls == 1
    assert output.model_tokens == 120
    assert output.model_cost_inr > 0
    request = client.completions.calls[0]
    assert "tools" not in request
    assert request["response_format"]["type"] == "json_schema"


def test_real_interpreter_output_abstains_before_provider_call():
    events, ledger = generate_fixture("R3_AMBIGUOUS", 1701, 1)
    event = normalize_razorpay_autopay_payload(to_razorpay_test_payload(events[0]))
    event = replace(
        event,
        failure_code="UNKNOWN",
        normalized_failure_reason="UNKNOWN_OR_CONFLICTING",
        failure_payload={
            **event.failure_payload,
            "conflict": "true",
            "error_reason": "unknown_or_conflicting",
            "error_description": "conflicting bank and risk signals",
        },
        valid_until=datetime.now(timezone.utc) + timedelta(days=1),
    )
    client = _FakeClient('{"reason":"UNKNOWN_OR_CONFLICTING","confidence":0.61}')
    run = run_policy_case(
        arm="B3",
        event=event,
        ledger=ledger,
        interpreter=RealBoundedInterpreter(client=client, model="test-model"),
    )

    assert run.decision.decision.value == "abstain"
    assert "ABSTAIN" in run.decision.reason_codes
    assert run.decision.model_calls == 1
    assert run.decision.model_used is True
    assert "MODEL_INTERPRETATION" in run.decision.reason_sources
    assert run.provider_result is None
    assert run.audit_verified is True


def test_real_interpreter_failure_fails_closed_to_abstain():
    events, ledger = generate_fixture("R3_AMBIGUOUS", 1701, 1)
    event = normalize_razorpay_autopay_payload(to_razorpay_test_payload(events[0]))
    event = replace(
        event,
        failure_code="UNKNOWN",
        normalized_failure_reason="UNKNOWN_OR_CONFLICTING",
        failure_payload={
            **event.failure_payload,
            "conflict": "true",
            "error_reason": "unknown_or_conflicting",
        },
        valid_until=datetime.now(timezone.utc) + timedelta(days=1),
    )

    class FailingInterpreter:
        def __call__(self, _event):
            raise RuntimeError("model unavailable")

    run = run_policy_case(arm="B3", event=event, ledger=ledger, interpreter=FailingInterpreter())
    assert run.decision.decision.value == "abstain"
    assert "ABSTAIN" in run.decision.reason_codes
    assert run.decision.model_calls == 0
    assert run.provider_result is None
    assert run.audit_verified is True
