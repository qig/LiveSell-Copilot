# Auto-message and Routing Corrections Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make exact absent-size questions deterministic, make Auto-message the default broker-approved execution mode, handle previous-listing notices without a model, bound text deduplication to five seconds, and remove R2/R3 wording from the seller UI.

**Architecture:** Keep entity and effect authority in application code. Extend the typed variant resolver and retrieval revalidation, broaden only the post-validation auto-send decision, add a deterministic previous-listing branch to the hardcoded pipeline, and keep the existing versioned capability/storage boundary. Preserve event-ID idempotency while replacing the lifetime canonical-text uniqueness index with a rolling lookup.

**Tech Stack:** Python 3.9/3.13, FastAPI, Pydantic, SQLite, pytest, Playwright, vanilla HTML/CSS/JavaScript.

---

### Task 1: Pin failing contracts

**Files:**
- Modify: `tests/unit/test_variant_resolution.py`
- Modify: `tests/integration/test_retrieval.py`
- Modify: `tests/integration/test_variant_workflows.py`
- Modify: `tests/integration/test_copilot_routing.py`
- Modify: `tests/integration/test_r3_safety.py`
- Modify: `tests/e2e/test_r3_controls.py`
- Modify: `tests/e2e/test_marketplace_ui.py`

Add regressions for exact decimal absence, inference/ambiguity, one-record projections in both workflows, five-second duplicate boundaries, deterministic previous-listing notices, default Auto-message, all broker-approved supported categories, unresolved Manual review cases, and absence of user-visible R2/R3 strings. Run focused tests and retain the expected failures before implementation.

### Task 2: Implement deterministic variant absence

**Files:**
- Modify: `src/sidestage/copilot/variants.py`
- Modify: `src/sidestage/copilot/retrieval.py`
- Modify: `src/sidestage/copilot/templates.py`
- Modify: `src/sidestage/copilot/broker.py`
- Modify: `src/sidestage/domain/replies.py`

Add an explicit exact-absence resolution backed by complete trusted catalog candidates. Project one negative availability record, render it deterministically, and revalidate it at final send. Keep ambiguous or untyped inputs failed closed.

### Task 3: Implement rolling deduplication and previous-listing notice

**Files:**
- Modify: `src/sidestage/storage/repositories.py`
- Modify: `src/sidestage/copilot/routing.py`
- Modify: `src/sidestage/copilot/pipeline.py`
- Modify: `src/sidestage/copilot/broker.py`

Replace lifetime canonical-text uniqueness with a non-unique timed lookup and a five-second transactional query. Add a no-model pipeline branch that builds a trusted current-listing notice and delegates its send/review outcome to the same versioned capability and result handler.

### Task 4: Make Auto-message the default and rename the UI

**Files:**
- Modify: `src/sidestage/storage/repositories.py`
- Modify: `src/sidestage/app.py`
- Modify: `src/sidestage/web/static/index.html`
- Modify: `src/sidestage/web/static/app.js`

Default new/reset sessions to enabled, preserve explicit seller toggles, and present mutually exclusive Auto-message/Manual review wording. Keep internal `r3` identifiers compatible.

### Task 5: Verify and document

**Files:**
- Modify: `docs/PRD.md`
- Modify: `docs/TDD.md`
- Modify: `docs/plans/2026-08-17-sidestage-v1-milestones.md`
- Modify: `docs/ai-proposal-rejection-history.md`
- Modify: `docs/debug-process.md`

Run focused unit/integration/E2E tests, the full non-live suite under the supported environments, and a manual local UI exercise. Record exact commands and evidence without marking results Verified until commit-bound evidence exists. Preserve unrelated dirty files, do not commit, and ask the builder for the exact commit message after the final diff is reviewed.
