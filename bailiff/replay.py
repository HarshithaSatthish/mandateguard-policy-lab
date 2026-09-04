from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Iterable, Mapping

from .domain import (
    ActionType,
    CommonOutcome,
    ConsentState,
    ProviderResult,
    RecoveryEvent,
)


class CommonOutcomeLedger:
    """A deterministic, shared counterfactual outcome ledger.

    The ledger is created once for an experiment and is read by every policy arm.
    It deliberately does not change as policies execute.
    """

    def __init__(self, outcomes: Iterable[CommonOutcome] = ()) -> None:
        self._outcomes = {outcome.case_id: outcome for outcome in outcomes}

    def add(self, outcome: CommonOutcome) -> None:
        if outcome.case_id in self._outcomes:
            raise ValueError(f"Outcome already exists for {outcome.case_id}")
        self._outcomes[outcome.case_id] = outcome

    def get(self, case_id: str) -> CommonOutcome:
        try:
            return self._outcomes[case_id]
        except KeyError as exc:
            raise KeyError(f"No common outcome for case {case_id}") from exc

    def cases(self) -> tuple[str, ...]:
        return tuple(sorted(self._outcomes))

    def snapshot(self) -> dict[str, CommonOutcome]:
        return dict(self._outcomes)

    def to_jsonable(self) -> list[dict[str, object]]:
        return [
            {
                "case_id": outcome.case_id,
                "latent_customer_state": outcome.latent_customer_state,
                "latent_bank_state": outcome.latent_bank_state,
                "latent_consent_state": {
                    "whatsapp": outcome.latent_consent_state.whatsapp,
                    "sms": outcome.latent_consent_state.sms,
                    "email": outcome.latent_consent_state.email,
                    "opted_out": outcome.latent_consent_state.opted_out,
                },
                "latent_recovery_window": outcome.latent_recovery_window,
                "latent_outcome_seed": outcome.latent_outcome_seed,
                "latent_recoverable_minor": outcome.latent_recoverable_minor,
                "latent_harm_minor": outcome.latent_harm_minor,
            }
            for outcome in (self._outcomes[case_id] for case_id in self.cases())
        ]

    @classmethod
    def from_jsonable(cls, rows: Iterable[Mapping[str, object]]) -> "CommonOutcomeLedger":
        outcomes: list[CommonOutcome] = []
        for row in rows:
            consent = row.get("latent_consent_state", {})
            if not isinstance(consent, Mapping):
                raise ValueError("latent_consent_state must be an object")
            outcomes.append(
                CommonOutcome(
                    case_id=str(row["case_id"]),
                    latent_customer_state=str(row["latent_customer_state"]),
                    latent_bank_state=str(row["latent_bank_state"]),
                    latent_consent_state=ConsentState(
                        whatsapp=bool(consent.get("whatsapp", False)),
                        sms=bool(consent.get("sms", False)),
                        email=bool(consent.get("email", False)),
                        opted_out=bool(consent.get("opted_out", False)),
                    ),
                    latent_recovery_window=str(row["latent_recovery_window"]),
                    latent_outcome_seed=int(row["latent_outcome_seed"]),
                    latent_recoverable_minor=int(row.get("latent_recoverable_minor", 0)),
                    latent_harm_minor=int(row.get("latent_harm_minor", 0)),
                )
            )
        return cls(outcomes)

    def canonical_json(self) -> bytes:
        return json.dumps(self.to_jsonable(), sort_keys=True, separators=(",", ":")).encode()

    def sha256(self) -> str:
        return sha256(self.canonical_json()).hexdigest()

    @classmethod
    def from_seed(cls, *, seed: int, case_ids: Iterable[str]) -> "CommonOutcomeLedger":
        """Create a reproducible fixture for local replay demos.

        The seed is part of the experiment record. The benchmark must preserve
        the resulting ledger and must not regenerate outcomes per policy arm.
        """
        outcomes: list[CommonOutcome] = []
        for index, case_id in enumerate(case_ids):
            digest = sha256(f"{seed}:{case_id}".encode()).digest()
            selector = digest[0] % 7
            bank_state = (
                "available",
                "temporary_failure",
                "mandate_revoked",
                "account_closed",
                "risk_rejected",
                "unknown",
                "available",
            )[selector]
            customer_state = (
                "willing",
                "willing",
                "unwilling",
                "unknown",
                "willing",
            )[digest[1] % 5]
            window = ("morning", "afternoon", "evening")[digest[2] % 3]
            consent = ConsentState(
                whatsapp=digest[3] % 2 == 0,
                sms=digest[4] % 2 == 0,
                email=True,
                opted_out=digest[5] % 11 == 0,
            )
            recoverable = bank_state in {"available", "temporary_failure"} and customer_state == "willing"
            outcomes.append(
                CommonOutcome(
                    case_id=case_id,
                    latent_customer_state=customer_state,
                    latent_bank_state=bank_state,
                    latent_consent_state=consent,
                    latent_recovery_window=window,
                    latent_outcome_seed=int.from_bytes(digest[:8], "big"),
                    latent_recoverable_minor=1 if recoverable else 0,
                    latent_harm_minor=1 if bank_state in {"mandate_revoked", "account_closed", "risk_rejected"} else 0,
                )
            )
        return cls(outcomes)


