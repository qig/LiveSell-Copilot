# M3 Approved-Template and OpenRouter Benchmark Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Compare the existing two-call grounded-draft path with a one-call approved-template selector on identical SideStage workloads, using OpenRouter for cross-model measurements without weakening the broker or the p95-under-two-seconds boundary.

**Architecture:** Keep M3A unchanged as the domain-neutral, one-request static core. Implement two concrete modules selected before startup. `template_workflow.py` registers one `EvidenceTemplateAgent`; application code bulk-loads a bounded evidence bundle, and that one core call selects both evidence IDs and one approved template before deterministic rendering. `two_call_workflow.py` registers `EvidencePlannerAgent` and `ReplyDrafterAgent`; targeted deterministic retrieval runs between their two distinct task sets/core calls. Both feed the same broker. There is no generic workflow registry or runtime switching. OpenRouter is a provider configuration of the existing compatible runner, with explicit model identity, fallback disabled, routing metadata enabled, and provider/cost/usage data recorded outside model-visible context.

**Tech Stack:** Python 3.9+, Pydantic v2, FastAPI, SQLite, httpx, pytest, existing M3A `StaticAgentCore`, OpenRouter Chat Completions-compatible API.

**Repository constraint:** Do not stage or commit during this plan. The builder must approve the exact commit message after reviewing the final diff.

---

### Task 1: Synchronize the accepted product and technical decision

**Files:**
- Modify: `docs/PRD.md`
- Modify: `docs/TDD.md`
- Modify: `docs/plans/2026-08-17-sidestage-v1-milestones.md`
- Modify: `docs/ai-proposal-rejection-history.md`

**Steps:**

1. Replace the two-call-only product description with an explicit baseline/challenger decision: `two_call_draft` remains benchmarkable; `one_call_template` is the release challenger.
2. Record that a template miss, ambiguous request, unsupported request, stale evidence, or invalid terminal selection becomes `Needs seller`; it never silently invokes the two-call path.
3. Define the approved template catalog and R2/R3 eligibility. Record that application-owned rendering replaces free-form model prose on the template path.
4. Update the M3.1-M3.4 compatibility table so both strategies use the same routing, temporal binding, broker, R2/R3 authority, persistence, and evaluation invariants.
5. Add a proposal-history entry superseding the two-call-only decision because measured sequential Luna latency made that common path non-viable for the accepted p95 target. Preserve the old decision as history.
6. Review with:

```bash
rg -n "two_call_draft|one_call_template|approved template|OpenRouter|M3\.1-M3\.4" docs
```

Expected: all four governing documents describe the same strategy boundary, catalog, fallback behavior, and evidence maturity.

### Task 2: Add closed template-selection and rendering contracts

**Files:**
- Create: `src/sidestage/copilot/templates.py`
- Modify: `src/sidestage/domain/replies.py`
- Modify: `src/sidestage/copilot/contracts.py`
- Test: `tests/unit/test_reply_templates.py`
- Test: `tests/unit/test_reply_contracts.py`

**Steps:**

1. Write failing tests for the closed `ReplyTemplateId` catalog: current price, exact variant availability, shipping, payment, returns, availability summary, listing identity, release date, MSRP, materials, sizing, authenticity, condition, needs seller, and no response.
2. Require every reply template to carry selected `evidence_ids`; additionally require `variant_id` for exact availability and `identity_field` for listing identity. Safe terminal outcomes carry only a closed `reason_code`. Model output never contains reply prose, price, inventory quantity, policy/evidence values, tone text, database queries, or effect authority.
3. Add immutable `TemplateSelectionTask`, `TemplateSelectionIntent`, `RenderedTemplateReply`, and template provenance (`template_id`, `template_version`). Ensure tenant IDs and authority remain outside the model projection.
4. Implement one versioned renderer registry in `templates.py`. Each renderer selects trusted records by fact type, derives `RequestReplySendIntent` claims, and fails closed on missing, conflicting, stale, or semantically invalid evidence.
5. Add exact output tests for every template and negative tests for fabricated variant IDs, missing facts, duplicate facts, oversized output, and prohibited phrases.
6. Run:

```bash
uv run pytest tests/unit/test_reply_templates.py tests/unit/test_reply_contracts.py -q
```

Expected: all template and contract tests pass; no test permits model-authored customer prose.

### Task 3: Register the concrete workflows and their static agents

**Files:**
- Modify: `src/sidestage/copilot/profile.py`
- Modify: `src/sidestage/copilot/__init__.py`
- Create: `src/sidestage/copilot/workflows/__init__.py`
- Create: `src/sidestage/copilot/workflows/template.py`
- Create: `src/sidestage/copilot/workflows/two_call.py`
- Test: `tests/unit/test_livesell_profile.py`
- Test: `tests/integration/test_livesell_agent.py`

