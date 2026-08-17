# SideStage Technical Design Document

> Status: `Accepted` — builder-approved v1 design; implementation evidence is pending
>
> Last updated: 2026-08-17
>
> Implementation commit: TBD
>
> Run command: TBD
>
> Test command: TBD
>
> Primary depth: Agentic outbound-reply write safety under live state changes

## 1. Scope and technical goals

The planned implementation is a bounded asynchronous Python state machine, not a general agent loop. The reply-critical path has one terminal-tool model request surrounded by application-owned retrieval, policy, effect brokering, tracing, and deadline control.

All catalogs, policies, listings, inventories, chat events, custom messages, and customer actions are synthetic mock test data. The prototype does not ingest real customer data or claim a production retention policy. Credentials and environment secrets must never enter event or trace payloads.

This is the accepted design contract. Concrete implementation file maps, function names, commands, and measured results are added only after they exist.

### Approved v1 runtime architecture

SideStage runs as one FastAPI/Uvicorn process with explicit `EventIngestor`, `MarketplaceService`, `ReplyPipeline`, `EvidenceRetriever`, `ModelRunner`, `ReplyEffectBroker`, and `TraceRecorder` boundaries. FastAPI serves a static HTML/CSS/JavaScript interface. HTTP commands carry custom chat, synthetic purchases, seller operations, and reply decisions; Server-Sent Events publish live chat, Inbox state, inventory updates, and diagnostic traces. No frontend build system, message broker, Redis, vector database, or second backend service is required.

SQLite in WAL mode stores runtime show state, normalized questions, replies, reply receipts, marketplace receipts, and queryable traces. The approved JSON/JSONL layout remains the portable fixture and replay format. Exact typed SQLite lookups provide current catalog, listing, inventory, and policy facts; tenant-filtered SQLite FTS5 searches the local sneaker research corpus. Retrieval always applies tenant scope before matching.

One pinned fast model is accessed through `ModelRunner`; the exact provider identifier is recorded when implemented. Deterministic tests replace it with a scripted fake and the hot path has no provider fallback. Server-issued demo sessions bind authenticated seller authority to one seller and show. Tester chat and purchase controls use a separate emulator-controller authority, and no client-supplied seller identifier establishes scope.

### Bounded agent boundary

Agentic behavior is limited to the reply plane: automatic eligibility routing, approved evidence access, a terminal write-intent decision, guarded abstention or review, and optionally authorized R3 delivery. A model-generated intent is data, not authority. Only the application effect broker may write a reply to live chat after deterministic grounding, policy, freshness, tenant, canonical-question uniqueness, and R3-capability checks.

The model has exactly two terminal effect tools:

- `request_reply_send(reply_text, answer_category, claims)` expresses a potential outbound write but performs no side effect itself.
- `abstain(reason_code)` records why no reply should be attempted.

The runtime injects seller, show, question, bound-listing snapshot, dependency versions, authorization state, and canonical-question identity from trusted state; these are not model arguments. The call is terminal, so no tool result is returned for another model round. A direct `send_reply` function and marketplace mutation functions—Push, Swap, Unlist, Price Markdown, Inventory Change, and rollback—must never be registered as model-callable tools. Buyer text is never promoted into system instructions, tool authority, or durable memory. No read tools are model-callable; application code retrieves the bounded evidence snapshot before the single model request.

### Synthetic fixture storage

Milestone 1 uses hybrid per-seller fixture bundles plus generated run artifacts:

```text
fixtures/
  sellers/<seller_id>/
    seller.json
    catalog.json
    policies.json
    shows.json
  scenarios/
    pressure_v1.json
    safety_races_v1.json
runs/<run_id>/
  manifest.json
  events.jsonl
  oracle.json
  evaluation.json  # emitted after Milestone 3 evaluation
```

Fixture bundles contain stable seller, product, listing, variant, inventory, policy, tone, and show-start data. Scenario JSON contains workload counts, timing constraints, scheduled operations, and a seed. `events.jsonl` is the exact generated stream for incremental replay. `oracle.json` maps generated event IDs to evaluator-only expected routes and outcomes and must never enter retrieval or model context. `manifest.json` records schema version, generator version, seed, fixture digest, scenario ID, and run ID.

