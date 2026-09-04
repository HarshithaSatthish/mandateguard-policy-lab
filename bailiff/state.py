from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .domain import CaseState, RecoveryEvent


TERMINAL_STATES = frozenset(
    {
        CaseState.RECOVERED,
        CaseState.TERMINAL_STOP,
    }
)

_ALLOWED_TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.SCHEDULED: frozenset({CaseState.FAILED}),
    CaseState.FAILED: frozenset({CaseState.CLASSIFIED}),
    CaseState.CLASSIFIED: frozenset(
        {
            CaseState.RETRY_SCHEDULED,
            CaseState.MESSAGE_SENT,
            CaseState.HUMAN_REVIEW,
            CaseState.TERMINAL_STOP,
        }
    ),
    CaseState.RETRY_SCHEDULED: frozenset(
        {CaseState.RECOVERED, CaseState.FAILED, CaseState.HUMAN_REVIEW, CaseState.TERMINAL_STOP}
    ),
    CaseState.MESSAGE_SENT: frozenset(
        {CaseState.RECOVERED, CaseState.FAILED, CaseState.HUMAN_REVIEW, CaseState.TERMINAL_STOP}
    ),
    CaseState.HUMAN_REVIEW: frozenset({CaseState.RETRY_SCHEDULED, CaseState.MESSAGE_SENT, CaseState.TERMINAL_STOP}),
    CaseState.RECOVERED: frozenset(),
    CaseState.TERMINAL_STOP: frozenset(),
}


class InvalidTransition(ValueError):
    """Raised when an event attempts an illegal or regressive state change."""


@dataclass
class CaseRecord:
    event: RecoveryEvent
    state: CaseState = CaseState.SCHEDULED
    seen_event_ids: set[str] = field(default_factory=set)
    transition_log: list[tuple[CaseState, CaseState, str]] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def transition(self, next_state: CaseState, reason: str) -> bool:
        if self.state in TERMINAL_STATES:
            if next_state != self.state:
                raise InvalidTransition(f"Terminal case cannot transition from {self.state} to {next_state}")
            return False
        if next_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise InvalidTransition(f"Invalid transition from {self.state} to {next_state}")
        previous = self.state
        self.state = next_state
        self.updated_at = datetime.now(timezone.utc)
        self.transition_log.append((previous, next_state, reason))
        return True


class CaseStore:
    def __init__(self) -> None:
        self._cases: dict[str, CaseRecord] = {}

    def create_or_get(self, event: RecoveryEvent) -> tuple[CaseRecord, bool]:
        current = self._cases.get(event.recovery_case_id)
        if current is not None:
            current.seen_event_ids.add(event.event_id)
            return current, False
        record = CaseRecord(event=event, seen_event_ids={event.event_id})
        self._cases[event.recovery_case_id] = record
        return record, True

    def get(self, case_id: str) -> CaseRecord:
        try:
            return self._cases[case_id]
        except KeyError as exc:
            raise KeyError(f"Unknown recovery case: {case_id}") from exc

    def all(self) -> tuple[CaseRecord, ...]:
        return tuple(self._cases.values())
