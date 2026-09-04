"""The inspection layer must stay an inspection layer.

Source lineage, the exception queue, and the action provenance chain all
render things that look like an operations console: case rows, severities, a
next step for a human. That resemblance is the risk. A console that can act
while presenting itself as a view is precisely the failure this project is
built to make impossible, so the tests here are not about formatting. They
assert that the read only layer:

  * invents nothing — every displayed value traces to canonical evidence, and
    a field the evidence lacks is reported missing rather than inferred;
  * executes nothing — building the queue cannot reach the provider
    simulator, cannot open a network socket, and cannot mutate a single byte
    under ``outputs/``;
  * contradicts nothing — the safety invariants the runtime enforces are the
    same ones the screen displays, and a denial still shows zero provider
    calls on screen exactly as it does in the receipt.

If any of these fail, the correct response is to fix the viewer, never to
relax the assertion.
"""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from bailiff.lineage import (
    DENIED_BEFORE_BOUNDARY,
    EXCEPTION_TAXONOMY,
    LINEAGE_SPEC,
    NOT_PRESENT,
    NON_EXECUTING_STATUSES,
    SCOPE_LABEL,
    SEVERITY_ORDER,
    SourceLabel,
    TIMEOUT_NEXT_STEP,
    classify,
    decision_summary,
    exception_queue,
    lineage_for,
    provenance_chain,
    queue_status_counts,
    to_exception_row,
)
from bailiff.policies import CANONICAL_ARM_ORDER

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
LEDGER = OUTPUTS / "evidence_ledger.json"

# Files the read only layer must never touch.
CANONICAL_OUTPUTS = (
    "outputs/aggregate.json",
    "outputs/anti_gaming.json",
    "outputs/breakeven.json",
    "outputs/evidence_ledger.json",
    "outputs/evidence_manifest.json",
    "outputs/fixture_sensitivity.json",
    "outputs/manifest.json",
    "outputs/per_seed.json",
    "outputs/report.md",
    "outputs/architecture.png",
    "outputs/frontier.png",
    "outputs/sensitivity.png",
    "FINDINGS.md",
)


@pytest.fixture(scope="module")
def ledger() -> list[dict]:
    if not LEDGER.exists():
        pytest.skip("evidence ledger not generated; run ./scripts/evaluate.sh")
    return json.loads(LEDGER.read_text())


def _hash_canonical() -> dict[str, str]:
    digests = {}
    for relative in CANONICAL_OUTPUTS:
        path = ROOT / relative
        if path.exists():
            digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


# ---------------------------------------------------------------------------
# 1 & 2. Lineage comes from canonical evidence, and never invents a value.
# ---------------------------------------------------------------------------


def test_every_lineage_value_traces_to_the_canonical_row(ledger):
    """A displayed value must be in the evidence, or be marked missing."""
    for row in ledger[:120]:
        for item in lineage_for(row):
            if not item.present:
                continue
            key = next(k for name, k, _ in LINEAGE_SPEC if name == item.name)
            raw = row.get(key)
            assert raw is not None, (
                f"{item.name} displayed {item.value!r} but the canonical row has "
                f"no {key!r} — the viewer invented it"
            )
            if isinstance(raw, (list, tuple)):
                for element in raw:
                    assert str(element) in item.value
            else:
                assert str(raw) == item.value


def test_absent_fields_are_reported_missing_not_fabricated(ledger):
    """The benchmark ledger genuinely lacks some requested fields.

    Mandate id, scheduled execution id and the wire timestamps are not in
    this evidence. The panel must say so in those words, for every row, and
    must never borrow a value from a neighbouring record to fill the space.
    """
    absent_keys = {
        "mandate_id",
        "scheduled_execution_id",
        "event_created_at",
        "event_received_at",
        "event_age_status",
    }
    displayed_names = {
        name for name, key, _ in LINEAGE_SPEC if key in absent_keys
    }
    assert displayed_names, "the panel must still list fields the fixture lacks"

    for row in ledger[:60]:
        for item in lineage_for(row):
            if item.name in displayed_names:
                assert item.value == NOT_PRESENT, (
                    f"{item.name} is not carried by this evidence but rendered "
                    f"{item.value!r}"
                )