Pydantic models are authoritative and emit JSON Schema. Money is integer minor units such as cents, entity versions are monotonic integers, and scenario time is relative `at_ms`. The same fixture digest, generator version, and seed must produce byte-identical events. Different seeds may vary only allowlisted fields: synthetic customer identity, wording template, emoji, valid SKU or variant choice, and timing jitter. Event-class counts and safety invariants remain fixed. Exploratory runs print and retain their seed; regression tests use fixed seeds.

### Core fixture entities and relationships

The state model is normalized rather than deeply nested or purely event-sourced:

```text
SellerProfile
├── Product 1─* Listing
│   ├── Listing 1─* Variant
│   │   └── Variant 1─1 InventoryPosition
│   └── Product 1─* EvidenceRecord
├── SellerPolicy *
└── Show *
    ├── active_listing_id: Listing?
    └── ListingEpoch *
```

`Product` holds stable sneaker identity and catalog facts; `Listing` is the seller-specific commercial offer, condition, price, and version; `Variant` is a size or color option; `InventoryPosition` holds available quantity and version; `EvidenceRecord` is a source-backed research fact; `SellerPolicy` is a shipping, payment, return, price-floor, or reply rule; `Show` owns active presentation state; and `ListingEpoch` records the listing displayed over a show-sequence interval. `SellerProfile` also contains the bounded tone configuration.

Identifiers use readable prefixes: `sel_`, `prd_`, `lst_`, `var_`, `pol_`, `show_`, `epoch_`, `cus_`, `evt_`, `run_`, `trace_`, and `receipt_`. Every tenant-owned top-level record repeats `seller_id`. Fixture validation rejects any foreign reference whose seller differs.

### Input event and timestamp contract

Every synthetic input uses a versioned discriminated envelope with `event_id`, `run_id`, `seller_id`, `show_id`, `show_seq`, `at_ms`, actor, `event_type`, and its typed payload. Runtime ingestion adds trusted `source_epoch_id`, `accepted_at`, and `trace_id`; fixture or model data cannot set them.

Time fields have distinct semantics:

- `at_ms`: deterministic synthetic offset from show start.
- `source_occurred_at`: UTC event time, derived from `run_started_at + at_ms` for generated events and current show time for custom input.
- `accepted_at`: UTC time SideStage accepts the event and starts its latency SLO.
- `state_changed_at`: UTC time of each question-state transition.
- `executed_at`: UTC time of an outbound reply or marketplace effect.
- `recorded_at`: UTC time an audit receipt is persisted.
- `show_seq`: authoritative ordering and tie-breaker when timestamps match or delivery is delayed.

All persisted UTC timestamps use ISO 8601 with millisecond precision. Stage timing uses a monotonic clock and persists `duration_ms`; latency is never calculated by subtracting wall-clock timestamps. Fixed-seed regression uses a fixed clock so enriched records are reproducible.

## 2. Non-negotiable invariants

- No cross-tenant context, replies, actions, or trace payloads.
- Duplicate input events never cause duplicate replies or marketplace effects.
- Every factual claim in an AI-authored suggestion or automatic reply is supported by a fresh, versioned evidence snapshot. Exact seller-authored edits remain governed by the separately approved warning-only override policy.
- Guardrails fail closed when required evidence or policy is missing.
- Buyer chat has no marketplace write authority and cannot create durable memory.
- A `request_reply_send` call never bypasses the effect broker or performs a direct write.
- An authorized reply, its receipt, and its canonical-question terminal state commit in one local transaction protected by a unique canonical-question constraint.
- If that transaction fails, no reply, receipt, or terminal-state update remains; there is no distributed `send_unknown` workflow in the in-process emulator.
- The only customer inputs are chat messages and validated purchase events; no bid or auction state machine exists.
- AI output never directly invokes a marketplace mutation.
- Every marketplace write is authenticated, validated, idempotent, version-checked, audited, and verified.
- A final-unit Inventory Change and its derived Unlist commit atomically or have no effect.
- Rollback of a supported seller operation creates a new recorded compensating event; it never erases history.
- Diagnostic tracing cannot block reply delivery, but persistence of an action audit intent fails closed before any write is attempted.

## 3. Planned reply pipeline

