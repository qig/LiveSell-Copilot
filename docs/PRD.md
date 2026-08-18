# SideStage Product Requirements Document

> Status: `Accepted` — builder-approved v1 design; Milestone 2 and deterministic M3B.1-M3B.4 behavior are `Verified`; the M3B.5 Optimization and Debug Session extension is `Accepted` but not yet `Implemented`, and the live release gate is open
>
> Last updated: 2026-08-18
>
> Milestone 2 terminal implementation commit: `734d151`
>
> M3B runtime commit: `7d6c349`; replay/evaluation commit: `6ba208a`
>
> Final SideStage evidence commit: TBD
>
> Primary depth: Agentic outbound-reply write safety under live state changes

## 1. Product summary

SideStage is a real-time copilot for sneaker live sellers. It ingests live buyer chat, retrieves tenant-scoped catalog, listing, inventory, and policy evidence, and prepares grounded replies for seller review. It also centralizes explicit seller controls for operational actions while treating buyer chat as untrusted input.

The 48-hour prototype is a synthetic technical demonstration. It does not validate GMV lift, conversion improvement, or reduced operator workload.

The livesell emulator is intentionally narrow: it exists to create realistic chat pressure and mutable listing state for bounded agentic-reply and safety evaluation, not to reproduce a full marketplace.

Milestone 3 separates a reusable, domain-neutral **static single-step agent core** from two concrete hardcoded livesell workflows. Each core run accepts one immutable task with preassembled context, makes one model request, and returns exactly one typed terminal intent or failure. M3A also supplies immutable startup profile registration. `one_call_template` registers one `EvidenceTemplateAgent`: application code bulk-loads a bounded tenant-scoped evidence bundle, and the agent selects both the relevant evidence IDs and one approved reply template in a single call before application-owned rendering. `two_call_draft` registers two agents: `EvidencePlannerAgent` requests targeted evidence, application code retrieves it, and `ReplyDrafterAgent` produces a grounded draft intent. There is no general workflow registry or engine. An accepted Optimization and Debug Session extension will register both closed workflows and an approved model allowlist at startup, then let the debugger select a compatible workflow/model pair independently for each active show. Selection changes do not mutate prompts, schemas, tools, credentials, or agent definitions. The models have no database access, dynamic tools, memory, direct effect authority, or—on the template workflow—free-form customer-reply authority.

In this PRD, **bounded agentic reply autonomy** means that each concrete workflow reacts to candidate customer questions, binds the trusted listing, and treats every model terminal as untrusted data rather than authority. On the one-call path, the model may select a versioned template, evidence IDs from the supplied bounded snapshot, and only the minimal semantic identifier required by that template, such as a variant ID. It cannot supply price, stock, policy or evidence values, reply prose, database queries, or effect identity. The application renderer materializes an evidence-backed intent, and the independent effect broker selects the safe outcome—deny, seller review, or authorized R3 auto-reply. Application code owns database reads, tenant scope, rendering, authorization, freshness, and every side effect. Buyer chat cannot create durable memory, and no model receives direct send or marketplace mutation authority.

## 2. Target users and prototype fixtures

The planned prototype defines exactly three isolated synthetic sneaker-reseller tenants:

1. **VelocityKicks:** High-volume new sneakers with size variants. Stresses chat bursts, SKU matching, stock freshness, and latency.
2. **VaultConsign:** Rare used and consignment sneakers. Stresses condition, authenticity, seller policy, and per-item price floors.
3. **RotationKicks:** Rapid sneaker rotation with mostly single-unit stock. Stresses Push, Swap, Unlist, explicit stock adjustment, and conditional seller-action rollback without a customer-commerce workflow.

These are test fixtures, not real pilot participants.

## 3. First seller workflow

The first workflow is **high-intent question to grounded answer**:

1. A seeded synthetic replay event or tester-entered custom buyer message enters a seller's live show.
2. SideStage identifies the tenant and show; preserves the raw event, ask time, show sequence, and listing epoch visible when it was asked; and classifies its eligibility.
3. A deterministic pre-router groups exact and normalization-equivalent duplicates and removes only high-certainty noise such as emoji-only messages and allowlisted greetings. Mixed or uncertain messages pass through rather than risk losing a real question.
4. Application code resolves the trusted bound sneaker listing and constructs a deterministic allowlisted evidence plan. Exact SKU or product overrides must be unambiguous; uncertainty exits to **Needs seller** before a model request.
5. Application code retrieves a fresh, versioned bundle of relevant catalog, listing, inventory, seller-policy, and packaged research evidence. It never silently retargets a pending question after a push or swap.
6. The concrete workflow/model selection pinned when the question is accepted runs to completion. `one_call_template` constructs one immutable task from the question and complete bounded candidate evidence; its registered `EvidenceTemplateAgent` makes one call and selects evidence IDs plus exactly one approved template, `needs_seller`, or `no_response`. `two_call_draft` runs its registered `EvidencePlannerAgent`, targeted retrieval, and registered `ReplyDrafterAgent`. A later debugger switch affects only newly accepted questions and cannot mix configurations inside an in-flight trace. Application code validates every terminal and renders template text from the selected trusted evidence. Neither workflow exposes database, direct-send, or marketplace-mutation tools.
7. The effect broker treats the rendered reply request as untrusted intent and deterministically validates template eligibility, price, availability, policy, evidence support, tenant scope, freshness, canonical-question uniqueness, and R3 authority. Tone is enforced by the versioned renderer and remains a quality check rather than an authorization source.
8. The broker denies, holds the candidate for seller review, or sends it under valid R3 authorization. For review, the seller accepts, edits, or dismisses the suggestion. An unchanged AI suggestion is revalidated when accepted. If the seller edits it, SideStage sends the seller's exact version; detected factual, policy, or tone conflicts appear only as non-blocking warnings and never rewrite the text.
9. The debugger renders the eight backend stage signals emitted around these exact component calls. A failed or bypassed component marks dependent stages skipped; the frontend never invents or infers runtime success.
10. Marketplace actions remain separate, explicit seller controls and never originate from buyer chat or either model call.

## 4. Actors and authority boundaries

| Actor or source | Trust level | Permitted effect |
| --- | --- | --- |
| Authenticated seller | Trusted for its own tenant | Perform explicit Push, Swap, Unlist, Price Markdown, and Inventory Change UI actions |
| Buyer chat | Untrusted | Request information; never authorize marketplace writes or durable memory |
| Registered evidence planner | Untrusted Workflow 2 retrieval planner | Propose a typed evidence request; never choose tenant scope, establish facts, send, or mutate marketplace state |
| Registered reply drafter | Untrusted Workflow 2 reply-intent generator | Draft only from retrieved evidence; never directly send or mutate marketplace state |
| Registered evidence-template agent | Untrusted Workflow 1 evidence/template selector | Select supplied evidence IDs plus one approved template, `needs_seller`, or `no_response`; never provide factual values or reply prose, directly send, or mutate marketplace state |

The synthetic customer surface contains exactly one action: send a chat message. Purchase, bidding, auction, offer, giveaway, cancellation, and every other customer-commerce workflow are out of scope. Internal action receipts remain required for technical auditability and rollback of seller operations.

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

R3 never sends unrestricted model prose. On `one_call_template`, application code renders both R2 suggestions and R3 replies from verified typed facts using versioned seller-approved wording and tone variants. Seller edits remain exact seller-authored text. Free-form model prose exists only in the retained `two_call_draft` benchmark baseline and is not the release-path fallback.

Condition, authenticity, fit or sizing advice, research-derived product facts, offers, negotiation, discounts, markdowns, customer-specific order issues, ambiguous questions, uncertain active-SKU matches, and questions bound to a listing that is no longer active always require seller approval.

Immediately before an R3 send, SideStage rechecks the R3 authorization version plus the bound listing epoch, active SKU, price, referenced variant-stock, and applicable policy versions. If the bound listing is no longer active, SideStage suppresses the candidate and moves the question to **Needs seller** with the previous SKU. Other version mismatches prevent auto-send and move the question to **Awaiting review** with refreshed card facts.

## 6. On-demand product research

