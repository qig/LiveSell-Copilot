# SideStage v1 Milestone Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
>
> Status: `Accepted`; Milestone 2 is `Verified` at `734d151`; deterministic M3B.1-M3B.4 behavior is `Verified` at `7d6c349` and `6ba208a`; the original M3B.5 is `Verified` at `39885e4`; latency/DBG-023 work is committed at `12f3bab` but awaits clean final verification, the reset/UI extension is committed at `b5823cc`, and the Auto-message/routing corrections are dirty-tree `Implemented`. The final live release gate remains open. This document does not authorize staging or commits by itself.

**Goal:** Build and verify the SideStage v1 synthetic livesell emulator, reusable static single-step agent core, and bounded reply copilot through small, testable sub-milestones, each independently reviewed and committed with a builder-approved message.

**Architecture:** A domain-neutral in-process Python `StaticAgentCore` owns one-request-per-run model invocation, immutable startup profile registration, static terminal-call validation, bounded FIFO scheduling, deadlines, and adapter-neutral tracing without importing livesell code or performing effects. One FastAPI/Uvicorn SideStage application owns the marketplace emulator, SQLite state, and one hardcoded `process_customer_reply()` function; there is no generic workflow object, user-authored registry, or engine. The function dispatches through one of two closed registered paths: one approved-template call, or an evidence-planning call followed by deterministic retrieval and one registered drafting call. M3B.5 adds a closed startup workflow/model catalog and an in-memory per-show debugger selection over immutable entries. The debugger renders signals emitted around the exact component calls rather than a separately hardcoded workflow projection.

**Tech Stack:** Python, `uv`, FastAPI, Uvicorn, Pydantic, SQLite WAL/FTS5, Server-Sent Events, static HTML/CSS/JavaScript, Pytest, HTTPX, and a small Playwright browser suite.

---

## 1. Design authority and execution order

This plan operationalizes:

- [Product Requirements Document](../PRD.md)
- [Technical Design Document](../TDD.md)
- [AI proposal and rejection history](../ai-proposal-rejection-history.md)
- [Debugging process and evidence log](../debug-process.md)

The accepted PRD and TDD define the final product and safety requirements; this plan defines implementation order and commit boundaries. Deferring a requirement to its first consumer does not remove it. A material product or safety-contract change stops the current sub-milestone and requires builder review before work continues.

```text
Design baseline
  -> Milestone 3A: General Static Agent Harness
  -> Milestone 1: P0 presentation-ready synthetic data
      -> Milestone 2.0: Marketplace UX design and interactive prototype
          -> Milestone 2.1-2.3: Authoritative Livesell Marketplace Emulator without Copilot
          -> Milestone 3B: Hardcoded Livesell Reply Copilot and Evaluation
```

M3A and M1/M2 may proceed independently after the design baseline. M3B begins only after M1, M2, and M3A have passed their respective review gates.

The first runtime gate to execute—M2.1 or M3A.1—creates the neutral `uv`/Python package scaffold. The other gate reuses or minimally extends that scaffold in its own reviewed diff. Scaffold ownership does not permit M3A to import M2 code and does not make either phase a behavioral dependency of the other.

| Milestone | Review sub-milestones | Exit condition |
| --- | ---: | --- |
| M1 — P0 Presentation Data | 2 | Three seller personas and prepared chat data validated as static artifacts |
| M2 — Marketplace Emulator | 5 | Reviewed marketplace UX, typed fixture import plus runtime import diagnosis and visual data projection, and the complete non-AI livesell UI with five authoritative operations, receipts, and supported compensation |
| M3A — General Static Agent Harness | 4 | Isolated one-request-per-run core, public immutable startup registration, strict terminal contract, deterministic harness, and separately labeled core latency evidence |
| M3B — Hardcoded Livesell Reply Copilot | 6 | Original M3.1-M3.4 livesell behavior, R2/R3 safety, per-show Optimization and Debug Session selection over closed startup registrations, end-to-end evaluation, and reviewer-ready evidence |

Marketplace operations are completed in Milestone 2. M3B reads their authoritative state but never duplicates their logic or grants the model marketplace authority. M3A imports neither marketplace implementation nor M1/M2 fixtures.

## 2. Planned repository shape

These paths are implementation targets, not claims that code already exists. A sub-milestone creates only what it needs.

```text
.gitignore
fixtures/
  sellers.json
  chat_messages.json
  agent_core/{contract_v1.json,pressure_v1.json}
pyproject.toml
uv.lock
src/sidestage/
  agent_core/{contracts,profile,model,terminal,core,scheduler,trace,evaluation}.py
  app.py
  config.py
  domain/{models,events,operations,replies}.py
  fixtures/{loader,generator,replay}.py
  storage/{database,repositories}.py
  marketplace/{authority,service}.py
  streaming/{hub,ingest}.py
  copilot/{contracts,routing,analysis,retrieval,profile,pipeline,broker}.py
  trace/{recorder,evaluator}.py
  web/static/index.html
  web/static/app.js
  web/static/styles.css
  web/static/debug.html
  web/static/debugger.js
tests/{unit,integration,e2e}/
runs/
  agent_core_regression_v1/{manifest.json,events.jsonl,oracle.json,evaluation.json}
  regression_v1/{manifest.json,events.jsonl,oracle.json}
  final_evaluation/{manifest.json,evaluation.json}
var/sidestage.sqlite3
```

Retention rules:

- Commit one compact fixed-seed regression run and the final reviewer-facing live evaluation.
- Ignore exploratory runs and `var/` runtime databases.
- Never commit credentials, environment values, or trace payloads containing secrets.
- Generated evidence is never hand-edited.

## 3. Mandatory lifecycle for every sub-milestone

Each numbered sub-milestone below is exactly one builder review and one commit boundary. If a boundary becomes too large or reveals a contract change, stop and ask the builder to approve a split; never split or combine it silently.

Milestone 1 contains only static data artifacts, while M2.0 contains the single browser interaction prototype. Their stated artifact and browser checks replace code-first runtime RED/GREEN steps. M2.1 adds typed data import and validates the M1 data projection through the existing M2.0 browser flow; M2.1-M2.3 and Milestone 3 create runtime behavior and must follow the full test-first RED/GREEN lifecycle below. No Python scaffold is created merely to make Milestone 1 or M2.0 look like a runtime milestone.

### 3.1 RED

For M2.1-M2.3 and Milestone 3:

1. Restate the included behavior, invariants, files, and focused tests.
2. Write the gate's tests before its product implementation.
3. Run the focused command and confirm failure for the intended missing behavior rather than an unrelated setup problem.
4. Retain the command and meaningful failure output for the review packet.

Expected red-test failures are normal TDD evidence. Record an entry in `docs/debug-process.md` only when implementation reveals a real material defect; deliberately injected test failures are not debugging incidents.

### 3.2 GREEN

For M2.1-M2.3 and Milestone 3:

1. Implement the smallest complete safe slice.
2. Run every focused test group until it passes.
3. Once the runtime scaffold exists, run `uv run pytest -q`; the default suite excludes tests marked `live_model`.
4. Run `git diff --check`, check untracked files for whitespace, and inspect `git status --short`.
5. Update the PRD, TDD, proposal history, or debug log only when the current work provides real evidence or changes an approved contract.

### 3.3 REVIEW

Before staging, present:

- Sub-milestone identifier and exact scope.
- All tracked and untracked files changed, plus diff/stat summary.
- RED command and intended failure for runtime gates, or the declared artifact-validation command for Milestone 1.
- GREEN, prior-regression, artifact, and applicable browser/live commands with results.
- Relevant seed, fixture digest, trace ID, receipt ID, screenshot, or generated artifact.
- Known limitations and intentionally deferred work.
- Confirmation that no adjacent sub-milestone or unrelated change is included.

### 3.4 COMMIT

1. Wait for the builder to approve the diff.
2. Ask the builder for the exact commit message.
3. Compare the requested message to the reviewed diff. If inaccurate, misleading, too broad, or materially incomplete, challenge it and propose a correction.
4. Wait for explicit approval of the final message; never silently rewrite it.
5. Stage only reviewed paths, inspect the staged diff, and commit with the exact approved text.
6. Rerun the focused gate against the committed tree and report the commit hash.
7. Never squash.

Code completion earns `Implemented`. A result becomes `Verified` only when tied to a commit, exact command, and retained evidence. Performance becomes `Measured` only when workload, seed, fixture digest, model, configuration, commit, and results are retained.

## 4. Design-baseline gate

Before M1.1, the builder reviews and separately commits `AGENTS.md`, the accepted PRD/TDD, proposal history, debug process, and this milestone plan. No implementation code belongs in that baseline commit.

**Validation**

```bash
git diff --check
! rg -n '[[:blank:]]+$' AGENTS.md docs
rg -n '^> Status: `Accepted`' docs/PRD.md docs/TDD.md
rg -n 'VelocityKicks|VaultConsign|RotationKicks' docs/PRD.md
rg -n 'push|swap|unlist|price_markdown|inventory_change' docs/TDD.md
rg -n 'Never create a commit without first asking' AGENTS.md
```

**Pass gate:** Manual cross-check confirms exactly three synthetic sellers, exactly five operation types, the R2/R3 boundary, the listed implementation sub-milestones, synthetic-only business evidence, and the human commit protocol. Presence checks alone are not treated as proof of semantic agreement.

---

# Milestone 1 — P0: Presentation-Ready Synthetic Data

**Objective for today:** Produce the smallest inspectable static artifacts that make the three seller personas and representative live-chat inputs concrete. Milestone 1 contains the two approved JSON files only. It has no frontend or application runtime; M2.0 is the single visual surface and M2.1 owns data import and projection checks.

**Explicitly deferred:** Python packages, provider calls, model schemas, domain classes, SQLite, marketplace state, show sessions, listing epochs, audit receipts, Copilot behavior, and performance claims. Each is introduced only by the later milestone that consumes it.

## M1.1 — Directly Authored Seller Information

**Files**

- Create only `fixtures/sellers.json`.

**Data boundary**

- Exactly three synthetic sneaker sellers: VelocityKicks, VaultConsign, and RotationKicks.
- Each seller contains identity, persona, tone rules, seller policies, and a product catalog.
- Each product directly nests its listing, price and floor, variants and available quantities, and factual research fields.
- The file contains no show, chat, runtime, provider, credential, trace, evaluator, or generated-state fields.
- The records are authored directly. There is no seller-data generator, loader, schema-export subsystem, or preflight script in this sub-milestone.

**Validation before review**

