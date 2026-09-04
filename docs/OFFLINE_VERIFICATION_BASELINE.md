# Final verification record

> **Scope of this record:** this document records the frozen **offline MandateGuard benchmark/archive verification**. It predates the optional RecoveryTruth Razorpay Test Mode execution path. Statements below about no Razorpay API calls refer to that frozen offline proof only. RecoveryTruth Test Mode evidence is **WAITING_FOR_TEST_MODE_CREDENTIALS**; this record does not contain receipts, Payment IDs, or RecoveryProof. A new final verification record will supersede this one after the credentialed Test Mode fallback, SAFE_BLOCK, and RecoveryProof artifacts are captured.

Everything below was produced by running the commands in this file against
the packaged archive, not carried forward from an earlier run. Where a number
appears here it was read off the run, not typed from memory.

## How this was verified

The archive was extracted into an empty directory and installed into a
**fresh virtual environment** with **no `PYTHONPATH` set** and no reliance on
any previously installed copy of the package. That matters more than it
sounds: an editable install left over from an earlier session can make
`import bailiff` succeed for reasons that have nothing to do with the archive
under test, which is exactly the kind of false pass this project is built to
refuse.

```bash
unzip -q mandateguard_submission_final_ready.zip
cd mandateguard_policy_lab
sha256sum -c SHA256SUMS.txt          # before installing anything

python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
python3 -m compileall -q bailiff tests scripts
bash scripts/test.sh
python3 scripts/mutation_check.py
python3 scripts/demo60.py
bash scripts/demo.sh
bash scripts/release_check.sh
bash scripts/verify_all.sh
sha256sum -c SHA256SUMS.txt          # again, after the whole workflow
```

This exact sequence was run twice against this v2 archive: once against the
working tree before packaging, and once more as a genuinely fresh extraction
of the built ZIP into an empty directory, in its own fresh virtual
environment, as the final acceptance test before this record was written.

## Results

| Check | Result |
|---|---|
| `compileall` (bailiff, tests, scripts) | clean |
| Test suite | **283 passed, 0 failed, 0 skipped** |
| Mutation check | **14 of 14 mutations caught** |
| Red team attacks (`tests/test_adversarial.py`) | 46 |
| Webhook ingress attacks (`tests/test_webhook_ingress.py`) | 39 |
| Policy arms | **9**, canonical order below |
| `scripts/demo60.py` | runs, prints its own live-checked counts |
| `scripts/demo.sh` | runs |
| Release gate (`scripts/release_check.sh`) | **passed** |
| Deep verification (`scripts/verify_all.sh`) | **all four stages passed** |
| Checksum manifest entries | **86** |
| Manifest immediately after extraction | **86 of 86 files verify** |
| Manifest after the entire workflow | **86 of 86 files verify** |
| Canonical outputs unchanged by the UI | **13 of 13 byte identical** |
| Clean install, no `PYTHONPATH` | works |
| Secrets, keys, caches, venvs, `.pyc` in archive | none |

The test count moved from 282 to 283 in this v2 build. It is not a chosen
number: a real defect surfaced while re-running the release gate in a fresh
virtual environment (below), a regression test was added so it cannot recur
silently, and 283 is what `pytest --collect-only` actually reports afterward.

The canonical policy arm order, from `bailiff.policies.CANONICAL_ARM_ORDER`,
which the UI now derives from rather than duplicating:

```text
B0, B1, B1.5, RZP, B2.25, B2.5, B2.75, B2, B3
```

Test, mutation, and webhook-attack counts are not trusted as prose anywhere.
`scripts/demo60.py` prints the first three and
`tests/test_demo60.py::test_the_closing_test_and_mutation_count_matches_reality`
re-derives them from a live `pytest --collect-only`; the webhook count in
`README.md` and `docs/panel_qa.md` is re-derived the same way by
`tests/test_positioning_discipline.py::test_the_webhook_attack_count_matches_the_real_suite`.
A stale count cannot survive a green run.

## UI read only guarantee

The lineage panel, exception queue, and action provenance chain are pure
functions in `bailiff/lineage.py` over evidence the benchmark already wrote.
They compute no benchmark metric, open no ledger, write no file, and open no
socket. `app.py` only renders what they return. No control on any screen
executes, approves, retries, or contacts anyone.

This is enforced, not asserted. `tests/test_lineage_and_exception_queue.py`:

| Guarantee | Enforcement |
|---|---|
| Never calls the provider simulator | Every public method on `ReplayProvider` is replaced with a trap, then the full queue is built |
| Never mutates a canonical output | All 13 canonical artefacts hashed before and after a full render pass over all 900 evidence rows |
| Never reaches the network | `socket.connect`, `socket.create_connection`, `socket.getaddrinfo` blocked during rendering |
| Never writes to disk | `app.py` and `bailiff/lineage.py` scanned for write operations |
| Never regenerates a chart | `app.py` scanned for `savefig` and the chart generators |
| Invents nothing | A field the evidence lacks renders as `not present in fixture`, asserted per row |
| Rows are immutable | Queue rows are frozen dataclasses; mutation raises |
| Arm order is canonical | `app.ARMS` is asserted equal to `CANONICAL_ARM_ORDER` |
| Degrades clearly | With Streamlit absent, `main()` exits 1 with an install instruction, not a traceback |

