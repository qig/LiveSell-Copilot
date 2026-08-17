# SideStage Product Requirements Document

> Status: `Accepted` — builder-approved v1 design; implementation evidence is pending
>
> Last updated: 2026-08-17
>
> Evidence commit: TBD
>
> Primary depth: Agentic outbound-reply write safety under live state changes

## 1. Product summary

SideStage is a real-time copilot for sneaker live sellers. It ingests live buyer chat, retrieves tenant-scoped catalog, listing, inventory, and policy evidence, and prepares grounded replies for seller review. It also centralizes explicit seller controls for operational actions while treating buyer chat as untrusted input.

The 48-hour prototype is a synthetic technical demonstration. It does not validate GMV lift, conversion improvement, or reduced operator workload.

The livesell emulator is intentionally narrow: it exists to create realistic chat pressure and mutable listing state for bounded agentic-reply and safety evaluation, not to reproduce a full marketplace.

In this PRD, **bounded agentic reply autonomy** means that SideStage reacts to candidate customer questions, assembles approved context, invokes product research when required, and makes one terminal tool call: request a reply write or abstain. A reply request is untrusted intent, not send authority. The application effect broker independently selects the safe outcome—deny, seller review, or authorized R3 auto-reply. Application code owns routing, retrieval, context scope, authorization, freshness, and every side effect. The model receives no read tools, buyer chat cannot create durable memory, and the model never receives direct send or marketplace mutation authority.

## 2. Target users and prototype fixtures

The planned prototype defines exactly three isolated synthetic sneaker-reseller tenants:

1. **VelocityKicks:** High-volume new sneakers with size variants. Stresses chat bursts, SKU matching, stock freshness, and latency.
2. **VaultConsign:** Rare used and consignment sneakers. Stresses condition, authenticity, seller policy, and per-item price floors.
3. **RotationKicks:** Rapid Buy-It-Now sneaker rotation with mostly single-unit stock. Stresses Push, Swap, Unlist, concurrent purchases, and conditional seller-action rollback without an auction workflow.

These are test fixtures, not real pilot participants.

## 3. First seller workflow

The first workflow is **high-intent question to grounded answer**:

1. A seeded synthetic replay event or tester-entered custom buyer message enters a seller's live show.
2. SideStage identifies the tenant and show; preserves the raw event, ask time, show sequence, and listing epoch visible when it was asked; and classifies its eligibility.
3. A deterministic pre-router removes exact duplicates and only high-certainty noise such as emoji-only messages and allowlisted greetings. Mixed or uncertain messages pass through rather than risk losing a real question.
4. For each remaining candidate, SideStage assembles evidence and the single model call jointly determines whether a reply is warranted and drafts it. The model requests a reply or abstains with a typed reason; no separate classifier-model call is made.
5. SideStage resolves the question's bound sneaker listing and retrieves a fresh, versioned bundle of relevant catalog, listing, inventory, seller-policy, and tone evidence. It never silently retargets a pending question after a push or swap.
6. The model makes one terminal `request_reply_send` or `abstain` tool call. It cannot call a direct send function.
7. The effect broker treats a reply request as untrusted intent and deterministically validates price, availability, policy, evidence support, tenant scope, freshness, canonical-question uniqueness, and R3 authority. Tone is checked as a reply-quality rule, not an authorization rule.
8. The broker denies, holds the candidate for seller review, or sends it under valid R3 authorization. For review, the seller accepts, edits, or dismisses the suggestion. An unchanged AI suggestion is revalidated when accepted. If the seller edits it, SideStage sends the seller's exact version; detected factual, policy, or tone conflicts appear only as non-blocking warnings and never rewrite the text.
9. A validated synthetic customer purchase emits the sole Inventory Change event and decrements inventory. If aggregate stock across every variant reaches zero, the same atomic transition also Unlists the SKU, closes its listing epoch, and leaves the active slot empty.
10. Every stage, including bypass and abstention decisions, emits a correlated diagnostic trace.

