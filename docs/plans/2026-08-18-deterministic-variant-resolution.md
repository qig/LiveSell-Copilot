# Deterministic Variant Resolution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve natural-language exact shoe-size questions to one trusted variant in deterministic Python, fail closed on ambiguity or absence, and keep complete per-variant inventory out of both model workflows.

**Architecture:** Add an application-owned typed parser/resolver between immutable listing binding and evidence retrieval. It parses trusted catalog labels and buyer wording into the same `(size_system, audience, size)` attributes, intersects only the bound listing's candidates, and returns an exact, ambiguous, missing, summary, or not-applicable plan. Exact plans retrieve one variant evidence record; general availability plans retrieve one compact aggregate evidence record; other plans retrieve no inventory records. Model output may select evidence or draft prose, but can neither establish nor replace variant identity.

**Tech Stack:** Python 3.12, Pydantic v2 contracts, SQLite inventory state, pytest, existing SideStage agent profiles and reply broker.

---

## Design decisions

1. **Chosen: deterministic typed resolution before both workflows.** Attribute order is irrelevant. Missing attributes narrow only through trusted bound-listing candidates, so one candidate resolves, zero becomes `missing_evidence`, and multiple become `ambiguous`.
2. **Chosen: one aggregate availability record for general questions.** `What sizes are available?` and `How many pairs are left across all sizes?` use an application-built summary containing labels, quantities, total quantity, and the inventory versions used. The model never receives the complete per-variant evidence array.
3. **Rejected: ask the LLM to canonicalize labels.** It adds latency and still permits semantically wrong-but-real variants.
4. **Rejected: pass compact candidate labels or IDs to the LLM and validate membership.** Membership proves authority but not semantic correspondence to the buyer wording.
5. **Preservation constraint:** implement in the current dirty worktree because the approved in-progress projection compression and removal of model-returned `variant_id` overlap the required boundary. Do not revert, overwrite, stage, or commit unrelated builder changes.

### Task 1: Specify the resolver with failing unit tests

**Files:**
- Create: `tests/unit/test_variant_resolution.py`
- Create later: `src/sidestage/copilot/variants.py`

1. Parameterize `US M 9`, `9 M US`, `Men's US 9`, `9 for men`, and `9 for man`; require the same trusted ID.
2. Prove `9.5` never matches `9`.
3. Prove missing system/audience resolves only when the filtered trusted candidate is unique.
4. Prove mixed systems or audiences return `ambiguous`.
5. Prove unknown sizes return `missing_evidence`.
6. Prove model/product numbers without size context are not parsed as sizes.
7. Prove both general-availability phrasings produce typed summary plans.
8. Run `uv run pytest tests/unit/test_variant_resolution.py -q` and retain the expected RED output.

### Task 2: Implement typed parsing and candidate resolution

**Files:**
- Create: `src/sidestage/copilot/variants.py`
- Test: `tests/unit/test_variant_resolution.py`

1. Add closed enums for size system, audience, resolution status, and summary kind.
2. Parse trusted catalog labels strictly; reject malformed or incomplete catalog attributes.
3. Parse buyer attributes with bounded tokens and decimal-safe numeric matching.
4. Require explicit sizing context before treating a bare number as a size.
5. Filter only trusted candidates supplied from the immutable bound listing.
6. Return exactly one trusted `variant_id`, `ambiguous`, `missing_evidence`, a summary plan, or not-applicable.
7. Run the unit test and make it GREEN.

### Task 3: Specify evidence planning and projection with failing integration tests

**Files:**
- Modify: `tests/integration/test_retrieval.py`
- Modify: `tests/unit/test_livesell_profile.py`
- Modify: `tests/unit/test_reply_templates.py`

1. Require exact queries to retrieve exactly one `variant_availability` record.
2. Require general availability to retrieve one aggregate record, never all variant records.
3. Require unrelated queries to contain no variant inventory in model projection.
4. Require the two-call planner contract to reject a model-authored `variant_mentions` field and use Python resolution of raw buyer wording.
5. Require exact one-call projection to contain one variant evidence record and no other variant inventory.
6. Require fabricated and wrong-but-real selections to fail rendering.
7. Run the focused tests and retain the expected RED output.

### Task 4: Apply the evidence plan to both retrieval workflows

**Files:**
- Modify: `src/sidestage/copilot/retrieval.py`
- Modify: `src/sidestage/copilot/contracts.py`
- Modify: `src/sidestage/domain/replies.py`
- Modify: `src/sidestage/copilot/profile.py`
- Modify: `src/sidestage/copilot/templates.py`
- Modify: `src/sidestage/copilot/broker.py`

1. Add raw question text to the trusted retrieval context, not to the LLM-produced request.
2. Resolve the bound listing's trusted candidates before inventory lookup in both entry points.
3. Remove `variant_mentions` from the two-call planner contract; exact availability uses no model-generated variant identity.
4. Retrieve exactly the resolved inventory row and preserve its trusted `variant_id` in `source_ref`.
5. Build one application-owned aggregate record for general availability; include deterministic version provenance sufficient for revalidation.
6. Exclude per-variant inventory from all template bundles and projections except the single exact record.
7. Teach the renderer and broker to validate/render the aggregate record without treating it as a model-authored fact.
8. Run focused retrieval, projection, rendering, and broker tests.

### Task 5: Prove both workflows end to end

**Files:**
- Modify: `tests/integration/test_livesell_agent.py`
- Modify: `tests/e2e/test_golden_demo.py`
- Modify as needed: `tests/integration/test_r3_safety.py`

1. Run equivalent exact-size expressions through `two_call_draft` and `one_call_template`.
2. Assert the trusted expected ID is the only variant evidence and the reply names the correct label/quantity.
3. Assert ambiguous and missing cases fail closed before publication.
4. Simulate a wrong-but-real model selection and assert it cannot render, publish, or commit an R3 effect.
5. Exercise both general availability examples and assert no full variant evidence array enters any model call.
6. Run the focused end-to-end command and make it GREEN.

### Task 6: Verify regressions and document evidence

**Files:**
- Modify: `docs/TDD.md`
- Modify: `docs/debug-process.md`

1. Update the TDD workflow contract: deterministic variant resolution and aggregate availability evidence precede both model strategies.
2. Update DBG-023 with RED evidence, implemented root fix, exact commands/results, and remaining language/catalog-label risks.
3. Keep DBG-023 at `Fixed` or `Implemented`, not `Verified`, until evidence is commit-bound.
4. Run `uv run pytest` for the focused resolver/workflow tests.
5. Run `uv run pytest -q` for the complete deterministic suite.
6. Inspect `git diff --check`, `git status --short`, and the final scoped diff.
7. Ask the builder for the exact commit message; do not commit automatically.
