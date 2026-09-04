"""Read only lineage, exception triage, and action provenance.

Everything in this module is a *view* over evidence that already exists. It
reads canonical rows that `bailiff.runner` wrote and rearranges them for a
human. It computes no benchmark metric, opens no ledger, calls no provider,
contacts nobody, and writes no file. That is not a stylistic preference: an
inspection layer that can act is not an inspection layer, and a recovery
console that can quietly issue a debit while claiming to be "just a view" is
the exact failure this project exists to make impossible.

The three views here are deliberately narrow:

  * **Source lineage** — where a single decision's inputs came from, and
    which of them are facts from the fixture versus project policy versus a
    model's opinion versus the guardrail's own verdict versus a simulated
    provider result. A field that the canonical evidence does not carry is
    reported as missing. It is never inferred, defaulted, or filled in from a
    neighbouring record.

  * **Exception queue** — the cases a human would actually have to look at,
    derived from reason codes that the runtime already emitted. Read only,
    deterministically ordered, and incapable of approving anything.

  * **Action provenance** — the ordered chain from input payload to audit
    receipt for one case, so a reviewer can see *why* in the same order the
    runtime decided it.

Design inspiration is credited in the documentation, not here; nothing in
this module integrates with, calls, or depends on any third party service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence

from .policies import CANONICAL_ARM_ORDER

# Shown verbatim wherever the canonical evidence does not carry a field.
# A viewer that guesses is worse than one that admits the gap, because a
# plausible guess is indistinguishable from a fact once it is on screen.
NOT_PRESENT = "not present in fixture"

# Must appear next to any lineage or queue rendering.
SCOPE_LABEL = (
    "Source: Razorpay shaped synthetic test payload. "
    "Provider: local simulator. No live Razorpay API call."
)


class SourceLabel(str, Enum):
    """Where a displayed value came from.

    The distinction that matters most is between the last three: a model's
    interpretation, the guardrail's decision, and a simulated provider
    result are three very different kinds of claim, and collapsing them is
    how a demo starts implying the model decided something it did not.
    """

    FACT_FROM_FIXTURE = "FACT_FROM_FIXTURE"
    PROJECT_POLICY = "PROJECT_POLICY"
    MODEL_INTERPRETATION = "MODEL_INTERPRETATION"
    GUARDRAIL_DECISION = "GUARDRAIL_DECISION"
    SIMULATED_PROVIDER_RESULT = "SIMULATED_PROVIDER_RESULT"


@dataclass(frozen=True)
class LineageField:
    """One row of the source lineage panel."""

    name: str
    value: str
    label: SourceLabel

    @property
    def present(self) -> bool:
        return self.value != NOT_PRESENT


def _present(row: dict[str, Any], key: str) -> str:
    """Return a displayable value, or NOT_PRESENT — never a fabrication.

    `None` and empty string both mean the canonical evidence does not carry
    the field. `False` and `0` are real values and must survive.
    """
    if key not in row:
        return NOT_PRESENT
    value = row[key]
    if value is None:
        return NOT_PRESENT
    if isinstance(value, str) and not value.strip():
        return NOT_PRESENT
    if isinstance(value, (list, tuple)):
        if not value:
            return NOT_PRESENT
        return ", ".join(str(item) for item in value)
    return str(value)


# The lineage panel, in display order. Each entry is
# (display name, evidence key, source label).
#
# Several fields the design asked for are simply not in this repository's
# canonical evidence: the benchmark ledger records decisions, not the wire
# level envelope, so mandate id, scheduled execution id, and the two
# timestamps have no source here. They are listed anyway, and they render as
# NOT_PRESENT. Listing them and admitting the gap is more useful to a
# reviewer than silently omitting the row, which would leave them unsure
# whether the field was missing or merely not displayed.
LINEAGE_SPEC: tuple[tuple[str, str, SourceLabel], ...] = (
    ("Event ID", "decision_id", SourceLabel.FACT_FROM_FIXTURE),
    ("Correlation ID", "correlation_id", SourceLabel.FACT_FROM_FIXTURE),
    ("Recovery case ID", "case_id", SourceLabel.FACT_FROM_FIXTURE),
    ("Mandate ID", "mandate_id", SourceLabel.FACT_FROM_FIXTURE),
    ("Scheduled execution ID", "scheduled_execution_id", SourceLabel.FACT_FROM_FIXTURE),
    ("Source system", "event_source", SourceLabel.FACT_FROM_FIXTURE),
    ("Source type", "provider_event", SourceLabel.FACT_FROM_FIXTURE),
    ("Payload SHA256", "provider_payload_hash", SourceLabel.FACT_FROM_FIXTURE),
    ("Ledger snapshot hash", "ledger_sha256", SourceLabel.FACT_FROM_FIXTURE),
    ("Event created at", "event_created_at", SourceLabel.FACT_FROM_FIXTURE),
    ("Received at", "event_received_at", SourceLabel.FACT_FROM_FIXTURE),
    ("Freshness", "event_age_status", SourceLabel.FACT_FROM_FIXTURE),
    ("Raw provider signal", "provider_error_reason", SourceLabel.FACT_FROM_FIXTURE),
    ("Raw provider description", "provider_error_description", SourceLabel.FACT_FROM_FIXTURE),
    ("Normalized project reason", "normalized_failure_reason", SourceLabel.PROJECT_POLICY),
    ("Diagnosed reason", "diagnosed_reason", SourceLabel.PROJECT_POLICY),
    ("Policy arm", "arm", SourceLabel.PROJECT_POLICY),
    ("Policy version", "policy_id", SourceLabel.PROJECT_POLICY),
    ("Rules provenance", "policy_provenance", SourceLabel.PROJECT_POLICY),
    ("Interpreter mode", "bounded_interpreter_model", SourceLabel.MODEL_INTERPRETATION),
    ("Interpreter influenced decision", "bounded_interpreter_influence", SourceLabel.MODEL_INTERPRETATION),
    ("Interpreter confidence", "confidence", SourceLabel.MODEL_INTERPRETATION),
    ("Proposed action", "proposed_action", SourceLabel.MODEL_INTERPRETATION),
    ("Authority envelope (final action)", "final_action", SourceLabel.GUARDRAIL_DECISION),
    ("Decision", "decision", SourceLabel.GUARDRAIL_DECISION),
    ("Reason codes", "reason_codes", SourceLabel.GUARDRAIL_DECISION),
    ("Reason sources", "reason_sources", SourceLabel.GUARDRAIL_DECISION),
    ("Audit receipt hash", "audit_event_hashes", SourceLabel.GUARDRAIL_DECISION),
    ("Audit chain verified", "audit_verified", SourceLabel.GUARDRAIL_DECISION),
    ("Provider call made", "provider_call_made", SourceLabel.SIMULATED_PROVIDER_RESULT),
    ("Provider call ID", "provider_call_id", SourceLabel.SIMULATED_PROVIDER_RESULT),
    ("Provider status", "provider_status", SourceLabel.SIMULATED_PROVIDER_RESULT),
    ("Provider postcondition", "provider_postcondition_state", SourceLabel.SIMULATED_PROVIDER_RESULT),
)


def lineage_for(row: dict[str, Any]) -> list[LineageField]:
    """Build the read only lineage panel for one canonical evidence row."""
    return [
        LineageField(name=name, value=_present(row, key), label=label)
        for name, key, label in LINEAGE_SPEC
    ]


# --------------------------------------------------------------------------
# Exception queue
# --------------------------------------------------------------------------

# Severity is a presentation concern only: it orders a reviewer's attention,
# it never changes a decision, and nothing downstream reads it.
SEVERITY_ORDER = ("BLOCKING", "ATTENTION", "INFORMATIONAL")

# Reason codes that put a case in front of a human, mapped to severity and to
# the status a reviewer sees. Every key here is a code the runtime already
# emits — from the guardrail engine or from the webhook gate. Nothing is
# invented, and a code that never occurs simply yields no rows.
EXCEPTION_TAXONOMY: dict[str, tuple[str, str]] = {
    # Guardrail and runtime outcomes.
    "ABSTAIN": ("BLOCKING", "ABSTAINED"),
    "HUMAN_REVIEW_REQUIRED": ("BLOCKING", "HUMAN_REVIEW_REQUIRED"),
    "UNKNOWN_POSTCONDITION": ("BLOCKING", "UNKNOWN_POSTCONDITION"),
    "TIMEOUT": ("BLOCKING", "TIMEOUT"),
    "INTERPRETER_CONFIDENCE_BELOW_THRESHOLD": ("ATTENTION", "ABSTAINED"),
    # Webhook ingress outcomes.
    "SIGNATURE_MISMATCH": ("BLOCKING", "SIGNATURE_REJECTED"),
    "SIGNATURE_MISSING": ("BLOCKING", "SIGNATURE_REJECTED"),
    "MALFORMED_BODY": ("BLOCKING", "MALFORMED_EVENT"),
    "SUPERSEDED_BY_TERMINAL_EVENT": ("ATTENTION", "SUPERSEDED"),
    "BLOCKED_SUBSCRIPTION_PAUSED_OR_HALTED": ("ATTENTION", "BLOCKED_PAUSED_OR_HALTED"),
    "STALE_DELIVERY": ("ATTENTION", "STALE_EVENT"),
    "DUPLICATE_DELIVERY_IGNORED": ("INFORMATIONAL", "DUPLICATE_IGNORED"),
}

# Statuses whose defining property is that nothing was executed. A row with
# one of these that also reports a provider call is a contradiction, and the
# queue says so rather than rendering it quietly.
#
# HUMAN_REVIEW_REQUIRED is deliberately NOT in this set. A timeout is the
# case that makes the distinction matter: the call was genuinely made, the
# postcondition is genuinely unknown, and a human genuinely has to look at
# it. Treating "needs review" as "nothing happened" would flag that correct
# behaviour as a safety contradiction and train a reviewer to ignore the
# warning that is supposed to mean something.
NON_EXECUTING_STATUSES = frozenset(
    {
        "ABSTAINED",
        "SIGNATURE_REJECTED",
        "MALFORMED_EVENT",
        "SUPERSEDED",
        "BLOCKED_PAUSED_OR_HALTED",
        "STALE_EVENT",
        "DUPLICATE_IGNORED",
    }
)

DENIED_BEFORE_BOUNDARY = "Denied before provider boundary: 0 provider calls."
TIMEOUT_NEXT_STEP = (
    "Provider state unknown: automated follow up blocked; human review required."
)


@dataclass(frozen=True)
class ExceptionRow:
    """One read only row of the exception queue."""

    severity: str
    status: str
    case_id: str
    event_id: str
    arm: str
    reason: str
    event_age: str
    amount_inr: float | None
    provider_calls: int
    human_next_step: str
    contradiction: str | None = None

    @property
    def shows_zero_provider_calls(self) -> bool:
        return self.provider_calls == 0


def _amount_for(row: dict[str, Any]) -> float | None:
    """Best available monetary figure already present in the evidence.

    No arithmetic beyond selecting a field that the runner computed. If the
    row carries none of them the amount is unknown and stays unknown.
    """
    for key in (
        "protected_value_by_denial_inr",
        "legitimate_recovery_forgone_inr",
        "realized_harm_inr",
    ):
        value = row.get(key)
        if isinstance(value, (int, float)) and value:
            return float(value)
    return None


def _provider_calls(row: dict[str, Any]) -> int:
    """Read the provider call count that the runtime recorded."""
    made = row.get("provider_call_made")
    if isinstance(made, bool):
        return 1 if made else 0
    if isinstance(made, (int, float)):
        return int(made)
    # Fall back to the call id only as evidence of a call having happened.
    return 1 if row.get("provider_call_id") else 0


def _human_next_step(status: str, row: dict[str, Any]) -> str:
    """Only surface a next step that canonical data already implies."""
    if status in {"TIMEOUT", "UNKNOWN_POSTCONDITION"}:
        return TIMEOUT_NEXT_STEP
    if status in {"ABSTAINED", "HUMAN_REVIEW_REQUIRED"}:
        return "Human review required before any further automated attempt."
    if status in NON_EXECUTING_STATUSES:
        return DENIED_BEFORE_BOUNDARY
    return NOT_PRESENT


def classify(row: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return (severity, status, reason code) if this row is an exception.

    A row is an exception because the runtime said so, via a reason code it
    already emitted. Timeouts are recognised from the recorded timeout flag
    and from a missing postcondition on a call that was actually made, which
    is the same condition the runtime routes to human review.
    """
    codes = row.get("reason_codes") or []
    if isinstance(codes, str):
        codes = [codes]

    # An explicit webhook verdict code, when the row is a webhook verdict.
    verdict_code = row.get("reason_code")
    if isinstance(verdict_code, str) and verdict_code in EXCEPTION_TAXONOMY:
        severity, status = EXCEPTION_TAXONOMY[verdict_code]
        return severity, status, verdict_code

    if row.get("provider_timed_out") is True:
        return (*EXCEPTION_TAXONOMY["TIMEOUT"], "TIMEOUT")

    if _provider_calls(row) and not row.get("provider_postcondition_state"):
        return (*EXCEPTION_TAXONOMY["UNKNOWN_POSTCONDITION"], "UNKNOWN_POSTCONDITION")

    for code in codes:
        if code in EXCEPTION_TAXONOMY:
            severity, status = EXCEPTION_TAXONOMY[code]
            return severity, status, code
    return None


