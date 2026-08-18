# M3B Livesell Reply Adapter Implementation Plan

> **Execution note:** This plan was executed sequentially in the shared workspace. The builder later approved the exact implementation and evaluation commit messages.

**Goal:** Connect the reviewed M3A static agent core to SideStage's M1 seller facts and M2.3 temporal marketplace runtime through one observable, grounded, and safely brokered customer-reply path.

**Architecture:** Keep M3A unchanged and domain-neutral. M3B owns a hardcoded eight-stage `process_customer_reply()` envelope: ingest, normalize/deduplicate, deterministic route, strategy-specific model work and tenant-scoped evidence handling, registered M3A agent execution, application-owned broker, and result publication. SQLite remains authoritative; browser surfaces render backend state and traces. The later approved-template/OpenRouter plan supersedes this plan's original two-call-only interior without adding a generic workflow engine.

**Technology:** Python 3.12, Pydantic v2, FastAPI, SQLite/FTS5, asyncio, existing M3A `ModelRunner`/`StaticAgentCore`, pytest, Playwright, SSE.

**Source contracts:** `docs/PRD.md`, `docs/TDD.md`, and `docs/plans/2026-08-17-sidestage-v1-milestones.md` are authoritative. This file operationalizes those accepted decisions and does not introduce a workflow registry, dynamic tools, model effect authority, or a third model round.

**Execution status (2026-08-18):** Runtime behavior is committed in `7d6c349`; replay, pressure evaluation, and benchmark diagnostics are committed in `6ba208a`. The exact commit-bound command `.venv/bin/pytest -q` passes with `288 passed, 4 deselected in 43.52s`, so deterministic behavior is `Verified`. The live pressure gate remains open. The pre-commit two-call Luna run produced 54/72 supported answerable suggestions, 14 hard timeouts, and 4,530.28 ms end-to-end p95; the later one-call Luna challenger improved to 66/72, zero hard timeouts, and 3,414.37 ms p95. Neither passes the release gate, and neither live artifact is `Measured`.

---

## Task 1: M3B.1 reply boundaries and immutable lifecycle

**Files**

- Create `src/sidestage/domain/replies.py`.
- Create `src/sidestage/copilot/__init__.py` and `src/sidestage/copilot/contracts.py`.
- Create `tests/unit/test_reply_contracts.py`.

**RED**

- Assert closed enums and immutable contracts for question state, route, fact type, evidence status, analysis failure, retrieval failure, terminal reply intent, abstention, broker verdict, and reply receipt.
- Assert `asked_at` and every `state_changed_at` are required trusted UTC values.
- Assert invalid lifecycle transitions and extra authority/credential/oracle fields fail validation.
- Assert the model-visible `ReplyTask` excludes tenant authority, write identity, prior chat, customer memory, R3 state, secrets, and evaluator labels.

**GREEN**

- Implement only the contracts required by the accepted two-call path.
- Add explicit conversion from `ReplyTask` to M3A `AgentTask`, with identity/deadline metadata kept outside model input.

**Verify**

```bash
uv run pytest tests/unit/test_reply_contracts.py -q
```

## Task 2: M3B.1 deterministic routing and temporal binding

**Files**

- Create `src/sidestage/copilot/routing.py`.
- Extend SQLite schema/repositories only for canonical questions and lifecycle state.
- Create `tests/integration/test_copilot_routing.py`.

**RED**

- Assert event-ID and normalization-equivalent duplicates group only within seller/show/bound epoch.
- Assert semantic paraphrases remain independent.
- Assert emoji-only and allowlisted standalone greetings exit before model work; mixed questions continue.
- Assert ask-time listing epoch is immutable across Swap.
- Assert already-inactive questions become `needs_seller(previous_listing)` with no analysis/retrieval/reply-agent call.
- Assert canonical persistence and state transition are atomic and tenant-scoped.

**GREEN**

- Implement bounded normalization and deterministic pre-routing.
- Persist the canonical question identity and ask-time listing binding.
- Reuse M2.3's trusted `accepted_at`, `source_epoch_id`, and `source_listing_id`.

**Verify**

```bash
uv run pytest tests/integration/test_copilot_routing.py -q
```

## Task 3: M3B.1 bounded analysis and tenant-scoped retrieval

**Files**

- Create `src/sidestage/copilot/analysis.py` and `src/sidestage/copilot/retrieval.py`.
- Extend SQLite schema/repositories with typed static evidence records and FTS5 research index.
- Create `tests/integration/test_analysis.py` and `tests/integration/test_retrieval.py`.

**RED**