Measured independently of the tests: hashing the 13 canonical outputs, then
rendering lineage and provenance for all 900 evidence rows plus the full
exception queue and every UI data loader, then re-hashing — **all 13
unchanged**.

## Exception queue no call guarantee

The queue is derived entirely from reason codes the runtime already emitted.
It recalculates nothing. In the shipped evidence it surfaces 76 exceptions:
73 `HUMAN_REVIEW_REQUIRED` and 3 `ABSTAINED`, every one of them showing
`provider_calls = 0`.

Two honest notes about coverage:

* The frozen benchmark ledger contains **no timeout** — every row records
  `provider_timed_out: false`. Rather than fabricate one, the timeout
  behaviour is asserted directly against the shape the runtime produces for a
  timeout, and `scripts/demo60.py` exercises the real path end to end. A
  timeout row reports unknown postcondition and routes to human review.
* Webhook ingress refusals (signature, duplicate, stale, superseded,
  paused/halted, malformed) are verdicts rather than ledger rows. The
  taxonomy covers them and classification is tested, but they appear in the
  queue only when such verdicts are supplied. Nothing is invented to fill the
  screen.

If a non executing row ever reported a provider call, the queue surfaces it
as an invariant contradiction rather than rendering it quietly.

## No Rillet integration

Rillet's public Aura and MCP material was used as design inspiration for
contextual data access, reviewable workflow actions, permission boundaries,
and auditability. MandateGuard does not integrate with Rillet. It applies
those ideas narrowly to scheduled AutoPay recovery policy evaluation.

There is no Rillet dependency, credential, endpoint, MCP server, or runtime
reference in this repository. The name appears nowhere in the product, the
UI, the policy arm list, the API, or the benchmark — only in the design
credit sentences in `README.md`, `ARCHITECTURE.md`, and `docs/panel_qa.md`.
`tests/test_positioning_discipline.py` fails the suite if any shipped
document ever asserts "Rillet integration", "integrates with Rillet",
"powered by Rillet", "built on Rillet", or "Rillet MCP".

## Frozen offline archive provider scope

No Razorpay API was called by the frozen offline archive verified in this record. The input is a Razorpay *shaped*,
signed test webhook fixture; the provider is a local simulator; no production
money moves and no customer is contacted. Every rupee figure is a synthetic
counterfactual over a frozen generated ledger.

## Chart checksum policy

Three of the 86 shipped files are rendered PNGs:
`outputs/architecture.png`, `outputs/frontier.png`, `outputs/sensitivity.png`.

**They are not byte reproducible across environments.** This was measured,
not assumed: from identical input data and identical source, Matplotlib
3.10.9 and Matplotlib 3.11.1 render all three differently. Every other
shipped file — source, documentation, JSON evidence, `ROBUSTNESS.md` — is
byte identical across both environments, including the artefacts the sweep
rewrites during verification.

So the contract is drawn where it can be kept:

* `SHA256SUMS.txt` is the checksum of the **shipped archive contents**. It
  must verify immediately after extraction, and it must still verify after
  the full verification workflow.
* It is **not** a claim that re-rendering the charts elsewhere reproduces the
  same bytes. `scripts/evaluate.sh` is the regeneration entry point, and on a
  different Matplotlib it will legitimately change those three hashes. If you
  regenerate, regenerate `SHA256SUMS.txt` in the same environment and re-ship
  both.

Two mechanisms keep that boundary from being erased by a later edit:

1. `scripts/verify_all.sh` captures the three chart hashes before stage 1 and
   re-checks them after stage 4, failing loudly if verification changed a
   chart. It then re-runs `sha256sum -c SHA256SUMS.txt` as its closing step.
2. `tests/test_chart_checksum_policy.py` asserts structurally that no
   verification script regenerates a chart, including transitively, and
   `tests/test_lineage_and_exception_queue.py` asserts the UI cannot either.

That second test exists because this genuinely went wrong once. The release
gate rebuilds derived evidence when it is missing, and `outputs/generated` is
deliberately not shipped — so in a *fresh extraction* the rebuild branch
always fired, called `scripts/evaluate.sh`, re-rendered all three charts, and
broke `sha256sum -c` for any reviewer whose Matplotlib differed. It now
preserves the shipped chart bytes across that rebuild.

## The one-command judge path is tested, not assumed

The README tells a reviewer to run:

```bash
pip install -r requirements.txt
python3 scripts/demo60.py
```

That exact path was executed in a clean virtual environment from a clean copy
of the tree, with no package install and no `PYTHONPATH`. The demo runs.