def to_exception_row(row: dict[str, Any]) -> ExceptionRow | None:
    """Project one canonical row into a queue row, or None if it is routine."""
    classified = classify(row)
    if classified is None:
        return None
    severity, status, code = classified
    calls = _provider_calls(row)

    contradiction = None
    if status in NON_EXECUTING_STATUSES and calls:
        # Surfaced, never smoothed over. If this ever appears, the invariant
        # "a non allow decision makes no provider call" has been broken and a
        # reviewer must see it, not a tidy row.
        contradiction = (
            f"{status} reported {calls} provider call(s); expected 0. "
            "This contradicts the runtime's own safety invariant."
        )

    return ExceptionRow(
        severity=severity,
        status=status,
        case_id=_present(row, "case_id"),
        event_id=_present(row, "decision_id"),
        arm=_present(row, "arm"),
        reason=code,
        event_age=_present(row, "event_age_status"),
        amount_inr=_amount_for(row),
        provider_calls=calls,
        human_next_step=_human_next_step(status, row),
        contradiction=contradiction,
    )


def _sort_key(item: ExceptionRow) -> tuple:
    """Total order, stable across runs and independent of input order."""
    severity_rank = (
        SEVERITY_ORDER.index(item.severity)
        if item.severity in SEVERITY_ORDER
        else len(SEVERITY_ORDER)
    )
    arm_rank = (
        CANONICAL_ARM_ORDER.index(item.arm)
        if item.arm in CANONICAL_ARM_ORDER
        else len(CANONICAL_ARM_ORDER)
    )
    return (severity_rank, arm_rank, item.status, item.case_id, item.event_id, item.reason)


