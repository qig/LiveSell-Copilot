# M2 Debugger Design

> Status: Implemented in the working tree for builder review; runtime integration remains pending
>
> Scope boundary: presentation-quality trace projection over synthetic fixtures, with the existing M2 marketplace ledger preserved

## Purpose

The debugger must answer one question before exposing detail: **where did this customer message stop, and why?** The current M2 developer ledger is useful for raw chat, listing epochs, and seller-operation receipts, but it does not make the reply path inspectable. M2 Debugger adds a reply-centered trace surface without claiming that M3B runtime tracing already exists.

The seller workspace remains a quiet live control desk. The developer route becomes its contrasting flight recorder: a pale, information-dense surface with one selected event, one seven-stage path, a prominent terminal or blocking explanation, exact stage inputs and outputs, and the product destinations that did or did not receive data.

## Approaches considered

1. **Replace the marketplace ledger.** This would simplify the page, but remove M2.1 evidence and break the separation between reply traces and seller-action audit records.
2. **Create a second developer route.** This avoids all overlap, but creates two competing places to debug one show.
3. **Extend the existing route — selected.** The reply trace becomes the primary diagnostic surface. The existing raw-event, epoch, and receipt ledger stays intact below it as supporting state.

## Information architecture

The trace surface contains:

1. Fixture and event controls for one focused event or a mixed bulk.
2. A seven-stage rail matching the TDD: Ingest; Normalize and deduplicate; Route eligibility; Evidence snapshot; Terminal intent or abstention; Broker authorization and guardrails; Terminal outcome.
3. A diagnosis banner naming the first blocked, failed, or typed early-exit stage. Later stages remain visibly skipped rather than appearing successful.
4. A stage inspector with a human summary, duration, reason code, and exact sanitized input/output JSON.
5. Product destinations for Chat Response, Copilot Inbox, and Reply Receipt.
6. The existing marketplace ledger for raw chat, listing epochs, and operation receipts.

Every fixture is labeled as a presentation projection. It cannot become `Verified` evidence and never substitutes for the M3B trace store, broker, receipts, or evaluation.

### Truthful current-build states

The reply rail distinguishes implementation from simulation. Real catalog-import stages may render green because the backend loader executed them. Reply-fixture preparation renders blue with the explicit state `simulated`; it never uses the green `passed` state. Any evidence-ready message stops at stage 5 with `AGENT_NOT_CONNECTED`, and Guardrails and Result remain gray and skipped. Missing evidence and noise may stop earlier. No fixture emits Chat, Inbox, or Receipt data.

Stage 5 represents the SideStage livesell reply-agent boundary, not the existence of generic M3A core files. Until the M3B adapter, livesell profile, and dispatch path are connected, the debugger must not claim an agent call, terminal intent, broker verdict, or product outcome.

## Data contract and future adapter

`fixtures/debugger/reply_trace_scenarios.json` is a serialized view-model contract, not a runtime domain model. It contains scenario metadata, event identity, the seven ordered stage projections, terminal destinations, reason codes, and sanitized synthetic payloads. The frontend reads this file directly and never imports M2.1 or M3A implementation modules.

M3B will later map real SideStage trace records into the same view shape. Stage 5 may then nest the correlated public M3A run, but the debugger must not import, infer, or duplicate M3A internals. Replacing fixture loading with HTTP/SSE is the only planned integration seam.

The M2.1 import trace uses a separate runtime contract because it observes a different boundary. `trace_seller_fixture_import()` invokes the real typed loader with a fail-open observer, and the local review server exposes the sanitized result at one same-origin endpoint. Its four import stages, ephemeral badge, source digest, counts, and first-stop diagnosis are rendered above the reply controls. A backend import success never changes the reply fixture's presentation-only label.

## Error handling and accessibility

A fixture-load failure leaves the marketplace ledger usable and shows a retryable trace error. Missing or malformed stage data fails visibly instead of fabricating completion. Native labels, buttons, selects, details, focus states, and live status text make the diagnostic path keyboard-usable. Color is redundant with state labels and icons. Narrow layouts stack the stage inspector and wrap the seven-stage rail into a compact 4+3 grid so the complete path remains visible without page overflow.

## Verification

Unit validation asserts the fixture schema, exact seven-stage order, simulated/blocked/skipped states, unique identities, mandatory first-stop consistency, zero destination emissions, and sanitized labeling. Browser verification exercises Agent-unavailable, evidence-blocked, early-exit, adversarial, and bulk selection flows; inspects stage payloads and destinations; captures desktop and narrow screenshots; and asserts that the existing marketplace-ledger selectors still work. The complete M2.1 unit and browser gates must pass again after the debugger is changed.
