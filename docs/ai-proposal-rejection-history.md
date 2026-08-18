# AI Proposal and Rejection History

> Status: Active, append-only decision record
>
> Last updated: 2026-08-17

This document records material proposals made or developed with AI that the builder rejected, narrowed, or superseded. It distinguishes explicit builder decisions from AI comparative recommendations and AI self-corrections. Rejection is not treated as failure: the purpose is to preserve judgment, alternatives, and authorship for implementation and interview review.

## Recording rules

Each entry must identify the proposal, disposition, reason, chosen alternative, and resulting implication. Distinguish an explicit builder rejection from an AI self-correction or a consequence of another decision.

## History

### APR-001 — Depend on a third-party live-selling simulator

- **Disposition:** Considered, then superseded by the builder's emulator decision.
- **Decision source:** The builder conditionally considered a third-party option if a suitable one existed, then selected an in-house emulator.
- **Reason:** No accessible option reliably covered live chat plus marketplace listing and inventory actions. The builder also needed prepared bursts, manual adversarial chat, and isolated inventory per seller.
- **Chosen alternative:** Build an in-repository Whatnot-like emulator with prepared bursts, manual adversarial chat, isolated seller inventories, and failure injection.
- **Implication:** The prototype validates SideStage behavior against a controlled adapter rather than claiming a production marketplace integration.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-002 — Use up to five synthetic seller fixtures

- **Disposition:** Narrowed.
- **Decision source:** Explicit builder decision.
- **Reason:** Exactly three differentiated tenants are sufficient to exercise multitenancy and workflow variance within the build window.
- **Chosen alternative:** VelocityKicks, VaultConsign, and RotationKicks. The third fixture was later narrowed from auction-first behavior to rapid Buy-It-Now rotation; see APR-022.
- **Implication:** Test depth per tenant takes priority over fixture count.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-003 — Apply business-outcome thresholds to the synthetic prototype evaluation

- **Disposition:** Explicitly rejected.
- **Decision source:** Builder clarification after an AI-proposed success-metric contract.
- **Reason:** Synthetic traffic can demonstrate technical behavior but cannot establish real business impact.
- **Chosen alternative:** Report latency, durability, grounding, abstention, isolation, injection resistance, write safety, auditability, compensation, deduplication, and trace completeness. Leave GMV and operator load as future real-pilot hypotheses.
- **Implication:** Submission language must clearly separate measured technical results from unvalidated business outcomes.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-004 — Use DeepSeek Harness as the application runtime

- **Disposition:** Evaluated and declined on AI comparative recommendation.
- **Decision source:** AI recommendation during the builder-requested Pi versus DeepSeek Harness comparison; not a literal builder rejection.
- **Reason:** Developer-preview instability and a large coding-agent/plugin integration surface did not fit a bounded 48-hour live-commerce workflow.
- **Chosen alternative at the time:** Evaluate Pi agent-core as a smaller embedded runtime.
- **Implication:** Useful guarded-tool and event-log concepts may be borrowed without adopting the runtime.
- **Evidence:** Framework-design conversation, 2026-08-17.

### APR-005 — Use Pi agent-core as the embedded application runtime

- **Disposition:** Superseded after comparison with an in-house Python pipeline.
- **Decision source:** AI self-correction after the builder requested a direct Pi-versus-Python comparison.
- **Reason:** SideStage has a fixed, one-model-call reply path and still requires application-owned tenant isolation, policy, tracing, audit, and compensation. Pi would add framework and TypeScript/Node integration surface without removing the domain work.
- **Chosen alternative:** Current direction is a bounded asynchronous Python state machine with replaceable model and research adapters.
- **Implication:** Harness engineering remains necessary, but a general agent framework is not part of the authorization boundary.
- **Evidence:** Framework-design conversation, 2026-08-17.

### APR-006 — Have the AI recommend marketplace actions

- **Disposition:** Explicitly rejected.
- **Decision source:** Explicit builder decision.
- **Reason:** The challenge requires operational actions to be supported; it does not require the AI to decide when sellers should take them.
- **Chosen alternative:** Authenticated sellers use the defined UI controls, while a validated synthetic customer purchase applies the defined Inventory Change. Cancellation was later removed explicitly; see APR-021.
- **Implication:** Buyer chat and the model have no independent marketplace write authority.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-007 — Maintain a marketplace-action automation ladder