**Steps:**

1. Write failing tests asserting that Workflow 1 registers only `EvidenceTemplateAgent`, while Workflow 2 registers only `EvidencePlannerAgent` and `ReplyDrafterAgent` with distinct adapter/task/profile identities.
2. Route the existing evidence-planning schema through a registered M3A profile rather than direct `ModelRunner` invocation; retain the existing `MessageAnalyzer.analyze()` application interface only as a thin adapter if useful.
3. Add the evidence-template profile using the existing immutable M3A registry and FIFO/deadline machinery. Give every template tool a static schema and validate selected evidence IDs against the immutable task after the terminal call.
4. Keep registration in the two concrete workflow modules. Register only the configured workflow before chat acceptance; forbid runtime switching or agent registration.
5. Ensure Workflow 1 makes exactly one provider request and Workflow 2 makes exactly two, each through M3A, with no retry or fallback.
5. Run:

```bash
uv run pytest tests/unit/test_livesell_profile.py tests/integration/test_livesell_agent.py -q
```

Expected: both concrete workflows remain independently testable; every model call has a registered profile identity, Workflow 1 uses one request, and Workflow 2 uses two distinct agent requests.

### Task 4: Build the deterministic evidence plan and bounded snapshot

**Files:**
- Modify: `src/sidestage/copilot/retrieval.py`
- Modify: `src/sidestage/copilot/routing.py`
- Test: `tests/integration/test_retrieval.py`
- Test: `tests/integration/test_copilot_routing.py`

**Steps:**

1. Write failing tests for Workflow 1's deterministic bounded evidence bundle and Workflow 2's targeted `EvidenceRequest`, both scoped to the immutable temporal listing.
2. For Workflow 1, retrieve listing identity, current price, every current variant record, applicable shipping/payment/returns policies, and available packaged research facts in one database read boundary. The agent—not the renderer—selects the relevant record IDs.
3. Keep exact SKU/product override deterministic. Conflicting or uncertain product attribution exits to `Needs seller` before the model request.
4. Cap and sort records deterministically, preserve source versions, and reject cross-tenant, conflicting, or stale records.
5. Run:

```bash
uv run pytest tests/integration/test_retrieval.py tests/integration/test_copilot_routing.py -q
```

Expected: fixture seed and database state produce byte-stable scoped snapshots; evaluator labels never enter retrieval or model context.

### Task 5: Add the one-call challenger without replacing the baseline

**Files:**
- Modify: `src/sidestage/copilot/pipeline.py`
- Modify: `src/sidestage/copilot/broker.py`
- Modify: `src/sidestage/app.py`
- Modify: `src/sidestage/trace/recorder.py`
- Modify: `src/sidestage/trace/projection.py`
- Test: `tests/integration/test_reply_pipeline_trace.py`
- Test: `tests/integration/test_reply_broker.py`
- Test: `tests/integration/test_r3_safety.py`
- Test: `tests/e2e/test_debugger.py`

**Steps:**

1. Write failing paired-strategy tests over the same raw events and mutable marketplace state.
2. Introduce a closed runtime workflow value: `two_call_draft` or `one_call_template`. Dispatch explicitly to the two concrete modules; do not create a workflow registry, plugin mechanism, common workflow protocol, or dynamic stage executor.
3. On Workflow 1, stage 4 prepares the bounded evidence bundle, stage 5 records its snapshot, and stage 6 performs one registered evidence/template-selection request plus deterministic rendering. On Workflow 2, stage 4 is the registered planner call, stage 5 is targeted retrieval, and stage 6 is the registered drafter call. Stages 7-8 remain shared.
4. Add a broker entry point for a prevalidated `RequestReplySendIntent` plus template provenance; retain the existing agent-result entry point for the baseline.
5. Revalidate template eligibility, evidence freshness, R3 capability/version, active listing, canonical-question uniqueness, and allowed tone immediately before any send.
6. Record strategy, template ID/version, provider call count, and stage durations in backend traces. Keep the debugger a projection of recorded runtime observations.
7. Run:

```bash
uv run pytest tests/integration/test_reply_pipeline_trace.py tests/integration/test_reply_broker.py tests/integration/test_r3_safety.py tests/e2e/test_debugger.py -q
```

Expected: template misses publish `Needs seller`; no test observes a hidden second call; all existing R2/R3 race invariants remain zero.

### Task 6: Add explicit OpenRouter routing and accounting metadata