```text
Chat event
  -> normalize and deduplicate
  -> tenant and show routing
  -> deterministic high-certainty noise pre-routing
  -> parallel versioned context retrieval for remaining candidates
  -> one terminal-tool model request that jointly classifies and drafts
  -> request_reply_send or abstain
  -> effect-broker grounding, policy, freshness, tone, capability, and uniqueness checks
  -> deny, seller suggestion, or authorized R3 send
  -> atomically persist reply, receipt, and terminal question state
```

The model has no read tools. The pipeline has no unbounded `while tool_calls` loop, no separate classifier-model request, no second model round after the terminal call, and no model-written durable memory.

### Model input and terminal-output contract

Application code supplies one immutable `ReplyTask` containing the current question identifier, text, and ask time; immutable listing and epoch binding; current product, listing, price, referenced variant, and inventory facts; only the applicable seller policies; retrieved evidence records with trusted identifiers, versions, source metadata, and freshness; and a bounded seller-tone policy. It does not contain arbitrary prior chat, customer memory, another seller's data, marketplace credentials, R3 authorization state, or write and idempotency identities.

The model must make exactly one terminal call:

```text
request_reply_send(
  reply_text,
  answer_category,
  claims: [{reply_span, evidence_ids}]
)
```

or:

```text
abstain(reason_code)
```

The runtime injects trusted seller, show, question, binding, version, authorization, and canonical-question fields after the call. The broker recomputes authorization-relevant category and claim support from trusted evidence rather than trusting the model's label. Unknown tools, multiple calls, malformed arguments, unknown or fabricated evidence identifiers, and unsupported factual spans fail closed.

## 4. Approved trace stages

The diagnostic UI exposes this correlated progression:

1. Ingest
2. Normalize and deduplicate
3. Route and classify eligibility
4. Assemble evidence snapshot
5. Generate terminal reply-write intent or abstention
6. Broker authorization and guardrails
7. Deny, hold for review, atomically send with receipt, or abstain

Each stage records trace, seller, show, event, and snapshot identifiers; timestamps; input and output references; verdicts; and latency. Payloads are synthetic, but environment credentials and secrets are always excluded or redacted.

## 5. Streaming ingestion requirements

- Preserve every raw event in a replayable event log.
- Preserve ordering within a seller show while permitting safe concurrency across independent questions.
- Use bounded queues and explicit backpressure behavior.
- Assign idempotency and correlation identifiers at acceptance.
- Record `source_occurred_at`/`asked_at`, `accepted_at`, and a show-local monotonic `show_seq`; use sequence rather than wall-clock time as the authoritative listing-boundary tie-breaker.
- Stamp each generated or custom chat event with the listing epoch visible at event creation.
- Deduplicate event-ID, exact-text, and normalization-equivalent chat without losing the raw events. Semantic paraphrases are not silently suppressed in v1.
- Support deterministic playback rate, pause, resume, burst injection, and manual adversarial messages.
- Generate variable synthetic workloads from an explicit pseudorandom seed and persist the seed with each run.
- Tag generated and tester-entered messages by input origin while routing both through the same production-shaped ingestion path.
- Revalidate any reply whose listing, inventory, or policy snapshot changes before emission.

Raw event order is always preserved in the replay log. Near-duplicate classification may suppress redundant reply suggestions, but never removes raw events or suppresses distinct marketplace events. Semantic duplicate grouping includes the bound listing identity, so matching text on opposite sides of a listing change remains distinct.

Every normalized chat event receives one traceable routing outcome. Routing is hybrid: deterministic code handles event-id duplication, exact normalized duplicates scoped to the same seller/show/listing epoch, emoji-only messages, and an allowlist of obvious standalone greetings. Any mixed or uncertain message proceeds so a customer question is not silently lost. The one reply-agent call completes natural-language classification while drafting or abstaining; model classification is never an authorization boundary.

Routing outcomes are:

- **Eligible:** Product, price, availability, condition, authenticity, shipping, or policy question; enters retrieval and generation.
- **Noise:** Reaction or obvious non-question. High-certainty deterministic cases bypass retrieval and generation; a harder case may be identified by `abstain(reason=no_response_needed)` in the combined model call and then remains outside the Copilot Inbox.
- **Duplicate:** Links to one canonical question and cannot produce a duplicate reply.
- **Ambiguous or unsupported:** Enters an explicit abstention path.
- **Adversarial:** Enters guardrail evaluation and cannot supply trusted instructions or write authority.

