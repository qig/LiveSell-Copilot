# M2 Debugger Truthful-State Correction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the debugger clearly separate implemented catalog-import evidence from simulated reply-flow preparation, and stop every eligible reply example at the unconnected Agent boundary.

**Architecture:** The real catalog import remains a four-stage backend check. Reply fixtures retain the seven-stage future shape, but pre-agent fixture steps use a distinct `simulated` state, eligible messages stop at stage 5 with `AGENT_NOT_CONNECTED`, and later steps remain skipped. Visible copy uses product language; milestone and architecture names remain in technical documents and payloads only.

**Tech Stack:** JSON fixture contracts, static HTML/CSS/JavaScript, Pytest, and Playwright.

---

### Task 1: Lock truthful fixture behavior

**Files:**
- Modify: `tests/unit/test_debugger_fixtures.py`
- Modify: `tests/e2e/verify_m2_debugger.py`

**Steps:**
1. Add `simulated` as the only allowed pre-agent completion state.
2. Require every evidence-ready event to stop at stage 5 with `AGENT_NOT_CONNECTED` and emit no destination data.
3. Require the UI to show no internal milestone names, no green reply stages, and skipped guardrail/outcome stages.
4. Run focused tests and capture the intended RED failures.

### Task 2: Correct reply fixture outcomes

**Files:**
- Modify: `fixtures/debugger/reply_trace_scenarios.json`

**Steps:**
1. Rename the successful scenario to an agent-unavailable scenario.
2. Change pre-agent `passed` states to `simulated`.
3. Stop eligible availability and adversarial examples at stage 5 with `AGENT_NOT_CONNECTED`.
4. Mark stages 6 and 7 skipped and every destination `NOT_EMITTED`.
5. Keep evidence rejection at stage 4 and noise exit at stage 3.

### Task 3: Simplify visible language and state styling

**Files:**
- Modify: `src/sidestage/web/static/debug.html`
- Modify: `src/sidestage/web/static/debugger.js`
- Modify: `src/sidestage/web/static/trace.css`

**Steps:**
1. Replace visible milestone, evidence-maturity, and transport jargon with catalog-check and message-trace language.
2. Render simulated stages in blue, the first unavailable stage in red, and later stages in gray.
3. Preserve expandable technical JSON for developers without putting internal names in the main reading path.
4. Keep the catalog import, reply trace, and marketplace activity visually distinct.

### Task 4: Verify current and future boundaries

**Files:**
- Modify: `docs/plans/2026-08-17-m2-debugger-design.md`
- Test: focused debugger fixture/browser tests plus M2.1 and full-suite regressions.

**Steps:**
1. Document that stage 5 represents the unconnected livesell reply-agent boundary even if generic agent-core work exists separately.
2. Run the runtime-server and static-fallback browser flows at unused test ports.
3. Inspect desktop and narrow captures for terminology, hierarchy, and overflow.
4. Run exact M2.1 and complete non-live suites; do not stage or commit without the builder's exact approved message.