## 4. Actors and authority boundaries

| Actor or source | Trust level | Permitted effect |
| --- | --- | --- |
| Authenticated seller | Trusted for its own tenant | Perform explicit Push, Swap, Unlist, and Price Markdown UI actions |
| Customer purchase | Trusted only after marketplace validation | Apply its Inventory Change and the deterministic zero-stock Unlist consequence |
| Buyer chat | Untrusted | Request information; never authorize marketplace writes or durable memory |
| AI model | Untrusted intent generator | Call `request_reply_send` or `abstain`; never directly send or mutate marketplace state |

The synthetic customer surface contains exactly two actions: send a chat message and purchase the currently active listing or one of its variants. There is no bidding, auction, offer, giveaway, cancellation, or customer-facing audit workflow. Internal action receipts remain required for technical auditability and rollback.

## 5. Copilot-to-automation ladder

The ladder applies to replies, not marketplace mutations:

- **R0 — Shadow:** Generate and trace a candidate without exposing it to the viewer.
- **R1 — Suggest:** Show a candidate that the seller may accept, edit, or dismiss.
- **R2 — Seller-approved send:** Send only after an authenticated seller decision. This is the default prototype level.
- **R3 — Bounded auto-reply:** Accepted for the prototype as an explicit seller opt-in for fresh, fully grounded answers in an allowlisted set of categories. A persistent warning remains visible while enabled, and the seller can disable it immediately at any moment.
- **R4 — Open-ended auto-reply:** Out of scope.

Disabling R3 prevents new automatic sends; replies already sent remain in the audit history. R3 never grants authority for marketplace actions. Operational actions use the authority matrix above rather than an AI automation ladder.

R3 may auto-send only:

- Current displayed price.
- Current availability for an exact size or variant.
- Exact-match shipping, payment, or return-policy FAQs.

R3 never sends unrestricted model prose. The broker renders the final short reply from verified typed price, variant-availability, or policy claims using a bounded set of seller-approved tone variants. Free-form model prose remains available for seller-reviewed R2 suggestions.

Condition, authenticity, fit or sizing advice, research-derived product facts, offers, negotiation, discounts, markdowns, customer-specific order issues, ambiguous questions, uncertain active-SKU matches, and questions bound to a listing that is no longer active always require seller approval.

Immediately before an R3 send, SideStage rechecks the R3 authorization version plus the bound listing epoch, active SKU, price, referenced variant-stock, and applicable policy versions. If the bound listing is no longer active, SideStage suppresses the candidate and moves the question to **Needs seller** with the previous SKU. Other version mismatches prevent auto-send and move the question to **Awaiting review** with refreshed card facts.

## 6. On-demand product research

Product research is invoked automatically for a candidate customer question that requires product knowledge. The seller does not initiate a separate research workflow. SideStage retrieves from a pre-indexed, source-backed sneaker corpus packaged with the prototype. Records cover release date, SKU and colorway, MSRP, materials, sizing guidance, and approved authenticity or condition facts.

Every fact carries source, timestamp, and provenance metadata. The model composes a reply candidate from retrieved evidence rather than returning a prewritten answer. Missing, stale, or conflicting evidence produces an explicit abstention. Live open-web research is out of scope so the workflow remains deterministic and compatible with the two-second latency target.

All raw messages remain observable. Reactions and high-certainty obvious noise bypass research; duplicates share a canonical question; uncertain messages may reach the single combined classification-and-reply call; and ambiguous, unsupported, and adversarial questions follow explicit guardrail or abstention paths. No event is silently discarded.

Eligible questions enter each seller show's processing queue in FIFO arrival order. SideStage does not semantically prioritize questions, and duplicate volume never raises a question's position. FIFO governs dispatch order; safe results appear as soon as they complete and remain anchored to the originating customer, message, and timestamp.

### Temporal listing attribution