Other abstention reasons include `ambiguous_question`, `missing_evidence`, `conflicting_evidence`, `prompt_injection`, and `unsupported_request`. Ambiguous, missing/conflicting-evidence, and unsupported customer questions transition to `needs_seller`; prompt injection is ignored when it contains no legitimate question and otherwise follows the safe answer or seller-escalation path.

Eligible questions enter a per-show FIFO work queue in acceptance order. There is no semantic priority or duplicate-count boost. FIFO controls dispatch, not completion. Bounded workers may process independent questions concurrently, and each safe outcome emits as soon as it completes. Every outcome carries the originating customer, message, timestamp, and sequence identifiers so completion reordering cannot break attribution.

The initial FIFO capacity is 64 candidate questions per show, with four concurrent reply workers per show and twelve globally. These values cover the approved synthetic profile with margin and must be benchmarked rather than justified by available memory alone. Crossing two seconds does not reject or discard a question. Queue depth and wait time are traced. The initial hard timeout is five seconds and may be changed only with recorded benchmark evidence. If the queue is actually full, the raw event remains durable, no model call begins, and the question receives a typed capacity outcome for seller attention and trace evaluation.

### Listing-epoch model

Every successful Push or Swap creates an append-only show epoch containing `epoch_id`, `listing_id`, `start_seq`, and `end_seq`. Unlist closes the active epoch and leaves the active-listing slot empty. The bounded synthetic prototype retains every epoch until the show ends; it does not require a production TTL or historical database.

Normalization persists immutable `bound_epoch_id`, `bound_listing_id`, `binding_basis` (`explicit` or `source_epoch`), and `binding_status` (`certain` or `uncertain`). A unique explicit SKU or listing mention overrides the source epoch. Missing, malformed, or conflicting attribution preserves the raw event but requires review or clarification. Delayed processing never rebinds a question to the then-current listing.

Before retrieval or generation, the pipeline compares the bound epoch with the active epoch. An already-inactive bound listing bypasses the model and emits `needs_seller(reason=previous_listing)` with the previous SKU. If the epoch becomes inactive after generation begins, final validation suppresses the candidate and emits the same outcome.

## 6. Catalog and policy grounding requirements

- All retrieval is tenant-scoped before ranking or filtering.
- Evidence records contain source type, source identifier, seller identifier, timestamp, and source version.
- The emulator marketplace state is the source of truth for listing identity, epoch history, and current inventory.
- Product identity is selected from the immutable question binding, while mutable price, stock, and policy facts are fetched fresh for that bound listing.
- Context is bounded and assembled by application code rather than autonomous agent memory.
- Missing, conflicting, stale, or insufficient evidence produces abstention or escalation.
- Generated reply text is never cached as a trusted fact.

## 7. Reply guardrails

Hard deterministic checks cover:

- Tenant and show scope.
- Bound listing and variant identity, including temporal-attribution certainty.
- Price and seller floor.
- Availability and inventory version.
- Required policy evidence.
- Unsupported product claims.
- Prompt-injection indicators and untrusted instructions.

Tone is a quality check and cannot authorize an otherwise unsafe reply. Deterministic hard language rules prevent an AI-authored draft or automatic reply from being exposed or sent. R3 rendering uses bounded seller-approved tone variants. Softer seller-style mismatches may remain review warnings for R2. A second model-based tone pass must not be added unless benchmark evidence shows that it fits the latency budget.

An unsafe candidate is never exposed as a partial draft. Eligible failures emit a typed `needs_seller` outcome with a reason code for previous listing, missing evidence, conflicting evidence, stale state, guardrail failure, or timeout. Noise and duplicates do not emit failure cards.

Results completed after the separate propagated hard timeout are discarded. Crossing the two-second SLO threshold alone does not discard a fresh result. If listing, inventory, or policy state changes during generation, the pipeline may revalidate once before the hard timeout. Without sufficient time or a valid snapshot, it emits `needs_seller` rather than a reply candidate.