- **Disposition:** Superseded.
- **Decision source:** Consequence of the builder's rejection of AI-recommended marketplace actions.
- **Reason:** An A0–A3 ladder invented autonomous action behavior outside the first seller workflow.
- **Chosen alternative:** Use an authority matrix for marketplace actions. Keep the copilot-to-automation ladder for replies.
- **Implication:** Action safety is evaluated by actor, authority, validation, audit, and compensation rather than increasing AI autonomy.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-008 — Demonstrate a preauthorized autonomous markdown

- **Disposition:** Consequentially superseded when the action ladder was removed.
- **Decision source:** Derived consequence rather than a standalone literal builder rejection.
- **Reason:** The action-authority decision removed independent AI mutations from the prototype.
- **Chosen alternative:** Explicit seller-triggered UI actions with deterministic guardrails, verification, audit, and conditional compensation.
- **Implication:** The planned prototype contains no independently initiated AI marketplace mutation.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-009 — Support natural-language seller action commands

- **Disposition:** Explicitly rejected.
- **Decision source:** Explicit builder decision.
- **Reason:** Parsing commands such as “mark this down to $190” is an additional feature and does not itself guarantee deeper agentic-write safety.
- **Chosen alternative:** Button and form controls with typed parameters.
- **Implication:** Operational action tests can focus on authority, concurrency, correctness, and recovery rather than language ambiguity.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-010 — Declare agentic-write safety as the primary depth area

- **Disposition:** Explicitly superseded.
- **Decision source:** AI challenge followed by explicit builder approval.
- **Reason:** Once model-proposed and model-initiated marketplace writes were removed, that claim would be difficult to defend.
- **Chosen alternative:** Streaming ingestion and grounded reply safety under live pressure.
- **Implication:** Streaming, ordering, deduplication, backpressure, tenant-scoped evidence, adversarial chat, traceability, and latency receive the deepest implementation and evaluation treatment.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-011 — Add a seller-facing research drawer

- **Disposition:** Explicitly rejected.
- **Decision source:** Explicit builder decision.
- **Reason:** Product research should be invoked by customer questions rather than requiring a separate seller workflow.
- **Chosen alternative:** A qualifying customer question automatically triggers tenant-scoped retrieval, and the result feeds the grounded reply candidate shown to the seller.
- **Implication:** There is no seller-invoked research drawer or freeform research UI in the prototype.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-012 — Revalidate and block unsafe seller-edited replies

- **Disposition:** Explicitly rejected.
- **Decision source:** Explicit builder decision followed by clarification.
- **Reason:** Once the seller edits a suggestion, the seller's version should remain authoritative and must not be replaced or blocked by the copilot.
- **Chosen alternative:** Send the seller's exact edited text. SideStage may display and trace detected conflicts as non-blocking warnings, but it never rewrites the message.
- **Implication:** Guarded AI-suggestion metrics and seller-authored override warnings are reported separately.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-013 — Exclude automatic replies from the prototype

- **Disposition:** Explicitly superseded.
- **Decision source:** AI proposal followed by explicit builder correction and clarification.
- **Reason:** The builder wants the prototype to demonstrate bounded reply automation while preserving seller awareness and control.
- **Chosen alternative:** Implement R3 as default-off, explicit seller opt-in auto-reply with a persistent warning and an immediate off control.
- **Implication:** Automatic reply authorization is versioned, revocable, audited, and strictly separate from marketplace-action authority.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-014 — Semantically prioritize eligible questions during bursts

- **Disposition:** Explicitly rejected.
- **Decision source:** Explicit builder decision after clarifying the effect of prioritization.
- **Reason:** The builder chose predictable arrival-order processing rather than ranking customer questions by inferred transactional importance.
- **Chosen alternative:** Use a per-show FIFO queue for eligible questions. Duplicate volume does not change queue position.
- **Implication:** Streaming pressure tests focus on bounded concurrency, queue wait, latency distribution, hard-timeout behavior, and fairness without a semantic ranking policy.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-015 — Treat two seconds as a hard per-request deadline