```bash
jq empty fixtures/sellers.json
jq -e '
  .synthetic == true and
  (.sellers | length == 3) and
  ([.sellers[] | [.seller_id, .persona]] | sort) == [
    ["sel_rotation_kicks", "rapid_rotation"],
    ["sel_vault_consign", "rare_consign"],
    ["sel_velocity_kicks", "high_volume_new"]
  ] and
  ([.sellers[].products[].product_id] as $ids | ($ids | length) == ($ids | unique | length)) and
  ([.sellers[].products[].sku | ascii_downcase] as $ids | ($ids | length) == ($ids | unique | length)) and
  ([.sellers[].products[].listing.listing_id] as $ids | ($ids | length) == ($ids | unique | length)) and
  ([.sellers[].products[].variants[].variant_id] as $ids | ($ids | length) == ($ids | unique | length)) and
  all(.sellers[];
    (.products | length) >= 3 and
    (.policies | keys | sort) == ["payment", "price_floor", "reply_rule", "returns", "shipping"] and
    all(.products[];
      (.listing.price_cents > 0) and
      (.listing.floor_price_cents > 0) and
      (.listing.price_cents >= .listing.floor_price_cents) and
      (.variants | length) >= 1 and
      all(.variants[]; .available_quantity >= 0) and
      (if .listing.status == "available" then ([.variants[].available_quantity] | add) > 0 else true end) and
      (.facts | keys | sort) == ["authenticity_status", "condition", "materials", "msrp_cents", "release_date", "sizing"] and
      all(.facts[]; . != null and . != "")
    )
  )
' fixtures/sellers.json
shasum -a 256 fixtures/sellers.json
```

**Pass gate:** The JSON is valid; the three personas are distinct; every seller has at least three products and all five policy fields; every product has one listing, at least one inventory-bearing variant, and product facts; no deferred runtime data is present.

**Review evidence:** One file, seller/product/variant counts, persona and policy summary, digest, and `git diff --check`. This is one separately reviewed commit.

## M1.2 — Prepared Chat Message Pools

**Files**

- Create only `fixtures/chat_messages.json`.

**Data boundary**

- Store short prepared message pools for answerable product questions, allowlisted greetings, literal emoji, reactions, off-topic chat, exact duplicates, ambiguous questions, and prompt-injection attempts.
- Include seller-specific questions where catalog differences matter and shared generic messages where they do not.
- Store only simple randomness controls: a fixed default seed, selection weights, and bounded timing jitter. Do not build a general workload generator in Milestone 1.
- Give every seller enough distinct non-temporal source data for the later PRD pressure profile: at least 24 canonical answerable parents, eight ambiguous/unsupported messages, and eight prompt-injection attempts. Temporal previous-listing sources are separate safety-race inputs and do not satisfy the 24 stable-answerable requirement.
- Define weight as one pool selection, before any emission expansion. An exact-duplicate pool selects one template and emits it verbatim twice as distinct adjacent events in the same seller/show/listing epoch. A normalized-pair pool selects one explicitly authored two-text pair and emits it in order; the surface strings differ while deterministic normalization is equal. Semantic paraphrases are not grouped.
- Mark temporal pools as requiring a scenario capable of changing the listing after the question is emitted but before reply processing begins; later scenario/runtime code owns that schedule.
- Custom tester text is not fixture data. Milestone 2 passes it through the same input adapter as selected prepared messages.
- `fixture_class`, scope, weight, emission mode, and scenario-capability fields are non-authoritative fixture metadata. Only the selected customer name and text cross into the runtime input adapter; metadata must never establish authority or enter retrieval/model context.

**Validation before review**

```bash
jq empty fixtures/chat_messages.json
jq --slurpfile seller_data fixtures/sellers.json -e '
  def canonical:
    ascii_downcase |
    gsub("[[:punct:]]"; "") |
    gsub("\\s+"; " ") |
    gsub("^ | $"; "");
  . as $chat |
  .schema_version == "1.0" and
  .synthetic == true and
  (.default_seed as $seed | ($seed | type) == "number" and $seed == ($seed | floor)) and
  (.selection_mode == "weighted_after_seller_and_scenario_capability_filter") and
  (.renormalize_after_filter == true) and
  (.weight_unit == "pool_selection") and
  (.default_emission_mode == "single_event") and
  (.timing_jitter_ms as $jitter |
    ($jitter.min | type) == "number" and
    ($jitter.max | type) == "number" and
    $jitter.min >= 0 and
    $jitter.max >= $jitter.min
  ) and
  (.customer_names | length) >= 6 and
  ((.customer_names | length) == (.customer_names | unique | length)) and
  ([.pools[].pool_id] as $ids | ($ids | length) == ($ids | unique | length)) and
  ([.pools[] | if has("messages") then .messages[] else .message_pairs[][] end] as $texts |
    ($texts | length) == ($texts | unique | length)
  ) and
  ([
    .pools[] as $pool |
    select($pool.fixture_class != "emoji") |
    if ($pool | has("messages"))
      then $pool.messages[]
      else $pool.message_pairs[][]
    end |
    {
      pool_id: $pool.pool_id,
      mode: ($pool.emission_mode // $chat.default_emission_mode),
      canonical: (. | canonical)
    }
  ] | group_by(.canonical) | all(.[];
    (length == 1) or
    (length == 2 and .[0].pool_id == .[1].pool_id and .[0].mode == "adjacent_normalized_pair")
  )) and
  ([.pools[].fixture_class] | unique | sort) == [
    "ambiguous",
    "answerable_listing",
    "answerable_policy",
    "answerable_research",
    "emoji",
    "greeting",
    "mixed_greeting_question",
    "off_topic",
    "prompt_injection",
    "reaction",
    "unsupported"
  ] and
  all(.pools[];
    . as $pool |
    (.emission_mode // $chat.default_emission_mode) as $mode |
    (.weight | type == "number") and
    (.weight > 0) and
    (if $mode == "adjacent_normalized_pair"
      then
        (has("messages") | not) and
        (.message_pairs | length) >= 2 and
        all(.message_pairs[];
          (type == "array") and
          (length == 2) and
          all(.[]; (type == "string") and (length > 0)) and
          (.[0] != .[1]) and
          ((.[0] | canonical) == (.[1] | canonical))
        )
      else
        (has("message_pairs") | not) and
        (.messages | length) >= 2 and
        all(.messages[]; (type == "string") and (length > 0))
    end) and
    (.seller_scope == "all" or any($seller_data[0].sellers[]; .seller_id == $pool.seller_scope))
  ) and
  all($seller_data[0].sellers[];
    .seller_id as $seller_id |
    ([$chat.pools[] | select(.seller_scope == "all" or .seller_scope == $seller_id) | .weight] | add) == 100
  ) and
  ([.pools[] | select(.emission_mode == "adjacent_duplicate_pair")] | length) == 3 and
  ([.pools[] | select(.emission_mode == "adjacent_normalized_pair")] | length) == 3 and
  all(.pools[];
    (.emission_mode // $chat.default_emission_mode) as $mode |
    ($mode == "single_event" or $mode == "adjacent_duplicate_pair" or $mode == "adjacent_normalized_pair")
  ) and
  all(.pools[] | select(.emission_mode == "adjacent_duplicate_pair");
    .fixture_class == "answerable_listing" and ((.required_scenario_capabilities // []) | length) == 0
  ) and
  all(.pools[] | select(.emission_mode == "adjacent_normalized_pair");
    .fixture_class == "answerable_listing" and ((.required_scenario_capabilities // []) | length) == 0
  ) and
  ([.pools[] | select(.required_scenario_capabilities == ["schedule_listing_change_after_ask"])] | length) == 3 and
  all(.pools[];
    all((.required_scenario_capabilities // [])[]; . == "schedule_listing_change_after_ask")
  ) and
  all($seller_data[0].sellers[];
    .seller_id as $seller_id |
    any($chat.pools[]; .seller_scope == $seller_id and .fixture_class == "answerable_listing") and
    any($chat.pools[]; .seller_scope == $seller_id and .fixture_class == "answerable_research") and
    any($chat.pools[]; .seller_scope == $seller_id and .emission_mode == "adjacent_duplicate_pair") and
    any($chat.pools[]; .seller_scope == $seller_id and .emission_mode == "adjacent_normalized_pair") and
    any($chat.pools[]; .seller_scope == $seller_id and .required_scenario_capabilities == ["schedule_listing_change_after_ask"]) and
    ([
      $chat.pools[] as $pool |
      select($pool.seller_scope == "all" or $pool.seller_scope == $seller_id) |
      select((($pool.required_scenario_capabilities // []) | length) == 0) |
      select(
        $pool.fixture_class == "answerable_listing" or
        $pool.fixture_class == "answerable_policy" or
        $pool.fixture_class == "answerable_research" or
        $pool.fixture_class == "mixed_greeting_question"
      ) |
      ($pool.emission_mode // $chat.default_emission_mode) as $mode |
      if $mode == "adjacent_normalized_pair"
        then $pool.message_pairs[][0]
        else $pool.messages[]
      end |
      canonical
    ] | unique | length) >= 24 and
    ([
      $chat.pools[] |
      select(.seller_scope == "all" or .seller_scope == $seller_id) |
      select(.fixture_class == "ambiguous" or .fixture_class == "unsupported") |
      .messages[]
    ] | unique | length) >= 8 and
    ([
      $chat.pools[] |
      select(.seller_scope == "all" or .seller_scope == $seller_id) |
      select(.fixture_class == "prompt_injection") |
      .messages[]
    ] | unique | length) >= 8
  )
' fixtures/chat_messages.json
shasum -a 256 fixtures/chat_messages.json
```

**Pass gate:** The static pool covers ordinary noise, reactions, answerable questions, exact and normalization-equivalent duplicates, ambiguity, future previous-listing races, and adversarial text; stored source strings do not collide across pools; every scope resolves to an approved seller; each seller has at least 24 distinct stable answerable candidates, eight distinct ambiguous/unsupported sources, eight distinct injection sources, listing and research coverage, both duplicate forms, and separate temporal data; base weights total 100 and are explicitly renormalized after capability filtering; randomness is bounded and seedable; no application or model code is introduced.

**Review evidence:** Pool/message counts, category summary, representative messages, digest, and `git diff --check`. This is a second separately reviewed commit.

**Milestone 1 exit evidence:** Two small static data files, their digests, artifact-validation output, and two builder-reviewed commits. The first browser screenshot and visual data-projection evidence are produced by M2.1 through the single M2.0 workspace. No provider or application scaffold is accepted as Milestone 1 evidence.

---

# Milestone 2 — Livesell Marketplace Emulator without Copilot

**Objective:** Complete the authoritative non-AI live-selling state, five marketplace operations, audit/compensation, raw chat, and minimal marketplace UI before connecting the model.

> Closeout status: `Verified` at terminal implementation commit `734d151`.
>
> Reviewed commit sequence: `e225a13` (M2.0 UI), `1f2db38` (M2.1 import), `693d86a` (debugger projection), `6d3a6e7` (M2.2 marketplace operations), and `734d151` (M2.3 streaming/server-owned UI).
>
> Commit-bound gate: the complete M2 selection passed `75 passed in 4.71s`; the full deterministic suite passed `161 passed, 2 deselected in 4.50s`. Runtime verification returned `200` for `/app/` and `/api/sellers` with all three approved personas. See [`docs/evidence/m2-closeout.md`](../evidence/m2-closeout.md).

## M2.0 — Marketplace UX Design and Interactive Prototype

**Purpose:** Lock the seller-facing information architecture, visual language, operation affordances, and debugger boundary before implementing the authoritative runtime. This is a presentation and interaction review gate, not marketplace safety, persistence, streaming, or durability evidence.