- Assert exactly one bounded non-effect analysis request per eligible question.
- Assert malformed, unavailable, or late analysis returns a typed failure and starts no retrieval/reply-agent work.
- Assert analysis can request intent, mentions, and fact types, but cannot set tenant, truth, binding, authority, or effect identity.
- Assert tenant filtering occurs before exact or FTS5 lookup.
- Assert each evidence item has stable ID, source JSON pointer, entity version, import timestamp, and `synthetic_seller_data` provenance.
- Assert fresh mutable price/stock/listing facts come from SQLite and wrong-SKU, stale, missing, or conflicting evidence fails closed.
- Assert no fixture oracle, prior chat, model output, or R3 state enters the reply task.

**GREEN**

- Implement an analysis-specific one-request adapter over the existing `ModelRunner` port, separate from M3A's registered reply-agent run.
- Project approved fixture facts into a typed evidence table/FTS index during database initialization.
- Build one immutable evidence snapshot for the ask-time listing.

**Verify**

```bash
uv run pytest tests/integration/test_analysis.py tests/integration/test_retrieval.py -q
```

## Task 4: M3B.1 eight-stage runtime trace spine

**Files**

- Create `src/sidestage/trace/__init__.py` and `src/sidestage/trace/recorder.py`.
- Create `src/sidestage/copilot/pipeline.py`.
- Create `tests/integration/test_reply_pipeline_trace.py`.

**RED**

- Assert the exact eight backend stages are emitted by actual component calls in order.
- Assert every invoked stage emits `started` plus exactly one terminal observation.
- Assert every downstream stage is `skipped` after a blocking failure or exit.
- Assert trace IDs, analysis IDs, evidence snapshot IDs, M3A run/profile IDs, verdicts, UTC timestamps, and monotonic durations correlate correctly without sensitive payloads.
- Assert trace persistence failure is fail-open and cannot authorize work.

**GREEN**

- Implement fail-open SQLite trace persistence.
- Implement the approved order directly in `process_customer_reply(raw_event, services)` without a generic executor or registry.

**Verify**

```bash
uv run pytest tests/unit/test_reply_contracts.py tests/integration/test_copilot_routing.py tests/integration/test_analysis.py tests/integration/test_retrieval.py tests/integration/test_reply_pipeline_trace.py -q
uv run pytest -q
```

## Task 5: M3B.2 registered livesell profile and independent broker

**Files**

- Create `src/sidestage/copilot/profile.py` and `src/sidestage/copilot/broker.py`.
- Create `tests/unit/test_livesell_profile.py`, `tests/integration/test_livesell_agent.py`, and `tests/integration/test_reply_broker.py`.

**RED**

- Assert startup registers exactly `request_reply_send` and `abstain` against the public M3A registry/core.
- Assert missing/mismatched registration starts zero provider work.
- Assert terminal schemas reject authority fields, invalid evidence IDs, free text, multiple tools, unknown tools, and malformed arguments.
- Assert broker independently verifies membership, tenant, binding, category, supported claim spans, price, stock, policy, freshness, canonical uniqueness, and hard tone rules.
- Assert prompt injection, fabricated/foreign/irrelevant/stale evidence, and advisory model categories cannot bypass the broker.

**GREEN**

- Implement `register_livesell_reply_agent(model_runner)` and inject the immutable handle at application startup.
- Decode M3A terminal intent into M3B's typed intent only after core validation.
- Keep the broker entirely application-owned and effect-capable only after its independent verdict.

**Verify**

```bash
uv run pytest tests/unit/test_livesell_profile.py tests/integration/test_livesell_agent.py tests/integration/test_reply_broker.py -q
```

## Task 6: M3B.2 R2 persistence, API, SSE, and Inbox

**Files**

- Extend `src/sidestage/app.py`, SQLite schema/repositories, and `src/sidestage/web/static/`.
- Create `tests/e2e/test_r2_inbox.py`.

**RED**

- Assert normal lifecycle `queued -> ai_working -> awaiting_review -> answered_by_seller`.
- Assert unchanged AI suggestions are revalidated; stale suggestions return for a new seller decision.
- Assert seller edits/manual replies are sent byte-for-byte with nonblocking warnings.
- Assert previous-listing manual reply works without an AI draft.
- Assert duplicate clicks cannot send twice.
- Assert reply, receipt, canonical uniqueness, terminal question state, and SSE record commit atomically.

**GREEN**

- Add background reply processing after authoritative chat acceptance.
- Add seller review endpoints and live Inbox projection.
- Preserve M2.3 session, snapshot, and replay semantics.

**Verify**

```bash
uv run pytest tests/e2e/test_r2_inbox.py -q
uv run pytest -q
```

## Task 7: M3B.3 default-off R3 capability and final races

**Files**

- Extend broker, application, storage, and Inbox UI.
- Create `tests/integration/test_r3_safety.py` and `tests/e2e/test_r3_controls.py`.