@dataclass(frozen=True)
class ProviderCall:
    provider_call_id: str
    action: ActionType
    case_id: str
    idempotency_key: str
    called_at: datetime


class ReplayProvider:
    """Provider shaped adapter for safe local scheduled AutoPay replay."""

    name = "replay_provider"

    def __init__(
        self,
        outcomes: CommonOutcomeLedger,
        *,
        timeout_idempotency_keys: frozenset[str] = frozenset(),
    ) -> None:
        self.outcomes = outcomes
        self.timeout_idempotency_keys = timeout_idempotency_keys
        self.calls: list[ProviderCall] = []
        self._results: dict[str, ProviderResult] = {}
        self._states: dict[str, str] = {}
        self._sequence = 0

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def calls_for(self, case_id: str) -> tuple[ProviderCall, ...]:
        return tuple(call for call in self.calls if call.case_id == case_id)

    def read_case_state(self, case_id: str) -> str | None:
        return self._states.get(case_id)

    def result_for(self, idempotency_key: str) -> ProviderResult | None:
        return self._results.get(idempotency_key)

    def execute(
        self,
        *,
        event: RecoveryEvent,
        action: ActionType,
        idempotency_key: str,
    ) -> ProviderResult:
        if idempotency_key in self._results:
            return self._results[idempotency_key]
        if action not in {
            ActionType.SCHEDULE_RETRY,
            ActionType.SEND_EMAIL,
            ActionType.SEND_SMS,
            ActionType.SEND_WHATSAPP,
        }:
            raise ValueError(f"Provider action is not executable: {action.value}")

        self._sequence += 1
        call_id = f"pcall_{self._sequence:06d}"
        now = datetime.now(timezone.utc)
        self.calls.append(
            ProviderCall(
                provider_call_id=call_id,
                action=action,
                case_id=event.recovery_case_id,
                idempotency_key=idempotency_key,
                called_at=now,
            )
        )

        if idempotency_key in self.timeout_idempotency_keys:
            self._states[event.recovery_case_id] = "UNKNOWN_POSTCONDITION"
            result = ProviderResult(
                provider=self.name,
                provider_call_id=call_id,
                status="timeout",
                provider_reference=None,
                idempotency_key=idempotency_key,
                executed_at=now,
                recovered=False,
                postcondition_state="UNKNOWN_POSTCONDITION",
                timed_out=True,
                error_code="PROVIDER_TIMEOUT",
            )
            self._results[idempotency_key] = result
            return result

        outcome = self.outcomes.get(event.recovery_case_id)
        recovered = action == ActionType.SCHEDULE_RETRY and (
            outcome.latent_bank_state == "available"
            and outcome.latent_customer_state == "willing"
        )
        status = "recovered" if recovered else "accepted"
        postcondition = "RECOVERED" if recovered else "ACTION_ACCEPTED"
        self._states[event.recovery_case_id] = postcondition
        result = ProviderResult(
            provider=self.name,
            provider_call_id=call_id,
            status=status,
            provider_reference=f"ref_{call_id}",
            idempotency_key=idempotency_key,
            executed_at=now,
            recovered=recovered,
            postcondition_state=postcondition,
        )
        self._results[idempotency_key] = result
        return result

    def seed_state(self, case_id: str, state: str) -> None:
        self._states[case_id] = state