**Files**

- Create: `docs/plans/2026-08-17-m2-marketplace-ui-design.md`.
- Create: `src/sidestage/web/static/index.html`, `app.js`, `styles.css`, `debug.html`, and `debugger.js`.
- Create: `tests/e2e/verify_m2_ui.py` as a browser-prototype interaction check.
- Update: `README.md` with the exact local preview command, seller-workspace URL, debugger URL, and browser-adapter limitation.

**Design and interaction boundary**

1. Use the builder-approved minimal visual language: warm off-white canvas, square white surfaces, thin neutral rules, system typography, blue actions/selections, green live/ready state, monospaced operational labels, and restrained shadow and motion.
2. Keep two primary seller surfaces: a chronological Live Room and a Show Desk containing the active listing, relevant policy, exactly five operation controls, and a compact catalog rail. Do not turn the interface into an analytics dashboard or buyer storefront.
3. Show only relevant operational context in the shared header: seller, show, room state, active SKU, Copilot-off state, and developer-ledger navigation. Do not invent viewer, conversion, revenue, latency, or model metrics.
4. Demonstrate Push, Swap, Unlist, Price Markdown, Inventory Change, concise applied/refused feedback, and latest-operation Undo through a deterministic browser-local adapter. Use the approved fixtures; do not add customer-commerce or AI behavior.
5. Keep raw events, listing epochs, receipts, compensation relationships, and state projections on a separate read-only developer surface rather than the seller workspace.
6. Make both surfaces usable at laptop and narrow mobile widths with native controls, visible keyboard focus, state labels that do not rely on color alone, and reduced-motion support.

**Prototype limitation**

The browser adapter may persist seller-scoped demo state in `localStorage` so every interaction can be reviewed. It is disposable presentation code. It does not establish authenticated authority, tenant isolation, SQLite ordering, server versions, idempotency, concurrency safety, conditional compensation, reconnect behavior, or SSE delivery. M2.1 and M2.2 implement those contracts; M2.3 replaces the browser adapter behind the reviewed interface.

**Run and review**

```bash
python3 -m http.server 8000
# Open http://127.0.0.1:8000/src/sidestage/web/static/
# Open http://127.0.0.1:8000/src/sidestage/web/static/debug.html
node --check src/sidestage/web/static/app.js
node --check src/sidestage/web/static/debugger.js
SIDESTAGE_BASE_URL=http://127.0.0.1:8000 python3 tests/e2e/verify_m2_ui.py
git diff --check
```

The browser command expects Playwright and its browser runtime to be available in the review environment. Expected successful output ends with `M2 UI browser flow passed` and writes desktop, debugger, and mobile captures to `/tmp/sidestage-m2-ui/`.

**Pass gate:** The builder approves the reference-aligned visual direction and information architecture; all three sellers render; the browser prototype demonstrates the complete five-operation interaction vocabulary, refusal, and Undo; the developer projection correlates the visible demo events, epochs, and receipts; laptop and mobile captures are readable; syntax, browser, and whitespace checks pass; every screen labels the browser adapter and Copilot-off boundary honestly.

**Review evidence:** Design record, exact local URLs, desktop/mobile/debugger captures, complete browser-flow output, syntax and `git diff --check` results, and an explicit list of authoritative runtime guarantees deferred to M2.1-M2.3. This is one separately reviewed commit and does not satisfy the Milestone 2 exit gate by itself.

## M2.1 — Runtime Contracts, Seller-Data Import, and Visual Projection

**Files**

- Create if absent, otherwise minimally extend the neutral scaffold from M3A.1: `pyproject.toml`, `uv.lock`, `.gitignore`, `src/sidestage/__init__.py`.
- Create: `src/sidestage/config.py`, `src/sidestage/domain/models.py`, `events.py`, `operations.py`.
- Create: `src/sidestage/fixtures/loader.py`.
- Test: `tests/unit/test_domain_contracts.py`, `test_seller_import.py`.
- Extend, do not duplicate: `tests/e2e/verify_m2_ui.py` with the M1 data-projection assertions. Reuse the existing M2.0 page and fixture source; create no second frontend or browser harness.

**RED test groups**

1. Import the exact three approved sellers from `fixtures/sellers.json` into typed tenant-owned records without changing source values.
2. Reject malformed IDs, duplicate seller/product/listing/variant IDs, negative stock, price below floor, missing required policies/facts, and any cross-seller reference created during normalization.
3. Define marketplace `operation_type` as exactly Push, Swap, Unlist, Price Markdown, and Inventory Change; define all five as authenticated seller operations and chat as the only customer input.
4. Keep trusted runtime fields—show identity, accepted timestamp, sequence, epoch, actor authority, trace, idempotency, and versions—out of the static seller file and inject them only when runtime state is created.
5. Confirm no provider SDK, model call, terminal reply tool, or Copilot module is present.
6. Before any marketplace mutation in the existing browser flow:
   - Assert the seller selector contains exactly VelocityKicks, VaultConsign, and RotationKicks.
   - For each seller, compare the intentionally visible projection—persona in the selector plus product/SKU counts, prices, and listing status—with the imported M1 values. Typed import tests, not extra seller-screen chrome, validate tone, all five policies, and product facts.
   - Push one listing through the existing browser-local M2.0 interaction and compare its current price, variant quantities, and applicable price-floor policy with the imported values. This is projection evidence, not authoritative operation evidence.
   - Trigger one prepared chat item and add one tester-entered message through the shared Live Room; assert both are visible and seller-scoped.
   - Capture the initial laptop view, verify the narrow layout has no horizontal overflow, and assert the page remains explicitly Copilot-off.
   - Treat this as data-projection and presentation evidence only; the browser-local M2.0 adapter is not authoritative marketplace evidence.

**Focused command**

```bash
uv run pytest tests/unit/test_domain_contracts.py tests/unit/test_seller_import.py -q
SIDESTAGE_BASE_URL=http://127.0.0.1:8000 uv run python tests/e2e/verify_m2_ui.py
```

**Pass gate:** The minimal Python runtime imports every direct seller-data field into typed tenant-safe records, and the single approved M2.0 workspace renders its intentionally bounded seller, catalog, current price, variant-stock, applicable-policy, prepared-chat, and custom-chat projection at laptop and narrow widths. No second frontend, extra seller-screen detail, or model/provider work is included.

**Review evidence:** Imported seller/product/variant counts, one accepted import, representative rejected mutations, focused/full tests, source-data digest, initial-state browser assertions, and laptop/narrow visual captures from the existing M2.0 interface.

## M2.debugger — Typed Import Trace Bridge

**Files**

- Create: `src/sidestage/fixtures/import_trace.py`, `src/sidestage/web/server.py`.
- Extend: `src/sidestage/fixtures/loader.py`, `src/sidestage/web/static/debug.html`, `debugger.js`, and isolated `trace.css`.
- Test: `tests/unit/test_import_trace.py`, `tests/integration/test_m2_debugger_server.py`, and `tests/e2e/verify_m2_debugger.py`.

**Boundary**

This parallel M2 review slice instruments the actual M2.1 typed import with a fail-open diagnostic observer and exposes a sanitized, ephemeral four-stage trace through the local review server. It does not add marketplace authority or persistence. The existing seven-stage reply debugger is a superseded presentation fixture, not runtime reply evidence. M3B replaces it with the accepted eight-stage backend trace emitted by the hardcoded reply function. A successful M2.1 import must not be presented as reply-flow progress; until runtime replacement, every reply example remains explicitly simulated and cannot appear end-to-end green.

**Focused command**

```bash
uv run pytest tests/unit/test_import_trace.py tests/integration/test_m2_debugger_server.py -q
SIDESTAGE_EXPECT_IMPORT_RUNTIME=1 SIDESTAGE_BASE_URL=http://127.0.0.1:8000 uv run python tests/e2e/verify_m2_debugger.py
```

**Pass gate:** A valid fixture runs through the authoritative M2.1 loader and renders four passed stages, source digest, and accepted counts; unavailable or invalid input stops at the first typed stage without leaking source data or paths; the reply projection and M2 marketplace ledger remain independently usable; exact M2.1 gates pass again.

**Review evidence:** Accepted and rejected import-trace JSON, endpoint/static-server integration output, desktop/narrow debugger captures, exact M2.1 regression output, and full non-live suite output. This is a separate builder-reviewed commit boundary.

## M2.2 — Marketplace Kernel and Five Complete Seller-Operation Slices

**Files**

- Create: `src/sidestage/storage/database.py`, `repositories.py`.
- Create: `src/sidestage/marketplace/authority.py`, `service.py`.
- Test: `tests/integration/test_marketplace_kernel.py`, `test_seller_actions.py`.

**Implementation slices inside this one review boundary**

1. SQLite WAL repository, typed `MarketplacePort`, trusted seller/show authority, expected versions, idempotency, and `OperationReceipt`. State and receipt commit in one local transaction; there is no separate action-intent table.
2. Append-only listing epochs and empty active-slot state.
3. Push and Swap, including receipts and conditional compensation.
4. Unlist and Price Markdown, including receipts and conditional compensation.
5. Inventory Change as a typed active-variant stock adjustment, including receipts and conditional compensation.

No operation is exposed without its validation, version checks, idempotency, audit outcome, negative tests, and allowed compensation.

**RED test groups**

1. Authority and tenant isolation:
   - Reject missing, wrong-tenant, and payload-supplied identity.
   - Server session—not request fields—establishes seller/show/actor scope.
2. Audit ordering and failures:
   - Receipt-persistence failure causes no mutation; no durable receipt is promised when persistence itself is unavailable.
   - A validated-but-rejected request leaves state unchanged and records `status=rejected`.
   - An injected failure before or after mutation records `status=failed`.
   - Verification failure leaves no committed partial marketplace state and records the failed outcome.
   - Assert `requested_at <= executed_at <= recorded_at` where those fields exist; durations use a monotonic clock.
3. Exact-five-operation receipts:
   - Parameterize applied, rejected, failed, and compensating receipts.
   - Compensation retains the original one-of-five `operation_type` and links `compensation_for_receipt_id`; `rollback` is never an operation type.
4. Seller operations:
   - Push requires empty slot plus available/in-stock target and opens an epoch.
   - Swap requires active, different, available/in-stock target and atomically closes/opens epochs.
   - Unlist marks the active listing `unlisted`, closes its epoch, and leaves the slot empty.
   - Markdown targets the active listing, strictly lowers price, and stays at/above seller floor.
   - Inventory Change targets a variant of the active listing, sets a nonnegative absolute quantity, and never implicitly changes listing state when quantity reaches zero.
   - Every stale version, invalid precondition, cross-tenant request, and conflicting idempotency reuse rejects with zero mutation.
   - Concurrent swaps yield one success and one stale rejection.
   - Concurrent Inventory Changes against the same version yield one success and one stale rejection.
   - Conditional compensation restores empty/previous active state, prior price, or prior quantity only if no newer state would be overwritten; epoch history is appended, never reopened or erased.
   - No Clear or Relist endpoint exists.

**Focused commands**