It did not always. `requirements.txt` omitted `hypothesis`, and the failure
mode was quiet rather than loud: nothing crashed, `tests/test_properties.py`
collected as a single skip, the total silently fell from 282 to a smaller
number, and the test that checks the advertised count then failed. A reviewer
following the documented instructions would have seen a red suite and a
project apparently overstating its own test count — which is exactly the
report that surfaced. The dependency is now pinned beside `pytest`, and
`tests/test_chart_checksum_policy.py::test_requirements_txt_covers_every_dependency_the_test_suite_imports`
fails the suite if `requirements.txt` and the test extras ever drift apart
again.

## What the RZP arm is, and is not

The RZP arm uses Razorpay's documented fixed **card** retry schedule as a
**temporal reference policy**. It does not reproduce or benchmark Razorpay's
current Intelligent UPI Retry Engine, and MandateGuard has not been evaluated
against Razorpay's production decision logic.

Every result about `RZP` is therefore a result about that fixed card-derived
temporal reference on a synthetic scheduled AutoPay ledger. Applying the card
schedule to that ledger is an explicit benchmark assumption, not a statement
about Razorpay's UPI retry behaviour or production recovery. The comparison is
framed throughout the release as **Fixed Retry Reference Policy vs Reason-Aware
Policies**.

## What changed between the hardened build and this v2 build

Two defects were found and fixed while re-running the verification gates
against a genuinely fresh checkout, neither of which was requested by name —
both surfaced because the gates were actually re-run rather than trusted from
the prior build:

1. **`scripts/release_check.sh` failed the release gate on a fresh virtual
   environment.** Its merge-conflict-marker scan did not exclude `.venv/`, so
   it tripped on legitimate `=======` section dividers inside third-party
   package metadata (`python-dateutil`, `pyparsing`) and inside a comment in
   pytest's own `_argcomplete.py` — none of it this project's source. Fixed by
   excluding standard build/cache/venv directories from the scan by name,
   leaving the project's own source, tests, docs, and outputs fully scanned.
   A regression test
   (`tests/test_chart_checksum_policy.py::test_release_check_excludes_a_fresh_venv_from_its_merge_marker_scan`)
   now asserts those exclusions are present. This is the reason the test count
   moved from 282 to 283: the fix added one test.
2. **Competitive-position wording was tightened across the release.** The
   final build makes only the claim the benchmark needs: `RZP` is derived from
   Razorpay's documented fixed card retry schedule and is a temporal reference
   arm, not a reproduction or benchmark of Razorpay's current UPI production
   retry engine.

`outputs/` was regenerated from source via `scripts/evaluate.sh` after both
fixes, rather than hand-edited, per the standard build process. Neither fix
touches any rule *value*, only documentation and a build-script glob — the
benchmark's numeric conclusions are unchanged, and the fixture sweep below
confirms it.

## Remaining limitations

These are stated here so a reviewer does not have to discover them.

1. **NPCI timing and retry values are project assumptions.** The non-peak
   windows and minimum retry gap in `bailiff/rules.json` carry source-tier
   metadata and are configurable. They are **not** pinned to a specific
   primary NPCI circular, and must not be described as official NPCI
   requirements.
2. **The failure taxonomy is a project taxonomy**, not an official or
   universal NPCI decline taxonomy.
3. **The Reddit corroboration in `docs/problem_evidence.md` was gathered by a
   separate tool and verified by the submitter**, who opened the links
   directly. It was not independently verified by the session that assembled
   this package, and the document says so. The complaint evidence supports a
   statement about what the sampled sources contained, not a claim about
   every customer everywhere.
4. **Every rupee figure is a synthetic counterfactual**, as described above.
5. **`outputs/real_interpreter_evidence.json` is a single captured run** of
   the optional real-interpreter mode against one model. It demonstrates that
   the guardrail bound holds against a live model; it is not the benchmark,
   and the default benchmark makes no model calls.
6. **The three chart PNGs are environment dependent**, as described above.
7. **There is no Razorpay MCP integration.** This frozen offline archive does
   not call Razorpay APIs; its provider is a synthetic local simulator.
   RecoveryTruth's Test Mode path is separate, not claimed as completed here,
   and is **WAITING_FOR_TEST_MODE_CREDENTIALS**. Production/live payments are
   not used. The scope of this record is the evaluation and bounded-runtime
   layer that sits in front of execution.
8. **The lineage panel cannot show fields this evidence does not carry.**
   Mandate id, scheduled execution id, event creation time, received time and
   freshness are not in the benchmark ledger. They are listed and marked
   `not present in fixture` rather than omitted or inferred.
9. **The exception queue's timeout and webhook-ingress rows are tested but
   not present in the frozen ledger**, for the reasons given above.
10. **This repository is not under version control in the build
    environment**, so no commit hash is recorded. Integrity is established by
    `SHA256SUMS.txt` and the archive sidecar hash instead.

## Note on the archive's own checksum

The SHA256 of the archive cannot live inside the archive it describes. It is
published alongside it in
`mandateguard_submission_final_ready.sha256`:

```bash
sha256sum -c mandateguard_submission_final_ready.sha256
```
