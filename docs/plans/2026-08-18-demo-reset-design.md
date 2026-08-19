# Demo Reset and Empty-Stage Guard Design

**Status:** Accepted on 2026-08-18

## Problem

The local seller workspace accepts prepared and custom buyer chat while the show has no active listing epoch. The backend correctly fails closed at deterministic routing with `uncertain_listing_binding`, but the UI presents a stream of generic `Needs You` cards. This makes a safe temporal-binding rule look like a broken Copilot workflow during manual testing.

The workspace also lacks a way to restore one synthetic seller/show after marketplace mutations, chat, replies, traces, R3 changes, or debugger runtime switches.

## Accepted behavior

The seller workspace disables prepared and custom buyer-chat submission while the active listing slot is empty. It explains that the operator must Push a listing before sending buyer questions. Server-side enforcement independently rejects chat acceptance without an active listing so a stale or direct client cannot bypass the UI.

A developer-only **Reset demo** control restores the authenticated synthetic seller/show to its fixture-visible baseline:

- empty active stage and no listing epochs;
- fixture listing price, availability status, and variant quantities;
- no chat, Copilot questions, suggestions, replies, receipts, traces, or marketplace-operation history;
- R3 disabled;
- startup-default workflow/model selection and a fresh prepared-chat sequence;
- no old latency samples in the debugger.

Reset derives seller/show authority only from the opaque demo session. It accepts no tenant, seller, show, model, prompt, or tool identifiers. It is developer tooling, not a marketplace action, model tool, customer workflow, or production seller authority.

## Concurrency and ordering

A per-show mutation gate gives ordinary mutable requests shared leases and Reset an exclusive lease. Reset waits for already admitted requests to finish or reach their existing hard timeout, prevents new mutations from entering during the reset, flushes buffered trace writes, and then changes persistent state in one SQLite transaction. This prevents a late model result or marketplace action from repopulating the reset state.

User-visible fixture values return to baseline, while internal listing, inventory, show, R3, and runtime selection versions remain monotonic across the reset boundary. The reset appends one authoritative SSE event after clearing prior stream rows so every open projection refreshes. The current demo session remains valid.

## UI

The seller header exposes a low-emphasis destructive **Reset demo** button. A confirmation dialog lists the cleared state and requires an explicit second action. During reset, mutable controls are disabled. On success the returned snapshot replaces local state and the normal SSE projection converges other open tabs.

When no listing is active, both chat entry paths are disabled and display: **Push a listing before sending buyer questions.** After Push succeeds, both controls become available. Questions accepted before a reset are erased rather than replayed.

The Copilot Inbox is ordered newest-first and split into two independently scrolling panels. **Now** contains full question cards accepted no more than twenty seconds ago. **Earlier** contains questions older than twenty seconds as compact collapsed rows, also newest-first; selecting a row expands its reply and dismiss controls in place. A one-second browser timer moves cards across the boundary without a server write. Question state remains server-authoritative, and age changes never alter routing, reply authority, or persistence.

The live chat feed has its own viewport-height scroll container, so the browser page does not grow with chat or Inbox volume. The Now and Earlier panels scroll independently. New activity auto-scrolls a region only when the operator is already near its newest edge, preserving position while older content is being read.

Every sent seller reply—unchanged AI acceptance, seller edit/manual reply, or R3 auto-reply—appears in the live chat timeline at its durable send time. Seller entries are visually distinct and quote the original buyer name and exact buyer message before the sent reply text. Dismissed questions create no timeline entry. The backend supplies a stable, application-owned timeline projection so equal wall-clock timestamps cannot reorder buyer messages and seller replies in the browser.

## Verification

Tests cover authoritative empty-stage rejection, UI disabled state, tenant/show isolation, fixture restoration, monotonic versions, runtime/R3/prepared-source reset, buffered trace flushing, exclusive reset against in-flight work, SSE refresh, newest-first Inbox ordering, the twenty-second Now/Earlier transition, independent scrolling, quoted R2/R3 timeline replies, and an end-to-end browser flow: mutate state, reset, Push a listing, submit a new question, and observe the registered agent workflow.