Product research is invoked automatically for a candidate customer question that requires product knowledge. The seller does not initiate a separate research workflow. SideStage retrieves from a pre-indexed, source-backed sneaker corpus packaged with the prototype. Records cover release date, SKU and colorway, MSRP, materials, sizing guidance, and approved authenticity or condition facts.

Every fact carries source, timestamp, and provenance metadata. On the one-call path, the model selects an approved research template and application code renders the candidate from the corresponding trusted record. Missing, stale, conflicting, or unrepresented evidence produces **Needs seller**. Live open-web research is out of scope so the workflow remains deterministic and compatible with the two-second latency target.

All raw messages remain observable. Reactions and high-certainty obvious noise bypass both model calls; duplicates share a canonical question; uncertain messages may reach the bounded analysis call; and ambiguous, unsupported, and adversarial questions follow explicit retrieval, guardrail, or abstention paths. No event is silently discarded.

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
- A reusable Python static agent core with immutable task input, one model request, statically registered terminal intents, deadline enforcement, and adapter-neutral traces.
- One hardcoded reply function with two explicit evaluation strategies: the retained two-call grounded-draft baseline and the one-call approved-template challenger; both reuse trusted evidence retrieval, brokering, and publication without exposing authority to a model.
- Domain-neutral scripted and live-model harness evaluation, reported separately from livesell end-to-end results.
- Grounded reply suggestions with evidence and guardrail verdicts.
- Seller accept, edit, dismiss, and send controls.
- Per-show, default-off bounded auto-reply toggle with a persistent enabled-state warning and immediate off control.
- Exactly five marketplace operation types: Push, Swap, Unlist, Price Markdown, and Inventory Change.
- Seller controls for all five operations, with Inventory Change presented as a typed stock adjustment.
- Zero available stock does not implicitly Unlist an active listing; Unlist remains a separate explicit seller action.
- Internal receipts, verification, and conditional rollback for all five seller operations.
- Eight-stage diagnostic traces sourced from the exact backend component calls, plus end-to-end latency measurement.
- A developer-only, per-show Optimization and Debug Session selector over startup-approved workflows and model profiles; the seller workspace displays the active selection read-only.
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
- Free-form stock edits outside the typed Inventory Change control.
- Purchase, checkout, cancellation, failed-payment, return, or refund workflows.
- Bids, auctions, offers, giveaways, and every other customer-commerce action.
- Automatic Unlist as a consequence of inventory reaching zero.
- A customer-facing audit workflow; auditability is an internal safety requirement.
- A general workflow object, user-authored workflow registry, DAG executor, arbitrary model entry, or runtime-extensible pipeline. The closed developer selector may resolve only startup-approved workflows and model profiles.
- A dynamic, multi-step, or runtime-extensible tool loop; model-callable reads; cross-task agent memory; a template miss that invokes hidden generation; or automatic provider/model fallback on either benchmark path.
- Treating domain-neutral agent-core evaluation as proof of SideStage grounding, livesell safety, or end-to-end latency.
- Video broadcasting, checkout, payment processing, fulfillment, and a production marketplace storefront.

## 8. Technical acceptance scorecard

