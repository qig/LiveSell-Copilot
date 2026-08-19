# SideStage Product Requirements Document

> Status: `Accepted` — the local P0 product surface is `Verified` at code head `3fda622`; the current-tree live-model latency qualification remains open and is not `Measured`
>
> Last updated: 2026-08-18
>
> Primary depth: Agentic outbound-reply write safety under live state changes

## 1. Product summary

SideStage is a real-time copilot for sneaker live sellers. It keeps buyer chat, grounded reply assistance, the active listing, inventory, and essential show operations in one workspace.

The product helps a seller answer high-intent questions without guessing. It may prepare a reply for review or send a narrowly bounded automatic message, but only when the answer is grounded in current catalog, listing, inventory, policy, or packaged product-research data. Buyer chat never authorizes a marketplace operation.

The P0 prototype is a synthetic technical demonstration built around a Whatnot-like emulator. It demonstrates product behavior and safety under live pressure; it does not prove GMV lift, conversion improvement, or reduced seller workload.

## 2. Target sellers

P0 uses exactly three isolated synthetic sneaker-reseller personas:

1. **VelocityKicks:** High-volume new sneakers with many size variants. Exercises burst traffic, SKU matching, stock freshness, and latency.
2. **VaultConsign:** Rare used and consignment sneakers. Exercises condition, authenticity, policy, and price-floor questions.
3. **RotationKicks:** Fast-moving, mostly single-unit inventory. Exercises frequent listing changes and stale-question handling.

These personas provide different product and policy conditions for technical validation. They are not real pilot participants.

## 3. First seller workflow

The first workflow is **high-intent buyer question to grounded answer**:

1. A prepared or tester-entered buyer message appears in Live Chat with its customer identity and ask time.
2. SideStage associates the message with the seller, show, and listing that was displayed when the message was sent.
3. Obvious reactions, greetings, and repeated questions remain visible in Live Chat but do not distract the seller with unnecessary Inbox cards.
4. An answerable question enters the Copilot workflow. SideStage gathers only relevant, seller-scoped catalog, listing, inventory, policy, and packaged research facts.
5. The copilot either prepares a grounded answer or marks the question **Needs seller** with a concise reason. It does not guess when evidence is missing, conflicting, stale, or ambiguous.
6. In **Manual review**, the seller accepts, edits, or dismisses the suggestion. In **Auto-message**, SideStage may send only an eligible, freshly revalidated, application-bounded response.
7. Every sent reply remains attached to the originating buyer message. Every question shows when it was asked and its current lifecycle state.
8. Seller marketplace operations remain separate, explicit controls; neither buyer chat nor the reply model may initiate them.

## 4. Product experience

### 4.1 Seller workspace

The seller workspace is a minimal two-surface technical demo:

- **Live Chat:** A chronological stream of every prepared and custom buyer message plus durable seller replies.
- **Copilot Inbox and Show Desk:** Open reply decisions beside only the relevant SKU, current price, referenced variant and stock, and applicable policy. The same area shows the active listing, catalog rail, five seller operations, and the latest valid Undo.

The header shows seller, show, active listing, active reply mode, and the current workflow/model as a read-only badge. When Auto-message is enabled, a persistent warning and immediate switch to Manual review remain visible.

The seller can run prepared chat, enter a custom test message, and reset the synthetic demo. Buyer chat is unavailable while no listing is active because there is no trusted item context.

### 4.2 Question lifecycle

Each eligible question displays its ask time, latest state-change time, and one clear state:

```text
Queued -> AI working
              |-> Awaiting review -> Answered by seller
              |-> Auto-answered
              |-> Needs seller -> Answered by seller / Unanswered
```

Grouped duplicates link to their canonical question. Answered and dismissed questions leave the open Inbox. A dismissed question creates no seller chat message.

### 4.3 Seller operations

P0 supports exactly five seller operation types:

1. **Push:** Put a listing on an empty stage.
2. **Swap:** Replace the active listing with another available SKU.
3. **Unlist:** Remove the active listing from sale and leave the stage empty.
4. **Price Markdown:** Lower the active listing price without crossing the seller's floor.
5. **Inventory Change:** Set a nonnegative quantity for an active listing variant.