def exception_queue(
    rows: Iterable[dict[str, Any]],
    *,
    statuses: Sequence[str] | None = None,
    arms: Sequence[str] | None = None,
    severities: Sequence[str] | None = None,
    max_provider_calls: int | None = None,
) -> list[ExceptionRow]:
    """Build the deterministically ordered, read only exception queue.

    Filters are plain predicates over already recorded values. There is no
    polling, no refresh, no recomputation, and nothing here can execute an
    action — the function only ever returns a list of value objects.
    """
    out: list[ExceptionRow] = []
    for row in rows:
        item = to_exception_row(row)
        if item is None:
            continue
        if statuses is not None and item.status not in statuses:
            continue
        if arms is not None and item.arm not in arms:
            continue
        if severities is not None and item.severity not in severities:
            continue
        if max_provider_calls is not None and item.provider_calls > max_provider_calls:
            continue
        out.append(item)
    return sorted(out, key=_sort_key)


def queue_status_counts(queue: Sequence[ExceptionRow]) -> dict[str, int]:
    """Counts by status, in the queue's own deterministic status order."""
    counts: dict[str, int] = {}
    for item in queue:
        counts[item.status] = counts.get(item.status, 0) + 1
    return dict(sorted(counts.items()))


# --------------------------------------------------------------------------
# Action provenance
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProvenanceStep:
    """One ordered step in the decision chain for a single case."""

    order: int
    title: str
    label: SourceLabel
    details: list[tuple[str, str]] = field(default_factory=list)