- **Disposition:** Explicitly corrected and superseded.
- **Decision source:** Builder challenge followed by clarification and approval.
- **Reason:** The accepted latency requirement is a p95 objective, so requests exceeding two seconds are SLO misses rather than automatic failures. A seller-facing overload card would not resolve processing capacity.
- **Chosen alternative:** Use a volume-sized, large but finite FIFO queue; include queue time in latency; let fresh over-two-second results complete; and determine a separate hard timeout through benchmarking.
- **Implication:** The tracer reports queue delay and the full latency distribution, while the seller sees failure only for a true hard timeout or another safety failure.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-016 — Use three primary seller-workspace panels

- **Disposition:** Narrowed and superseded.
- **Decision source:** Explicit builder direction after an AI-proposed Live Chat, Copilot Inbox, and separate Active Listing layout.
- **Reason:** The prototype should be a minimal, elegant technical demo without a distracting operations dashboard.
- **Chosen alternative:** Use Live Chat plus a Copilot Inbox that combines grounding supervision, R3 state, listing controls, and customer-driven inventory events. Keep detailed tracing in a separate developer view.
- **Implication:** Active-listing context appears compactly in the shared header and inbox rather than occupying a third primary panel.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-017 — Show grounding states and detailed source evidence on seller cards

- **Disposition:** Narrowed and superseded.
- **Decision source:** Explicit builder correction after an AI-proposed three-state grounding display with source chips.
- **Reason:** Evaluation belongs on the backend and in the diagnostic tracer. Exposing evaluator detail would distract from the minimal technical-demo workflow.
- **Chosen alternative:** Show the reply beside only the relevant current listing, inventory, and applicable policy facts. Keep evidence, provenance, freshness, and evaluator verdicts in the backend trace.
- **Implication:** The seller UI contains no numeric confidence score or detailed grounding visualization.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-018 — Add a prototype data-retention policy

- **Disposition:** Rejected as unnecessary prototype scope.
- **Decision source:** Explicit builder direction.
- **Reason:** The technical demonstration and tests use synthetic mock data only.
- **Chosen alternative:** Treat buffered events, custom messages, traces, seller data, and customer actions as synthetic fixtures; make no production retention or privacy claim.
- **Implication:** Real customer data and PII are out of scope, while credentials and environment secrets remain prohibited from trace payloads.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-019 — Generate a private AI draft for a previous-listing question

- **Disposition:** Explicitly rejected.
- **Decision source:** Explicit builder decision after an AI recommendation.
- **Reason:** Once the relevant listing is no longer active, the builder wants the seller to decide whether the question still merits a response rather than spending AI work or presenting a generated answer.
- **Chosen alternative:** Show a `Needs seller` card tagged **Previous listing** with the previous SKU. Offer manual reply or dismiss, with no AI-generated draft and no automatic send.
- **Implication:** An already-inactive bound listing bypasses generation; if a listing becomes inactive during generation, final validation suppresses the candidate.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-020 — Collapse Push and Swap into one Highlight action

- **Disposition:** Explicitly rejected.
- **Decision source:** Explicit builder decision after an AI recommendation based on platform terminology research.
- **Reason:** Push and Swap are both named in the challenge, and the builder wants the prototype to demonstrate them as distinct seller operations.
- **Chosen alternative:** Define Push as selecting a SKU when the active-listing slot is empty, and Swap as replacing an existing active SKU with a different SKU because the current listing is wrong.
- **Implication:** The operations have mutually exclusive preconditions, distinct receipts, and listing-epoch effects; invalid combinations fail without mutation.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-021 — Add customer cancellation and failed-payment inventory restoration

- **Disposition:** Explicitly rejected.
- **Decision source:** Explicit builder correction of an AI-added workflow.
- **Reason:** Cancellation is outside the requested prototype scope and would introduce another business workflow rather than deepen the five required marketplace operations.
- **Chosen alternative:** Limit the operation surface to exactly Push, Swap, Unlist, Price Markdown, and Inventory Change. Audit all five, but permit conditional rollback only for the four seller operations.
- **Implication:** Synthetic customer purchases may decrement inventory atomically and idempotently, but that Inventory Change has no rollback path and the emulator contains no cancellation, failed-payment, return, or refund workflow.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-022 — Include bidding or auction buyer workflows

