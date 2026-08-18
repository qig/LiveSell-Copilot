# M2 Debugger Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the existing M2 developer route with a presentation-quality reply tracer that identifies the first stopped stage while preserving every M2.1 marketplace-ledger behavior.

**Architecture:** A standalone JSON view-model fixture supplies scripted reply traces to the existing static developer route. Vanilla JavaScript projects one event through the approved seven-stage rail, stage inspector, and terminal destinations; the existing localStorage marketplace ledger remains a separate supporting section. No M2.1 Python module or M3A implementation module is imported or modified.

**Tech Stack:** Static HTML, isolated CSS, vanilla JavaScript, JSON fixtures, Pytest contract checks, and headless Chromium through Python Playwright.

---

### Task 1: Lock the debugger fixture contract

**Files:**
- Create: `tests/unit/test_debugger_fixtures.py`
- Create: `fixtures/debugger/reply_trace_scenarios.json`

**Steps:**
1. Write contract tests for synthetic labeling, unique scenario/event/trace IDs, the exact ordered seven-stage keys, allowed stage states, typed first-stop consistency, sanitized payloads, and three terminal destinations.
2. Run `uv run pytest tests/unit/test_debugger_fixtures.py -q` and confirm the missing fixture fails RED.
3. Add focused single-event scenarios plus one mixed bulk using real M1 seller/listing identifiers and wholly synthetic trace payloads.
4. Rerun the focused test and require GREEN.

### Task 2: Write the failing browser contract

**Files:**
- Create: `tests/e2e/verify_m2_debugger.py`

**Steps:**
1. Assert the debugger loads without marketplace state, exposes seven stages, labels fixtures as non-runtime evidence, and selects an event.
2. Assert every evidence-ready trace stops at the unconnected Agent stage, a missing-evidence trace stops earlier at Evidence Snapshot, and an injection example does not claim that downstream guardrails ran.
3. Assert bulk event selection changes the diagnosis, stage inspector, and terminal destinations.
4. Assert the raw-event, epoch, and receipt ledger selectors remain present.
5. Run through `with_server.py` and confirm RED against the current developer ledger.

### Task 3: Build the reply trace interface

**Files:**
- Modify: `src/sidestage/web/static/debug.html`
- Modify: `src/sidestage/web/static/debugger.js`
- Create: `src/sidestage/web/static/trace.css`

**Steps:**
1. Add the trace controls, event readout, seven-stage rail, diagnosis banner, stage inspector, destinations, and presentation-fixture disclosure above the existing ledger.
2. Load and validate the fixture view model without hiding the existing ledger when marketplace state is absent.
3. Render stage state and diagnosis from fixture data; never infer a successful stage from missing data.
4. Add keyboard-operable stage selection, bulk event selection, fixture reset, JSON disclosure panels, and concise loading/error states.
5. Apply an editorial flight-recorder visual system that complements the committed M2.0 seller workspace and remains usable at narrow widths.

### Task 4: Verify debugger and M2.1 regression safety

**Files:**
- Test: `tests/unit/test_debugger_fixtures.py`
- Test: `tests/e2e/verify_m2_debugger.py`
- Regression: `tests/unit/test_domain_contracts.py`
- Regression: `tests/unit/test_seller_import.py`
- Regression: `tests/e2e/verify_m2_ui.py`

**Steps:**
1. Run `node --check src/sidestage/web/static/debugger.js` and `git diff --check`.
2. Run the focused fixture and debugger browser gates and capture desktop/narrow screenshots under `/tmp/sidestage-m2-debugger`.
3. Run `uv run pytest tests/unit/test_domain_contracts.py tests/unit/test_seller_import.py -q`.
4. Run the complete M2.1 browser flow through the managed temporary server.
5. Inspect the final diff and confirm no M2.1 Python or M3A files changed.
6. Stop for builder review. Do not stage or commit until the builder supplies and approves the exact commit message.