```bash
uv run pytest tests/integration/test_marketplace_kernel.py tests/integration/test_seller_actions.py -q
```

**Pass gate:** All five seller operations are safe, tenant-scoped, temporally correct, idempotent, audited, verified, and conditionally reversible while the operation enum remains exactly five values.

**Review evidence:** Authority matrix, before/after snapshots, epoch timeline, applied/rejected/failed/compensation receipts, race result, failure-injection result, and focused/full tests.

## M2.3 — Temporal Chat Ingestion, Streaming UI, and Release Gate

> Status: `Verified` at `734d151`. Copilot remains off, so this is non-AI marketplace evidence only.

**Files**

- Create: `src/sidestage/streaming/hub.py`, `ingest.py`, `src/sidestage/app.py`.
- Extend: `src/sidestage/web/static/index.html`, `app.js`, `styles.css`, `debug.html`, and `debugger.js`; preserve the approved M2.0 presentation and interaction contracts while replacing the browser-local adapter with the authoritative HTTP/SSE runtime.
- Test: `tests/integration/test_streaming_api.py`, `tests/e2e/test_marketplace_ui.py`.

**RED test groups**

1. Input ordering and timestamps:
   - Prepared-pool and tester-entered chat use the same ingestion path.
   - The prepared-message adapter projects only the selected customer display name and raw text, plus trusted `input_origin=prepared`; the authenticated runtime session injects seller and show scope.
   - Reject or strip `pool_id`, `fixture_class`, `seller_scope`, weight, emission mode, and scenario capabilities before raw-event persistence. `seller_scope` is selection metadata and can never establish tenant authority.
   - Prove fixture metadata is absent from retrieval input, `ReplyTask`, and model-visible context. M3B.4 may read it only on the generator/evaluator side.
   - Ingestion atomically assigns trusted `accepted_at`, `show_seq`, `trace_id`, and current `source_epoch_id`.
   - Equal wall-clock timestamps immediately before/after Swap bind correctly by `show_seq`.
   - UTC timestamps serialize to milliseconds; stage durations use a monotonic clock.
2. HTTP/SSE and UI:
   - Preserve raw order, pause/resume, reconnect offset, tenant isolation, and persisted state after reconnect.
   - Replace `localStorage` as marketplace authority; reloading or opening another browser projection must converge on the same server-owned state.
   - Display Live Chat, active SKU/price/variant stock/policy, five seller controls, concise success/refusal feedback, and only the latest version-valid Undo.
   - Keep the full receipt ledger in the debugger, not the seller workspace.
   - The tester control exposes only chat; no customer-commerce control or endpoint exists.
   - Browser path: Push → custom chat → Inventory Change → Undo Inventory Change → Swap → Markdown → Undo Markdown → Unlist → Undo Unlist.
   - Assert no model or Copilot call occurs.

**Focused commands**

```bash
uv run pytest tests/integration/test_streaming_api.py -q
uv run pytest tests/e2e/test_marketplace_ui.py -q
```

**Pass gate:** The non-AI application works end to end, covers all five operation types, attributes chat across listing changes correctly, reconnects without state drift, and exposes no excluded commerce action.

**Milestone 2 exit evidence:** The deterministic browser gate covers desktop and 390 px mobile layouts, correlated events/epochs/receipts, equal-timestamp boundary attribution, stale-version and tenant refusal, zero-stock-without-Unlist, all five operation types, supported Undo, SSE/reload convergence, and zero model calls. M1 fixture/import gates and all M2 tests pass. Exact commands, results, commits, scope, and limitations are retained in [`docs/evidence/m2-closeout.md`](../evidence/m2-closeout.md).

---

# Milestone 3 — Static Agent Core and Livesell Copilot

**Objective:** First prove a domain-neutral, static single-step Python agent core and its immutable startup registration API independently of M1/M2. Then reuse that exact core in one hardcoded SideStage reply function with two explicit implemented evaluation strategies: the `two_call_draft` baseline and the `one_call_template` release challenger. Both preserve the original M3.1-M3.4 safety, supervision, and evaluation requirements without expanding marketplace authority or adding a workflow framework.

## M3.1-M3.4 compatibility contract

The M3A/M3B split changes ownership and implementation order; it does not narrow the accepted original M3.1-M3.4 behavior. The following mapping is a release gate, not historical commentary:

| Original requirement lineage | M3A owner | M3B owner | Preserved exit evidence |
| --- | --- | --- | --- |
| M3.1 — reply contracts, routing, temporal scheduling, analysis/planning, retrieval, trace spine | M3A.1 owns domain-neutral profile/task/result contracts and immutable registration; M3A.3 owns FIFO, concurrency, deadlines, and core trace events | M3B.1 owns the explicit two-workflow dispatch, `EvidencePlanningTask`/`EvidenceRequest`, `ReplyTask`, `TemplateSelectionTask`, question routing, listing-epoch binding, bulk or targeted retrieval, livesell queue policy, and eight-stage trace correlation | Safe route for every candidate; no generation for inactive-listing questions; tenant-safe bounded fresh evidence; correct FIFO/out-of-order attribution; debugger stages match the selected workflow's actual component calls |
| M3.2 — registered agents, effect broker, R2 backend, Inbox | M3A.2 owns exactly one provider request per core run and one statically registered terminal result; M3A never performs the requested effect | M3B.2 owns `register_template_workflow()` with one evidence-template agent, `register_two_call_workflow()` with separate evidence-planner and reply-drafter agents, the template catalog/renderer, broker, persistence, SSE, and seller-review UI | No unsafe draft or rendered reply can be sent; one seller decision on the normal R2 path; exact seller edits; one atomic receipt per send; a template miss becomes `Needs seller` without hidden fallback |
| M3.3 — R3 capability and revocation races | None; effect authorization is intentionally outside the core | M3B.3 owns the complete original R3 capability, allowlist, final revalidation, rendering, kill switch, and race matrix | Zero direct, unauthorized, ungrounded, stale, duplicate, or unreceipted automatic sends |
| M3.4 — developer tracer and deterministic scripted safety evaluator | M3A.4 owns adapter-neutral contract/pressure generation, failure injection, replay, core evaluation, and `evaluation_scope=agent_core` artifacts | M3B.4 owns livesell generation/replay, oracle isolation, strategy-aware eight-stage runtime debugger, paired scripted safety evaluation, and OpenRouter comparison artifacts | Replayable failures and complete traces; identical workloads across strategies; generic core results are never substituted for livesell safety/product results |

Compliance rules:

- A requirement remains open until its owning M3A and/or M3B gate passes; completing only one side of a split row does not complete the original lineage.
- M3A tests must run without importing or loading seller, catalog, listing, marketplace, or livesell modules and fixtures.
- M3B must use the same public M3A contracts, `register_profile()`/`AgentProfileRegistry`, and core implementation for all three registered agents. Workflow 1 bulk-loads bounded candidate evidence, then makes one evidence/template-selection core call. Workflow 2 makes one evidence-planner core call, performs targeted deterministic retrieval, then makes one reply-drafter core call. Neither may fork, subclass around, or duplicate the core loop to regain database tools, multiple requests within one core run, another model round after a terminal call, or effect authority.
- Strategy is fixed before a run and recorded in its manifest. A challenger template miss, unsupported/ambiguous selection, invalid terminal, or rendering failure must become `Needs seller` or `no_response`; it may not invoke the baseline.
- OpenRouter comparison cells request one explicit model, disable automatic model/provider fallback, use identical workload inputs and SLO boundaries, and record resolved provider, routing attempts, usage, and cost.
- M3A measurements use `evaluation_scope=agent_core`. Only M3B may produce `evaluation_scope=sidestage_e2e`, grounding, reply-safety, R2/R3, or two-second SideStage SLO evidence.
- The original M3.1-M3.4 pass gates and review evidence below remain mandatory after this ownership split.

## M3A.1 — Immutable core contracts, profiles, and isolation

**Files**

- Create if absent, otherwise minimally extend the neutral scaffold from M2.1: `pyproject.toml`, `uv.lock`, `.gitignore`, `src/sidestage/__init__.py`.
- Create: `src/sidestage/agent_core/__init__.py`, `contracts.py`, `profile.py`.
- Test: `tests/unit/agent_core/test_contracts.py`, `test_profile.py`, `test_isolation.py`.

**RED test groups**

1. Define immutable Pydantic `AgentProfile`, `RegisteredAgentProfile`, `AgentTask`, `AgentRunResult`, terminal schema, trace identity, and typed core-failure contracts without livesell fields.
2. Export `register_profile(profile) -> RegisteredAgentProfile`; validate and compile its schemas, canonically hash it, and expose the immutable profile digest before any task can run.
3. Export `AgentProfileRegistry(profiles)` as the startup-only registration boundary; register each supplied profile exactly once, reject duplicate identities, resolve only matching adapter/version/digest triples, and reject runtime attempts to add or replace profiles, policy, model configuration, or terminal schemas.
4. Reject unknown adapters, schema/profile-digest mismatches, invalid deadlines, oversized model input, and empty terminal sets before provider work.
5. Separate model-visible policy/input/tools from non-model-visible task, correlation, deadline, evaluator, dependency, credential, authorization, and effect metadata.
6. Import and run the suite with an import spy that fails if M1/M2, seller, listing, catalog, marketplace, livesell, or their fixture paths are touched. M3A supplies generic registration only; it must not define or register the livesell profile.

**Focused command**

```bash
uv run pytest tests/unit/agent_core/test_contracts.py tests/unit/agent_core/test_profile.py tests/unit/agent_core/test_isolation.py -q
```

**Pass gate:** `register_profile()` and `AgentProfileRegistry` form a stable public startup API; profile digests are deterministic; duplicate, unknown, invalid, or mutable configurations fail before provider work; sensitive non-model metadata cannot enter the provider projection; and the gate passes in M1/M2 isolation.

**Review evidence:** Exported registration API and schemas, two identical digest calculations, duplicate/unknown/mutation-rejection cases, immutable registry-resolution example, model-visible projection snapshot, forbidden-import report, and tests.

## M3A.2 — One-request core, provider port, and terminal validation

**Files**

- Create: `src/sidestage/agent_core/model.py`, `terminal.py`, `core.py`.
- Test: `tests/unit/agent_core/test_model_runner.py`, `test_terminal_validation.py`, `test_core_effect_isolation.py`; `tests/integration/agent_core/test_live_provider.py`.

**RED test groups**

1. Resolve every accepted task through the M3A startup registry, then submit exactly one provider request; submit zero requests for unregistered profile identity, invalid input, or pre-dispatch rejection; prohibit retry/fallback, read tools, multi-turn continuation, and model-written memory.
2. Accept exactly one allowed statically registered terminal call and decode it against its strict argument schema.
3. Fail closed with typed outcomes for free text, missing call, multiple calls, unknown tool, malformed arguments, provider error, cancellation, and hard timeout; no invalid response starts another model round.
4. Use an effect spy to prove the core returns intent data only, invokes no adapter effect, and never reports that an adapter effect executed.
5. Provide both a deterministic scripted runner and one configurable live-provider runner behind the same `ModelRunner` port; keep live tests separately marked.