- **Disposition:** Explicitly rejected.
- **Decision source:** Explicit builder scope correction.
- **Reason:** The prototype customer should do only two things: type in chat and purchase. Bidding or auction state would add an unrelated commerce workflow.
- **Chosen alternative:** Use direct synthetic purchases only. Replace the auction-first third fixture with a rapid Buy-It-Now rotation fixture while preserving concurrency and listing-transition pressure.
- **Implication:** The emulator has no bid, auction, offer, or giveaway state machine. Backend write auditing remains because the challenge explicitly requires action auditability and rollback; it is not a customer action.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-023 — Keep a zero-stock SKU active as Sold out

- **Disposition:** Explicitly rejected after builder challenge.
- **Decision source:** AI recommendation followed by builder correction and approval of the replacement.
- **Reason:** With Push defined as filling an empty slot, leaving an exhausted SKU active would force an unnecessary Swap and make the operation model less coherent.
- **Chosen alternative:** A purchase of the final aggregate unit atomically applies Inventory Change and a linked Unlist, closes the listing epoch, and leaves the slot empty for the next Push. A single exhausted variant does not Unlist while another remains available.
- **Implication:** The transaction produces both audit receipts or no state change, and the purchase-derived Unlist has no rollback path because cancellation is out of scope.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-024 — Keep streaming and grounded reply safety as the primary depth claim

- **Disposition:** Superseded by later builder direction.
- **Decision source:** Builder reopened the depth-area decision after clarifying the meaning of agentic-write safety.
- **Reason:** R3 creates a narrow but real model-initiated external side effect: writing a reply to live chat. The builder wants the submission to go deep on the agent boundary while retaining streaming as the live pressure environment.
- **Chosen alternative:** Make **agentic outbound-reply write safety under live state changes** the primary depth. Give the model only terminal `request_reply_send` and `abstain` tools; mediate every requested send through an application-owned effect broker. Marketplace writes remain outside model authority.
- **Implication:** The depth claim depends on authorization, revocation, freshness, idempotency, audit-intent persistence, verification, and adversarial race testing—not on the tool name alone. APR-010 remains the record of the earlier decision point.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-025 — Give the reply model an evidence-lookup tool

- **Disposition:** Explicitly declined through approval of the mutually exclusive boundary.
- **Decision source:** Builder approval after an AI-presented comparison.
- **Reason:** Application-owned retrieval can assemble the bounded tenant-scoped snapshot in parallel without another model round or dynamic tool loop.
- **Chosen alternative:** Give the model no read tools. Application code prefetches evidence, and the model makes one terminal reply-write request or abstention.
- **Implication:** Retrieval scope, tenant isolation, and latency variance remain application-owned and deterministically testable.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-026 — Add a separate LLM classification request

- **Disposition:** Explicitly declined through approval of the hybrid one-call design.
- **Decision source:** Builder approval after clarification of whether classification uses an LLM.
- **Reason:** A second model request would add latency and variance while duplicating interpretation work already required for reply generation.
- **Chosen alternative:** Deterministically filter only high-certainty noise and duplicates, then jointly classify and draft or abstain in the single reply-agent call.
- **Implication:** Custom natural-language messages still receive semantic interpretation, while obvious noise avoids model work and uncertain messages fail open into evaluation rather than being silently dropped.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-027 — Auto-send unrestricted model prose under R3

- **Disposition:** Explicitly declined through approval of constrained rendering.
- **Decision source:** Builder approval after an AI-presented safety trade-off.
- **Reason:** Evidence mappings alone do not prevent an otherwise grounded answer from adding an unsupported promise, misleading phrasing, or a tone violation.
- **Chosen alternative:** Preserve free-form model prose for seller-reviewed R2 suggestions. For R3, have the broker render a short response from verified typed claims and bounded seller-approved tone variants.
- **Implication:** The automatic-write path can guarantee the factual and tonal surface without a second model pass.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-028 — Build a distributed reply-intent transaction and reconciliation state machine

- **Disposition:** Explicitly rejected as over-design.
- **Decision source:** Explicit builder challenge.
- **Reason:** SideStage and the synthetic chat emulator run in one application against one local state store. Modeling lost remote acknowledgements, unknown send outcomes, reconciliation, and a multi-state intent ledger would solve a production-integration problem that the prototype does not have.
- **Chosen alternative:** Use one atomic local transaction for reply, receipt, and terminal question state, protected by a unique canonical-question key. The builder approved this replacement.
- **Implication:** The prototype should prove authorization, grounding, freshness, deduplication, and auditability without pretending it has a distributed marketplace boundary.
- **Evidence:** Product-design conversation, 2026-08-17.