def test_a_false_or_zero_value_is_not_mistaken_for_a_missing_one():
    """`False` and `0` are facts. Only None and empty mean absent."""
    row = {"provider_call_made": False, "audit_event_count": 0, "case_id": ""}
    fields = {item.name: item.value for item in lineage_for(row)}
    assert fields["Provider call made"] == "False"
    assert fields["Recovery case ID"] == NOT_PRESENT


def test_the_scope_label_names_the_simulator_and_denies_a_live_api_call():
    assert "local simulator" in SCOPE_LABEL
    assert "No live Razorpay API call" in SCOPE_LABEL
    assert "synthetic test payload" in SCOPE_LABEL


# ---------------------------------------------------------------------------
# 3. Deterministic status and ordering.
# ---------------------------------------------------------------------------


def test_the_queue_order_is_total_and_independent_of_input_order(ledger):
    forward = exception_queue(ledger)
    backward = exception_queue(list(reversed(ledger)))
    assert forward == backward, "queue order depends on input order"
    assert forward == exception_queue(ledger), "queue order is not reproducible"


def test_the_queue_sorts_by_severity_then_canonical_arm_order(ledger):
    queue = exception_queue(ledger)
    ranks = [SEVERITY_ORDER.index(item.severity) for item in queue]
    assert ranks == sorted(ranks), "severity is not the primary sort key"

    for earlier, later in zip(queue, queue[1:]):
        if earlier.severity != later.severity:
            continue
        if earlier.arm in CANONICAL_ARM_ORDER and later.arm in CANONICAL_ARM_ORDER:
            assert CANONICAL_ARM_ORDER.index(earlier.arm) <= CANONICAL_ARM_ORDER.index(
                later.arm
            ), "arms are not ordered canonically within a severity"


def test_the_filters_are_deterministic_subsets(ledger):
    full = exception_queue(ledger)
    statuses = sorted({item.status for item in full})
    subset = exception_queue(ledger, statuses=statuses[:1])
    assert all(item.status == statuses[0] for item in subset)
    assert subset == [item for item in full if item.status == statuses[0]]

    zero_only = exception_queue(ledger, max_provider_calls=0)
    assert all(item.provider_calls == 0 for item in zero_only)


def test_status_counts_match_the_queue_itself(ledger):
    queue = exception_queue(ledger)
    counts = queue_status_counts(queue)
    assert sum(counts.values()) == len(queue)
    for status, count in counts.items():
        assert count == sum(1 for item in queue if item.status == status)


# ---------------------------------------------------------------------------
# 4 & 5. The queue executes nothing and mutates nothing.
# ---------------------------------------------------------------------------


def test_building_the_queue_never_calls_the_provider_simulator(ledger, monkeypatch):
    """Booby trap the provider: any call at all fails the test."""
    from bailiff import replay

    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the read only queue called the provider simulator")

    for attribute in dir(replay.ReplayProvider):
        if attribute.startswith("_"):
            continue
        if callable(getattr(replay.ReplayProvider, attribute, None)):
            monkeypatch.setattr(replay.ReplayProvider, attribute, explode, raising=False)

    queue = exception_queue(ledger)
    assert queue, "expected the canonical evidence to contain exceptions"
    for row in ledger[:40]:
        lineage_for(row)
        provenance_chain(row)


def test_reading_the_queue_mutates_no_canonical_output(ledger):
    before = _hash_canonical()
    assert before, "no canonical outputs found to protect"

    exception_queue(ledger)
    exception_queue(ledger, max_provider_calls=0, severities=list(SEVERITY_ORDER))
    for row in ledger[:80]:
        lineage_for(row)
        provenance_chain(row)
        decision_summary(row)

    assert _hash_canonical() == before, "the read only layer changed a canonical output"


