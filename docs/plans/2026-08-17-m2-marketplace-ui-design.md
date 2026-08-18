# M2 Marketplace UI Design

> Status: Reference-aligned implementation complete and browser-tested; committed-tree verification pending
>
> Scope authority: accepted PRD and TDD; the stale purchase-oriented M2.3 text in the milestone plan is not used

## Purpose

M2 needs a credible non-AI live-selling workspace before the reply copilot exists. The interface must let a seller keep the current pair, raw chat, and explicit marketplace controls in view without turning the prototype into an analytics dashboard.

The accepted runtime begins with an empty active-listing slot. Buyer-side commerce is out of scope. Every marketplace mutation comes from an authenticated seller control and is one of exactly five operation types: Push, Swap, Unlist, Price Markdown, or Inventory Change.

## Approaches considered

### 1. Conventional operations dashboard

A three-column layout for chat, active listing, and operations would expose the most data at once. It was rejected because it reproduces the three-primary-panel direction superseded in APR-016 and makes the demo feel like inventory software rather than live show control.

### 2. Consumer live-shopping replica

A video-first storefront with floating chat and product overlays would look familiar, but video and customer commerce are outside scope. It would also make the seller operations harder to inspect during a technical review.

### 3. Reference-aligned minimal control desk — selected

The selected direction uses the visual language of the builder-provided Mini SideStage reference at `http://127.0.0.1:8765/`. The left surface is the chronological live room; the right surface is the show desk. The active listing behaves like the current cue, catalog choices form the next-cue rail, and destructive or state-changing operations remain explicit typed controls.

The visual system is intentionally quiet: a warm off-white canvas, white square panels, black system typography, blue primary actions, green live/ready state, monospaced uppercase metadata, one-pixel neutral borders, and modest shadows. Product context is expressed through text and structured facts rather than decorative illustration. The memorable behavior is the listing change itself: Push or Swap advances a visible epoch marker while chat remains anchored to the listing that was live when the message arrived.

## Information architecture

The compact shared header contains the SideStage identity, selected synthetic seller, show identifier, stream state, active SKU, and an explicit “Copilot off · M2” badge. It does not show invented conversion, revenue, viewer, or latency metrics.

The workspace has two primary surfaces:

1. **Live room.** A chronological stream of prepared and custom chat. Controls allow deterministic playback, pause/resume, and a bounded burst. A custom-message composer uses the same visible ingestion path as prepared messages.
2. **Show desk.** The empty or active listing slot, current price, variant stock, one applicable policy line, next-listing rail, and exactly five seller operation entry points. Push is available only when the slot is empty; Swap, Unlist, Price Markdown, and Inventory Change require an active listing.

The latest still-valid seller operation exposes one Undo action. Full receipts, state snapshots, and epoch history live on a separate developer route, not in the seller workspace.

## Interaction contracts

- **Push:** choose an available in-stock listing while the slot is empty; open a new epoch.
- **Swap:** choose a different available in-stock listing while one is active; close the current epoch and open another.
- **Unlist:** explicitly clear the active slot and close its epoch.
- **Price Markdown:** enter a lower price at or above the configured floor.
- **Inventory Change:** choose an active variant and set a nonnegative absolute quantity. Quantity zero does not unlist the listing.
- **Undo:** compensate only the most recent operation when no newer mutation has invalidated its resulting version.

Typed dialogs carry operation parameters and surface concise applied or refused outcomes. Inline UI copy explains preconditions before submission. Rejections leave state unchanged.

## Runtime boundary for this UI slice

The repository does not yet contain the M2 FastAPI, SQLite, authority, or SSE runtime described by the TDD. To make the requested UI executable now, the frontend uses a deterministic in-browser demo adapter over the approved fixture files. It persists a seller-scoped show snapshot, ordered chat events, listing epochs, and operation receipts in `localStorage` and synchronizes the developer view through browser storage events.

That adapter is presentation and interaction evidence only. It is not represented as the authoritative M2 marketplace kernel, authenticated authority, durable audit ordering, idempotency proof, concurrency proof, or SSE implementation. The rendering layer keeps runtime reads and commands behind a small boundary so the later FastAPI adapter can replace the demo adapter without redesigning the views.

## Error and empty states

- Fixture-load failure shows a retryable full-surface error.
- The initial empty slot teaches Push rather than inventing an active product.
- Invalid operation parameters keep their dialog open and explain the exact constraint.
- Refused operations produce a concise amber notice and a developer receipt without mutating listing state.
- Empty chat uses a quiet invitation to start prepared playback or enter a custom message.
- Narrow layouts stack the two surfaces while keeping the composer and operation dock reachable.

## Accessibility and motion

All controls use native buttons, labels, inputs, and dialogs. State is not communicated by color alone. Focus rings are high contrast, operation dialogs return focus to their trigger, and notices use an `aria-live` region. Motion is limited to a staged page entrance, stream-item insertion, and the active-cue transition; `prefers-reduced-motion` disables them.

## Verification

Browser checks cover the accepted seller path:

1. Load all three sellers from fixtures and confirm the show starts empty.
2. Push a listing and verify the active cue, epoch, and enabled operations.
3. Add a custom chat message and confirm chronological placement.
4. Swap, markdown, change inventory to zero without unlisting, and Undo the latest change.
5. Unlist and Undo it.
6. Open the separate developer view and inspect correlated raw events, epochs, and receipts.
7. Check the laptop and narrow responsive layouts and assert no console errors.

The complete flow passed locally on 2026-08-17 using a temporary server on port `8877` so the builder's reference on port `8765` remained untouched. With Python Playwright and its browser runtime installed, the repository-level command is:

```text
SIDESTAGE_BASE_URL=http://127.0.0.1:8877 python3 tests/e2e/verify_m2_ui.py
```

Evidence artifacts: `/tmp/sidestage-m2-ui/seller-workspace-desktop.png`, `/tmp/sidestage-m2-ui/seller-workspace-mobile.png`, and `/tmp/sidestage-m2-ui/developer-ledger-desktop.png`. This browser run is not assigned the repository evidence-maturity state `Verified`; that state requires a rerun against the committed tree.