If the seller edits a safe suggestion, the edited text becomes an authenticated seller-authored reply. SideStage sends that exact text without rewriting or blocking it. Deterministic checks may emit non-blocking price, availability, policy, evidence, or tone warnings before send; warnings and the seller's decision are traced. Tests and metrics must keep guarded AI suggestions separate from seller-edited overrides.

If the seller accepts an AI-authored suggestion without editing it, the broker revalidates its referenced listing, price, inventory, policy, and evidence versions at acceptance. A stale unchanged suggestion cannot be sent; it returns to review with refreshed facts or moves to `needs_seller`. This stricter path does not override the approved exact-text behavior for a seller edit.

## 8. On-demand product research

On-demand product research is triggered only by a candidate normalized customer question that requires product knowledge. The retrieval query is constructed by application code from the tenant-scoped customer question and its bound-listing context; retrieval is not model-callable. The seller has no separate research endpoint or UI. Research uses a pre-indexed, source-backed sneaker corpus packaged with the prototype and has no live-web dependency. Records cover release date, SKU and colorway, MSRP, materials, sizing guidance, and approved authenticity or condition facts.

Each record must carry source, timestamp, and provenance metadata. Research output feeds the reply-candidate pipeline and passes through the same evidence-support and policy guardrails as other chat replies. Missing, stale, conflicting, or late evidence produces an explicit abstention. Tenant-filtered SQLite FTS5 performs local research retrieval; tests must prove that replies are composed from retrieved evidence rather than ungrounded model knowledge.

## 9. Reply automation gates

The default reply level is R2 seller-approved send. R3 bounded auto-reply is a per-show capability that is off by default and requires an explicit authenticated seller opt-in. While enabled, the seller UI displays a persistent warning and immediate off control.

The enabled state must be versioned and attached to every automatic-send authorization. Disabling R3 invalidates the current authorization so no later candidate can auto-send against stale enabled state. Already-sent replies remain immutable and auditable.

The R3 allowlist contains only:

- Current displayed price.
- Current availability for an exact size or variant.
- Exact-match shipping, payment, or return-policy FAQs.

R3 cannot send unrestricted model prose. For automatic replies, the broker renders the final short text from verified typed claims: current price with listing version, exact variant availability with inventory version, or a canonical policy answer with policy version. It may choose only from bounded seller-approved tone variants and cannot add factual content. The model's freer `reply_text` is retained for R2 seller review.

Condition, authenticity, fit or sizing advice, research-derived product facts, offers, negotiation, discounts, markdowns, customer-specific order issues, ambiguous questions, uncertain active-SKU matches, and inactive bound listings must downgrade to seller approval.

R3 freshness is version-based rather than time-to-live based. Immediately before send, the gateway requires the question's bound epoch to remain the active epoch and rechecks the R3 authorization version plus active SKU, price, referenced variant-stock, and applicable policy versions. An inactive bound listing suppresses the candidate and transitions the question to `needs_seller(reason=previous_listing)` with the previous SKU and manual reply or dismiss controls. Other mismatches reject automatic authorization and transition the question to `awaiting_review` with refreshed minimal card facts.

R3 grants reply-send authority only. It cannot authorize Push, Swap, Unlist, Price Markdown, Inventory Change, or any other marketplace mutation.

For an authorized R3 write, the effect broker uses one local database transaction to insert the reply, insert its `ReplyReceipt`, and mark the canonical question `auto_answered`. A unique constraint on canonical-question identity prevents duplicate replies, including for grouped duplicate chat. The receipt records reply, canonical-question, actor, R2/R3 mode, evidence, validated versions, guardrail verdict, and creation time. Transaction failure rolls back every change and emits no reply. Sent replies are immutable and have no rollback path. A distributed send-intent, acknowledgement-reconciliation, or `send_unknown` state machine is explicitly out of scope while the broker and chat emulator share one local transaction boundary.

## 10. Listing and inventory actions

Marketplace effects originate from either an authenticated seller UI action or a validated synthetic customer purchase. Chat input never carries action authority.

Planned write flow:

```text
Typed seller UI action request or marketplace event
  -> authenticate source and tenant
  -> validate schema, policy, and expected version
  -> apply idempotency check
  -> persist audit intent or transactional outbox record
  -> execute against emulator adapter
  -> read after write
  -> append verified outcome to the audit record
  -> expose a conditional compensating operation for a supported seller action
```

Execution must not begin if the audit intent cannot be persisted. Intent-persistence failure causes no mutation and cannot promise a durable receipt because the audit store itself is unavailable. A trusted request rejected after intent persistence records `rejected`; execution or verification failure records `failed`; neither may leave an unrecorded partial marketplace mutation.

The prototype exposes exactly five marketplace operation types:

- `push`: `PushRequest(target_listing_id, expected_show_version)` requires an empty active slot and an available, in-stock target. It makes the listing active and opens a listing epoch.
- `swap`: `SwapRequest(target_listing_id, expected_active_listing_id, expected_show_version)` requires an active listing and a different available, in-stock target. It atomically closes the prior epoch, activates the target, opens a new epoch, and leaves the previous listing available but inactive.
- `unlist`: Seller `UnlistRequest(expected_active_listing_id, expected_show_version)` marks the active listing `unlisted`, closes its epoch, and leaves the slot empty. A derived zero-stock Unlist instead marks the listing `sold_out`.
- `price_markdown`: `PriceMarkdownRequest(listing_id, new_price_cents, expected_listing_version)` must target the active listing, lower its price, and remain at or above its seller-configured floor.
- `inventory_change`: A validated `PurchaseRequest(purchase_id, variant_id, quantity=1)` decrements the variant. If resulting aggregate stock is zero, it commits a linked `unlist` in the same transaction. Exhausting only one variant does not Unlist while another remains available.

Actor, seller, and show identity come from the authenticated session rather than request fields. The customer submits `PurchaseRequest`, never a direct Inventory Change. Push against a non-empty slot, Swap against an empty slot, Swap to the already-active SKU, and every stale or policy-invalid request are rejected without mutation and receive an audited refusal. The show starts with an empty active-listing slot. An explicitly unlisted listing returns only through a valid rollback; no separate Clear or Relist operation is in scope.

Customer cancellation, failed-payment, return, and refund events are out of scope. Free-form manual stock adjustment, AI-recommended actions, and natural-language seller commands are also out of scope.

There is no bidding, auction, offer, giveaway, or customer-facing audit action. The action audit ledger is backend safety infrastructure required by the challenge and is not part of the customer interaction model.

## 11. Auditability and rollback

Every attempted operation returns one `OperationReceipt` containing:

- `receipt_id`, `operation_id`, and one of the five `operation_type` values.
- Actor type and identifier from trusted authority state.
- Seller, show, listing, and optional variant identifiers.
- Status: `applied`, `rejected`, or `failed`.
- Requested parameters plus before and after state.
- Expected and resulting versions.
- Policy and authorization verdicts.
- Idempotency key.
- Optional parent operation identifier for a derived zero-stock Unlist, plus optional `compensation_for_receipt_id` for rollback. A compensating receipt retains the original one-of-five `operation_type`; `rollback` is never a sixth operation type.
- `recorded_at`, optional `executed_at`, and optional typed error code.

All five operation types produce internal receipts. A rollback request references the original `receipt_id`; it is a compensating safety control, not a sixth operation. Rollback is supported only for the four authenticated seller operations:

- Push rollback returns the just-pushed active slot to empty.
- Swap rollback restores the previous active SKU.
- Unlist rollback restores the previously active SKU.
- Price Markdown rollback restores the previous price.

Each rollback is a version-checked internal compensating action linked to its original receipt. It refuses safely when later state would be overwritten. A completed purchase-driven Inventory Change and its derived zero-stock Unlist are not rollback-capable because that would create a cancellation workflow; they must instead commit atomically, be idempotent, and be fully audited. Rollback is not a sixth product operation.

## 12. Latency boundary and budget

The two-second SLO starts at trusted `accepted_at`. For R2 it ends when a complete safe review or `needs_seller` card is published to the Inbox stream. For R3 it ends when the atomic auto-reply transaction commits and the corresponding chat event is published. Queue wait is included. The objective is p95 under two seconds across eligible questions; it is not a per-request deadline. Browser rendering and seller decision time are measured separately because the acceptance evaluator runs on the backend.