def test_the_view_layer_opens_no_socket(ledger, monkeypatch):
    """No network, not even a DNS lookup, from the inspection layer."""

    def refuse(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the read only layer attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse, raising=False)
    monkeypatch.setattr(socket, "create_connection", refuse, raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", refuse, raising=False)

    exception_queue(ledger)
    for row in ledger[:40]:
        lineage_for(row)
        provenance_chain(row)


def test_queue_rows_are_immutable_value_objects(ledger):
    """A row a caller can edit is a row a caller can launder."""
    queue = exception_queue(ledger)
    with pytest.raises(Exception):
        queue[0].provider_calls = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 6 & 7. What denied, abstained and timeout rows must visibly say.
# ---------------------------------------------------------------------------


def test_every_denied_or_abstained_row_shows_zero_provider_calls(ledger):
    queue = exception_queue(ledger)
    non_executing = [item for item in queue if item.status in NON_EXECUTING_STATUSES]
    assert non_executing, "expected abstained or refused rows in the evidence"
    for item in non_executing:
        assert item.provider_calls == 0, (
            f"{item.status} row {item.case_id} reports {item.provider_calls} "
            f"provider calls"
        )
        assert item.shows_zero_provider_calls
        assert item.contradiction is None


def test_an_abstained_row_routes_a_human_to_review(ledger):
    abstained = [item for item in exception_queue(ledger) if item.status == "ABSTAINED"]
    assert abstained, "expected the canonical evidence to contain an ABSTAIN"
    for item in abstained:
        assert "review" in item.human_next_step.lower()
        assert item.provider_calls == 0


def test_a_timeout_row_shows_unknown_postcondition_and_human_review():
    """Constructed, and labelled as such.

    The frozen benchmark ledger contains no timeout — every row records
    `provider_timed_out: False`. Rather than pretend otherwise, this asserts
    the classification directly on the shape the runtime produces for a
    timeout, which `scripts/demo60.py` exercises end to end.
    """
    timed_out = {
        "case_id": "t_timeout",
        "decision_id": "d_timeout",
        "arm": "B2",
        "provider_call_made": True,
        "provider_timed_out": True,
        "provider_postcondition_state": None,
        "reason_codes": ["HUMAN_REVIEW_REQUIRED"],
    }
    item = to_exception_row(timed_out)
    assert item is not None
    assert item.status == "TIMEOUT"
    assert item.severity == "BLOCKING"
    assert item.human_next_step == TIMEOUT_NEXT_STEP
    assert "unknown" in item.human_next_step.lower()
    assert "human review" in item.human_next_step.lower()
    assert decision_summary(timed_out) == TIMEOUT_NEXT_STEP

    lineage = {item.name: item.value for item in lineage_for(timed_out)}
    assert lineage["Provider postcondition"] == NOT_PRESENT


def test_a_call_with_no_postcondition_is_treated_as_unknown_even_without_the_flag():
    """The dangerous shape is a call whose result nobody knows."""
    row = {
        "case_id": "c",
        "arm": "B2",
        "provider_call_made": True,
        "provider_postcondition_state": None,
        "reason_codes": [],
    }
    severity, status, code = classify(row)
    assert status == "UNKNOWN_POSTCONDITION"
    assert severity == "BLOCKING"
    assert code == "UNKNOWN_POSTCONDITION"


def test_a_non_executing_row_that_reports_a_call_is_surfaced_as_a_contradiction():
    """If the invariant ever breaks, the screen must not render it tidily."""
    impossible = {
        "case_id": "c",
        "arm": "B3",
        "provider_call_made": True,
        "provider_postcondition_state": "RECOVERED",
        "reason_codes": ["ABSTAIN"],
    }
    item = to_exception_row(impossible)
    assert item is not None
    assert item.status == "ABSTAINED"
    assert item.contradiction is not None
    assert "expected 0" in item.contradiction


def test_the_denial_sentence_is_the_one_the_specification_requires():
    denied = {"case_id": "c", "arm": "B2", "provider_call_made": False, "reason_codes": []}
    assert decision_summary(denied) == DENIED_BEFORE_BOUNDARY
    assert DENIED_BEFORE_BOUNDARY == "Denied before provider boundary: 0 provider calls."


# ---------------------------------------------------------------------------
# 8. Provenance labelling.
# ---------------------------------------------------------------------------


def test_every_source_label_class_is_actually_used_by_the_lineage_panel():
    used = {label for _, _, label in LINEAGE_SPEC}
    assert used == set(SourceLabel), f"unused source labels: {set(SourceLabel) - used}"


def test_labels_attribute_each_value_to_the_right_kind_of_claim():
    """The distinction that matters: fixture fact vs policy vs model vs guardrail."""
    by_name = {name: label for name, _, label in LINEAGE_SPEC}
    assert by_name["Payload SHA256"] is SourceLabel.FACT_FROM_FIXTURE
    assert by_name["Normalized project reason"] is SourceLabel.PROJECT_POLICY
    assert by_name["Interpreter confidence"] is SourceLabel.MODEL_INTERPRETATION
    assert by_name["Decision"] is SourceLabel.GUARDRAIL_DECISION
    assert by_name["Provider postcondition"] is SourceLabel.SIMULATED_PROVIDER_RESULT


def test_the_provenance_chain_is_in_the_specified_order(ledger):
    for row in ledger[:40]:
        chain = provenance_chain(row)
        orders = [step.order for step in chain]
        assert orders == sorted(orders)
        assert orders[0] == 1 and orders[-1] == 10
        assert chain[0].title.startswith("Input source")
        assert "Audit receipt" in chain[-1].title


def test_the_interpreter_step_appears_only_when_a_model_was_consulted(ledger):
    """An empty interpreter step on a deterministic arm implies a model ran."""
    for row in ledger:
        has_step = any(step.order == 6 for step in provenance_chain(row))
        if row.get("arm") != "B3":
            assert not has_step, (
                f"arm {row.get('arm')} is deterministic but shows an interpreter step"
            )


def test_the_interpreter_step_states_it_cannot_authorize(ledger):
    b3 = [row for row in ledger if row.get("arm") == "B3"]
    assert b3, "expected B3 rows in the canonical evidence"
    for row in b3:
        step = next((s for s in provenance_chain(row) if s.order == 6), None)
        if step is None:
            continue
        text = " ".join(value for _, value in step.details).lower()
        assert "cannot authorize" in text
        assert step.label is SourceLabel.MODEL_INTERPRETATION
        return
    pytest.skip("no B3 row in this evidence consulted the interpreter")


# ---------------------------------------------------------------------------
# 9. Hash consistency.
# ---------------------------------------------------------------------------


def test_the_payload_hash_and_receipt_hash_survive_the_view_unchanged(ledger):
    """The viewer must not reformat, truncate, or normalise a hash."""
    checked = 0
    for row in ledger:
        fields = {item.name: item.value for item in lineage_for(row)}
        payload = row.get("provider_payload_hash")
        if payload:
            assert fields["Payload SHA256"] == str(payload)
            checked += 1
        receipt = row.get("audit_event_hashes")
        if receipt:
            for digest in receipt if isinstance(receipt, list) else [receipt]:
                assert str(digest) in fields["Audit receipt hash"]
    assert checked, "no payload hashes found to verify"


def test_the_ledger_snapshot_hash_is_shared_by_every_row_of_a_run(ledger):
    """One frozen ledger per run is the whole basis of comparability."""
    hashes = {row.get("ledger_sha256") for row in ledger if row.get("ledger_sha256")}
    assert hashes, "no ledger hash recorded"
    per_case = {}
    for row in ledger:
        per_case.setdefault(row.get("case_id"), set()).add(row.get("ledger_sha256"))
    for case_id, values in per_case.items():
        assert len(values) == 1, f"case {case_id} compared arms across two ledgers"


# ---------------------------------------------------------------------------
# 10, 11, 12, 13, 14. The feature changed nothing it was not allowed to change.
# ---------------------------------------------------------------------------


def test_policy_outcomes_are_identical_with_the_view_layer_imported():
    """Importing an inspection module must not perturb the runtime."""
    from bailiff.demo import execute, make_ambiguous_event, make_event

    def outcome(event):
        decision, _result, provider, _chain, _engine = execute(event)
        return (
            tuple(decision.reason_codes),
            str(decision.final_action),
            provider.call_count,
        )

    permitted_before = outcome(make_event("view_layer_probe"))
    ambiguous_before = outcome(make_ambiguous_event("view_layer_ambiguous"))

    import bailiff.lineage as lineage_module  # noqa: F401  (import is the point)

    assert outcome(make_event("view_layer_probe")) == permitted_before
    assert outcome(make_ambiguous_event("view_layer_ambiguous")) == ambiguous_before



def test_the_ui_does_not_regenerate_a_chart():
    """Structural: the app must contain no chart writing call at all."""
    source = (ROOT / "app.py").read_text()
    for forbidden in ("savefig", "make_frontier", "make_sensitivity_chart", "make_architecture"):
        assert forbidden not in source, f"app.py references chart generation: {forbidden}"


def test_the_ui_never_writes_to_disk():
    """No open-for-write, no unlink, no mkdir anywhere in the view layer."""
    for relative in ("app.py", "bailiff/lineage.py"):
        source = (ROOT / relative).read_text()
        for forbidden in (
            "write_text",
            "write_bytes",
            "os.remove",
            "shutil.",
            ".unlink(",
            "mkdir(",
            '"w"',
            "'w'",
        ):
            assert forbidden not in source, (
                f"{relative} contains a write operation ({forbidden}); the "
                f"inspection layer must be read only"
            )


def test_the_ui_makes_no_network_call():
    for relative in ("app.py", "bailiff/lineage.py"):
        source = (ROOT / relative).read_text()
        for forbidden in ("requests.", "urllib.request", "httpx.", "socket.", "openai"):
            assert forbidden not in source, (
                f"{relative} references network access ({forbidden})"
            )


def test_the_app_degrades_clearly_when_streamlit_is_missing(monkeypatch, capsys):
    """A judge without Streamlit must get an instruction, not a traceback."""
    import app as app_module

    monkeypatch.setattr(app_module, "HAS_STREAMLIT", False)
    with pytest.raises(SystemExit) as exit_info:
        app_module.main()
    assert exit_info.value.code == 1
    printed = capsys.readouterr().out
    assert "streamlit is not installed" in printed
    assert "pip install streamlit" in printed


def test_the_displayed_arm_order_is_exactly_the_canonical_order():
    import app as app_module

    assert tuple(app_module.ARMS) == CANONICAL_ARM_ORDER
    assert CANONICAL_ARM_ORDER == ("B0", "B1", "B1.5", "RZP", "B2.25", "B2.5", "B2.75", "B2", "B3")


def test_the_exception_queue_is_reachable_as_a_screen():
    source = (ROOT / "app.py").read_text()
    assert "Exception Queue" in source
    assert "render_exception_queue" in source


def test_the_taxonomy_covers_every_exception_class_the_specification_names():
    required = {
        "ABSTAIN",
        "HUMAN_REVIEW_REQUIRED",
        "UNKNOWN_POSTCONDITION",
        "TIMEOUT",
        "DUPLICATE_DELIVERY_IGNORED",
        "SUPERSEDED_BY_TERMINAL_EVENT",
        "BLOCKED_SUBSCRIPTION_PAUSED_OR_HALTED",
        "SIGNATURE_MISMATCH",
        "STALE_DELIVERY",
        "MALFORMED_BODY",
    }
    missing = required - set(EXCEPTION_TAXONOMY)
    assert not missing, f"exception taxonomy is missing {sorted(missing)}"


def test_webhook_verdict_codes_classify_without_touching_the_ledger():
    """Ingress refusals are exceptions too, and arrive as verdicts not rows."""
    for code in (
        "SIGNATURE_MISMATCH",
        "DUPLICATE_DELIVERY_IGNORED",
        "SUPERSEDED_BY_TERMINAL_EVENT",
        "BLOCKED_SUBSCRIPTION_PAUSED_OR_HALTED",
    ):
        verdict = {"reason_code": code, "case_id": NOT_PRESENT, "arm": NOT_PRESENT}
        item = to_exception_row(verdict)
        assert item is not None, f"{code} was not recognised as an exception"
        assert item.provider_calls == 0
        assert item.severity in SEVERITY_ORDER