**Focused commands**

```bash
uv run pytest tests/unit/agent_core/test_model_runner.py tests/unit/agent_core/test_terminal_validation.py tests/unit/agent_core/test_core_effect_isolation.py -q
uv run pytest tests/integration/agent_core/test_live_provider.py -m live_model -q
```

**Pass gate:** Every accepted scripted task resolves through one registered startup profile, causes at most one provider request, and returns one decoded allowed terminal intent or one typed no-effect failure; the live smoke test records one sanitized terminal outcome and pinned model identifier when credentials are supplied.

**Review evidence:** Provider call counts, terminal-verdict matrix, effect-spy result, sanitized live call/model identifier, and tests.

## M3A.3 — Bounded FIFO scheduling, deadlines, and core trace

> Status: `Verified` for deterministic behavior at implementation commit `f64a045` and rechecked by the full suite at code head `6ba208a`. No M3A.4 or livesell product evidence is claimed by this slice.

**Files**

- Create: `src/sidestage/agent_core/scheduler.py`, `trace.py`.
- Test: `tests/unit/agent_core/test_scheduler.py`, `test_deadlines.py`, `test_trace.py`.

**RED test groups**

1. Enforce immutable startup queue capacity and concurrency, FIFO dispatch, explicit full-queue rejection, and correct task/run attribution when provider calls complete out of order.
2. Propagate one absolute monotonic deadline through queue wait, provider work, and parsing; cancel queued/in-flight work safely and discard late provider results without returning intent.
3. Emit adapter-neutral accepted, queued, provider-started, provider-completed, terminal-validated, and completed/failed events with task, adapter, profile, run, trace, model, and scenario identifiers.
4. Report monotonic queue, provider, parse, and total durations; prove trace writes are nonblocking and that injected trace-sink failure does not change the run result.
5. Start zero provider work for invalid/full-queue tasks and expose deterministic controls for fake clocks, provider latency, cancellation, and failures.

**Focused command**

```bash
uv run pytest tests/unit/agent_core/test_scheduler.py tests/unit/agent_core/test_deadlines.py tests/unit/agent_core/test_trace.py -q
```

**Pass gate:** The scheduler is bounded and deterministic, each accepted task is attributed correctly, all deadlines fail closed, queue/provider/parse/total accounting is internally consistent, and tracing cannot block or authorize work.

**Review evidence:** FIFO/out-of-order timeline, capacity/provider-call counts, cancellation/timeout traces, latency-accounting assertions, trace-failure injection, and tests.

## M3A.4 — Domain-neutral deterministic harness and core latency evidence

> Status: `Verified` for deterministic behavior at implementation commit `8f9625b` and rechecked by the full suite at code head `6ba208a`. The earlier retained scripted artifact records a dirty working tree, so its timing is not `Measured`. Its generic synthetic timing and exploratory `gpt-5.6-luna` live timing are not SideStage end-to-end or livesell evidence.

**Files**

- Create: `fixtures/agent_core/contract_v1.json`, `pressure_v1.json`.
- Create: `src/sidestage/agent_core/evaluation.py`.
- Retain one fixed-seed scripted artifact under `runs/agent_core_regression_v1/`.
- Test: `tests/unit/agent_core/test_scenario_generator.py`; `tests/integration/agent_core/test_replay.py`, `test_evaluation.py`, `test_pressure.py`.

**RED test groups**

1. Generate bounded generic text-and-evidence tasks, static terminal schemas, scheduled concurrency, expected terminal/failure oracles, and injected provider conditions without domain identifiers or M1/M2 data.
2. Require identical profile/scenario digests, generator version, seed, fixed clock, and configuration to produce byte-identical `manifest.json`, `events.jsonl`, and `oracle.json`; reject malformed or digest-mismatched replay with seed and task ID.
3. Keep oracle labels outside runtime tasks and provider projection; record `evaluation_scope=agent_core`, profile version/digest, seed, fixed/live clock, model mode/identifier/configuration reference, sanitized live-provider base URL, queue/deadline configuration, scenario digest, implementation commit, and dirty flag without recording credentials.
4. Evaluate terminal-contract compliance, provider-call count, FIFO/backpressure/deadline behavior, complete success/early-exit traces, effect-spy results, trace overhead, and queue/provider/parse/total p50, p95, and maximum latency.
5. Run a separately marked live-model matrix. Treat the shared queue-plus-core allocation of 1,450 ms p95 as an engineering budget for the declared generic workload, not as evidence that SideStage meets its two-second end-to-end SLO.

**Focused commands**

```bash
uv run pytest tests/unit/agent_core/test_scenario_generator.py tests/integration/agent_core/test_replay.py tests/integration/agent_core/test_evaluation.py tests/integration/agent_core/test_pressure.py -q
uv run python -m sidestage.agent_core.evaluation --scenario fixtures/agent_core/pressure_v1.json --seed 20260817 --model scripted --output runs/agent_core_regression_v1
uv run python -m sidestage.agent_core.evaluation --scenario fixtures/agent_core/pressure_v1.json --seed 20260817 --model live --output runs/exploratory/agent_core_live
```

**Pass gate:** Fixed contract and pressure suites pass without M1/M2 imports or fixtures; scripted artifacts replay byte-for-byte; every accepted task has one terminal/failure outcome and complete core trace; no effect occurs; live results report the declared core metrics and budget verdict without making livesell claims.

**Review evidence:** Isolation report, fixed-seed manifest/digests, terminal/failure matrix, failure-injection replay, scripted and sanitized live latency reports, trace-overhead result, and tests.

The current exploratory Luna matrix uses `SIDESTAGE_MODEL_REASONING_EFFORT=none`, which is retained in the sanitized manifest. It returned all four expected terminal outcomes with no effects or failures. Provider p95 was about 1,065 ms; two-worker queue wait p95 was about 1,015 ms; total core p95 was about 2,057 ms and missed the 1,450 ms generic budget. This four-sample nearest-rank p95 equals the maximum and remains `Implemented` diagnostic evidence until a clean commit-bound rerun and a larger selection sample exist.

M3A completion permits M3B to consume the reviewed public core API and register one immutable livesell reply profile at SideStage startup. It does not register that domain profile itself and does not complete the hardcoded livesell analysis, retrieval, reply, broker, or debugger path.

## M3B.1 — Reply contracts, routing, temporal scheduling, retrieval, and livesell trace spine

> Status: both `two_call_draft` and `one_call_template` are committed in `7d6c349` and `Verified` for deterministic behavior by the full suite at code head `6ba208a`. The baseline registers `EvidencePlannerAgent` and `ReplyDrafterAgent`; the challenger registers only `EvidenceTemplateAgent`.

**Files**

- Create: `src/sidestage/domain/replies.py`.
- Create: `src/sidestage/copilot/contracts.py`, `routing.py`, `analysis.py`, `retrieval.py`, `pipeline.py`.
- Create: `src/sidestage/trace/recorder.py`.
- Test: `tests/unit/test_reply_contracts.py`, `tests/integration/test_copilot_routing.py`, `test_analysis.py`, `test_retrieval.py`, `test_reply_pipeline_trace.py`.

**RED test groups**

1. Reply/task boundary:
   - Define typed `EvidenceRequest`, `ReplyTask`, terminal intent shapes, abstention reasons, broker outcomes, `ReplyReceipt`, and valid question states.
   - Define immutable `TemplateSelectionTask`, closed template-selection arguments, rendered-template provenance, and a projection with no free reply-text field.
   - The analysis request may identify intent, product/variant mentions, and required fact types; it may not establish tenant scope, listing authority, evidence truth, send authority, or effect identity.
   - Project the bounded baseline `ReplyTask` or challenger `TemplateSelectionTask` into the reviewed M3A `AgentTask` without changing the core loop or public contracts.
   - Reject arbitrary prior chat, customer memory, credentials, R3 state, write identities, foreign evidence, and invalid transitions.
   - Require `asked_at` plus every `state_changed_at`; inject trusted `accepted_at` rather than reading it from fixtures/model output.
2. Routing and scheduling:
   - Event-ID replay stays indefinitely idempotent; normalization-equivalent text groups only inside a five-second seller/show/bound-listing-epoch window.
   - Semantic paraphrases are not silently suppressed in v1; they proceed as independent candidates.
   - Emoji-only and allowlisted standalone greetings bypass model work; mixed greeting/questions proceed.
   - Questions on opposite sides of Swap remain distinct.
   - Previous-listing questions show the previous SKU and never invoke a model. Application code builds the current-stage notice; Auto-message sends it and Manual review holds it.
   - The M3A FIFO dispatch preserves correct livesell attribution while delayed work completes out of order.
   - Configure both static profiles for capacity 64/show, five workers/show, fifteen global, and the propagated five-second timeout; a full queue preserves raw input and starts no registered-agent provider call. Only the baseline may already have completed its bounded analysis call. The five/fifteen setting supersedes the original four/twelve value after the recorded 72-call benchmark.
3. Retrieval and context:
   - On the baseline, make exactly one bounded analysis-model request before retrieval and validate its `EvidenceRequest`. On the challenger, make zero analysis requests and deterministically request the complete approved fact set for the trusted temporal listing.
   - Apply tenant scope before exact lookup or FTS5 matching.
   - Project each imported static product fact into a typed evidence record with a stable evidence ID, `synthetic_seller_data` provenance, source JSON pointer, current entity version, and import timestamp before indexing or retrieval.
   - Treat the static seller file as the synthetic source of truth; do not invent external citations or present it as real marketplace research.
   - Fetch fresh mutable facts for the immutable bound listing.
   - Represent missing, stale, conflicting, and wrong-SKU evidence as typed outcomes.
   - Exclude prior chat, model output, R3 state, and oracle labels from both task projections.
   - Preserve evidence source, version, timestamp, and provenance.
4. Trace spine:
   - Implement the MVP order directly in `process_customer_reply(raw_event, services)`; do not introduce a workflow object, user-authored workflow registry, stage executor, plugin mechanism, or generic DAG abstraction. M3B.5 may add only the closed selector over these two explicit branches.
   - Wrap the exact eight component calls/branches in `TraceRecorder` spans: ingest, normalize/deduplicate, deterministic route, strategy-specific evidence planning, evidence retrieval/snapshot, registered agent decision/rendering, broker/guardrails, and result.
   - Emit `started` plus exactly one `completed`, `failed`, `exited`, or `skipped` terminal observation from each stage invocation. Record downstream stages as `skipped` after the first blocking or exiting stage.
   - Correlate the registered M3A run beneath livesell stage 6 and record required component/trace/analysis/agent/profile/snapshot IDs, UTC stage timestamp, monotonic `duration_ms`, sanitized references, verdict, and reason code.
   - Add a call-order spy proving the trace order is produced by the actual function calls. The browser and fixture files may not invent runtime stages or infer success from component availability.
   - An injected trace-write failure does not block the pipeline; this test is separate from normal trace-completeness evaluation.

**Focused commands**

