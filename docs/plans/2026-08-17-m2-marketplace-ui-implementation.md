# M2 Marketplace UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an executable, responsive M2 marketplace show desk for raw chat and the five explicit seller operations, with a separate developer ledger and no Copilot behavior.

**Architecture:** Static HTML/CSS/JavaScript renders two seller surfaces over a deterministic in-browser demo runtime because the FastAPI/SQLite M2 kernel does not yet exist. The demo runtime owns fixture import, seller-scoped show state, chronological chat, operation preconditions, versioned epochs, latest-operation compensation, and receipt projection behind a boundary that a later HTTP/SSE adapter can replace.

**Tech Stack:** Semantic HTML, modern CSS, vanilla JavaScript modules, approved JSON fixtures, browser `localStorage`, Python static HTTP server, and Python Playwright verification.

---

### Task 1: Add the seller workspace shell and visual system

**Files:**

- Create: `src/sidestage/web/static/index.html`
- Create: `src/sidestage/web/static/styles.css`

**Steps:**

1. Create the compact shared header with seller selector, show identity, live state, active SKU, and `Copilot off · M2` status.
2. Create exactly two primary landmarks: Live room and Show desk.
3. Add semantic empty, loading, dialog, notice, and narrow-screen states.
4. Add the reference-aligned minimal design tokens, system typography, responsive grid, focus treatment, reduced-motion support, and no invented business metrics.
5. Run `git diff --check` and open the static HTML through a local server.

**Review/commit gate:** Stop after verification. Do not stage or commit until the builder reviews the diff and supplies the exact approved commit message.

### Task 2: Implement fixture import and deterministic show state

**Files:**

- Create: `src/sidestage/web/static/app.js`

**Steps:**

1. Fetch `/fixtures/sellers.json` and `/fixtures/chat_messages.json`.
2. Normalize products without changing fixture prices, floors, status, variants, tone, or policies.
3. Initialize a seller-scoped show with an empty active slot, monotonic show/listing/inventory versions, empty epochs, and a small prepared-chat queue.
4. Persist only synthetic demo state under a versioned local key.
5. Render loading and retryable fixture errors without partially enabling actions.

### Task 3: Implement the five seller operations and compensation

**Files:**

- Modify: `src/sidestage/web/static/app.js`
- Modify: `src/sidestage/web/static/index.html`
- Modify: `src/sidestage/web/static/styles.css`

**Steps:**

1. Implement Push-from-empty and Swap-from-active with different preconditions and append-only epoch changes.
2. Implement explicit Unlist, strict Price Markdown at or above floor, and absolute nonnegative Inventory Change.
3. Prove Inventory Change to zero leaves the active listing unchanged.
4. Record applied and rejected demo receipts with before/after projections.
5. Expose Undo only for the latest applied operation and implement version-valid compensating state without erasing history.
6. Render concise success/refusal notices; keep the receipt ledger out of the seller surface.

### Task 4: Implement prepared and custom chat controls

**Files:**

- Modify: `src/sidestage/web/static/app.js`
- Modify: `src/sidestage/web/static/index.html`
- Modify: `src/sidestage/web/static/styles.css`

**Steps:**

1. Project prepared fixture input to customer display name and raw text only.
2. Add deterministic play, pause/resume, one-message advance, and bounded burst controls.
3. Route tester-entered text through the same append function with trusted synthetic origin supplied by the UI adapter.
4. Stamp messages with ordered sequence, display time, and the epoch visible at acceptance.
5. Keep chat chronological and auto-scroll only when the seller is already near the bottom.

### Task 5: Add the separate developer ledger

**Files:**

- Create: `src/sidestage/web/static/debug.html`
- Create: `src/sidestage/web/static/debugger.js`
- Modify: `src/sidestage/web/static/styles.css`

**Steps:**

1. Reuse the shared visual system while clearly identifying the developer route.
2. Render raw events, listing-epoch history, and operation receipts as separate inspectable sections.
3. Show operation status, before/after version projections, compensation links, and timestamps.
4. Read the same synthetic local snapshot without placing ledger detail in the seller workspace.

### Task 6: Verify behavior and visuals

**Files:**

- Create: `tests/e2e/verify_m2_ui.py`

**Steps:**

1. Run the bundled server helper `--help`, then launch the repository with `python3 -m http.server 8000`.
2. Use headless Chromium and wait for `networkidle` before inspecting the dynamic DOM.
3. Assert all three sellers load and the initial slot is empty.
4. Exercise Push, custom chat, Swap, Markdown, Inventory Change to zero, Undo, Unlist, Undo, and developer-ledger navigation.
5. Capture laptop and narrow screenshots in `/tmp` and assert no page or console errors.
6. Run `git diff --check` and inspect `git status --short`.

**Review/commit gate:** Present files, commands, screenshots, known limitations, and exact results. Do not stage or commit until the builder reviews the implementation and supplies the exact approved commit message.