Each successful Push or Swap creates a show-scoped listing epoch; Unlist closes the current epoch and leaves the active-listing slot empty. A question stores the epoch and listing that were visible when the message occurred, even if processing begins after the seller changes the listing. An unambiguous explicit SKU or product reference may override that temporal default; conflicting or missing attribution requires seller clarification rather than a guess.

The prototype keeps the complete epoch history for the bounded synthetic show. This history binds product identity, not stale facts: any seller-facing facts use the latest price, inventory, and applicable policy for the bound listing. Historical price or stock reconstruction is out of scope. A question tied to a previous listing remains eligible but enters **Needs seller**, shows a **Previous listing** tag plus the previous SKU, and does not receive an AI-generated draft. The seller may write a manual response or dismiss it. If the listing becomes inactive while generation is in flight, SideStage suppresses the candidate rather than exposing or sending it. Questions on opposite sides of a listing change are not grouped as duplicates merely because their text matches.

## 7. Prototype scope

### In scope

- Deterministic Whatnot-like live-selling emulator.
- Seeded randomized bulk-chat generation and replay plus tester-entered custom and adversarial messages.
- Three isolated seller catalogs, policies, listings, and inventories.
- Synthetic mock data only, including buffered events and operator-entered custom messages.
- Streaming ingestion, FIFO ordering, deduplication, eligibility routing, and backpressure behavior.
- Grounded reply suggestions with evidence and guardrail verdicts.
- Seller accept, edit, dismiss, and send controls.
- Per-show, default-off bounded auto-reply toggle with a persistent enabled-state warning and immediate off control.
- Exactly five marketplace operation types: Push, Swap, Unlist, Price Markdown, and Inventory Change.
- Seller controls for Push, Swap, Unlist, and Price Markdown using the challenge vocabulary.
- Purchase-driven Inventory Change plus atomic zero-stock Unlist through a trusted synthetic marketplace event.
- Internal receipts for all five operations plus verification and conditional rollback for the four seller operations.
- Seven-stage diagnostic traces and end-to-end latency measurement.
- Failure injection and deterministic replay.

### Out of scope

- A production Whatnot or other marketplace API dependency.
- Live open-web product research.
- A seller-invoked research drawer or freeform research workflow.
- Real seller participation during the 48-hour build.
- Real customer data, PII, and production data-retention behavior.
- Claims of real GMV, conversion, or operator-load impact.
- AI-recommended marketplace actions.
- Natural-language seller action commands.
- Independent or preauthorized AI marketplace mutations.
- Default-on or open-ended auto-reply.
- Free-form or manual seller stock adjustment outside the defined Inventory Change event.
- Customer cancellation, failed-payment, return, or refund workflows.
- Bids, auctions, offers, giveaways, and any other customer commerce action besides purchase.
- A customer-facing audit workflow; auditability is an internal safety requirement.
- A general-purpose agent framework or dynamic tool loop on the reply path.
- Video broadcasting, checkout, payment processing, fulfillment, and a production marketplace storefront.

## 8. Technical acceptance scorecard

| Metric | Acceptance target | Status |
| --- | --- | --- |
| Grounded-suggestion latency | p95 under 2 seconds | Not measured |
| Raw event durability | Zero lost ingested events | Not measured |
| Answerable-question coverage | At least 95% produce supported suggestions | Not measured |
| Ambiguous or unsupported requests | 100% abstain or escalate | Not measured |
| Tenant isolation | Zero cross-seller context leakage | Not measured |
| Prompt-injection resistance | Zero unauthorized instruction adoption, guardrail bypass, cross-tenant disclosure, or write; safe refusals are allowed | Not measured |
| Write safety | Zero unauthorized, below seller-configured floor, or stale-version writes | Not measured |
| Action auditability | 100% of executed actions produce complete receipts | Not measured |
| Seller-action rollback | 100% of supported rollback attempts compensate correctly or refuse safely without overwriting newer state | Not measured |
| Deduplication | No duplicate replies or writes from duplicate events | Not measured |
| Trace completeness | Every eligible event has a complete stage trace | Not measured |
| UX interaction proxy | At most one seller decision for a reply and one form submission for a seller operation | Not measured |
| Seller-edit integrity | Edited seller text is sent unchanged; detected conflicts produce traceable non-blocking warnings | Not measured |
| Auto-reply kill switch | No new automatic send after disable acknowledgement | Not measured |
| Auto-reply freshness | Zero R3 sends against changed authorization, SKU, price, variant-stock, or policy versions | Not measured |
| Agentic reply-write authorization | Zero direct, unauthorized, duplicate, ungrounded, or unreceipted model-requested sends | Not measured |
| Temporal listing attribution | Zero silent retargets and zero auto-replies for inactive bound listings | Not measured |
| Zero-stock transition | Last aggregate unit atomically changes inventory to zero and Unlists; a single sold-out variant never Unlists while another remains | Not measured |
| Question-state integrity | Every eligible question follows a valid transition with asked and state-change timestamps | Not measured |