```bash
uv run pytest tests/unit/test_reply_contracts.py tests/integration/test_copilot_routing.py tests/integration/test_analysis.py tests/integration/test_retrieval.py tests/integration/test_reply_pipeline_trace.py -q
```

**Pass gate:** Every candidate has one safe route, no inactive-listing question reaches evidence/model work, no cross-tenant evidence leaks, every model-visible fact is bounded, fresh, and sourced, each strategy uses its declared provider-call count, and every backend debugger stage is sourced from the corresponding real call in the hardcoded function.

**Review evidence:** Schemas, deterministic pre-route table, FIFO/out-of-order traces, previous-listing case, sanitized analysis/evidence snapshots, call-order trace assertion, cross-tenant sweep, and tests.

## M3B.2 — Livesell terminal profile, effect broker, R2 backend, and Copilot Inbox

> Status: the two-call profiles, one-call evidence/template profile, deterministic bundle retrieval, versioned renderer, shared broker, persistence, and browser path are committed in `7d6c349` and `Verified` by the full deterministic suite. A template miss remains in Workflow 1 and publishes `Needs seller`.

**Files**

- Create: `src/sidestage/copilot/profile.py`, `broker.py`, `templates.py`.
- Extend: `src/sidestage/app.py` and static Inbox UI.
- Test: `tests/unit/test_livesell_profile.py`, `tests/integration/test_livesell_agent.py`, `test_reply_broker.py`, `tests/e2e/test_r2_inbox.py`.

**Internal implementation order within this one review boundary**

1. Implement `register_livesell_reply_agent(model_runner)`: construct the immutable livesell profile, pass it through M3A `register_profile()`/`AgentProfileRegistry`, bind `StaticAgentCore` to that registry, and return a handle carrying the registered profile identity/digest and `run()` entry point.
2. Implement `register_livesell_template_agent(model_runner)` with exactly the approved static template terminals and the same M3A registration/core path.
3. Register only the explicitly configured strategy during application startup and inject its handle into the hardcoded function. Missing or invalid registration fails before chat acceptance; runtime registration is forbidden.
4. Baseline: decode exactly one `request_reply_send` or `abstain`. Challenger: decode one approved template, validate semantic arguments against the snapshot, and render a versioned `RequestReplySendIntent` in application code.
5. Route both through independent broker validation and the same R2 backend transaction, SSE Inbox, and seller-review flow.

**RED test groups**

1. Model contract:
   - Retain exactly two baseline terminals. Register exactly the fifteen approved challenger terminals listed in the TDD. Neither profile has reads, direct send, marketplace tools, fallback provider, an additional round inside the core, or memory.
   - Assert the registered handle resolves the exact adapter/version/digest produced at startup and that a mismatched or absent registration starts zero provider work.
   - Parse valid baseline intent/abstention and every approved template/reason; reject free prose, factual values, evidence text/IDs, authority, and effect identity in challenger arguments.
   - Confirm M3A maps unknown tool, multiple calls, free text without terminal call, and malformed arguments to typed no-effect failures; reject authority fields and syntactically invalid evidence IDs in the livesell schema.
   - Model classification is advisory; it cannot authorize a send.
2. Broker safety:
   - Independently verify evidence-ID membership, tenant, claim span support, category, binding, price, stock, policy, freshness, canonical uniqueness, and hard tone rules.
   - Fabricated, foreign, irrelevant, partially unsupported, or stale evidence cannot yield a safe draft.
   - Model-labeled category cannot bypass broker recomputation.
   - Pure prompt injection causes no reply; a legitimate mixed question uses only trusted evidence or escalates.
3. R2 lifecycle and transaction:
   - Normal fresh path is `queued → ai_working → awaiting_review → answered_by_seller` with one seller decision.
   - Accepting an unchanged suggestion revalidates facts; a stale suggestion intentionally returns for another decision.
   - Exact seller edits and manual replies are sent byte-for-byte; factual/policy/tone conflicts produce nonblocking warnings.
   - Previous-listing manual response works without an AI draft.
   - Duplicate click cannot create a second reply.
   - Reply, `ReplyReceipt`, and terminal state commit atomically; persistence failure leaves none committed.
4. Live strategy paths:
   - A separately marked baseline smoke records its analysis plus registered-agent calls. A challenger smoke records exactly one registered template call. Both retain sanitized outcomes with the pinned requested/resolved model and perform no effect until the broker authorizes it.

**Focused commands**

```bash
uv run pytest tests/unit/test_livesell_profile.py tests/integration/test_livesell_agent.py tests/integration/test_reply_broker.py tests/e2e/test_r2_inbox.py -q
uv run pytest tests/integration/test_live_app_factory.py::test_live_app_factory_executes_the_real_two_call_r2_path -m live_model -q
```

`pyproject.toml` configures the default suite to exclude `live_model`; the explicit live command remains required review evidence.

**Pass gate:** No unsafe AI draft or server-rendered template can be sent; a template miss never invokes the baseline; the normal fresh R2 path needs one seller decision; stale unchanged suggestions require re-review; seller-authored text remains exact; every sent reply has one atomic receipt.

**Review evidence:** Registered-tool list, sanitized live call/model ID/latency, broker verdict matrix, adversarial/race traces, exact-edit warning fixture, browser capture, reply receipt, and tests.

## M3B.3 — R3 capability, broker-rendered auto-replies, and revocation races

> Status: committed in `7d6c349` and `Verified` by deterministic authorization, freshness, atomicity, and browser race tests at code head `6ba208a`.

**Files**

- Extend: `src/sidestage/copilot/broker.py`, `app.py`, Inbox UI.
- Test: `tests/integration/test_r3_safety.py`, `tests/e2e/test_r3_controls.py`.

**RED test groups**

1. Capability UI:
   - Auto-message is the default for new/reset demo shows; the seller UI never displays R2/R3 labels.
   - The persistent warning explains that fully grounded replies send and judgment cases remain for Manual review.
   - Switching to Manual review is immediate and no new automatic send occurs after acknowledgement.
2. Broker-approved rendering:
   - Auto-send every current supported single-fact reply only after deterministic scope, freshness, evidence, claim, tone, and category validation.
   - Render from verified typed records and bounded tone variants; never send unrestricted model prose.
   - Price, exact/aggregate availability, policy, listing identity, research, condition, authenticity, and sizing use the same broker/final gateway. Negotiation, markdown, order issues, ambiguity, missing/conflicting evidence, and stale state never auto-send.
   - A fully typed absent catalog size becomes one revalidated negative availability record. No workflow sends the full variant inventory to a model.
   - A pre-generation previous-listing question uses a zero-model deterministic current-stage notice; an in-flight listing change still fails closed.
3. Final races and atomicity:
   - Recheck capability version, active epoch/SKU, price, referenced stock, and policy immediately before write.
   - In-flight Swap produces `needs_seller(previous_listing)`, shows previous SKU, and exposes no draft.
   - Other price/stock/policy changes produce `awaiting_review` with refreshed facts.
   - Disable race, prompt injection, malformed/fabricated claims, grouped duplicates, hard tone violation, and transaction failure produce zero unauthorized writes.
   - One canonical question produces at most one auto-reply and one receipt.

**Focused commands**

```bash
uv run pytest tests/integration/test_r3_safety.py tests/e2e/test_r3_controls.py -q
```

**Pass gate:** The fixed agentic-write matrix records zero direct, unauthorized, ungrounded, stale, duplicate, or unreceipted automatic sends, and the kill switch is visibly testable.

**Review evidence:** Auto-message/Manual review controls, default/reset warning capture, valid automatic replies across the fact registry, unresolved holds, exact-absence and previous-listing notices, disable/Swap/version-race traces, atomic database evidence, and tests.

## M3B.4 — Developer tracer and deterministic scripted livesell safety evaluator

> Status: the persisted debugger stages are committed in `7d6c349`; fixed-seed generation/replay, scripted safety evaluation, and strategy-aware pressure evaluation are committed in `6ba208a`. Their deterministic behavior is `Verified` by the full suite. The fixed 360-event workload runs either workflow with identical seed, events, queue policy, timeout, and scorecard. The specialized ten-case R3 race evaluator remains a two-call regression suite; none of this is live-model evidence.

**Files**

- Create: `fixtures/scenarios/pressure_v1.json`, `safety_races_v1.json`.
- Create: `src/sidestage/fixtures/generator.py`, `replay.py`.
- Create: retained fixed-seed artifacts under `runs/regression_v1/`.
- Create: `src/sidestage/trace/evaluator.py`.
- Extend: `src/sidestage/web/static/debug.html`, `debugger.js` from the Milestone 2 raw-event/receipt shell.
- Test: `tests/unit/test_scenario_generator.py`, `tests/integration/test_fixture_replay.py`, `test_trace_evaluator.py`, `tests/e2e/test_debugger.py`.

**Implementation recipe**

1. Load and digest `sellers.json`, `chat_messages.json`, and `pressure_v1.json`. Resolve seed precedence as CLI, scenario, then fixture default. Sort all source records and derive an independent stable seller seed from `SHA-256("<seed>:<seller_id>")`; do not use Python `hash()`.
2. Allocate emitted-event quotas before consulting pool weights: per seller, 60 noise, 24 distinct non-temporal answerable parents, 20 duplicate children linked one-to-one to 20 of those parents, eight distinct ambiguous/unsupported messages, and eight distinct prompt injections. The 24 answerable candidates must be explicitly marked `pressure_answerable=true`, must contain no required scenario capability, and must remain answerable against the seller's designated primary active listing; broader multi-product presentation pools and temporal-race cases are outside this stable pressure denominator. Generation fails unless exactly 24 such canonical candidates exist. These quotas total exactly 120 chat events. Controls and seller operations are not chat events.
3. Count a `single_event` message or exact-duplicate source once as a canonical parent. Count an authored normalized pair once, using its first surface for the parent and second for its duplicate. Select all explicit exact and normalized candidates into the 20 duplicated parents, then select the remaining duplicate parents without replacement. Keep each child adjacent to its parent with a distinct event ID; never count either child as another unique answerable.
4. Build 100 schedulable blocks: 20 parent/child blocks, four unpaired answerable blocks, and 76 other single-event blocks. Place ten duplicate blocks—covering every authored exact and normalized form—at deterministic anchors in `[10_000, 12_000)`, producing exactly 20 burst events. Draw noncolliding 100-millisecond anchors for the remaining 90 blocks from `[0, 10_000)` and `[12_000, 30_000)`. Put each duplicate child at parent `at_ms + 1`, then sort and assign `show_seq`.
5. Write `manifest.json`, runtime-safe `events.jsonl`, and evaluator-only `oracle.json`. The workflow-neutral manifest records versions, resolved seed, fixed clock, input digests, per-seller quotas, and burst window; it does not retain a model configuration or agent-profile digest. The event stream contains no fixture class, pool, weight, scenario capability, expected route, or semantic label. The oracle stores expected buckets/routes, canonical links, and—only for answerable parents—expected answer category, evidence fact type, approved one-call template, and exact variant label where applicable. Replay regenerates and compares those labels so a rehashed semantic tamper still fails. Fail rather than pad, silently repeat an answerable, or regenerate when capacity, digest, count, or ordering checks fail.

