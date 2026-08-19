# Demo Reset and Empty-Stage Guard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a safe full-demo reset, prevent buyer chat before a listing epoch exists, and make the high-volume chat/Inbox workspace usable without whole-page scrolling.

**Architecture:** A per-show shared/exclusive mutation gate protects all mutable demo endpoints, while a dedicated reset service restores fixture-visible state atomically and resets in-memory prepared/runtime state. The FastAPI route remains session-authoritative and projects a stable buyer/seller chat timeline. The static UI provides empty-stage gating, a confirmed Reset demo control, independent scroll regions, and a time-partitioned newest-first Inbox.

**Tech Stack:** Python 3.12, FastAPI, SQLite, asyncio, Pydantic, vanilla HTML/CSS/JavaScript, pytest, Playwright.

---

### Task 1: Lock the server contracts with failing tests

**Files:**
- Modify: `tests/integration/test_streaming_api.py`
- Create: `tests/integration/test_demo_reset.py`
- Modify: `tests/e2e/test_marketplace_ui.py`

**Steps:**

1. Add an integration test proving both `/chat/custom` and `/chat/prepared` reject with a typed `active_slot_empty` response before Push and start zero model work.
2. Add a reset test that Pushes, changes price/inventory, changes R3/runtime selection, submits chat, and asserts the reset response restores fixture-visible state and clears all dependent rows.
3. Assert a different seller/show is unchanged, internal versions advance, runtime returns to the startup default, and prepared chat restarts deterministically.
4. Add a concurrency test with a delayed model runner proving Reset cannot complete before admitted work exits and no late result appears after reset.
5. Add browser assertions for disabled chat controls, the guidance message, Reset confirmation, and post-reset Push/chat recovery.
6. Add browser assertions that Inbox questions are newest-first, cards move from Now to collapsed Earlier after twenty seconds, and all three high-volume regions scroll independently.
7. Add R2 and R3 assertions that sent replies enter the chat timeline with the exact original buyer quote and stable ordering.
8. Run `uv run pytest tests/integration/test_streaming_api.py tests/integration/test_demo_reset.py tests/e2e/test_marketplace_ui.py -q`; expect failures for missing reset/gating/timeline behavior.

### Task 2: Add the shared/exclusive demo mutation gate

**Files:**
- Create: `src/sidestage/marketplace/demo_reset.py`
- Modify: `src/sidestage/app.py`
- Test: `tests/integration/test_demo_reset.py`

**Steps:**

1. Implement a per-show async gate whose ordinary lease increments an active count and whose reset lease blocks new entrants, waits for the active count to reach zero, and releases all waiters on success or failure.
2. Wrap chat acceptance, seller decisions, R3 changes, marketplace actions, compensation, and debugger runtime switches in ordinary leases. Snapshot and SSE reads remain lock-free.
3. Recheck session authority and active listing inside the ordinary chat lease; raise typed `active_slot_empty` before ingestion or provider work.
4. Run the focused concurrency and empty-stage tests and confirm they pass without serializing ordinary requests.

### Task 3: Implement the transactional reset service

**Files:**
- Create: `src/sidestage/marketplace/demo_reset.py`
- Modify: `src/sidestage/copilot/runtime.py`
- Modify: `src/sidestage/streaming/ingest.py`
- Modify: `src/sidestage/app.py`
- Test: `tests/integration/test_demo_reset.py`

**Steps:**

1. Add `PreparedChatSource.reset(seller_id)` to discard only that seller's seeded RNG state.
2. Add `RuntimeSelector.reset(authority)` that installs the catalog default with a monotonic selection version and clears obsolete cold markers for that show.
3. In one SQLite transaction, delete show-scoped reply/idempotency/suggestion/question/trace/chat/stream/operation/epoch rows in foreign-key order; restore fixture listing/status/price and inventory values; empty the stage; disable R3; and advance authority versions.
4. Flush the buffered trace sink before the transaction, reset prepared/runtime in-memory state while holding the exclusive lease, append one `demo_reset` stream event, then notify SSE listeners.
5. Expose `POST /api/sessions/{session_token}/demo/reset` with no caller-supplied scope and return the authoritative snapshot.
6. Run `uv run pytest tests/integration/test_demo_reset.py tests/integration/test_streaming_api.py -q`; expect all reset and API-contract tests to pass.