### APR-029 — Prebuild the provider, runtime contracts, fixture loader, and generated replay system in Milestone 1

- **Disposition:** Explicitly rejected and narrowed.
- **Decision source:** Explicit builder correction after reviewing the implementation scope.
- **Reason:** The immediate artifact only needs believable seller information and a minimal presentation. Provider probes, Python domain models, loaders, exported schemas, and generalized fixture generation had no current consumer and created unnecessary maintenance work.
- **Chosen alternative:** Author one static `fixtures/sellers.json`, follow it with one small prepared chat-pool file, and use a disposable read-only browser preview for today's presentation. Introduce marketplace/runtime code in Milestone 2 and provider/model validation in Milestone 3, when those components are actually consumed.
- **Implication:** The `Add mock seller data` commit contains only seller data. Milestone 1 cannot claim provider viability, runtime validation, or latency evidence.
- **Evidence:** Implementation-scope review conversation, 2026-08-17.

### APR-032 — Apply an industrial stage-manager aesthetic to the M2 seller workspace

- **Disposition:** Explicitly rejected and superseded.
- **Decision source:** Explicit builder correction after reviewing the implemented M2 UI.
- **Reason:** The dark control-room treatment, serif display type, decorative product art, numbered action tiles, and dense status chrome conflicted with the already accepted minimal, elegant, and clear seller-workspace direction.
- **Chosen alternative:** Use the visual language of the builder-provided Mini SideStage reference at `http://127.0.0.1:8765/`: warm off-white canvas, white square panels, black system typography, blue primary actions, green live state, monospaced uppercase metadata, thin neutral borders, and minimal decoration.
- **Implication:** Preserve the two-surface workflow and five typed operation behaviors while reducing ornamental hierarchy, visual density, and dashboard-like chrome.
- **Evidence:** Builder UI review and reference-page direction, 2026-08-17.

### APR-030 — Keep customer purchase and purchase-driven Inventory Change in v1

- **Disposition:** Explicitly superseded.
- **Decision source:** Explicit builder scope simplification.
- **Reason:** Customer purchase introduced last-unit races, a derived zero-stock Unlist, and purchase-specific rollback exceptions without deepening the primary customer-question and reply-safety workflow.
- **Chosen alternative:** Buyer chat is the only customer surface. Push, Swap, Unlist, Price Markdown, and Inventory Change are all authenticated seller controls. Inventory Change is a typed stock adjustment; reaching zero never implicitly Unlists, and all five seller operations support version-valid conditional rollback.
- **Implication:** Remove purchase controls, endpoints, events, linked zero-stock Unlist behavior, final-unit tests, and the purchase rollback exception from v1. APR-021, APR-022, and APR-023 preserve the earlier decision path but are superseded by this narrower boundary.
- **Evidence:** Product-scope simplification conversation, 2026-08-17.

### APR-031 — Keep the reply-agent harness coupled directly to livesell runtime state

- **Disposition:** Explicitly superseded and narrowed.
- **Decision source:** Explicit builder decision after reviewing M3 dependencies and comparing a single-step core with a bounded multi-step tool loop.
- **Reason:** A livesell-coupled M3 could not be implemented or evaluated until M1 and M2 were complete, which delayed evidence about provider behavior, terminal-call compliance, queueing, failure handling, tracing, and core latency. A multi-step tool loop would improve generality but add model round trips, nondeterminism, prompt-injection surface, and deadline complexity that threaten the p95-under-two-seconds requirement.
- **Chosen alternative:** Split M3 into M3A, a domain-neutral static single-step Python agent core, and M3B, a SideStage livesell reply adapter. M3A accepts an immutable adapter-prepared task, makes one model request, validates exactly one statically registered terminal intent, performs no effect, and can be tested without M1/M2. M3B owns livesell routing, retrieval, authority, brokering, persistence, UI, and end-to-end evaluation.
- **Implication:** The core is extensible across bounded single-decision workflows through static adapter contracts, not dynamic tools or multiple model rounds. M3A metrics are labeled `evaluation_scope=agent_core` and cannot support SideStage grounding, safety, or end-to-end latency claims; those require M3B against the real M1/M2 state.
- **Evidence:** M3 architecture review conversation, 2026-08-17.