**RED test groups**

- Generate exactly 120 chat events over 30 seconds per seller from the static seller/chat inputs: 60 noise + 24 unique answerable parents + 20 duplicate children + 8 ambiguous/unsupported + 8 injections. Assert exactly 20 emitted events in the reserved half-open two-second burst; keep seller operations outside chat denominators.
- Apply weights only within an already allocated quota when more eligible candidates exist than needed; weights never replace the fixed pressure counts. An `adjacent_duplicate_pair` selection emits one chosen text verbatim twice as distinct event IDs in the same seller/show/listing epoch. An `adjacent_normalized_pair` emits the explicitly authored surface pair in order. Both must exercise exact/normalization-equivalent canonical grouping rather than event-ID retry deduplication; semantic paraphrases remain independent.
- Select a `schedule_listing_change_after_ask` pool only when the scenario guarantees a listing change after event emission but before reply processing/model work; preserve the ask-time epoch so the question becomes previous-listing work without being retargeted.
- Require the same input digests, generator version, scenario, seed, and fixed clock to produce byte-identical events; different seeds may vary only approved identity, wording, emoji, valid SKU/variant choice, and timing jitter.
- Preserve source order in replay, reject malformed or digest-mismatched artifacts with seed/event ID, and keep evaluator-only oracle labels out of runtime events, retrieval, and model context.
- Consume `fixture_class`, scope, weight, emission mode, and scenario capabilities only inside generation/evaluation; assert none appear in the application event or any model-visible projection.
- Replace the M2 presentation fixture as the default source: fetch persisted runtime traces emitted by `process_customer_reply()` and render their authoritative eight-stage order without maintaining a frontend stage catalog.
- Display persisted raw events, selected strategy, actual route filters, expected-versus-actual oracle outcome, eight-stage drilldown, evidence plan or baseline analysis result, evidence snapshot, registered profile/agent run, template/render provenance when applicable, terminal call, broker verdict, lifecycle transitions, receipt, queue wait, and latency.
- Prove every rendered runtime stage carries the backend component identifier and observation ID from the exact function invocation. The browser must not infer a pass from fixture content, component presence, or a later stage.
- Require complete normal traces or a typed early-exit path with required IDs/timestamps.
- Keep noise, duplicate, previous-listing, capacity, and timeout outcomes inspectable.
- Prove oracle labels never enter retrieval, prompt, or model-visible trace input.
- Prove filters return only selected actual outcomes.
- Run fixed scripted cases for Manual review, a broker-approved nonlegacy category, fabricated evidence, injection, cross-tenant request, disable race, Swap race, state-version race, malformed tool call, and duplicate intent.
- Route every registered-agent decision through the reviewed M3A core and scripted `ModelRunner`; the baseline may inject its separate analysis outcome, while the challenger must make exactly one total model request. The evaluator may not bypass or reimplement the core contract or synthesize debugger success states.
- Replay the identical generated event stream through both strategies, record distinct strategy/profile digests and provider-call counts, and preserve the same routing, safety, latency, and oracle denominators.
- A deliberately injected invariant violation exits nonzero with seed and trace ID; it remains regression evidence, not a fabricated debugging incident.

**Focused commands**

```bash
uv run pytest tests/unit/test_scenario_generator.py tests/integration/test_fixture_replay.py tests/integration/test_trace_evaluator.py tests/e2e/test_debugger.py -q
uv run python -m sidestage.fixtures.generator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --output runs/regression_v1
uv run python -m sidestage.trace.evaluator --scenario fixtures/scenarios/safety_races_v1.json --seed 20260817 --model scripted --output runs/exploratory/evaluation_scripted.json
```

**Pass gate:** The explicitly labeled `evaluation_scope=sidestage_e2e`, `evaluation_mode=scripted` evaluation reports no lost raw events, cross-tenant leakage, unauthorized/duplicate R3 writes, silent listing retargeting, or debugger/runtime stage drift; every injected failure is replayable. Scripted results are never presented as final live-model product metrics.

**Review evidence:** Scripted evaluator JSON, debugger captures for success/abstention/injection/race, failing-seed replay, and tests.

## M3B.5 — Optimization and Debug Session

> Status: the deterministic workflows, live factory, OpenRouter transport, pressure evaluator, debugger-controlled runtime selector, expanded model profiles, semantic oracle v2, denominator-separated latency report, and workflow-neutral workload manifest are `Verified` through `39885e4`. The latency/DBG-023 extension is committed at `12f3bab` but awaits clean final verification; the reset/UI extension is `Implemented` but uncommitted. The final live release gate remains open pending the latter's builder-approved commit and a clean rerun.

**Purpose:** Turn the existing pressure harness and persisted debugger into a controlled optimization session. A developer can compare approved workflow and model combinations on one active synthetic seller/show without restarting the server. The selection affects the real reply pipeline—including normal R2 cards and broker-authorized R3 replies—but never grants new authority, edits runtime definitions, or changes already accepted work. The detailed boundary is recorded in the [Optimization and Debug Session design](2026-08-18-optimization-debug-session-design.md).

**Files**

- Create: `src/sidestage/copilot/templates.py`.
- Create: a bounded runtime catalog/selection module under `src/sidestage/copilot/` for immutable startup registrations and per-show session state.
- Extend: reply contracts/profile/retrieval/pipeline/broker, compatible provider routing metadata, queue/deadline instrumentation, evaluator, and golden-demo support.
- Extend: `src/sidestage/app.py`, question/trace/reply-receipt persistence, snapshot/SSE projection, `web/static/debug.html`, `debugger.js`, marketplace header markup, and styles.
- Create: `src/sidestage/marketplace/demo_reset.py` for developer-only per-show mutation admission and fixture reset.
- Test: `tests/integration/test_latency_accounting.py`, `tests/integration/test_live_app_factory.py`, a new runtime-selection integration suite, `tests/e2e/test_debugger.py`, `tests/e2e/test_golden_demo.py`, and marketplace badge coverage.
- Update implementation commands in `README.md` only after they work; do not yet claim final measured values.

**RED test groups**

1. Latency accounting:
   - R2 boundary is trusted `accepted_at` through safe Inbox/`needs_seller` SSE publication.
   - R3 boundary is trusted `accepted_at` through atomic reply commit plus chat SSE publication.
   - Queue wait is included; browser rendering and seller decision are separate.
   - Over-two-second results complete and count as SLO misses; results beyond five seconds use the typed timeout path.
   - Monotonic durations—not wall-clock subtraction—drive latency; tracing delay cannot block completion.
   - Record strategy and provider-call count. Baseline analysis and agent calls remain separate; challenger reports exactly one provider call plus deterministic render time.
2. Pressure contract:
   - Run three sellers concurrently, each with exactly 120 chat events over 30 seconds and a 20-chat/two-second burst.
   - Seller-operation control events are reported separately from chat denominators.
   - Enforce five workers/show and fifteen globally for the measured release candidate; retain 64/show capacity and the five-second hard timeout.
3. Golden demo:
   - Mixed chat/noise filtering → R2 review/edit → R3 allowed auto-reply → injection abstention → in-flight listing-change suppression → debugger inspection.
   - Add a tester-entered product-research question through custom ingestion → FTS5 → model intent → grounded R2 card; show provenance in debugger and never R3 auto-send it.
4. Benchmark metadata:
   - Require explicit strategy, seed, `--model live`, one requested OpenRouter model ID, resolved model/provider, routing attempts, fallback-disabled configuration, fixture digest, M3A profile digest, commit field, and worktree-dirty flag. The preliminary report is labeled dirty; only the post-commit M3B.6 run supports final claims.
   - Machine-readable output labels `evaluation_mode=live`; scripted and live reports cannot overwrite one another.
   - Record prompt/completion/reasoning/cache tokens and cost when OpenRouter returns them. Missing usage may be reported as unavailable; a missing resolved provider or any fallback invalidates model comparison.
   - Use identical generated events, seed, timeout, queue/concurrency configuration, and SLO denominator for every strategy/model cell. First screen with latency-sorted provider selection, then pin the provider for finalists.
5. Reviewer live factory:
   - `create_live_app()` fails before database initialization when the startup model allowlist, default selection, matching exported credentials, or any configured compatibility declaration is missing or invalid. It builds reusable strict runners for approved entries, stores no credential in application state/metadata, and closes owned HTTP clients at shutdown.
   - `create_app()` remains the credential-free deterministic injection factory and must not silently pretend to be live.
6. Approved-template release challenger:
   - Register the closed fifteen-terminal catalog defined in the TDD. The model selects a template and only its minimal semantic argument; it cannot provide reply text or factual values.
   - Application code renders versioned R2/R3 text from trusted evidence. Exact variant selection is validated against current snapshot records.
   - Unsupported, ambiguous, stale, conflicting, invalid, or unrepresented selections become `Needs seller` or `no_response`; no challenger outcome invokes the baseline.
7. Closed startup registration:
   - Register both approved workflows before chat acceptance; do not introduce a general workflow engine, plugin interface, or runtime agent mutation.
   - Load a server-side allowlist of named model profiles containing provider, exact requested model ID, reasoning setting, optional direct-OpenAI service tier, timeout, sanitized configuration reference, and supported workflows. Credentials remain server-only. Treat Luna standard/priority and reasoning variants as different immutable profile IDs; reject OpenAI service-tier configuration on OpenRouter profiles.
   - Reject duplicate public IDs, missing or mismatched credentials, unknown workflows, invalid profiles, and unsupported workflow/model pairs before database initialization.
   - Build reusable immutable runners and workflow handles without making a provider call during a debugger switch.
8. Per-show debugger selection and execution pinning:
   - Expose independent workflow/model selectors only in the authenticated debugger for one seller/show. Disable incompatible pairs in the browser and reject them again on the server.
   - A successful switch atomically increments an in-memory per-show selection version. It is session-only and resets to startup defaults after process restart or show recreation.
   - Chat acceptance pins workflow ID, model-profile ID, requested model, configuration reference, and selection version. Queued and in-flight questions finish under that immutable selection; only later accepted chat sees the switch.
   - Resolve one of the two hardcoded workflow branches from the pinned catalog entry. Missing or incompatible entries fail closed before provider work; no stage may mix selections.
   - Preserve the existing broker, R2/R3 authorization, freshness, canonical uniqueness, and receipt transaction. Debugger selection may exercise full runtime behavior but gains no additional effect authority.
9. Surfaces, attribution, and comparison metrics:
   - Show current workflow/model as a read-only badge in the seller marketplace. The debugger owns the controls and displays public catalog metadata and selection version.
   - Persist the pinned public selection identity on question execution metadata, every trace, Inbox card, reply receipt, and SSE projection. Add resolved provider/model and routing attempts when known; never persist credentials.
   - Mark the first model-backed request after each selection version as `cold`; noise and duplicate no-call paths do not consume the marker. Mark later model-backed requests `steady`.
   - Report cold samples, steady-state p50/p95/maximum, and combined p50/p95/maximum per workflow/model pair. Pressure artifacts additionally separate all-event, answerable-parent, model-backed, R2-published, and R3-committed denominators. The switch action itself is outside the reply SLO, but every accepted question retains the unchanged acceptance-to-publication boundary; answerable-parent p95 is the release gate.
   - Prove a switch event and later response cannot let an older SSE snapshot overwrite the current marketplace badge.