| Metric | Acceptance target | Status |
| --- | --- | --- |
| Grounded-suggestion latency | p95 under 2 seconds | Gate remains open. The latest pre-commit one-call Luna diagnostic improved to 3,414.37 ms all-event workload p95 from the 4,530.28 ms two-call baseline, but still fails; eligible-question p95 is not yet reported separately and is not `Measured` |
| Static agent terminal contract | 100% of accepted tasks produce exactly one valid terminal intent or a typed core failure, with zero extra model rounds | `Verified` by the commit-bound deterministic suite; live provider results remain diagnostic |
| Static agent isolation | Zero adapter authority, credentials, effect identities, or evaluator labels enter model-visible context | `Verified` by deterministic isolation and projection tests at code head `6ba208a` |
| Agent-core latency accounting | Report queue, provider, parse, and total core p50, p95, maximum, SLO misses, and timeouts separately from the rest of the hardcoded reply path | `Verified` structurally by deterministic tests; retained live timing reports are not `Measured` |
| Runtime selection isolation | Every accepted question uses exactly one pinned workflow, model profile, and configuration version from acceptance through publication | `Accepted` for the Optimization and Debug Session; not yet `Implemented` |
| Debug comparison latency | Report first-model-backed-request cold latency, steady-state p50/p95, and combined latency separately for each selected workflow/model pair | `Accepted`; not yet `Implemented` or `Measured` |
| Raw event durability | Zero lost ingested events | `Verified` for deterministic M2 ingestion/reconnect and the committed M3B scripted suite; pre-commit live diagnostics also report zero loss |
| Answerable-question coverage | At least 95% produce supported suggestions | Committed scripted run: 72/72; latest pre-commit one-call Luna diagnostic: 66/72 (91.7%) broker-accepted grounded suggestions, improved from two-call 54/72 but below the gate. Expected-template/evidence semantic accuracy is not yet scored separately |
| Ambiguous or unsupported requests | 100% abstain or escalate | `Verified` in committed scripted cases; the latest pre-commit Luna diagnostic reports 24/24 safe |
| Tenant isolation | Zero cross-seller context leakage | `Verified` for M2 and the committed M3B deterministic suite; pre-commit live diagnostics report zero Copilot evidence leakage |
| Prompt-injection resistance | Zero unauthorized instruction adoption, guardrail bypass, cross-tenant disclosure, or write; safe refusals are allowed | `Verified` in committed scripted safety cases; the latest pre-commit Luna diagnostic reports 24/24 no-effect |
| Write safety | Zero unauthorized, below seller-configured floor, or stale-version writes | `Verified` by the committed deterministic race matrix; pre-commit live diagnostics report zero unauthorized R3 writes |
| Action auditability | 100% of executed actions produce complete receipts | `Verified` in the deterministic M2 suite at `734d151` |
| Seller-action rollback | 100% of supported rollback attempts compensate correctly or refuse safely without overwriting newer state | `Verified` in the deterministic M2 suite at `734d151` |
| Deduplication | No duplicate replies or writes from duplicate events | `Verified` in committed scripted pressure; the latest pre-commit live diagnostic groups 60/60 duplicate children |
| Trace completeness | Every eligible event has a complete stage trace | `Verified` in the committed deterministic suite; pre-commit live reports contain zero incomplete/drifted traces |
| UX interaction proxy | At most one seller decision for a reply and one form submission for a seller operation | `Verified` in committed browser tests; not a real operator-load measurement |
| Seller-edit integrity | Edited seller text is sent unchanged; detected conflicts produce traceable non-blocking warnings | `Verified` in committed R2/browser tests |
| Auto-reply kill switch | No new automatic send after disable acknowledgement | `Verified` in committed deterministic race/browser tests |
| Auto-reply freshness | Zero R3 sends against changed authorization, SKU, price, variant-stock, or policy versions | `Verified` in committed deterministic race tests |
| Agentic reply-write authorization | Zero direct, unauthorized, duplicate, ungrounded, or unreceipted model-requested sends | `Verified` in committed scripted safety tests; pre-commit live diagnostics report zero violations |
| Temporal listing attribution | Zero silent retargets and zero auto-replies for inactive bound listings | `Verified` in committed routing/race tests and scripted safety evaluation |
| Inventory adjustment safety | Seller adjustments are nonnegative, version-checked, audited, and never implicitly change listing state | `Verified` in the deterministic M2 suite at `734d151` |
| Question-state integrity | Every eligible question follows a valid transition with asked and state-change timestamps | `Verified` in committed deterministic lifecycle tests |

The UX interaction proxy is not proof of real workload reduction. AI-suggestion guardrail metrics and seller-edited warning metrics are reported separately; seller-authored overrides are not represented as AI-generated safe replies.

## 9. Degraded experience

When an eligible high-intent question cannot produce a safe suggestion, SideStage creates a **Needs seller** card with a concise reason: previous listing, missing evidence, conflicting evidence, stale inventory, guardrail failure, or timeout. It never exposes an unsafe partial draft. The seller may answer manually from the card.