def _pairs(row: dict[str, Any], spec: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(name, _present(row, key)) for name, key in spec]


def provenance_chain(row: dict[str, Any]) -> list[ProvenanceStep]:
    """The ordered chain from input payload to audit receipt.

    The order is the order the runtime actually decides in, not a narrative
    reordering: input, normalisation, consent and mandate, budget and timing,
    authority, interpreter proposal, guardrail verdict, call decision, result,
    receipt. Step 6 appears only when a bounded interpreter was consulted,
    because showing an empty interpreter step on a deterministic arm invites
    the reader to think a model was involved when none was.
    """
    steps: list[ProvenanceStep] = [
        ProvenanceStep(
            1,
            "Input source and payload hash",
            SourceLabel.FACT_FROM_FIXTURE,
            _pairs(
                row,
                (
                    ("Source system", "event_source"),
                    ("Source type", "provider_event"),
                    ("Payload SHA256", "provider_payload_hash"),
                    ("Ledger snapshot hash", "ledger_sha256"),
                ),
            ),
        ),
        ProvenanceStep(
            2,
            "Normalized provider signal and project reason",
            SourceLabel.PROJECT_POLICY,
            _pairs(
                row,
                (
                    ("Raw provider signal", "provider_error_reason"),
                    ("Raw description", "provider_error_description"),
                    ("Failure code", "failure_code"),
                    ("Normalized project reason", "normalized_failure_reason"),
                    ("Diagnosed reason", "diagnosed_reason"),
                ),
            ),
        ),
        ProvenanceStep(
            3,
            "Consent and mandate state",
            SourceLabel.GUARDRAIL_DECISION,
            [
                ("Consent and mandate gates", _gate_summary(row, _CONSENT_MANDATE_CODES)),
            ],
        ),
        ProvenanceStep(
            4,
            "Attempt budget and timing checks",
            SourceLabel.GUARDRAIL_DECISION,
            [
                ("Attempt and timing gates", _gate_summary(row, _BUDGET_TIMING_CODES)),
            ],
        ),
        ProvenanceStep(
            5,
            "Authority envelope",
            SourceLabel.GUARDRAIL_DECISION,
            _pairs(
                row,
                (
                    ("Proposed action", "proposed_action"),
                    ("Final action", "final_action"),
                    ("Policy version", "policy_id"),
                ),
            ),
        ),
    ]

    if _interpreter_was_consulted(row):
        steps.append(
            ProvenanceStep(
                6,
                "B3 interpreter proposal",
                SourceLabel.MODEL_INTERPRETATION,
                _pairs(
                    row,
                    (
                        ("Interpreter mode", "bounded_interpreter_model"),
                        ("Confidence", "confidence"),
                        ("Influenced decision", "bounded_interpreter_influence"),
                        ("Proposed action", "proposed_action"),
                    ),
                )
                + [
                    (
                        "Authority",
                        "The interpreter annotates only. It cannot authorize a "
                        "payment action or widen the authority envelope.",
                    )
                ],
            )
        )

    steps.extend(
        [
            ProvenanceStep(
                7,
                "Deterministic guardrail result",
                SourceLabel.GUARDRAIL_DECISION,
                _pairs(
                    row,
                    (
                        ("Decision", "decision"),
                        ("Reason codes", "reason_codes"),
                        ("Reason sources", "reason_sources"),
                    ),
                ),
            ),
            ProvenanceStep(
                8,
                "Provider call decision",
                SourceLabel.GUARDRAIL_DECISION,
                [
                    ("Provider calls", str(_provider_calls(row))),
                    ("Outcome", decision_summary(row)),
                ],
            ),
            ProvenanceStep(
                9,
                "Provider result or unknown postcondition",
                SourceLabel.SIMULATED_PROVIDER_RESULT,
                _pairs(
                    row,
                    (
                        ("Provider call ID", "provider_call_id"),
                        ("Provider status", "provider_status"),
                        ("Postcondition", "provider_postcondition_state"),
                    ),
                ),
            ),
            ProvenanceStep(
                10,
                "Audit receipt hash and chain verification",
                SourceLabel.GUARDRAIL_DECISION,
                _pairs(
                    row,
                    (
                        ("Audit receipt hash", "audit_event_hashes"),
                        ("Audit event count", "audit_event_count"),
                        ("Chain verified", "audit_verified"),
                    ),
                ),
            ),
        ]
    )
    return steps