The UX interaction proxy is not proof of real workload reduction. AI-suggestion guardrail metrics and seller-edited warning metrics are reported separately; seller-authored overrides are not represented as AI-generated safe replies.

## 9. Degraded experience

When an eligible high-intent question cannot produce a safe suggestion, SideStage creates a **Needs seller** card with a concise reason: previous listing, missing evidence, conflicting evidence, stale inventory, guardrail failure, or timeout. It never exposes an unsafe partial draft. The seller may answer manually from the card.

Noise and duplicate messages do not create failure cards; they remain observable in the raw stream and diagnostic tracer. Crossing two seconds records an SLO miss but does not discard an otherwise fresh result. Results arriving after a separate hard timeout are discarded. If the underlying listing, inventory, or policy snapshot changes during generation, SideStage may revalidate once before the hard timeout; otherwise it marks the candidate stale and requires the seller.

Eligible questions wait in a large but finite FIFO queue sized from the defined workload, measured service time, worker concurrency, and a safety margin. Queue time is included in latency measurements. Queue depth and delay are diagnostic signals rather than seller-facing failure cards.

## 10. Seller workspace

The seller experience is a minimal, elegant two-surface technical demo:

- **Live Chat:** A chronological stream of every raw buffered mock event plus custom messages entered by the demo operator.
- **Copilot Inbox:** A focused supervision and operations surface for questions that require a reply decision. Noise does not create an Inbox card. The seller sees each reply beside only the relevant current listing, inventory, and policy facts; enables or disables bounded auto-reply; reviews or edits suggestions; performs Push, Swap, Unlist, and Price Markdown operations; observes customer-driven Inventory Change events; and may Undo only the latest still-version-valid seller operation.

A compact header identifies the seller, show, and active listing and contains the R3 toggle. Its persistent warning appears whenever auto-reply is enabled. The diagnostic tracer remains a separate developer view and can filter events by actual routing outcome: all, eligible, noise, duplicate, ambiguous or unsupported, and adversarial. The seller workspace excludes extra dashboards, analytics panels, and navigation that do not directly serve the technical demonstration.

Grounding and guardrail evaluation run on the backend. Detailed verdicts, evidence provenance, freshness, and stage data belong in the diagnostic trace, not the seller card. The seller UI contains no numeric confidence score or expanded evaluator output.

Each eligible customer question displays its asked time, latest state-change time, and one lifecycle state:

```text
Queued -> AI working
              |-> Awaiting review -> Answered by seller
              |-> Auto-answered
              |-> Needs seller -> Answered by seller / Unanswered
```

A duplicate question displays **Grouped** and links to its canonical question. A question whose bound listing is no longer active displays a compact **Previous listing** tag plus the previous SKU, enters **Needs seller**, and offers manual reply or dismiss without an AI draft. **Unanswered** becomes terminal only when the seller dismisses the question or the show ends. Each card otherwise shows only SKU, current price, referenced variant plus stock, and an applicable policy line when relevant.

## 11. Synthetic pressure workload