### APR-033 — Maintain a separate M1.3 read-only frontend

- **Disposition:** Explicitly superseded.
- **Decision source:** Explicit builder decision after comparing the completed M1.3 preview with the approved M2.0 workspace.
- **Reason:** A standalone M1.3 page duplicated fixture loading, seller switching, catalog/policy rendering, prepared chat, custom chat, responsive layout, and visual styling already owned by M2.0. Keeping both would create unnecessary code and test maintenance while risking two conflicting UI directions.
- **Chosen alternative:** Use the M2.0 seller workspace as the single frontend. M2.1 owns typed seller-data import and extends the existing M2.0 browser flow with the former M1.3 data-projection assertions before marketplace mutations run.
- **Implication:** Delete the uncommitted `web/preview/` implementation; Milestone 1 exits after two static data commits; no third M1 commit or second browser harness exists. M2.1 produces the first visual projection evidence and reuses `tests/e2e/verify_m2_ui.py`.
- **Evidence:** Milestone-boundary review conversation, 2026-08-17.

### APR-034 — Add a general workflow object and registry for reply orchestration

- **Disposition:** Explicitly rejected as unnecessary MVP abstraction.
- **Decision source:** Explicit builder correction during reply-workflow and debugger review.
- **Reason:** SideStage has one fixed reply path. A workflow subject, registry, generic stage executor, plugin mechanism, or DAG would add configuration and drift risk without a second runtime workflow that needs the abstraction.
- **Chosen alternative:** Hardcode the approved component order in one `process_customer_reply()` function. Keep one backend stage constant and emit diagnostic spans around the exact function calls; the debugger renders those observations rather than defining its own workflow.
- **Implication:** M3B tests must prove the trace order matches actual call order. A future second workflow may reopen the abstraction, but v1 contains no runtime-extensible workflow mechanism.
- **Evidence:** Builder design decision, 2026-08-17.

### APR-035 — Keep classification and reply generation in one LLM request

- **Disposition:** Explicitly superseded; this reverses APR-026's chosen alternative.
- **Decision source:** Explicit builder correction after inspecting how the debugger claimed evidence was found.
- **Reason:** Evidence selection needs an observable analysis step that interprets the buyer question and produces a typed request before trusted retrieval. Showing a pre-agent evidence snapshot without the responsible model call made the debugger misleading.
- **Chosen alternative:** Use two bounded requests for an eligible reply: a non-effect LLM analysis call that returns an untrusted typed `EvidenceRequest`, followed by deterministic tenant-scoped retrieval and one startup-registered M3A reply-agent call. Preserve the M3A invariant of at most one provider request per core run and add no third round after the terminal call.
- **Implication:** The end-to-end latency budget includes both calls. The debugger has eight backend-sourced stages and stops at analysis, retrieval, or registered-agent dispatch when the corresponding component fails; downstream stages are skipped rather than green.
- **Evidence:** Builder design and debugger review, 2026-08-17.

### APR-036 — Persist a separate marketplace ActionIntent before executing locally

- **Disposition:** Explicitly superseded after builder challenge.
- **Decision source:** AI self-correction approved by the builder.
- **Reason:** The marketplace emulator, mutable state, and audit ledger share one local SQLite database. A separate durable intent phase would duplicate the request already retained by the receipt and introduce a second commit boundary without solving a remote unknown-outcome problem.
- **Chosen alternative:** Execute each seller action inside one SQLite transaction, read back the result, and commit the state change and its applied, rejected, or failed receipt together. Receipt-persistence failure rolls back the effect. Idempotency resolves retries, and Undo remains a new version-checked compensating operation.
- **Implication:** M2.2 has no `ActionIntent` table or transactional outbox. Revisit an explicit intent/outbox state machine only when a future marketplace adapter can succeed remotely while the local result remains unknown.
- **Evidence:** M2.2 transaction-design review conversation, 2026-08-17.

### APR-037 — Keep the sequential two-call draft path as the only M3B release path