A malformed, missing, multiple, unknown, or late terminal call is a typed static-agent failure. The core performs no effect and returns the failure to the hardcoded reply function, which maps it to the appropriate `needs_seller` or diagnostic outcome. A core failure never grants application code permission to infer or repair a model intent.

Noise and duplicate messages do not create failure cards; they remain observable in the raw stream and diagnostic tracer. Crossing two seconds records an SLO miss but does not discard an otherwise fresh result. Results arriving after a separate hard timeout are discarded. If the underlying listing, inventory, or policy snapshot changes during generation, SideStage may revalidate once before the hard timeout; otherwise it marks the candidate stale and requires the seller.

Eligible questions wait in a large but finite FIFO queue sized from the defined workload, measured service time, worker concurrency, and a safety margin. Queue time is included in latency measurements. Queue depth and delay are diagnostic signals rather than seller-facing failure cards.

## 10. Seller workspace

The seller experience is a minimal, elegant two-surface technical demo:

- **Live Chat:** A chronological stream of every raw buffered mock event plus custom messages entered by the demo operator.
- **Copilot Inbox:** A focused supervision and operations surface for questions that require a reply decision. Noise does not create an Inbox card. The seller sees each reply beside only the relevant current listing, inventory, and policy facts; enables or disables bounded auto-reply; reviews or edits suggestions; performs Push, Swap, Unlist, Price Markdown, and Inventory Change operations; and may Undo only the latest still-version-valid seller operation.

A compact header identifies the seller, show, active listing, and active workflow/model and contains the R3 toggle. The workflow/model badge is read-only in the seller workspace. Its persistent warning appears whenever auto-reply is enabled. The diagnostic tracer remains a separate developer view; it owns the per-show workflow and model selectors and can filter events by actual routing outcome: all, eligible, noise, duplicate, ambiguous or unsupported, and adversarial. The seller workspace excludes extra dashboards, analytics panels, and navigation that do not directly serve the technical demonstration.

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

The emulator generates synthetic chat with pseudorandom variation and records the seed on every run. A seed determines message text, synthetic usernames, inter-arrival timing, and ordering within the workload constraints, so a failure can be replayed exactly. The default pressure profile gives each seller 120 emitted chat events over 30 seconds:

- 60 irrelevant noise or reaction events, including emoji-only messages, greetings, cheers, and off-topic banter.
- 20 exact or normalization-equivalent duplicate events, including surface differences in case, punctuation, or emoji.
- 24 unique answerable questions.
- 8 distinct ambiguous or unsupported questions.
- 8 distinct prompt-injection attempts.
- One burst of 20 events within 2 seconds.

These are mutually exclusive emitted-event quotas. The 24 answerable events establish 24 distinct canonical questions. The 20 duplicate events are additional children of 20 of those questions—one child per selected parent—and do not create or consume another unique-answerable slot. The burst is a subset of the 120 events, not 20 additional events. Across three tenants, this yields 72 unique eligible answerable-question traces plus noise, ambiguity, duplication, and adversarial cases.

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

### Milestone 1 — P0 Presentation-Ready Synthetic Data

Directly author one static file containing the three seller personas, their tone and policies, catalogs, listings, variants, inventory, and product facts. Add one small prepared chat-message pool. Exit when the two static artifacts pass their approved integrity and coverage checks. Do not create a standalone Milestone 1 frontend: the approved M2.0 workspace is the single UI, and M2.1 verifies that it renders the imported M1 data correctly before marketplace behavior is treated as runtime evidence. Do not build provider, replay, or Copilot infrastructure in this milestone.

### Milestone 2 — Livesell Marketplace Emulator

Create the typed runtime and import the static seller data, first validating its exact seller, policy, catalog, inventory, prepared-chat, and custom-chat projection through the approved M2.0 workspace. Then run the livesell interaction without AI: buffered and custom chat, listing epochs, five explicit seller actions—Push, Swap, Unlist, Price Markdown, and Inventory Change—plus internal receipts and conditional rollback. Exit when the data projection, five operation types, and temporal races pass deterministic tests and the minimal marketplace UI works end to end with the copilot disabled.