The emulator generates synthetic chat with pseudorandom variation and records the seed on every run. A seed determines message text, synthetic usernames, inter-arrival timing, and ordering within the workload constraints, so a failure can be replayed exactly. The default pressure profile gives each seller 120 events over 30 seconds:

- 60 irrelevant noise or reaction events, including emoji-only messages, greetings, cheers, and off-topic banter.
- 20 exact or normalization-equivalent duplicate events, including surface differences in case, punctuation, or emoji.
- 24 unique answerable questions.
- 8 ambiguous or unsupported questions.
- 8 prompt-injection attempts.
- One burst of 20 events within 2 seconds.

Across three tenants, this yields 72 eligible answerable-question traces plus noise, ambiguity, duplication, and adversarial cases.

Generated fixtures carry evaluator-only expected routing labels that are never placed in model context. The tracer can compare this expected label with the actual route so the tester can inspect false filtering and missed filtering. The tester can also inject arbitrary custom messages into a running show. Custom messages are stamped with the currently displayed listing epoch, use the same ingestion, tracing, queueing, and guardrail path as generated messages, and are tagged only by input origin. Regression tests use fixed recorded seeds; exploratory pressure runs may use a new seed, which must be printed and retained for replay.

## 12. Future seller pilot definition

The challenge requires a 3–5 seller pilot definition. SideStage therefore defines, but does not execute or claim results from, a future three-seller validation:

- Three real sneaker resellers.
- Two-week period.
- One shadow-mode show followed by three assisted shows per seller.
- Within-seller comparison against matched recent shows.
- Directional analysis only; the sample is too small for a causal or statistically conclusive business claim.

Future business measures:

- **GMV:** Completed-order value per live hour. The pilot success hypothesis is at least a 5% median within-seller lift, with positive lift for at least two of three sellers.
- **Operator load:** Active seller-handling seconds per eligible question. The pilot success hypothesis is at least a 30% reduction in the median within-seller measure.
- **Guardrails:** Zero severe safety incidents and no material increase in cancellations or refunds.

These are future-pilot hypotheses, not prototype acceptance criteria or measured submission results.

## 13. Implementation-time confirmations

- Exact pinned model identifier and structured-output adapter.
- Measured queue, worker, hard-timeout, and latency-budget values.
- Final run, test, deployment, and access commands.

## 14. Implementation milestones

### Milestone 1 — Synthetic Data Contracts

Define and validate versioned JSON contracts for the three seller fixtures, catalogs, policies, listings, variants, inventory, seeded chat scenarios, expected evaluator labels, and replay metadata. Exit when the fixtures validate, identical seeds reproduce identical events, different seeds vary only approved fields, and cross-tenant references fail validation.

### Milestone 2 — Livesell Marketplace Emulator

Run the livesell interaction without AI: buffered and custom chat, listing epochs, Push, Swap, Unlist, Price Markdown, customer Purchase to Inventory Change, linked zero-stock Unlist, internal receipts, and supported seller-action rollback. Exit when the five operation types and temporal races pass deterministic tests and the minimal marketplace UI works end to end with the copilot disabled.

### Milestone 3 — Reply Agent and Copilot

Add eligibility routing, bounded context retrieval, terminal `request_reply_send` or `abstain`, the effect broker, R2 review, R3 auto-reply, Copilot Inbox, diagnostic traces, safety evaluation, and latency reporting. Exit when deterministic agentic-write tests pass, synthetic pressure evaluation runs from one command, and p95 latency is measured against the approved boundary.

Marketplace operations belong to Milestone 2 rather than being described as an AI copilot feature: they create the mutable environment against which Milestone 3's reply agent is tested.

## 15. Related documents

- [Technical Design Document](TDD.md)
- [v1 milestone implementation plan](plans/2026-08-17-sidestage-v1-milestones.md)
- [AI proposal and rejection history](ai-proposal-rejection-history.md)
- [Debugging process and evidence log](debug-process.md)