_CONSENT_MANDATE_CODES = (
    "MANDATE_ACTIVE",
    "MANDATE_NOT_ACTIVE",
    "MANDATE_REVOKED_OR_CANCELLED",
    "CUSTOMER_OPTED_OUT",
    "RECOVERY_STOP_REQUESTED",
    "PRE_DEBIT_VALID",
    "PRE_DEBIT_NOTICE_INVALID",
)

_BUDGET_TIMING_CODES = (
    "ATTEMPT_AVAILABLE",
    "ATTEMPT_POLICY_EXHAUSTED",
    "RETRY_GAP_TOO_SHORT",
    "EXECUTION_OUTSIDE_NON_PEAK_WINDOW",
    "RETRY_OUTSIDE_NON_PEAK_WINDOW",
)


def _gate_summary(row: dict[str, Any], codes: Sequence[str]) -> str:
    present = [code for code in (row.get("reason_codes") or []) if code in codes]
    return ", ".join(present) if present else NOT_PRESENT


def _interpreter_was_consulted(row: dict[str, Any]) -> bool:
    """True only when this row actually involved the bounded interpreter."""
    if row.get("arm") != "B3":
        return False
    return bool(
        row.get("bounded_interpreter_model")
        or row.get("bounded_interpreter_influence")
        or row.get("confidence") is not None
    )


def decision_summary(row: dict[str, Any]) -> str:
    """The sentence a reviewer should read for this case's outcome."""
    calls = _provider_calls(row)
    if row.get("provider_timed_out") is True or (
        calls and not row.get("provider_postcondition_state")
    ):
        return TIMEOUT_NEXT_STEP
    if calls == 0:
        return DENIED_BEFORE_BOUNDARY
    return (
        f"Authorized and executed against the local simulator: "
        f"{calls} provider call(s), postcondition "
        f"{_present(row, 'provider_postcondition_state')}."
    )