### Task 4: Add Reset demo and empty-stage guidance to the UI

**Files:**
- Modify: `src/sidestage/web/static/index.html`
- Modify: `src/sidestage/web/static/app.js`
- Modify: `src/sidestage/web/static/styles.css`
- Modify: `tests/e2e/test_marketplace_ui.py`

**Steps:**

1. Add a header-level `Reset demo` button and reuse the existing modal shell for a reset-specific destructive confirmation.
2. Disable custom Send and prepared-chat controls whenever there is no active listing or a reset is pending; render the approved guidance copy.
3. Call the reset endpoint with the current session token, replace the local snapshot on success, reconnect SSE from the returned offset, and expose typed failure notices without clearing local state optimistically.
4. Ensure all other mutable controls are inert while reset is pending and restored on either success or failure.
5. Run the focused Playwright test and visually inspect desktop and narrow layouts.

### Task 5: Add the ordered quoted-reply timeline and time-partitioned Inbox

**Files:**
- Modify: `src/sidestage/copilot/broker.py`
- Modify: `src/sidestage/app.py`
- Modify: `src/sidestage/web/static/index.html`
- Modify: `src/sidestage/web/static/app.js`
- Modify: `src/sidestage/web/static/styles.css`
- Modify: `tests/e2e/test_r2_inbox.py`
- Modify: `tests/e2e/test_r3_controls.py`
- Modify: `tests/e2e/test_marketplace_ui.py`

**Steps:**

1. Project a stable `chat_timeline` from durable inbound chat and outbound reply records with application-owned ordering, actor kind, sent time, buyer identity, original buyer text, and reply text; expose no prompt/model internals.
2. Render buyer and seller timeline entries distinctly; seller entries quote the exact original buyer name/message and show the actual sent reply beneath it.
3. Preserve scroll position unless the chat reader is near the newest edge.
4. Sort Inbox questions by `asked_at` plus stable question identity descending. Partition at `now - 20 seconds` into full-card Now and collapsed-row Earlier panels.
5. Move questions between panels on a one-second timer, keep only explicit Earlier rows expanded, and preserve all existing reply/dismiss authority and form behavior.
6. Constrain chat, Now, and Earlier to independent viewport-height scroll regions on desktop, with a deliberate stacked responsive layout on narrow screens.
7. Run the focused R2, R3, and browser tests and visually inspect a populated desktop snapshot.

### Task 6: Update product, technical, milestone, and debugging evidence

**Files:**
- Modify: `docs/PRD.md`
- Modify: `docs/TDD.md`
- Modify: `docs/plans/2026-08-17-sidestage-v1-milestones.md`
- Modify: `docs/debug-process.md`

**Steps:**

1. Record Reset as developer-only synthetic-session tooling, not seller marketplace authority or a model tool.
2. Document the mutation gate, transactional reset order, monotonic-version rule, SSE behavior, and empty-stage server enforcement.
3. Add the UX/reset work to the current optimization/debug-session milestone.
4. Record the observed empty-stage incident with the actual session evidence: `active_listing_id=null`, zero epochs, fifteen `Needs You` cards, and the stage-3 `uncertain_listing_binding` exit with stages 4-8 skipped.
5. Record the approved newest-first Now/Earlier Inbox, independent scrolling, and quoted-reply timeline as seller-workspace behavior.
6. Keep evidence status `Implemented` until it is tied to an approved commit and command output.

### Task 7: Verify the complete change

**Files:**
- Test: full repository

**Steps:**

1. Run `git diff --check` and correct formatting errors.
2. Run the focused reset/API/UI tests.
3. Run `uv run pytest -q`; expect every default test to pass and live-model tests to remain deselected.
4. Restart the live server, manually Reset, Push a listing, submit an exact-size question, and verify the debugger reaches retrieval and the registered reply agent.
5. Review `git status --short`; preserve and exclude unrelated `AGENTS.md` and `docs/evidence/m2-closeout.md`.
6. Ask the builder for the exact commit message. Do not stage or commit before approval.