The seller may Undo the latest operation only when doing so would not overwrite newer state. Reaching zero inventory does not automatically Unlist a product.

### 4.4 Developer debugger

A separate developer view explains what happened without cluttering the seller workspace. It shows actual routing outcome, grounded evidence, guardrail and freshness verdicts, reply/action receipts, backend stages, and end-to-end latency. It also lets the tester select only an approved workflow/model combination for the active synthetic show.

The debugger is a technical validation surface, not a seller analytics product.

## 5. Copilot-to-automation ladder

The ladder applies only to replies, never to marketplace operations:

- **R0 — Shadow:** Generate and trace a candidate without showing or sending it. Planned for a future real-seller pilot.
- **R1 — Suggest:** Show a candidate that the seller may accept, edit, or dismiss.
- **R2 — Seller-approved send:** Send only after seller approval. The P0 UI combines R1 and R2 as **Manual review**.
- **R3 — Bounded auto-reply:** Send an eligible reply only after independent grounding, scope, freshness, duplicate, tone, and authorization checks. The P0 UI calls this **Auto-message**.
- **R4 — Open-ended auto-reply:** Out of scope.

P0 exposes Manual review and bounded Auto-message. Auto-message is enabled for a new or reset demo show, displays a persistent warning, and can be turned off immediately. Disabling it prevents new automatic sends; already sent replies remain in history.

## 6. Product safety behavior

- **Grounding:** Every AI-authored factual claim must be supported by current seller-scoped data. Missing or conflicting evidence becomes **Needs seller**.
- **Freshness:** SideStage rechecks the listing, price, stock, policy, and Auto-message authorization needed by a reply immediately before exposure or send.
- **Temporal attribution:** A question stays attached to the listing displayed when it was asked unless an explicit, unambiguous product reference identifies another listing. SideStage never silently retargets it after a Push, Swap, or Unlist.
- **Previous listings:** A question already known to concern a previous listing is tagged with the previous SKU and bypasses AI generation. SideStage may show or send only an application-owned notice that the item is no longer on stage; it does not answer the old product question from current-listing facts.
- **In-flight listing changes:** If a generated answer becomes stale because the listing changed during processing, it is suppressed and moved to **Needs seller**.
- **Seller edits:** If the seller edits a suggestion, SideStage sends the seller's exact text. Factual, policy, or tone conflicts appear only as non-blocking warnings and never rewrite it.
- **Duplicate safety:** Replayed events and grouped repeat questions cannot create duplicate replies or writes.
- **Authority:** Buyer text and model output cannot recommend, authorize, or execute Push, Swap, Unlist, Price Markdown, Inventory Change, or Undo.
- **Prompt injection:** Buyer attempts to override instructions, request another seller's data, or gain write authority cannot change trusted scope or capabilities.
- **Fail closed:** Unsafe partial drafts are never exposed. A safe explanation or **Needs seller** state is preferred to a guess.

## 7. Product research

Product research is triggered only by a buyer question that needs product knowledge. The seller does not open a separate research workflow.

P0 uses a packaged, source-backed sneaker corpus covering release date, SKU and colorway, MSRP, materials, sizing guidance, authenticity, and condition. Each fact includes provenance and freshness metadata. Missing, stale, conflicting, or unsupported research becomes **Needs seller**. Live open-web research is out of scope.

## 8. P0 scope and delivery status

P0 includes:

- Three differentiated seller personas with isolated catalogs, policies, listings, variants, and inventory.
- Prepared randomized chat, custom test messages, deterministic replay, and adversarial cases.
- The two-surface seller workspace and separate developer debugger.
- The five seller operations, internal receipts, safe refusals, and conditional Undo.
- Grounded Manual review and bounded Auto-message reply paths.
- Product research from the packaged corpus.
- Backend evaluation, failure injection, latency accounting, and protected reviewer access.

