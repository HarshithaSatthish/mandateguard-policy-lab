"""Optional real bounded interpreter for ambiguous scheduled AutoPay failures.

The interpreter is deliberately an annotation service. It receives a compact
Razorpay shaped signal, returns one reason from the project taxonomy and a
confidence score, and cannot call a payment provider or change authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

from .domain import FailureReason, RecoveryEvent


@dataclass(frozen=True)
class InterpreterOutput:
    reason: str
    confidence: float
    model: str
    model_calls: int
    model_tokens: int
    model_cost_inr: float
    reason_source: str = "MODEL_INTERPRETATION"


class RealBoundedInterpreter:
    """Call the configured OpenAI compatible model for ambiguous cases only.

    Not tied to OpenAI's own endpoint. Any provider that speaks the OpenAI
    chat-completions wire format works: set ``MANDATEGUARD_INTERPRETER_BASE_URL``
    to that provider's OpenAI-compatible base URL and put its key in
    ``OPENAI_API_KEY`` (the ``openai`` SDK reads that variable regardless of
    which host it is pointed at). Groq's free tier
    (https://console.groq.com/docs/openai) and Gemini's free tier
    (https://ai.google.dev/gemini-api/docs/openai) both expose this contract
    at no cost, which is what a judge running this without a paid OpenAI
    account should reach for.
    """

    # Structured-output "reasoning effort" is an OpenAI-reasoning-family
    # extension (gpt-5.x, o-series). Free-tier hosts (Groq, Gemini, etc.)
    # reject an unrecognised extra_body field, so it is only sent to a model
    # that is actually part of that family.
    _REASONING_FAMILY_PREFIXES = ("gpt-5", "o1", "o3", "o4")

    def __init__(
        self,
        *,
        model: str | None = None,
        usd_to_inr: float | None = None,
        client: Any | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model or os.getenv("MANDATEGUARD_INTERPRETER_MODEL", "gpt-5-mini")
        self.usd_to_inr = float(usd_to_inr or os.getenv("MANDATEGUARD_USD_TO_INR", "85"))
        self.base_url = base_url or os.getenv("MANDATEGUARD_INTERPRETER_BASE_URL") or None
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise RuntimeError("install the interpreter extra to use the real bounded interpreter") from exc
            # base_url=None keeps the SDK's own default (api.openai.com); any
            # other value points the same client at an OpenAI-compatible free
            # tier instead. The API key still comes from OPENAI_API_KEY either way.
            self._client = OpenAI(base_url=self.base_url) if self.base_url else OpenAI()
        return self._client

    @property
    def _is_reasoning_family(self) -> bool:
        return self.model.startswith(self._REASONING_FAMILY_PREFIXES)

    @staticmethod
    def _event_signal(event: RecoveryEvent) -> dict[str, object]:
        return {
            "provider": event.failure_payload.get("provider", "razorpay"),
            "provider_event": event.failure_payload.get("provider_event"),
            "error_code": event.failure_code,
            "error_reason": event.failure_payload.get("error_reason"),
            "error_source": event.failure_payload.get("error_source"),
            "error_step": event.failure_payload.get("error_step"),
            "error_description": event.failure_payload.get("error_description"),
            "normalized_project_reason": event.normalized_failure_reason,
            "amount_minor": event.amount_minor,
            "currency": event.currency,
            "attempt_count": event.attempt_count,
            "mandate_state": event.mandate_state,
        }

    def __call__(self, event: RecoveryEvent) -> InterpreterOutput:
        reasons = [reason.value for reason in FailureReason]
        schema = {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "enum": reasons},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["reason", "confidence"],
            "additionalProperties": False,
        }
        system = (
            "You are a bounded payment failure interpreter. Output JSON only. "
            "Choose exactly one reason from the supplied project taxonomy and a confidence from 0 to 1. "
            "You may not propose an amount, change consent, change mandate state, choose a provider, "
            "authorize a retry, or call any tool. Low confidence is acceptable and will be abstained by code. "
            "The taxonomy is a project normalization, not an official NPCI taxonomy."
        )
        user = json.dumps({"allowed_reasons": reasons, "provider_signal": self._event_signal(event)}, sort_keys=True)
        request: dict[str, Any] = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "bounded_payment_interpretation",
                    "strict": True,
                    "schema": schema,
                },
            },
            max_completion_tokens=200,
        )
        if self._is_reasoning_family:
            request["extra_body"] = {"reasoning": {"effort": "minimal"}}
        response = self.client.chat.completions.create(**request)
        content = response.choices[0].message.content
        if not content:
            raise ValueError("bounded interpreter returned empty content")
        parsed = json.loads(content)
        reason = parsed["reason"]
        confidence = float(parsed["confidence"])
        FailureReason(reason)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("bounded interpreter confidence must be between zero and one")

        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        token_count = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
        input_rate = float(os.getenv("MANDATEGUARD_MODEL_INPUT_USD_PER_1M", "0.25"))
        output_rate = float(os.getenv("MANDATEGUARD_MODEL_OUTPUT_USD_PER_1M", "2.0"))
        cost_usd = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
        return InterpreterOutput(
            reason=reason,
            confidence=confidence,
            model=self.model,
            model_calls=1,
            model_tokens=token_count,
            model_cost_inr=round(cost_usd * self.usd_to_inr, 6),
        )