10. Developer reset and high-volume seller-workspace operability:
   - Require an active immutable listing epoch before either prepared or custom buyer chat can enter routing; reject an empty stage with typed `active_slot_empty` before provider work and mirror that state with disabled UI controls.
   - Add a session-authoritative **Reset demo** control that waits for admitted mutable work, restores fixture-visible seller/show state transactionally, advances internal versions, clears chat/Copilot/reply/trace/metric/action history, restores default Auto-message, restores the startup runtime selection, resets the prepared stream, and publishes one reset SSE event. It is debugger/demo tooling, not a sixth marketplace action or model effect.
   - Order open Inbox questions newest-first. Keep full cards in independently scrolling **Now** for twenty seconds; move unresolved older questions into independently scrolling compact **Earlier** rows with explicit in-place expansion. The browser timer changes presentation only.
   - Project the authoritative buyer/seller chat timeline from persisted stream order. Every R2 edit/accept/manual reply and R3 auto-reply quotes its exact source buyer message; answered questions leave the open panels and dismiss creates no timeline entry.
   - Constrain the desktop seller workspace to viewport-height chat and Inbox regions so volume does not force whole-page scrolling; preserve reader position unless already near the newest edge.

**Focused commands before review**

```bash
uv run pytest tests/integration/test_latency_accounting.py tests/e2e/test_golden_demo.py -q
uv run pytest tests/integration/test_live_app_factory.py -q
uv run pytest tests/unit/test_runtime_selection.py tests/integration/test_runtime_switching.py tests/e2e/test_debugger.py -q
uv run --env-file .env python -m sidestage.trace.evaluator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --model live --strategy one_call_template --output runs/exploratory/openrouter_candidate_one_call.json
```

**Implementation review gate:** Both workflow/model selectors expose only startup-approved compatible values; per-show switches are atomic and session-only; in-flight work remains pinned; full R2/R3 behavior retains the same broker authority; marketplace/debugger projections converge; and cold, steady-state, and combined metrics are separated without changing the release denominator. M3B.5 is `Verified` at commit `39885e4`: `uv run pytest -q` passed with `300 passed, 5 deselected in 52.29s`. This does not by itself close the M3B.6 live release gate.

**Current gate evidence:** The commit-bound suite at `39885e4` includes localhost Playwright/server checks, seller-visible convergence to the exact switched profile name/version, and a delayed seller-session regression proving old-show controls are inert until the new snapshot arrives. It covers Luna standard `none`, Luna standard `low`, Luna priority `none`, Gemini 3.7 Flash `low`, and Gemini 3.5 Flash-Lite `minimal`; transport tests distinguish direct-OpenAI `service_tier` from OpenRouter reasoning. The v2 workload retains explicit semantic contracts and separate all-event, answerable-parent, model-backed, R2, and R3 latency denominators. Commit `12f3bab` contains the follow-up closed scope gates and DBG-023 resolver: exactly 72 answerable parents enter `one_call_template`, model projection omits non-semantic authority/provenance metadata, typed Python resolution maps natural-language sizes to one trusted bound-listing variant for both workflows, exact availability projects one record, general availability projects one aggregate rather than the full variant array, and scheduler limits are five/show and fifteen/global. Commit `b5823cc` adds the seller-workspace reset/operability extension: empty-stage chat fails before provider work, reset is exclusive and transactional, and open questions/timeline entries use the approved viewport-bounded presentation. The first clean run then found DBG-025/DBG-026. Their dirty-tree fixes pass the full suite on both the reused and clean interpreters with `357 passed, 5 deselected`, but are not commit-bound final evidence. The later dirty-tree Auto-message/routing correction makes automatic mode the default, broadens it only after the same one-fact broker validation, adds revalidated exact-size absence, bounds text grouping to five seconds, and adds the zero-model previous-listing notice. The same pass exposes only **Auto-message** and **Manual review** in the seller UI. A subsequent full-suite failure exposed a Python 3.9 SSE condition-lock race; the event-based wakeup correction and a same-show fan-out regression now pass the complete dirty-tree suite with `368 passed, 5 deselected` on both Python 3.9 and Python 3.13/FastAPI 0.141.1. These corrections are `Implemented`, not commit-bound `Verified`. A live same-show diagnostic passed one-call colloquial size resolution through all eight stages, switched to the two-call branch, and observed quoted manual and automatic replies, but did not run the fixed pressure workload and is not `Measured`. The earlier exploratory artifact `runs/exploratory/openrouter_gemini_3_5_flash_lite_minimal_evidence_variant_c5_one_call_v2.json` passed with 72/72 semantic correctness, 14/14 exact variants, all hard invariants zero, zero SLO misses/timeouts, 976.73 ms queue p95, and 1,848.92 ms answerable-parent p95. Because the artifact predates `12f3bab` and identifies `39885e4`, it remains diagnostic only.

**Mandatory post-commit run:** The full deterministic suite must be rerun from a clean worktree after the DBG-025/DBG-026 fix commit before M3B.6 changes status. Live pressure must then be rerun against that same passing committed configuration; write final raw evidence beneath `runs/final_evaluation/` with its implementation commit hash. Do not edit or commit the final evidence until M3B.6 review.

**Review evidence:** [M3 pressure metrics report](../evidence/m3-pressure-metrics-report.md), preliminary live artifacts with explicit mode/model, stage breakdown, queue/worker statistics, golden-demo capture including custom research, and tests.

## M3B.6 — Committed-tree verification, evidence, and submission handoff

> Status: M3B.5 is `Verified` at `39885e4`; latency/DBG-023 is committed at `12f3bab`, and reset/UI is committed at `b5823cc`. The first clean run from `b5823cc` exposed the FastAPI lifecycle compatibility defect DBG-025 and interpreter-dependent scripted saturation defect DBG-026, so M3B.6 correctly returned to a separate implementation sub-milestone. The later builder-approved Auto-message/routing correction and DBG-028 SSE wakeup correction are also dirty-tree `Implemented`. The combined full suites pass on the reused Python 3.9 and clean Python 3.13/FastAPI 0.141.1 environments (`368 passed, 5 deselected` each), but final evidence remains blocked until the fixes receive a builder-approved commit and the resulting clean committed tree is rerun. The older Gemini Flash-Lite diagnostic predates `12f3bab` and cannot close the gate.

**Files**

- Retain: `runs/final_evaluation/manifest.json`, `evaluation.json`, and approved small supporting artifacts.
- Update: `README.md`, `docs/PRD.md`, `docs/TDD.md`, `docs/debug-process.md`, and submission/access notes.
- Do not change product behavior in this evidence-only sub-milestone.

**Verification sequence against the final committed implementation tree**

```bash
uv sync --group dev
uv run playwright install chromium
uv run pytest -q
uv run uvicorn sidestage.app:create_live_app --factory --host 127.0.0.1 --port 8000
uv run python -m sidestage.trace.evaluator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --model live --strategy one_call_template --output runs/final_evaluation/evaluation.json
```

Run the server and evaluator in separate terminals. Record the exact final commands that actually work; do not preserve a planned command if implementation differs.

**Final live-model scorecard gates**

- At least 95% of answerable fixtures produce a broker-accepted, semantically correct suggestion: expected category and evidence fact type, expected exact variant where applicable, and expected approved template on the one-call path.
- 100% of ambiguous/unsupported fixtures abstain or escalate.
- Zero cross-tenant leakage.
- Zero direct, unauthorized, stale, duplicate, or unreceipted R3 sends.
- Zero raw-event loss and zero silent previous-listing retargeting.
- Complete eligible traces or typed early exits.
- Real-model answerable-parent p95 below two seconds at the approved acceptance-to-publication backend boundary; all-event, model-backed, R2-published, and R3-committed distributions remain separately visible.
- Report p50, p95, maximum, SLO misses, hard timeouts, queue depth, and queue wait.

**Pass gate:** Evidence identifies `evaluation_scope=sidestage_e2e`, `evaluation_mode=live`, pinned model, seed, fixture digest, M3A profile digest, configuration, and final implementation commit. Clean run/test/evaluation commands succeed. Documentation reports only observed results and keeps GMV/operator-load explicitly unmeasured.

If verification finds a behavior defect, do not hide a code fix inside M3B.6. Return to a separately reviewed implementation sub-milestone, obtain an approved commit message, then rerun verification on the new commit.

**Milestone 3 exit evidence:** Final evaluation/benchmark JSON, retained manifest, model ID, implementation commit, representative trace/receipt IDs, golden-demo capture, exact reviewer commands, access instructions, and accurate AI/reuse/debug disclosures.

---

## 5. Planned command contract

These interfaces become submission claims only after M3B.6 verifies them from a clean setup.

```bash
# Install
uv sync --group dev
uv run playwright install chromium

# Run end to end
uv run uvicorn sidestage.app:create_live_app --factory --host 127.0.0.1 --port 8000

# Run deterministic tests; live_model is excluded by pytest configuration
uv run pytest -q

# Run the isolated scripted M3A contract/pressure harness
uv run python -m sidestage.agent_core.evaluation --scenario fixtures/agent_core/pressure_v1.json --seed 20260817 --model scripted --output runs/agent_core_regression_v1

# Run scripted safety evaluation
uv run python -m sidestage.trace.evaluator --scenario fixtures/scenarios/safety_races_v1.json --seed 20260817 --model scripted --output runs/exploratory/evaluation_scripted.json

# Run final live pressure evaluation
uv run python -m sidestage.trace.evaluator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --model live --strategy one_call_template --output runs/final_evaluation/evaluation.json
```

## 6. Scope-stop rules

Stop and request builder direction rather than adding:

- A third-party marketplace dependency.
- Bidding, auctions, offers, giveaways, cancellation, returns, refunds, or payment workflows.
- A sixth marketplace operation type.
- Customer-independent manual inventory editing.
- AI-recommended or AI-triggered marketplace mutations.
- Seller-invoked research.
- Model-visible read tools, durable buyer memory, more than one request within a core run, a third workflow-level model round beyond approved analysis plus registered reply agent, or hot-path provider fallback.
- An AI draft or automatic reply for an inactive bound listing.
- Distributed reply-send reconciliation for the in-process emulator.
- Business-impact claims from synthetic evaluation.

If excluded behavior appears necessary to pass a gate, stop for a PRD/TDD decision; do not expand scope silently.

## 7. Reviewer order

1. PRD and TDD.
2. This milestone plan and unsquashed commit history.
3. Exact run/test/evaluation commands.
4. M1 seller/chat data and minimal read-only presentation.
5. M2 emulator, temporal state, five operation receipts, and compensation.
6. M3 model boundary, R2/R3 races, debugger, and final live evaluation.
7. Debug log, AI proposal/rejection history, and submission disclosure.

The build is complete only when source, commands, retained artifacts, documentation claims, and reviewed commits agree.