The initial p95 budget is:

| Stage | Budget |
| --- | ---: |
| FIFO queue wait | 250 ms |
| Normalize, bind, and retrieve | 150 ms |
| Single model request | 1,200 ms |
| Broker, local transaction, and SSE publish | 100 ms |
| Contingency | 300 ms |
| **Total** | **2,000 ms** |

Questions that exceed two seconds continue processing and count as SLO misses. Results beyond the five-second hard timeout are discarded and move to the typed timeout path. Raw-event acceptance, normalization, model time to first token when available, backend completion, browser-render delay, seller decision time, and marketplace-action duration are measured separately. Measured p50, p95, and maximum values replace assumptions in the submission evidence.

## 13. Marketplace integration boundary

The planned prototype will use an in-repository Whatnot-like emulator behind a typed marketplace port. No external marketplace API is required to run or test the submission.

The emulator must support:

- Isolated seller catalogs, listings, policies, and inventories.
- Active-listing state and a complete per-show listing-epoch history.
- Seeded randomized chat generation, exact replay, and tester-entered custom chat events.
- Explicit seller Push-from-empty, Swap-from-active, Unlist, and Price Markdown actions.
- Validated customer-purchase Inventory Change events.
- Atomic linked Unlist when a purchase exhausts aggregate SKU inventory.
- No bid, auction, offer, giveaway, cancellation, or other customer-commerce state machine.
- Version conflicts, latency, and failure injection.
- Receipts and verification reads for all five operations, plus conditional rollback for the four seller operations.

The port must remain compatible with a future marketplace adapter that handles authentication and token scope, webhook signature validation, rate limits, retry and idempotency semantics, version conflicts, reconciliation, and platform-specific error mapping. These production concerns are designed at the boundary but are not claimed as an implemented external integration.

## 14. Seller UI event surfaces

The planned technical-demo UI has two primary seller surfaces:

- **Live Chat:** Renders chronological buffered mock events and accepts custom demo messages.
- **Copilot Inbox:** Renders the reply with only its relevant current listing, inventory, and applicable policy facts; reply controls and R3 state; explicit listing actions; and customer-driven inventory events.

A compact shared header carries seller, show, active-listing, latency-health, and R3 enabled-state information. Server-Sent Events update the UI; HTTP POST commands carry user decisions and emulator inputs. Only the latest rollback-eligible seller operation exposes Undo, and only while its expected resulting version remains current; complete compensation detail stays in the debugger. The diagnostic tracer is a separate developer route and must not add complexity to the seller workspace. It supports routing-outcome filters for all, eligible, noise, duplicate, ambiguous or unsupported, and adversarial events. For generated fixtures it also shows evaluator-only expected route versus actual route; expected labels are never included in retrieval or model context.

Grounding and guardrail evaluation execute on the backend. Detailed evidence, provenance, freshness, evaluator verdicts, and stage payloads are written to the diagnostic trace. The seller UI receives only the minimal facts and lifecycle state required to supervise a reply; it does not render a confidence score or evaluator internals.

The question lifecycle enum is:

- `queued`
- `ai_working`
- `awaiting_review`
- `auto_answered`
- `needs_seller`
- `answered_by_seller`
- `unanswered`
- `grouped`

Valid transitions mirror the PRD state model. `unanswered` is terminal only after seller dismissal or show end. `grouped` references a canonical question. Every state record carries `asked_at` and `state_changed_at`. The minimal card facts are SKU, current price, referenced variant plus stock, and one applicable policy line when relevant.

## 15. Diagnostic trace and receipt separation

- **Replay event log:** Durable input history for deterministic reruns.
- **Diagnostic trace store:** Nonblocking stage observations for debugging, latency analysis, and expected-versus-actual routing inspection.
- **Reply receipts:** Records atomically committed with outbound replies and terminal question state.
- **Action audit ledger:** Safety-critical, append-only record required before a write is considered successful.

The four may share correlation identifiers and a unified UI but have distinct durability and failure semantics.

## 16. Test strategy

The final suite must map exact test names and commands to:

- Stream ordering, reconnect, backpressure, and burst behavior.
- Fixed-seed regression replay, multi-seed invariant sweeps, and failing-seed reporting.
- Custom-message ingestion through the same path as generated events.
- Emoji, greeting, reaction, and off-topic-noise bypass without raw-event loss.
- Expected-versus-actual route inspection and filtering in the diagnostic view.
- FIFO dispatch with deliberately reordered completion and correct message attribution.
- Question-before-swap processing that remains bound to the previous listing, displays the previous SKU, emits no AI draft, and never R3 auto-sends.
- Previous listing detected before generation bypassing the model, plus an in-flight swap suppressing the completed candidate.
- Same-text questions on opposite sides of a swap remaining distinct.
- Explicit old-SKU references, uncertain swap-boundary references, delayed delivery, and equal-timestamp sequence tie-breaking.
- Fresh price, stock, and policy validation for the historically bound listing without historical-fact reconstruction.
- Event-ID, exact, and normalization-equivalent duplicate handling without fuzzy semantic suppression.
- Tenant isolation.
- Catalog, listing, inventory, and policy freshness.
- Unsupported and ambiguous questions.
- Prompt injection and malicious cross-tenant requests.
- Guardrail failures and explicit abstention.
- `needs_seller` reason mapping, late-result discard, and stale-snapshot handling.
- Exact preservation of seller-edited text and non-blocking warning behavior.
- Default-off R3 state, explicit enable, persistent warning, disable race, and stale-authorization rejection.
- Strict terminal-tool schemas, rejection of every unregistered tool, and server-side attachment of all authority and scope fields.
- `request_reply_send` denial, seller-review downgrade, authorized R3 execution, atomic reply-and-receipt commit, transaction rollback, and duplicate prevention by canonical-question uniqueness.
- Final-send R3 version checks and downgrade to `awaiting_review` on any mismatch.
- Valid question-state transitions, timestamps, duplicate grouping, dismissal, and show-end finalization.
- Stale-version action rejection.
- Push-from-empty and Swap-from-active success, plus audited rejection for every invalid Push/Swap precondition.
- Atomic Swap epoch transition and concurrent stale-active-listing rejection.
- Unlist epoch closure and return to an empty active-listing slot.
- Validated Inventory Change without any cancellation, failed-payment, return, or refund workflow.
- Idempotent retries and duplicate marketplace events.
- Partial seller-action failure, verification failure, conditional rollback, and safe rollback refusal after newer state.
- Atomic, idempotent purchase Inventory Change with no rollback path.
- Final-unit purchase and linked Unlist atomicity, variant-level nonzero-stock behavior, and concurrent last-unit purchase rejection.
- Complete trace and audit records.
- p50, p95, and maximum stage and end-to-end latency.
- Queue-capacity sizing, over-two-second completion, and separate hard-timeout behavior.

Exact run and test commands remain TBD until implementation exists.

## 17. Code map and open decisions

Do not add speculative file or function names. Populate this section from the implemented code before submission.

Implementation-time confirmations:

- Exact pinned model identifier and structured-output adapter.
- Measured queue, worker, hard-timeout, and latency-budget values.
- Exact local run/test commands and any deployed URL.
- Environment-variable names and reviewer credential instructions.

## 18. Implementation sequence

Implementation follows three independently testable milestones:

1. **Synthetic Data Contracts:** Versioned fixture schemas, deterministic generator, validation, and replay.
2. **Livesell Marketplace Emulator:** Non-AI chat and listing UI, five marketplace operations, temporal state, audit receipts, and supported rollback.
3. **Reply Agent and Copilot:** Retrieval, terminal intent tools, effect broker, R2/R3 UX, diagnostic tracing, evaluation, and latency measurement.

Each milestone must have an exact run or validation command and focused tests before the next milestone begins. File names and commands will be recorded only after implementation exists.

The reviewed test-first sub-milestones and mandatory human-approved commit gates are defined in the [v1 milestone implementation plan](plans/2026-08-17-sidestage-v1-milestones.md).

## 19. Related documents

- [Product Requirements Document](PRD.md)
- [v1 milestone implementation plan](plans/2026-08-17-sidestage-v1-milestones.md)
- [AI proposal and rejection history](ai-proposal-rejection-history.md)
- [Debugging process and evidence log](debug-process.md)