**Files:**
- Modify: `src/sidestage/agent_core/model.py`
- Modify: `src/sidestage/app.py`
- Test: `tests/unit/agent_core/test_model_runner.py`
- Test: `tests/integration/test_live_app_factory.py`

**Steps:**

1. Write failing transport tests for an OpenRouter request with one explicit model, `allow_fallbacks=false`, `require_parameters=true`, latency sorting, and router metadata enabled.
2. Extend provider configuration with optional, sanitized routing options. Default behavior must remain compatible with direct OpenAI requests.
3. Parse optional response usage, cost, resolved model, provider, and routing-attempt metadata into immutable provider metadata. Never include the API key or authorization header.
4. Read `OPENROUTER_API_KEY` only for an explicitly selected OpenRouter benchmark; continue reading `OPENAI_API_KEY` for direct OpenAI mode. Fail before database initialization on a provider/key mismatch.
5. Run:

```bash
uv run pytest tests/unit/agent_core/test_model_runner.py tests/integration/test_live_app_factory.py -q
```

Expected: payload/header snapshots prove fallback is disabled and metadata is sanitized; direct OpenAI tests remain unchanged.

### Task 7: Produce comparable strategy/model benchmark artifacts

**Files:**
- Modify: `src/sidestage/trace/pressure.py`
- Modify: `src/sidestage/trace/evaluator.py`
- Test: `tests/integration/test_trace_evaluator.py`
- Test: `tests/integration/test_latency_accounting.py`
- Update: `README.md`

**Steps:**

1. Write failing evaluator tests requiring strategy, requested/resolved model, provider, routing attempts, per-stage/provider/queue/end-to-end latency, usage, cost, coverage, contract failures, timeouts, and safety invariants.
2. Ensure each model/strategy cell uses the identical generated events, seed, fixture digest, queue policy, timeout, concurrency, and scorecard. Automatic model fallback is a benchmark error.
3. Use the separately marked one-question live workflow smoke as the compatibility screen before the unchanged fixed 360-event pressure scenario. Resolve exact OpenRouter model slugs from its live model catalog and write them into the run manifest; do not guess aliases in code or add a second scenario with different scorecard quotas.
4. Keep raw run artifacts separate by model and strategy. Reports must distinguish `Implemented` dirty-tree diagnostics from commit-bound `Verified` or `Measured` evidence.
5. Run deterministic verification first:

```bash
uv run pytest tests/integration/test_trace_evaluator.py tests/integration/test_latency_accounting.py -q
uv run pytest -q
```

6. Then run a bounded live smoke for each candidate before a full pressure run. Stop a candidate if tool compliance, safety, or timeout gates fail. The exact live command is finalized only after the OpenRouter model catalog resolves current model IDs.

Expected: a machine-readable matrix compares two-call and one-call paths without changing the SLO denominator, excluding queue time, or substituting generic M3A latency for SideStage end-to-end latency.

## Dirty-tree implementation outcome — 2026-08-18

The implementation is committed through the preliminary benchmark boundary, but the release gate is not. Runtime behavior is in `7d6c349`; replay/evaluation behavior is in `6ba208a`. The exact commit-bound command `.venv/bin/pytest -q` passes with `288 passed, 4 deselected in 43.52s`. Deterministic pressure passes both strategies; `one_call_template` makes exactly 135 scripted requests and supports 72/72 answerable parents with zero hard-invariant failures.

The live matrix has no winning cell:

| Strategy/model/transport | Supported answerable | Hard timeouts | End-to-end p95 | Outcome |
| --- | ---: | ---: | ---: | --- |
| `two_call_draft` / GPT-5.6 Luna / direct OpenAI | 54/72 | 14 | 4,530.28 ms | Fails quality and latency |
| `one_call_template` / GPT-5.6 Luna / direct OpenAI | 66/72 | 0 | 3,414.37 ms | Better architecture; still fails quality and latency |
| `one_call_template` / DeepSeek V4 Flash / OpenRouter → Inceptron | 7/72 | 88 | 5,022.01 ms | Rejected |
| `one_call_template` / Kimi K3 / OpenRouter → Together | 17/72 | 87 | 5,024.85 ms | Rejected |
| `one_call_template` / GLM 5.2 / OpenRouter | — | — | — | Strict compatibility smoke failed; pressure not run |

OpenRouter requests retain `allow_fallbacks=false`, `require_parameters=true`, data-collection denial, and sanitized router/usage metadata. They omit only the optional OpenAI `parallel_tool_calls` hint because Kimi does not advertise that parameter; SideStage's local decoder continues to require exactly one registered terminal. All live results above are pre-commit `Implemented` diagnostics. None is `Measured`, and no result supports GMV, conversion, or operator-load claims.