| P0 product promise | Status |
| --- | --- |
| Synthetic sellers, chat, marketplace emulator, workspace, five operations, receipts, Undo, and temporal listing behavior | `Verified` deterministically at `3fda622` |
| Grounded Copilot Inbox, Manual review, Auto-message, seller edits, research, safety races, and debugger | `Verified` deterministically at `3fda622` |
| Protected local reviewer boundary | `Verified` at `3fda622` |
| Vercel reviewer routing correction | `Implemented` in the working tree; not yet commit-bound `Verified` |
| Restart-safe reviewer session on one persistent SQLite instance, plus portable Docker/Render deployment | `Implemented` and container-restart tested in the working tree; not yet commit-bound `Verified` |
| Current committed live configuration with at least 95% semantic correctness, zero hard-safety violations, and answerable-question p95 below two seconds | **P0 release gate open** |

P1 begins after the P0 release gate:

- Add true R0 Shadow mode and seller-handling-time instrumentation.
- Execute the future three-seller pilot.
- Replace local runtime infrastructure with shared durable services only if multi-instance hosting requires it.

Out of scope for v1:

- A production Whatnot or other external marketplace integration.
- Real customer data or production retention behavior.
- Video broadcasting, checkout, payments, fulfillment, purchase, bidding, auction, offer, giveaway, cancellation, return, or refund workflows.
- Seller-invoked or live open-web research.
- AI-recommended, natural-language, preauthorized, or independent marketplace actions.
- Open-ended auto-reply, unrestricted model prose in Auto-message, durable buyer memory, or a dynamic multi-step agent/tool loop.
- Claims that synthetic evaluation proves GMV, conversion, or operator-load impact.

## 9. Prototype acceptance metrics

The default pressure profile emits 120 chat events per seller over 30 seconds, including 60 noise/reaction events, 20 duplicate events, 24 unique answerable questions, 8 ambiguous or unsupported questions, 8 prompt-injection attempts, and one 20-event burst inside two seconds. The detailed generation and evaluation contract belongs to the TDD.

P0 succeeds when:

| Measure | Target |
| --- | --- |
| Grounded reply latency | Answerable-question end-to-end p95 below 2 seconds |
| Semantic correctness | At least 95% of answerable questions produce the expected safe category and evidence basis |
| Ambiguous, unsupported, and adversarial handling | 100% abstain, escalate, or answer safely without unauthorized behavior |
| Tenant and write safety | Zero cross-seller leakage and zero unauthorized, stale, duplicate, or below-floor writes |
| Action auditability | 100% of attempted seller operations produce an appropriate receipt; Undo compensates or refuses without overwriting newer state |
| Event and question integrity | Zero lost accepted events, zero duplicate effects, and valid lifecycle attribution |
| Traceability | Every eligible question exposes a complete backend trace and latency breakdown |

Synthetic results validate technical behavior only. They are not business-impact measurements.

## 10. Future three-seller pilot

The challenge requires a 3–5 seller pilot definition. SideStage defines, but does not execute, this future validation:

- Three real sneaker resellers.
- Two weeks.
- One Shadow-mode show followed by three assisted shows per seller.
- Within-seller comparison against matched recent shows.
- Directional interpretation only; three sellers cannot support a causal or statistically conclusive claim.

Future business hypotheses:

- **GMV:** Completed-order value per live hour improves by at least 5% at the median, with positive lift for at least two of three sellers.
- **Operator load:** Active seller-handling seconds per eligible question decreases by at least 30% at the median.
- **Guardrails:** Zero severe safety incidents and no material increase in cancellations or refunds.

These are future-pilot success hypotheses, not measured submission results.

## 11. Remaining P0 release confirmations

- Select the final pinned live model/provider with fallback disabled.
- Retain a clean, current-commit live artifact proving semantic correctness, hard-safety invariants, and answerable-question p95 below two seconds.
- Publish the final reviewer URL and credentials, or provide the exact supported local run command and access notes.

## 12. Related documents

- [Technical Design Document](TDD.md) — architecture, data contracts, agent workflows, guardrails, persistence, latency, deployment, and tests
- [AI proposal and rejection history](ai-proposal-rejection-history.md)
- [Debugging process and evidence log](debug-process.md)