**RED**

- Assert R3 is default-off, authenticated enable shows persistent warning, and disable is immediate/versioned.
- Assert only current price, exact variant availability, and exact-match shipping/payment/return policy are eligible.
- Assert broker renders R3 text from verified typed claims and bounded tone variants; model prose is never auto-sent.
- Assert final capability, epoch/SKU, price, stock, policy, uniqueness, and transaction checks.
- Assert disable, Swap, state-version, injection, malformed claims, duplicate, tone, and persistence races produce zero unauthorized writes.

**GREEN**

- Persist versioned R3 capability.
- Add narrow broker rendering and atomic final send transaction.
- Add visible enable/disable controls and warning.

**Verify**

```bash
uv run pytest tests/integration/test_r3_safety.py tests/e2e/test_r3_controls.py -q
uv run pytest -q
```

## Task 8: M3B.4 deterministic livesell harness and debugger

**Files**

- Create `fixtures/scenarios/pressure_v1.json` and `fixtures/scenarios/safety_races_v1.json`.
- Create `src/sidestage/fixtures/generator.py`, `src/sidestage/fixtures/replay.py`, and `src/sidestage/trace/evaluator.py`.
- Replace the M2 presentation trace source in `debug.html`/`debugger.js` with persisted runtime traces.
- Create unit, integration, and browser tests named in the milestone plan.

**RED/GREEN**

- Implement the exact fixed-seed quotas, duplicate semantics, burst window, listing-change scheduling, digests, runtime/oracle separation, byte-stable replay, and failure diagnostics from M3B.4.
- Require exactly 24 seller-scoped candidates marked `pressure_answerable=true`, all answerable against the seller's designated primary active listing or seller-wide policy; do not use broader multi-product presentation or temporal-race pools to pad the stable pressure denominator.
- Route every scripted reply decision through the actual M3A core.
- Render backend observation IDs and actual outcomes; do not maintain a frontend stage catalog or infer success.

**Verify**

```bash
uv run pytest tests/unit/test_scenario_generator.py tests/integration/test_fixture_replay.py tests/integration/test_trace_evaluator.py tests/e2e/test_debugger.py -q
uv run python -m sidestage.fixtures.generator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --output runs/regression_v1
uv run python -m sidestage.trace.evaluator --scenario fixtures/scenarios/safety_races_v1.json --seed 20260817 --model scripted --output runs/exploratory/evaluation_scripted.json
```

## Task 9: M3B.5 live pressure, latency accounting, and golden demo

**Files**

- Extend evaluator/instrumentation and add `tests/integration/test_latency_accounting.py` and `tests/e2e/test_golden_demo.py`.
- Update `README.md` only after commands work.

**RED/GREEN**

- Account R2/R3 latency from trusted acceptance through the approved backend publication/commit boundary, including queue wait.
- Enforce 64 capacity/show, four reply workers/show, twelve global, two-second p95 target, and five-second hard timeout.
- Run the approved three-seller, 120-chat/30-second pressure workload and golden flow.
- Retain model, seed, fixture/profile digest, config, commit field, and dirty flag; label exploratory results `Implemented`, never `Measured`.
- Provide `create_live_app()` as the fail-fast reviewer Uvicorn factory. It constructs one shared strict runner from exported model environment, records only sanitized configuration, closes owned HTTP resources, and leaves `create_app()` credential-free for deterministic injection/inspection.

**Verify**

```bash
uv run pytest tests/integration/test_latency_accounting.py tests/e2e/test_golden_demo.py -q
uv run pytest tests/integration/test_live_app_factory.py -q
uv run pytest tests/integration/test_live_app_factory.py::test_live_app_factory_executes_the_real_two_call_r2_path -m live_model -q
uv run python -m sidestage.trace.evaluator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --model live --output runs/exploratory/evaluation_live_precommit.json
```

## Task 10: M3B.6 audit and pending clean-commit verification

**Status:** The no-commit deterministic audit and documentation/artifact reconciliation are complete. Final verification remains blocked by the failed Task 9 live gate and the required builder-approved commit sequence.

**No-commit audit now**

- Run every focused deterministic gate, full suite, lock check, diff check, credential-pattern scan, and source/doc consistency review.
- Update PRD/TDD/milestone/debug/README only with actually implemented or verified evidence.
- Leave clean-commit live measurement and final submission evidence explicitly pending.

**Deferred until builder approves commits**

- Create reviewed commits with builder-approved exact messages.
- Rerun from the clean M3B.5 implementation commit.
- Retain `runs/final_evaluation/` with that commit hash.
- Promote evidence to `Verified`/`Measured` only when commands and artifacts satisfy M3B.6.
