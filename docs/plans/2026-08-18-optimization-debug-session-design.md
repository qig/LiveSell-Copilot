# Optimization and Debug Session Design

> Status: `Implemented` in the current uncommitted tree; pre-commit deterministic and browser checks pass, but commit-bound `Verified` and live `Measured` evidence remain pending
>
> Date: 2026-08-18
>
> Milestone: M3B.5

## Purpose

Let a developer compare approved SideStage workflows and LLM models against one active synthetic seller/show without restarting the server. The debugger owns the controls. The seller marketplace displays the active selection read-only. Selected runs use the real reply pipeline and may produce normal R2 review cards or broker-authorized R3 replies.

The switch is an evaluation control, not new agent authority. Existing grounding, freshness, tenant, canonical-question, R3 capability, receipt, and kill-switch checks remain unchanged.

## Accepted decisions

- Scope is one seller/show, selected from the authenticated debugger.
- The server registers both closed workflows and an approved model allowlist before accepting chat.
- Workflow and model use independent selectors, constrained by a server-owned compatibility matrix.
- Arbitrary model IDs, prompts, schemas, tools, templates, base URLs, credentials, and effect permissions cannot be entered at runtime.
- A switch affects only chat accepted afterward. Queued and in-flight questions retain their captured selection.
- Overrides are session-only and reset to startup defaults after restart or show recreation.
- The marketplace shows the active workflow/model as a read-only badge.
- The switch action itself is outside the reply SLO. Reply processing retains the existing `accepted_at`-to-publication boundary.
- The first model-backed request after a selection version is a cold sample. Later model-backed requests are steady-state. Reports also retain the combined distribution.

## Architecture

M3A remains unchanged. `AgentProfileRegistry` and every registered terminal schema remain immutable after startup.

SideStage adds two bounded startup catalogs:

1. A workflow catalog containing only `one_call_template` and `two_call_draft`.
2. A model catalog containing approved public profile ID, provider, exact requested model ID, sanitized configuration reference, reasoning setting, optional direct-OpenAI service tier, timeout, and supported workflows.

Startup validates all entries and builds reusable runners and workflow handles. The runtime selector resolves a compatible pair from those immutable entries. It is not a general workflow engine, plugin system, or runtime registration API.

Each seller/show has an in-memory active selection with a monotonically increasing version. The configured default is version 1. A successful debugger switch atomically installs the next version. Restart discards overrides.

## Data flow

1. The debugger fetches sanitized workflow/model catalogs plus the selected show's active version.
2. The browser disables incompatible pairs. The server independently validates every submitted pair and authenticated seller/show scope.
3. A successful switch updates the in-memory selection and publishes a new snapshot/SSE event.
4. Chat acceptance copies the active workflow ID, model-profile ID, requested model, configuration reference, and selection version into trusted question execution metadata.
5. `process_customer_reply()` resolves the captured entry and dispatches through one of its two explicit branches.
6. The selected immutable runner performs its registered call or calls. Later switches cannot change the captured handles.
7. The existing broker determines deny, R2 review, or authorized R3 send.
8. Question state, trace observations, Inbox cards, receipts, and SSE projections record the pinned public configuration identity. Resolved model/provider and routing attempts are added when known.

## Failure handling

- Invalid startup registrations fail before database initialization or chat acceptance.
- Unknown or incompatible switch requests return a typed conflict and do not change the active version.
- A missing captured catalog entry fails closed before provider work and produces no reply effect.
- A failed provider call remains attributed to its pinned selection and follows the existing typed failure path.
- A switch cannot cancel, restart, or partially reconfigure in-flight work.
- The active marketplace badge may update after a switch, but historical cards, receipts, and traces continue to show their pinned version.
- Credentials and raw authorization headers never enter API responses, SQLite metadata, SSE payloads, traces, or model input.

## Latency reporting

For each workflow/model pair, report:

- Cold request count and individual latency.
- Steady-state p50, p95, and maximum.
- Combined p50, p95, maximum, SLO misses, and hard timeouts.
- Queue wait, provider duration per call, parse/render time, broker/persistence/publication time, token usage, and cost when available.

Noise and duplicate paths that make no provider request do not consume the cold marker. Cold requests remain in the combined release distribution; they are separated only to explain startup behavior.

## Test boundary

The implementation gate requires deterministic proof of:

- Startup allowlist validation, sanitized projection, and credential exclusion.
- Browser and server compatibility enforcement.
- Per-show isolation and session-only reset.
- Atomic version increments and switch visibility through snapshot/SSE.
- Acceptance-time pinning across delayed, queued, and in-flight questions.
- No mixed workflow/model stages in one trace.
- Unchanged R2/R3 authorization, freshness, receipt, duplicate, and kill-switch behavior.
- Read-only marketplace badge convergence without stale-SSE regression.
- Trace, card, and receipt attribution to requested and resolved identities.
- Correct cold-marker consumption and cold/steady/combined latency calculations.

Live results remain diagnostic until a committed configuration, fixed workload, exact model/provider identity, and retained artifact satisfy the M3B.6 evidence gate.

## Implementation snapshot

The current uncommitted tree implements this boundary in `src/sidestage/copilot/runtime.py`, `src/sidestage/trace/runtime_metrics.py`, `src/sidestage/app.py`, the SQLite projections, and the two static browser surfaces. `config/runtime_model_profiles.json` is the credential-free live catalog; the ignored `.env` remains the only source of provider secrets. Deterministic coverage is concentrated in `tests/unit/test_runtime_selection.py`, `tests/integration/test_runtime_switching.py`, `tests/integration/test_live_app_factory.py`, the R3 receipt suite, and `tests/e2e/test_debugger.py`.

The catalog treats provider, exact model, reasoning effort, and service tier as one immutable profile identity. Direct OpenAI Luna exposes standard `none`, standard `low`, and priority `none` profiles; `service_tier=priority` is independent of reasoning. OpenRouter Gemini 3.7 Flash `low` and Gemini 3.5 Flash-Lite `minimal` are separate candidates. OpenRouter reasoning uses the router's unified `reasoning.effort` envelope, and an OpenAI service tier on an OpenRouter profile is rejected before startup.

The exact full offline command `.venv/bin/pytest -q -m 'not live_model'` passed with `300 passed, 5 deselected in 53.98s`, including the localhost Playwright/server checks. The browser regressions switch to a second model profile in the debugger, return to the seller workspace, observe the exact friendly profile name plus selection version in the read-only badge, and prove that show controls are inert while a seller-session change is pending. This supports `Implemented`, not commit-bound `Verified`. A credential-safe startup check of the builder's current `.env` failed because it contains `OPEN_API_KEY` rather than `OPENAI_API_KEY` and omits `SIDESTAGE_MODEL_ID`. A command-scoped alias allowed an earlier test to switch the show to Kimi version 2 and reach OpenRouter, but that request failed closed on HTTP 429; a successful live switched response is not claimed.
