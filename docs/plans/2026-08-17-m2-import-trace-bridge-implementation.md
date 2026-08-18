# M2.1 Import Trace Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Route a real M2.1 typed seller-fixture import through a sanitized runtime trace endpoint and render that trace inside the existing M2.debugger.

**Architecture:** The existing M2.1 loader gains a no-authority observer hook. A separate import-trace recorder builds an ephemeral JSON-safe view contract, and a dependency-free local review server serves both the existing static UI and one diagnostic endpoint. The debugger adds a compact runtime-import panel while preserving its synthetic reply tracer and browser-local marketplace ledger.

**Tech Stack:** Python standard library, existing Pydantic M2.1 models, static HTML/CSS/JavaScript, Pytest, and headless Chromium through Playwright.

---

### Task 1: Lock the import-trace contract

**Files:**
- Create: `tests/unit/test_import_trace.py`
- Create: `src/sidestage/fixtures/import_trace.py`
- Modify: `src/sidestage/fixtures/loader.py`

**Steps:**
1. Write failing tests for accepted, contract-rejected, and unavailable-source traces.
2. Require the exact four-stage order, passed/failed/skipped consistency, accepted M2.1 counts, sanitized errors, a source digest, and no absolute paths or source values.
3. Add an optional stage observer to the real loader without changing existing return or exception behavior.
4. Implement the recorder around `load_seller_fixture()` and rerun focused M2.1 plus trace tests.

### Task 2: Expose the runtime trace

**Files:**
- Create: `src/sidestage/web/__init__.py`
- Create: `src/sidestage/web/server.py`
- Create: `tests/integration/test_m2_debugger_server.py`

**Steps:**
1. Write a failing HTTP integration test for `GET /api/debug/import-trace`.
2. Implement a repository-root static review server with the single no-store JSON endpoint.
3. Assert the endpoint reports `runtime_source=m2_1_typed_loader` and that existing static fixture URLs still work.

### Task 3: Render the M2.1 import trace

**Files:**
- Modify: `src/sidestage/web/static/debug.html`
- Modify: `src/sidestage/web/static/debugger.js`
- Modify: `src/sidestage/web/static/trace.css`
- Modify: `tests/e2e/verify_m2_debugger.py`

**Steps:**
1. Add failing browser assertions for runtime labeling, four stages, accepted counts, rerun, and sanitized payload inspection.
2. Add the compact import panel and explicit unchecked/loading/runtime/offline/rejected states.
3. Fetch the endpoint only on developer action; leave the reply fixture and marketplace ledger independent.
4. Preserve keyboard access, state text independent of color, and no horizontal overflow at 430 pixels.

### Task 4: Update technical run guidance and verify compatibility

**Files:**
- Modify: `README.md`
- Modify: `docs/TDD.md`
- Modify: `docs/plans/2026-08-17-m2-debugger-design.md`

**Steps:**
1. Document the review-server command, endpoint boundary, ephemeral durability, and static-preview fallback.
2. Run syntax, focused unit/integration, debugger browser, exact M2.1 unit/browser, and complete non-live suites.
3. Inspect desktop and narrow screenshots and audit the diff for M3A isolation.
4. Stop for builder review; do not stage or commit until the builder supplies and approves the exact commit message.