Milestone 2 is `Verified` at terminal implementation commit `734d151`, following the reviewed M2.0, M2.1, debugger, and M2.2 commits. The retained closeout record contains the exact 75-test gate, runtime smoke check, commit sequence, and boundary of the evidence. It proves the synthetic non-AI marketplace and streaming environment; it does not prove agentic reply safety, the two-second reply SLO, GMV lift, conversion improvement, or operator-load reduction.

### Milestone 3A — General Static Agent Harness

Build a domain-neutral asynchronous Python agent core around one immutable task, one provider request per run, and exactly one statically registered terminal intent. Export `register_profile()` and an immutable startup `AgentProfileRegistry`. Add a scripted model, live-model adapter, bounded FIFO scheduling, deadline propagation, strict terminal-call validation, adapter-neutral tracing, deterministic generic scenarios, failure injection, and separate queue/provider/parse/total latency reporting. Exit when the core and registration API pass fixed contract and pressure tests without importing seller, listing, catalog, marketplace, or livesell fixtures. M3A evidence is labeled `evaluation_scope=agent_core` and is not presented as SideStage product evidence.

### Milestone 3B — Livesell Reply Adapter and Copilot

Implement one hardcoded `process_customer_reply()` function with two closed strategies. Preserve `two_call_draft` as the benchmark baseline. Add `one_call_template`, which performs eligibility routing, temporal listing attribution, deterministic allowlisted evidence planning and retrieval, one registered M3A template-selection call, application-owned rendering, and the same independent reply effect broker. Add R2 review, R3 auto-reply, Copilot Inbox, eight-stage backend traces, deterministic livesell generation and replay, safety evaluation, and full latency/cost reporting. For the Optimization and Debug Session, register both workflows and approved model profiles at startup, expose independent but compatibility-constrained selectors in the debugger, pin the resolved selection per accepted question, and show the active selection as a read-only marketplace badge. Benchmark selections with explicit model IDs, provider fallback disabled, identical workload inputs, recorded resolved provider metadata, and separate cold, steady-state, and combined latency. Exit only when one approved release configuration passes deterministic safety and coverage gates and measures p95 below two seconds across the unchanged end-to-end SideStage boundary.

Current state: both closed workflows defined by the M3.1-M3.4 compatibility map are committed in `7d6c349`, and replay/evaluation support is committed in `6ba208a`. The commit-bound deterministic suite passes with `288 passed, 4 deselected in 43.52s`; the fixed 360-event scripted one-call diagnostic makes 135 model requests, supports 72/72 answerable parents, and retains zero values for every recorded hard invariant. The same-model pre-commit direct-OpenAI comparison favors `one_call_template`: Luna improved from 54/72 supported answers, 14 hard timeouts, and 4,530.28 ms p95 on `two_call_draft` to 66/72, zero hard timeouts, and 3,414.37 ms p95 on the challenger. It still fails the 95% coverage and two-second latency gates. Fallback-disabled OpenRouter pressure cells also failed: DeepSeek V4 Flash resolved to Inceptron and reached 7/72 with 88 hard timeouts and 5,022.01 ms p95; Kimi K3 resolved to Together and reached 17/72 with 87 hard timeouts and 5,024.85 ms p95. GLM 5.2 did not pass the strict one-call compatibility smoke and was not promoted to pressure. Those live runs remain pre-commit `Implemented` diagnostics, not `Measured` release evidence. The Optimization and Debug Session runtime selector is `Accepted` but not yet `Implemented`. M3B.5 remains open, and M3B.6 final live evidence remains pending.

Marketplace operations belong to Milestone 2 rather than being described as an AI copilot feature: they create the mutable environment consumed only by the Milestone 3B reply path. Milestone 3A has no dependency on M1 seller/chat fixtures or M2 marketplace state.

## 15. Related documents

- [Technical Design Document](TDD.md)
- [v1 milestone implementation plan](plans/2026-08-17-sidestage-v1-milestones.md)
- [AI proposal and rejection history](ai-proposal-rejection-history.md)
- [Debugging process and evidence log](debug-process.md)
- [Milestone 2 closeout evidence](evidence/m2-closeout.md)
- [M3 pressure metrics report](evidence/m3-pressure-metrics-report.md)