- **Disposition:** Explicitly superseded after live latency evidence and builder review.
- **Decision source:** Builder approval of the one-call approved-template challenger on 2026-08-18.
- **Reason:** The latest valid fixed-seed Luna pressure diagnostic recorded about 1.13 seconds median analysis time and 1.08 seconds median reply-agent time before burst queueing, producing 4,530.28 ms end-to-end p95 and 14 hard timeouts. The sequential lower bound is incompatible with the accepted p95-under-two-seconds target for this workload even after correctness and schema fixes.
- **Chosen alternative:** Preserve `two_call_draft` as a benchmark baseline. Add `one_call_template`, which deterministically prefetches an allowlisted evidence snapshot, makes one registered M3A call to select a versioned server-owned template, renders customer text in application code, and reuses the same effect broker. A template miss, ambiguous/unsupported selection, invalid terminal, or rendering failure becomes `Needs seller` or `no_response`; it never silently invokes the baseline.
- **Implication:** This supersedes APR-035 as the release-path decision while preserving its implementation and evidence as the baseline. M3A remains unchanged. Paired evaluation must use identical workloads and report strategy/provider-call count; no one-call result is `Measured` until commit-bound live evidence exists.
- **Evidence:** Builder-approved redesign conversation, 2026-08-18; `DBG-018`; `runs/exploratory/evaluation_live_precommit_v4.json`.

### APR-038 — Integrate and compare each model provider through separate bespoke clients

- **Disposition:** Narrowed through explicit builder selection of OpenRouter for benchmarking.
- **Decision source:** Builder direction on 2026-08-18.
- **Reason:** Separate provider clients would add adapter variance to a latency comparison and duplicate tool-call, authentication, usage, and cost instrumentation. Automatic router fallbacks would create the opposite problem by obscuring which model/provider served a cell.
- **Chosen alternative:** Use the existing OpenAI-compatible runner through OpenRouter for cross-model screening. Request one explicit model per run, disable fallbacks, require requested parameters, enable router metadata, record requested/resolved model and provider plus usage/cost, and rerun finalists with a pinned provider. Direct OpenAI remains available as a separate diagnostic path.
- **Implication:** `OPENROUTER_API_KEY` and `OPENAI_API_KEY` remain provider-specific secrets. A fallback, missing resolved provider, strategy mismatch, or changed workload digest invalidates a comparison cell rather than being normalized into the scorecard.
- **Evidence:** Builder benchmark decision conversation, 2026-08-18; OpenRouter provider-routing, metadata, and usage-accounting documentation.

### APR-039 — Keep workflow and model selection fixed for the process lifetime

- **Disposition:** Explicitly superseded and narrowly reopened for developer evaluation.
- **Decision source:** Builder-approved Optimization and Debug Session design on 2026-08-18.
- **Reason:** Restarting the live server for every workflow/model comparison makes interactive optimization cumbersome and disconnects the selected configuration from the seller marketplace and persisted debugger traces. The debugger needs to compare approved combinations against the real R2/R3 path while preserving exact configuration attribution.
- **Chosen alternative:** Register both closed workflows and a server-side allowlist of model profiles before chat acceptance. Let the authenticated debugger independently select only compatible workflow/model pairs for one seller/show. Store the active override only in memory, pin its immutable version when each question is accepted, and let in-flight work finish under its original selection. The marketplace shows the active selection read-only. The first model-backed request after a switch is reported as cold; later requests are steady-state, and the combined distribution retains both.
- **Implication:** APR-034's rejection of a general workflow engine, user-authored registry, plugin mechanism, and dynamic agent mutation remains in force. Runtime selection resolves only prebuilt immutable handles and never edits prompts, schemas, tools, credentials, templates, or effect authority. Debug-selected runs may exercise normal R2 and broker-authorized R3 behavior, but the same freshness, uniqueness, receipt, and kill-switch checks apply. The extension is `Accepted`, not yet `Implemented` or `Measured`.
- **Evidence:** Builder design conversation, 2026-08-18.

## Entry template

```md
### APR-___ — Proposal title

- **Disposition:** Rejected | Narrowed | Superseded | Deferred
- **Decision source:** Explicit builder decision | AI comparison | AI self-correction | Derived consequence
- **Reason:**
- **Chosen alternative:**
- **Implication:**
- **Evidence:** Conversation, commit, issue, trace, or test reference
```
