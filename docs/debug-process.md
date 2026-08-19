# SideStage Debugging Process and Evidence Log

> Status: Active engineering process and interview evidence log
>
> Last updated: 2026-08-18
>
> Milestone 2 evidence target: `734d151`
>
> Current deterministic P0 evidence target: `3fda622`
>
This is a contemporaneous engineering journal and interview aid. Record observed failures while they happen; do not manufacture plausible debugging stories after the build.

## 1. Debugging method

For every material failure:

1. Preserve the failing input, tenant, seed, trace identifier, and current commit.
2. Write the expected and observed behavior before changing code.
3. Capture the exact reproduction command and smallest deterministic fixture.
4. Inspect stage traces to identify the first incorrect transition rather than the final symptom.
5. List competing hypotheses and the evidence that eliminates them.
6. Make the smallest scoped fix.
7. Add or update a regression test before declaring the issue resolved.
8. Run the focused test, relevant suite, and end-to-end reproduction.
9. Record remaining uncertainty and the 60-second explanation for the interview.

## 2. Reproduction baseline

Populate these fields as soon as commands exist:

| Item | Exact value |
| --- | --- |
| End-to-end live run command | `uv run uvicorn sidestage.app:create_live_app --factory --host 127.0.0.1 --port 8000` after exporting the required model environment |
| Full test command | `uv run pytest -q` |
| Pressure-test command | `SIDESTAGE_MODEL_ID=gpt-5.6-luna SIDESTAGE_MODEL_REASONING_EFFORT=none uv run python -m sidestage.trace.evaluator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --model live --output runs/exploratory/evaluation_live.json` with `OPENAI_API_KEY` or `SIDESTAGE_MODEL_API_KEY` set outside the command |
| Deterministic seed | `20260817` for M2 prepared chat and the retained M3A/M3B regression workloads |
| Environment setup | `uv sync --group dev` and `uv run playwright install chromium` |
| Trace export location | `/app/debug.html`; `GET /api/debug/copilot?session_token=<opaque-session-token>` for M3B and `GET /api/debug/marketplace?session_token=<opaque-session-token>` for the M2 ledger |
| Current evidence commit | `3fda622` for the complete deterministic P0 implementation; live release measurement remains pending |

## 3. Issue index

| ID | Status | Summary |
| --- | --- | --- |
| DBG-001 | Fixed | M2 browser verification could not start in the default sandbox/Python environment |
| DBG-002 | Fixed | Native Markdown field validation bypassed the application refusal receipt path |
| DBG-003 | Fixed | RED-first uv install left the new M2.1 package unavailable to Pytest |
| DBG-004 | Fixed | Initial listing-condition contract rejected approved consignment records |
| DBG-005 | Fixed | M2.1 browser assertions confused fixture status with derived UI state |
| DBG-006 | Fixed | M3A.1 tests constructed profiles outside the strict validation path |
| DBG-007 | Fixed | Immutable JSON documents exported a misleading string schema |
| DBG-008 | Fixed | Provider work started after the absolute deadline expired at dispatch |
| DBG-009 | Fixed | Live-provider HTTP client was closed from a different event loop |
| DBG-010 | Open | Bare API key exposed by environment-name inspection; rotation remains required |
| DBG-011 | Fixed | Trace-overhead benchmark rejected strict enum and then under-measured the path |
| DBG-012 | Fixed | Permissive JSON constants escaped the evaluator's typed error boundary |
| DBG-013 | Fixed | GPT-5.6 Luna rejected Chat Completions tools at its default reasoning effort |
| DBG-014 | Fixed | M2.3 reload silently replaced the opaque server session |
| DBG-015 | Fixed | Runtime debugger sent its placeholder label as an actual-route filter |
| DBG-016 | Fixed | Product-mention routing helper accidentally ended the router class |
| DBG-017 | Fixed | Debugger SSE refresh displaced the stage being inspected |
| DBG-018 | Diagnosed | Two-call Luna pressure missed correctness and latency gates |
| DBG-019 | Fixed | Documented Uvicorn factory silently used an empty scripted runner |
| DBG-020 | Fixed | Strict provider schema caused every live analysis request to fail before retrieval |
| DBG-021 | Fixed | Stale SSE refresh intermittently overwrote a newer R3 response |
| DBG-022 | Fixed | Sandbox network and localhost restrictions produced false validation failures |
| DBG-023 | Fixed | Natural-language size wording was not deterministically bound to one trusted variant |
| DBG-024 | Fixed | Empty-stage chat accumulated Needs You cards and the seller workspace lacked reset/volume controls |
| DBG-025 | Fixed | Fresh FastAPI removed the shutdown-registration API used by both app factories |
| DBG-026 | Fixed | Scripted pressure saturation depended on interpreter scheduling behavior |
| DBG-027 | Fixed | Grounded questions stayed in Manual review or Needs seller, and repeated text was over-grouped |
| DBG-028 | Fixed | Concurrent SSE listeners could violate Python 3.9 condition-lock ownership |

### DBG-001 — M2 browser verification environment could not launch

- **Date and commit:** 2026-08-17; uncommitted M2 UI working tree
- **Status:** Fixed
- **Expected:** Start a repository-root static HTTP server and run the Playwright seller-flow verification against it.
- **Observed:** The sandboxed server bind failed with `PermissionError: [Errno 1] Operation not permitted`. The approved unsandboxed retry started the server, then the verification process failed with `ModuleNotFoundError: No module named 'playwright'`.
- **Exact reproduction command:** `python /Users/qiguo/.codex/skills/webapp-testing/scripts/with_server.py --server "python3 -m http.server 8000" --port 8000 -- python tests/e2e/verify_m2_ui.py`
- **Tenant, fixture, seed, and trace ID:** No tenant selected; browser verification stopped before fixture load; no seed or trace ID.
- **Log, trace, screenshot, or artifact:** Terminal output retained in the active Codex task; no screenshot was produced.
- **Impact:** JavaScript syntax and whitespace checks pass, but the required real-browser interaction and visual verification is not yet complete.
- **Hypotheses considered:** Port collision; incorrect server command; sandbox bind restriction; missing browser automation dependency.
- **First incorrect pipeline stage:** Browser verification environment setup, before application navigation.
- **Root cause:** The default sandbox prohibits binding the local test server, and the selected Python interpreter does not have the Playwright package installed.
- **Fix:** Loaded the bundled workspace runtime, installed Python Playwright only under `/tmp/sidestage-playwright`, ran the local server outside the bind-restricted sandbox, and added a 500 ms settled-state wait before the retained desktop capture so the screenshot does not land inside the intentional cue transition.
- **Files and functions changed:** `tests/e2e/verify_m2_ui.py`; no product behavior changed while diagnosing.
- **Verification commands and results:** `node --check src/sidestage/web/static/app.js`, `node --check src/sidestage/web/static/debugger.js`, and `git diff --check` passed. `python /Users/qiguo/.codex/skills/webapp-testing/scripts/with_server.py --server "python3 -m http.server 8765" --port 8765 -- env PYTHONPATH=/tmp/sidestage-playwright SIDESTAGE_BASE_URL=http://127.0.0.1:8765 /Users/qiguo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 tests/e2e/verify_m2_ui.py` passed and produced three screenshots under `/tmp/sidestage-m2-ui`.
- **Regression test:** `tests/e2e/verify_m2_ui.py` passed in headless Chromium.
- **Remaining risk:** The UI still runs over the explicitly labeled browser adapter; FastAPI, SQLite, authority, idempotency, concurrent-write, and SSE behavior remain M2 backend work.
- **What I personally did:** Inspected the listening port, reproduced the sandbox bind failure directly, retried with approved local-server permission, and isolated the missing Python package.
- **What AI suggested:** Use the repository skill's server lifecycle helper and a native Python Playwright flow.
- **What I rewrote or rejected:** Did not bypass browser verification with DOM-only assertions or claim screenshots that do not exist.
- **60-second interview explanation:** The first M2 UI verification failed before the application loaded. Direct reproduction separated two environment problems: sandboxed socket binding and a Python interpreter without Playwright. I kept the incident open, installed Playwright only in a temporary directory, reran the same flow outside the sandbox, and inspected the resulting desktop, developer-ledger, and mobile captures. The browser flow then passed with no console or page errors.

### DBG-002 — Native Markdown validation bypassed audited refusal

- **Date and commit:** 2026-08-17; uncommitted M2 UI working tree
- **Status:** Fixed
- **Expected:** Submitting a Markdown below the seller floor reaches the operation handler, leaves price unchanged, shows the exact refusal, and appends a `status=rejected` Price Markdown receipt.
- **Observed:** The browser's native `min` constraint stopped form submission before `executeOperation`, so the dialog stayed open with no application error and no refusal receipt.
- **Exact reproduction command:** `python /Users/qiguo/.codex/skills/webapp-testing/scripts/with_server.py --server "python3 -m http.server 8765" --port 8765 -- env PYTHONPATH=/tmp/sidestage-playwright SIDESTAGE_BASE_URL=http://127.0.0.1:8765 /Users/qiguo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 tests/e2e/verify_m2_ui.py`
- **Tenant, fixture, seed, and trace ID:** VelocityKicks; `VK-CP-SC-002`; no scenario seed or backend trace ID in the browser adapter.
- **Log, trace, screenshot, or artifact:** Playwright assertion output showed an empty hidden `#dialog-error` while the price input remained at `1`.
- **Impact:** A policy-invalid seller attempt was blocked visually but was not represented in the UI adapter's developer receipt projection.
- **Hypotheses considered:** Wrong dialog event listener; integer-cent conversion error; floor lookup error; native HTML constraint preventing submit.
- **First incorrect pipeline stage:** Browser form submission, before application parameter validation.
- **Root cause:** The Markdown input encoded the seller floor in native `min`, duplicating the policy check and preventing the application-owned rejection path from running.
- **Fix:** Retained only the generic positive-price input constraint and let `executeOperation` enforce current price and seller floor so the refusal is recorded. Tightened the Playwright Cancel selector after its first rerun matched both the icon close and named Cancel buttons.
- **Files and functions changed:** `src/sidestage/web/static/app.js` in `dialogFields`; `tests/e2e/verify_m2_ui.py` refusal case.
- **Verification commands and results:** The expanded browser command passed. It submitted `$1`, asserted the seller-floor error and unchanged `$145` price, navigated to the developer ledger, and found a visible `rejected` receipt. JavaScript syntax and `git diff --check` also passed in the same command.
- **Regression test:** `tests/e2e/verify_m2_ui.py` now submits `$1`, asserts the seller-floor error and unchanged active price, then asserts the rejected receipt in the developer ledger.
- **Remaining risk:** The browser adapter demonstrates UI refusal behavior only; durable backend audit ordering and failure semantics remain M2 kernel work.
- **What I personally did:** Expanded the happy-path browser test to include a policy refusal and used the rendered accessibility snapshot to identify that the form never reached application code.
- **What AI suggested:** Move policy enforcement to the typed operation boundary while leaving only generic numeric validity in HTML.
- **What I rewrote or rejected:** Rejected weakening the test to accept native validation because M2 explicitly requires audited refusals.
- **60-second interview explanation:** A new negative browser test found that duplicating the seller floor in HTML looked safe but bypassed the application audit path. The browser rejected `$1` before JavaScript ran. I moved the business constraint back to the typed operation handler, reran the browser flow, and confirmed the price remained `$145` while a rejected receipt appeared in the ledger. Invalid attempts are now no-op but observable, which is the behavior the M2 safety contract requires.

### DBG-003 — RED-first uv install left the M2.1 package unavailable

- **Date and commit:** 2026-08-17; uncommitted M2.1 working tree
- **Status:** Fixed
- **Expected:** After writing the M2.1 implementation, the unchanged focused command would move from the intended missing-module RED failure to contract execution.
- **Observed:** `uv run pytest tests/unit/test_domain_contracts.py tests/unit/test_seller_import.py -q` still failed collection with `ModuleNotFoundError: No module named 'sidestage'` after the source package existed.
- **Exact reproduction command:** `uv run pytest tests/unit/test_domain_contracts.py tests/unit/test_seller_import.py -q`
- **Tenant, fixture, seed, and trace ID:** No seller was loaded; collection failed before fixture import.
- **First incorrect pipeline stage:** Test-environment package discovery.
- **Root cause:** The RED run built and installed the project before `src/sidestage/__init__.py` existed, leaving an empty installed artifact in the uv environment. The test command had no explicit `src` discovery fallback.
- **Fix:** Added `pythonpath = ["src"]` to the repository Pytest configuration. The next uv run also rebuilt the project after the `pyproject.toml` change.
- **Files and functions changed:** `pyproject.toml` Pytest configuration.
- **Verification commands and results:** The focused command collected the M2.1 tests and advanced to two real data-contract failures; after the separate condition fix, all 24 tests passed.
- **Regression test:** The documented focused command now imports the source tree deterministically after a RED-first setup.
- **Remaining risk:** Normal runtime imports still rely on the packaged project; the wheel is built in every clean `uv sync`/`uv run` environment and was rebuilt successfully in this environment.
- **60-second interview explanation:** Running RED before the package existed created an unusual local state: uv had installed an empty project artifact, so adding source files did not make Pytest import them. I kept the command unchanged and made test discovery explicit through the standard `src` layout. That turned an environment failure into the actual contract failures the suite was meant to expose.

### DBG-004 — Approved consignment listings failed typed import

- **Date and commit:** 2026-08-17; uncommitted M2.1 working tree
- **Status:** Fixed
- **Expected:** `fixtures/sellers.json` imports byte-for-value into immutable typed records.
- **Observed:** The loader rejected two VaultConsign products because `ListingCondition` allowed only `new` and `used`, while the approved records use `consignment`.
- **Exact reproduction command:** `uv run pytest tests/unit/test_domain_contracts.py tests/unit/test_seller_import.py -q`
- **Tenant, fixture, seed, and trace ID:** `sel_vault_consign`; the two consignment listings in the committed seller fixture; no scenario seed or trace ID.
- **First incorrect pipeline stage:** Pydantic listing validation during fixture import.
- **Root cause:** The initial model vocabulary was inferred from the first sample records rather than enumerated across the complete approved fixture.
- **Fix:** Expanded `ListingCondition` to exactly `new | used | consignment`; the fixture remained unchanged.
- **Files and functions changed:** `src/sidestage/domain/models.py`, `ListingCondition`.
- **Verification commands and results:** The focused M2.1 suite passed: `24 passed in 0.09s`. The round-trip test proves the typed document dumps back to the exact source values.
- **Regression test:** `test_imports_exact_approved_sellers_without_changing_source_values` loads every product and compares the entire JSON projection.
- **Remaining risk:** Any future listing condition must be an explicit contract change rather than silently accepted free text.
- **60-second interview explanation:** The first typed import rejected valid consignment inventory because I modeled conditions from an incomplete sample. I did not rewrite the fixture or loosen the field to arbitrary text. I enumerated the approved third value and kept the closed vocabulary, then used the full-document round-trip test to prove every seller record imports unchanged.

### DBG-005 — Browser projection asserted source status instead of UI state

- **Date and commit:** 2026-08-17; uncommitted M2.1 working tree
- **Status:** Fixed
- **Expected:** The inherited browser flow validates all three seller catalogs, a prepared event, a custom event, active price/stock/policy, and the existing M2.0 interaction flow.
- **Observed:** The first run expected every source-`available` catalog card to display `Available`, but the UI correctly labels the default pending Push target `Selected`. After that correction, the developer ledger correctly contained two raw events while the old M2.0 assertion still expected one.
- **Exact reproduction command:** `SIDESTAGE_BASE_URL=http://127.0.0.1:8877 uv run python tests/e2e/verify_m2_ui.py`
- **Tenant, fixture, seed, and trace ID:** All three sellers for catalog projection; VelocityKicks for prepared/custom chat and operation flow; no scenario seed or backend trace ID in the browser adapter.
- **First incorrect pipeline stage:** Browser-test expectation construction, not product rendering.
- **Root cause:** The new test compared a source listing field directly to a derived presentation label and did not propagate the added prepared event into the existing ledger count.
- **Fix:** Assert `Selected` for the first pending catalog target and `Available` for the remaining cards; assert two correlated raw events after one prepared and one custom message.
- **Files and functions changed:** `tests/e2e/verify_m2_ui.py`, `assert_m2_1_data_projection` and the ledger count assertion.
- **Verification commands and results:** The complete Chromium flow passed and wrote four screenshots under `/tmp/sidestage-m2-ui`, including `m2-1-data-projection-desktop.png`; the narrow-layout overflow assertion also passed.
- **Regression test:** The browser flow now validates exact fixture values and their deliberately derived UI states before continuing through the existing operation flow.
- **Remaining risk:** This remains browser-adapter projection evidence; the Python importer does not become the UI's runtime source until the authoritative HTTP/SSE wiring milestone.
- **60-second interview explanation:** I initially treated an `available` listing as if its UI badge had to say “Available.” The M2 design intentionally marks the first empty-stage target “Selected.” The failure showed the test was flattening source state and view state. I corrected the assertion to model that projection and updated the ledger count for the newly added prepared event, then reran the entire browser flow successfully.

### DBG-006 — M3A.1 tests constructed profiles outside the strict validation path

- **Date and commit:** 2026-08-17; uncommitted M3A.1 working tree
- **Status:** Fixed
- **Expected:** The first M3A.1 GREEN run validates deeply immutable profiles, duplicate terminal-tool rejection, and startup registration.
- **Observed:** `test_profile_and_task_are_deeply_immutable` failed because `model_copy(update=...)` installed a raw dictionary without validation, while the duplicate-tool test supplied a list to a strict tuple field and failed before reaching the uniqueness invariant. The focused run reported `2 failed, 22 passed`.
- **Exact reproduction command:** `uv run pytest tests/unit/agent_core/test_contracts.py tests/unit/agent_core/test_profile.py tests/unit/agent_core/test_isolation.py -q`
- **Tenant, fixture, seed, and trace ID:** Domain-neutral M3A profile tests; no seller, M1/M2 fixture, scenario seed, or runtime trace.
- **Log, trace, screenshot, or artifact:** Pytest showed `AttributeError: 'dict' object has no attribute 'to_dict'` during registration and a strict `tuple_type` validation error in the duplicate-tool case.
- **Impact:** Product contracts were not shown to be incorrect, but the tests were bypassing the same strict construction path they were intended to verify. The `model_copy` behavior also identified a startup-hardening opportunity.
- **Hypotheses considered:** Broken deep-immutable JSON wrapper; invalid Pydantic serializer; `model_copy(update=...)` bypassing validation; incorrect strict container type in the test payload.
- **First incorrect pipeline stage:** Test fixture construction before the profile invariants under test.
- **Root cause:** Pydantic deliberately does not validate `model_copy(update=...)`, and strict tuple fields reject lists before model-level uniqueness validation.
- **Fix:** Construct the immutable profile through normal validation, pass a tuple to the duplicate-name test, and defensively revalidate a copied `AgentProfile` inside `register_profile` before schema compilation and hashing.
- **Files and functions changed:** `tests/unit/agent_core/test_contracts.py`, `tests/unit/agent_core/test_profile.py`, and `src/sidestage/agent_core/profile.py::register_profile`.
- **Verification commands and results:** The unchanged focused command passed with `24 passed in 0.29s`.
- **Regression test:** The immutability test now mutates its original source schema after validated construction, and registration revalidates the complete serialized contract before accepting it.
- **Remaining risk:** Full-suite regression and clean-tree evidence remain part of the M3A.1 review gate.
- **60-second interview explanation:** My first GREEN run accidentally tested Pydantic construction shortcuts instead of the public strict boundary. One shortcut bypassed validation; the other failed on the container type before reaching the uniqueness rule. I corrected the fixtures and also made startup registration revalidate the full profile, so a malformed copied model cannot bypass the frozen registry. The same focused command then passed all 24 cases.

### DBG-007 — Immutable JSON documents exported a misleading string schema

- **Date and commit:** 2026-08-17; uncommitted M3A.1 working tree
- **Status:** Fixed
- **Expected:** Exported `AgentProfile` and `AgentTask` schemas describe adapter input schemas, tool argument schemas, model input, and correlation metadata as JSON objects.
- **Observed:** The schema-export inspection reported the internal `FrozenJsonObject` definition as `type: string`, even though construction and serialization correctly accepted and emitted objects.
- **Exact reproduction command:** `uv run python -c 'import json; from sidestage.agent_core import AgentProfile, AgentTask, AgentRunResult; schemas={c.__name__:c.model_json_schema() for c in (AgentProfile,AgentTask,AgentRunResult)}; print(json.dumps(schemas, sort_keys=True)[:1200])'`
- **Tenant, fixture, seed, and trace ID:** Domain-neutral M3A schema export; no seller, fixture, seed, or trace ID.
- **Log, trace, screenshot, or artifact:** The output contained `"FrozenJsonObject": {..., "type": "string"}`.
- **Impact:** Runtime validation remained correct, but an adapter or reviewer consuming the exported contract would receive a false interface description.
- **Hypotheses considered:** Incorrect object serializer; incorrect root-model input validator; Pydantic schema generation reflecting the immutable internal string representation instead of the public serialized representation.
- **First incorrect pipeline stage:** Contract schema generation, after correct runtime construction and before adapter consumption.
- **Root cause:** A custom Pydantic serializer changes emitted values but does not automatically change the generated JSON Schema for a `RootModel[str]`.
- **Fix:** Added an explicit `__get_pydantic_json_schema__` hook advertising the public object representation and a regression assertion for both profile and task schema exports.
- **Files and functions changed:** `src/sidestage/agent_core/contracts.py::FrozenJsonObject` and `tests/unit/agent_core/test_contracts.py`.
- **Verification commands and results:** The focused M3A.1 suite passed with `25 passed in 0.32s`; a concise export command printed `object` for both `AgentProfile` and `AgentTask`.
- **Regression test:** `test_exported_contract_schemas_describe_json_documents_as_objects`.
- **Remaining risk:** Exported schemas describe arbitrary JSON-object contents; the adapter-specific input and terminal schemas remain the authoritative nested constraints compiled at profile registration.
- **60-second interview explanation:** I inspected the generated schemas rather than assuming runtime tests covered them. The immutable wrapper stored canonical JSON internally as a string, and Pydantic exposed that implementation detail even though public serialization was an object. I overrode the schema representation and added a regression test. The runtime contract and exported contract now agree.

### DBG-008 — Provider work started after deadline expiry at dispatch

- **Date and commit:** 2026-08-17; uncommitted M3A.2 working tree on `d8c997f`
- **Status:** Fixed
- **Expected:** If the absolute monotonic deadline expires before provider dispatch, return `hard_timeout` and start zero provider work.
- **Observed:** The core returned `hard_timeout`, but the deterministic runner recorded one invocation when the clock crossed the deadline between the remaining-time check and the provider-start timestamp.
- **Exact reproduction command:** `uv run pytest tests/unit/agent_core/test_model_runner.py::test_deadline_expiring_at_dispatch_starts_zero_provider_work -q`
- **Tenant, fixture, seed, and trace ID:** Domain-neutral task `task-m3a2-1`; no tenant or fixture; deterministic injected clock; trace `trace-m3a2-1`.
- **Log, trace, screenshot, or artifact:** The focused failure reported `runner.calls` containing one `ModelInvocation` instead of `()`; terminal output is retained in the active Codex task.
- **Impact:** The late result was safely discarded and no intent/effect escaped, but an already-expired task could still consume one paid provider request and violate the zero-work pre-dispatch invariant.
- **Hypotheses considered:** `asyncio.wait_for` failed to cancel; task validation used wall time; provider returned too quickly; remaining time was sampled before the separately sampled dispatch boundary.
- **First incorrect pipeline stage:** Provider dispatch, after valid task projection and before awaiting the provider.
- **Root cause:** `StaticAgentCore.run` computed `remaining_s`, then sampled `provider_started_at`, but passed the stale earlier duration to `asyncio.wait_for` without rechecking the absolute deadline at the actual dispatch timestamp.
- **Fix:** Recompute remaining time from the final `provider_started_at` timestamp and reject before calling `ModelRunner.run` when the absolute deadline is no longer in the future. The zero-work path records no provider duration because no provider work began.
- **Files and functions changed:** `src/sidestage/agent_core/core.py::StaticAgentCore.run` and `tests/unit/agent_core/test_model_runner.py`.
- **Verification commands and results:** The exact regression passed with `1 passed in 0.14s`; the focused M3A.2 suite passed with `19 passed in 0.20s`; `uv run pytest -q` passed with `92 passed, 1 skipped in 1.03s`; `git diff --check` and `uv lock --check` passed.
- **Regression test:** `test_deadline_expiring_at_dispatch_starts_zero_provider_work`.
- **Remaining risk:** `asyncio` scheduling still has an unavoidable sub-call timing gap after the final monotonic sample, but `wait_for` uses the recomputed remaining duration and every response is checked again against the same absolute deadline before parsing or returning intent. M3A.3 will exercise this boundary under queued concurrency and cancellation pressure.
- **60-second interview explanation:** A result-level timeout test was not enough: it proved late intent suppression but not that an expired task avoided provider cost. I injected a clock that crossed the deadline between the initial remaining-time check and dispatch. The result still failed closed, but the call counter exposed one unnecessary request. The dispatch path needs to recompute remaining time from its final provider-start timestamp before invoking the runner.

### DBG-009 — Live-provider client closed from a different event loop

- **Date and commit:** 2026-08-17; uncommitted M3A.2 working tree on `d8c997f`
- **Status:** Fixed
- **Expected:** The credential-gated OpenAI smoke test makes one request, closes its owned HTTP client cleanly, and then asserts one sanitized terminal outcome.
- **Observed:** The request completed far enough to leave a live HTTP connection, but the test called `asyncio.run(core.run(task))` and then a second `asyncio.run(runner.aclose())`. HTTPX cleanup failed with `RuntimeError: Event loop is closed` before the result assertions ran.
- **Exact reproduction command:** `SIDESTAGE_MODEL_BASE_URL=https://api.openai.com/v1 SIDESTAGE_MODEL_API_KEY="$(tr -d '\\r\\n' < .env)" SIDESTAGE_MODEL_ID=gpt-5.4-nano-2026-03-17 uv run pytest tests/integration/agent_core/test_live_provider.py -m live_model -q`
- **Tenant, fixture, seed, and trace ID:** Domain-neutral task `live-smoke-task`; no tenant, fixture, or seed; trace `live-smoke-trace`; pinned model snapshot `gpt-5.4-nano-2026-03-17`.
- **Log, trace, screenshot, or artifact:** Pytest traceback retained in the active Codex task; no credential or response body was printed.
- **Impact:** The live request path could not be classified as passed or failed even though unit-level HTTP mapping passed; cleanup failure masked the returned `AgentRunResult`.
- **Hypotheses considered:** Invalid API key; unsupported model; tool-call schema rejection; HTTP timeout; HTTPX client bound to the event loop used by the request.
- **First incorrect pipeline stage:** Test cleanup after `StaticAgentCore.run` returned, before live-result assertions.
- **Root cause:** Async network resources are bound to their creating/operating event loop. The test used two independent `asyncio.run()` calls for request and cleanup.
- **Fix:** Added one `run_and_close` coroutine that awaits `StaticAgentCore.run` and closes the runner in `finally`, then calls `asyncio.run()` exactly once. Added a credential-free sanitized summary containing only configured/reported model ID, status, terminal or failure code, and latency.
- **Files and functions changed:** `tests/integration/agent_core/test_live_provider.py::test_configured_live_provider_returns_one_sanitized_terminal_outcome`.
- **Verification commands and results:** The corrected live test first passed with `1 passed in 4.13s`. The retained sanitized rerun passed with `1 passed in 1.07s` and reported configured/reported model `gpt-5.4-nano-2026-03-17`, `status=succeeded`, terminal `finish`, provider `901.315 ms`, parse `0.135 ms`, and core total `901.489 ms`. The offline M3A.2 suite passed with `19 passed in 0.17s`; `uv run pytest -q` passed with `94 passed, 1 skipped in 1.23s`; diff and lock checks passed.
- **Regression test:** The credential-gated `test_configured_live_provider_returns_one_sanitized_terminal_outcome` is the reproduction.
- **Remaining risk:** This is one smoke request, not a latency distribution or terminal-compliance matrix. M3A.4 must run the declared live workload repeatedly before any p50/p95 or provider-quality claim.
- **60-second interview explanation:** The first real API call uncovered an async ownership mistake in the smoke test, not a model-contract failure. HTTPX kept a connection associated with the request loop, while cleanup ran in a fresh loop. The fix is to wrap both the core call and `aclose()` in one coroutine and invoke `asyncio.run()` exactly once, preserving deterministic cleanup and allowing the actual model result to be evaluated.

### DBG-010 — Bare API key exposed by environment-name inspection

- **Date and commit:** 2026-08-17; uncommitted M3A.3 working tree on `693d86a`
- **Status:** Open pending credential rotation
- **Expected:** Inspect only environment-variable names without printing any credential value before rerunning the credential-gated live smoke test.
- **Observed:** `.env` contains a bare API key rather than `NAME=value`; a command intended to strip values therefore printed the bare credential into the local tool transcript. During the later M3B.5 audit, a second value-redaction command repeated the same invalid assignment-format assumption and exposed the still-unrotated value again.
- **Exact reproduction command:** First occurrence: `sed -E 's/[[:space:]]*=.*$//' .env | sed '/^[[:space:]]*#/d' | sed '/^[[:space:]]*$/d'`. Recurrence: `sed -E 's/=.*/=<redacted>/' .env`.
- **Tenant, fixture, seed, and trace ID:** No tenant, fixture, seed, or agent trace; local credential-handling incident.
- **Log, trace, screenshot, or artifact:** The secret-bearing output exists in the active Codex tool transcript and is deliberately not copied into this log.
- **Impact:** The OpenAI credential must be treated as exposed and rotated. No repository file was modified with the credential, and the value remains ignored by Git through `.gitignore`.
- **Hypotheses considered:** Conventional dotenv assignment; bare-key file; comment-only file.
- **First incorrect pipeline stage:** Credential-shape discovery before the live-provider test.
- **Root cause:** The inspection assumed dotenv assignment syntax despite prior evidence that this repository's `.env` stores one bare key.
- **Fix:** Stop inspecting or sourcing the file as dotenv. Map the file contents directly into `SIDESTAGE_MODEL_API_KEY` with command substitution that is never echoed, update reviewer commands to reflect the actual bare-key shape, and ask the builder to rotate the exposed key.
- **Files and functions changed:** This incident entry only; `.env` and application code are unchanged.
- **Verification commands and results:** The no-echo mapping successfully ran the existing live smoke with `1 passed in 2.23s`; its sanitized output contained only model identity, terminal status, and latency. The M3B reviewer-path smoke later passed with a credential already exported in the process environment and printed no secret. Credential rotation remains pending.
- **Regression test:** Operational rule: never print, enumerate, or source this bare-key `.env`; use a no-echo direct mapping only when explicitly running the live smoke.
- **Remaining risk:** The exposed key remains usable until the builder revokes or rotates it, and existing local transcript retention is outside the repository's control.
- **60-second interview explanation:** I assumed `.env` used normal `NAME=value` syntax and ran a name-only inspection. Because the file contained only the raw key, the transformation had nothing to remove and printed it. I stopped, disclosed the exposure immediately, avoided copying the credential into the repository, documented the exact failure without the value, and required rotation.

### DBG-011 — Trace-overhead benchmark rejected strict enum and then under-measured the path

- **Date and commit:** 2026-08-17; uncommitted M3A.4 working tree on `693d86a`
- **Status:** Fixed
- **Expected:** The generic pressure evaluator measures the per-event cost of constructing a validated core trace event and passing it through the same fail-open emitter used by `StaticAgentCore`.
- **Observed:** The first focused M3A.4 run failed because the benchmark serialized a strict `CoreTraceEventType` enum to JSON text and passed the string back into strict Pydantic validation. Reusing the already-validated event made the tests pass but timed only the in-memory sink append, which understated core instrumentation cost.
- **Exact reproduction command:** `uv run pytest tests/unit/agent_core/test_scenario_generator.py tests/integration/agent_core/test_replay.py tests/integration/agent_core/test_evaluation.py tests/integration/agent_core/test_pressure.py -q -m 'not live_model' -x`
- **Tenant, fixture, seed, and trace ID:** No tenant; `fixtures/agent_core/pressure_v1.json`; seed `20260817`; generated generic task traces.
- **Log, trace, screenshot, or artifact:** Pytest reported `CoreTraceEvent.event_type` required a `CoreTraceEventType` instance but received the string `task_accepted`. The corrected retained result is in `runs/agent_core_regression_v1/evaluation.json`.
- **Impact:** Runtime behavior was unaffected, but the harness could not complete initially; the first passing workaround would also have produced misleadingly small trace-overhead evidence.
- **Hypotheses considered:** Relax strict event validation; validate JSON-mode dumps; emit the retained object directly; benchmark the actual construction-plus-emission boundary with Python-mode enum values.
- **First incorrect pipeline stage:** M3A.4 evaluator metric collection after the deterministic core execution completed.
- **Root cause:** JSON-mode serialization intentionally converts the enum to a string, while the immutable trace contract is strict. Separately, sink-only timing did not represent the declared metric.
- **Fix:** Build a Python-mode field mapping that preserves the enum instance, construct and strictly validate one fresh `CoreTraceEvent` per sample, and emit it through `SafeTraceEmitter` into the no-I/O sink.
- **Files and functions changed:** `src/sidestage/agent_core/evaluation.py::_trace_overhead` and this incident entry.
- **Verification commands and results:** The exact M3A.4 focused command passed with `8 passed, 1 deselected`; the default repository suite passed with `115 passed, 2 deselected`; the retained scripted artifact replay matched. The corrected 2,000-sample benchmark reports about `0.0037 ms` p95 per event against the declared `0.25 ms` budget on this run.
- **Regression test:** `tests/integration/agent_core/test_pressure.py::test_pressure_reports_fifo_backpressure_latency_and_trace_overhead` requires at least 1,000 samples and a passing declared overhead verdict.
- **Remaining risk:** This local microbenchmark describes validated event construction plus an in-memory fail-open emission only. A future asynchronous persistence adapter needs its own enqueue and downstream storage measurements and still must not block the core.
- **60-second interview explanation:** Strict trace contracts preserve enum types in Python but serialize them to strings in JSON. I initially fed the JSON string back to strict validation and the evaluator failed. Reusing the existing object removed the error but timed only a list append, so I rejected that as misleading. The final benchmark constructs a fresh validated event with the enum preserved and sends it through the real fail-open emitter, which measures the boundary we actually claim.

### DBG-012 — Permissive JSON constants escaped the evaluator's typed error boundary

- **Date and commit:** 2026-08-17; uncommitted M3A.4 working tree on `693d86a`
- **Status:** Fixed
- **Expected:** Digest-bearing fixture/replay JSON and model-returned terminal arguments reject non-standard non-finite constants and duplicate object keys through sanitized typed failures.
- **Observed:** A malformed-scenario regression containing `NaN` reached canonical hashing and raised a raw `ValueError` instead of `EvaluationArtifactError`. The same audit showed that Python's permissive `json.loads` could admit `NaN` into a numeric terminal schema and could silently keep the last duplicate object key.
- **Exact reproduction command:** `uv run pytest tests/unit/agent_core/test_scenario_generator.py tests/integration/agent_core/test_replay.py -q -x`
- **Tenant, fixture, seed, and trace ID:** No tenant; temporary mutation of `fixtures/agent_core/pressure_v1.json`; seed `20260817`; no runtime trace because generation failed before submission.
- **Log, trace, screenshot, or artifact:** Pytest reported `ValueError: Out of range float values are not JSON compliant` from `_canonical_json_line`; no secret or model payload was printed.
- **Impact:** The malformed fixture did not produce a false passing evaluation, but it escaped the evaluator's declared error contract. At the terminal boundary, a non-finite number could have raised outside the required typed `malformed_arguments` path after schema validation.
- **Hypotheses considered:** Validate only numeric budget fields; rely on Pydantic after parsing; allow Python JSON extensions; reject non-finite constants and duplicate keys at every untrusted JSON parse boundary.
- **First incorrect pipeline stage:** JSON parsing before scenario digesting; the analogous risk was terminal-argument parsing before strict intent construction.
- **Root cause:** Python's standard JSON loader accepts `NaN` and infinities by default and collapses duplicate object keys, while canonical serialization and immutable core contracts intentionally reject those values.
- **Fix:** Added strict `parse_constant` and `object_pairs_hook` callbacks to evaluator fixture/event parsing and terminal-argument parsing. Added scenario/profile-bound validation before evaluation, explicit malformed-manifest handling, and regressions for non-finite constants, duplicate keys, unknown provider conditions, excessive deadlines, and malformed manifest model metadata.
- **Files and functions changed:** `src/sidestage/agent_core/evaluation.py::_load_json_object`, `_read_event_records`, and `generate_workload`; `src/sidestage/agent_core/terminal.py::decode_terminal_response`; associated M3A unit/integration tests.
- **Verification commands and results:** Strict terminal/scenario/replay tests passed with `21 passed`; the documented offline gates then passed with M3A.1 `28`, M3A.2 `22`, M3A.3 `14`, and M3A.4 `14 passed, 1 deselected`. The regenerated 20-task artifact replay matched.
- **Regression test:** `test_generator_rejects_malformed_or_unbounded_scenarios`, `test_generator_rejects_duplicate_fixture_object_keys`, the non-finite/duplicate terminal verdict cases, and `test_replay_rejects_malformed_manifest_model_with_seed`.
- **Remaining risk:** JSON returned inside a provider's terminal-call argument remains untrusted until this parser runs; provider transport failures and non-JSON response envelopes are separately mapped to `provider_error`.
- **60-second interview explanation:** Python accepts `NaN` and duplicate keys even though canonical JSON and our immutable contracts do not. The evaluator initially failed with a raw serialization error, which revealed the same risk at the model terminal boundary. I moved rejection to parsing, where untrusted bytes first become data, so fixtures fail as `EvaluationArtifactError` and model arguments fail as `malformed_arguments` before any intent or effect can exist.

### DBG-013 — GPT-5.6 Luna rejected Chat Completions function tools at its default reasoning effort

- **Date and commit:** 2026-08-17; HEAD `6d3a6e78f298476019db6885bc428753c5509784` plus the current dirty M3A working tree.
- **Status:** Fixed
- **Expected:** The existing one-request OpenAI-compatible runner should return exactly one registered `finish` terminal call when configured with `gpt-5.6-luna`.
- **Observed:** The core returned sanitized `provider_error` after about 1,273 ms with no terminal call. A sanitized direct diagnostic returned HTTP 400: function tools with reasoning effort are unsupported for Luna on Chat Completions unless reasoning effort is `none` or the request uses Responses.
- **Exact reproduction command:** `SIDESTAGE_MODEL_BASE_URL=https://api.openai.com/v1 SIDESTAGE_MODEL_API_KEY=<rotated-secret> SIDESTAGE_MODEL_ID=gpt-5.6-luna uv run pytest tests/integration/agent_core/test_live_provider.py -m live_model -q -s`
- **Tenant, fixture, seed, and trace ID:** Domain-neutral task `live-smoke-task`; no tenant, fixture, or seed; trace `live-smoke-trace`; model `gpt-5.6-luna`.
- **Log, trace, screenshot, or artifact:** Sanitized failing `LIVE_SMOKE` output in the development session; successful four-task artifacts under `runs/exploratory/agent_core_luna/`.
- **Impact:** A model-ID-only switch could not exercise M3A terminal tools, and the sanitized provider boundary intentionally hid the provider's request-validation detail from the core result.
- **Hypotheses considered:** Invalid model access; unsupported `tool_choice=required`; unsupported `parallel_tool_calls`; malformed tool schema; Luna default reasoning incompatibility with Chat Completions function tools.
- **First incorrect pipeline stage:** Provider request configuration before the one Chat Completions call.
- **Root cause:** GPT-5.6 Luna defaults to medium reasoning. Its Chat Completions endpoint rejects function tools at that effort and requires `reasoning_effort=none`; the M3A runner previously had no explicit reasoning-effort configuration.
- **Fix:** Added an optional allowlisted reasoning-effort field to `OpenAICompatibleModelConfig`, conditionally projected it into the provider request, exposed optional `SIDESTAGE_MODEL_REASONING_EFFORT` to the live smoke and evaluator, and retained it in the sanitized live manifest. The Luna run uses `none`; unspecified providers retain the previous omitted-field behavior.
- **Files and functions changed:** `src/sidestage/agent_core/model.py::OpenAICompatibleModelConfig` and `OpenAICompatibleModelRunner.run`; `src/sidestage/agent_core/evaluation.py`; live and unit agent-core tests; TDD and milestone evidence notes.
- **Verification commands and results:** Focused offline configuration/generator tests passed with `17 passed`. The corrected Luna smoke passed with one `finish` terminal call, about 1,186 ms provider time, and about 1,187 ms total core time. The four-task live matrix returned 4/4 expected outcomes, four complete traces, zero failures, and zero effects; provider p95 was about 1,065 ms, queue p95 about 1,015 ms, and total core p95 about 2,057 ms, a miss against the 1,450 ms generic budget.
- **Regression test:** `test_openai_compatible_runner_maps_one_http_request`, `test_openai_compatible_runner_omits_unspecified_reasoning_effort`, and `test_live_manifest_records_endpoint_and_model_without_credentials`.
- **Remaining risk:** Four samples establish compatibility but not a stable p95. With two workers, the declared four-task burst queues a second wave and misses the generic core budget even though provider p95 is below the budget. Luna is not yet the selected production model, and the SideStage two-request end-to-end boundary remains unmeasured.
- **What I personally did:** The builder selected Luna as the candidate, confirmed credential rotation, and authorized the live calls.
- **What AI suggested:** Preserve the generic core and add the smallest provider-specific reasoning option rather than coupling Luna behavior to agent profiles.
- **What I rewrote or rejected:** Rejected both silently accepting Luna's medium default and migrating to Responses during the model comparison, because either would make the compatibility or latency result ambiguous.
- **60-second interview explanation:** The model swap initially failed even though Luna supports function tools. The provider explained that Luna's medium default is incompatible with function tools on Chat Completions. I kept the agent contract unchanged, made reasoning effort an optional provider setting, and ran Luna at `none`. The terminal contract then passed, but the four-task burst exposed a separate queue-capacity issue: provider latency was near one second while the second worker wave pushed total core latency above two seconds.

### DBG-014 — M2.3 reload silently replaced the opaque server session

- **Date and commit:** 2026-08-17; discovered after `6d3a6e7`, fixed and regression-tested in `734d151`.
- **Status:** Fixed
- **Expected:** Reloading the seller workspace reuses the opaque server-issued session, reconstructs the same SQLite state, and resumes SSE from the current persisted offset.
- **Observed:** Marketplace state appeared correct after reload, but the browser test found that the session token changed. The initial boot path always issued a new demo session for the default seller, masking the replacement because both sessions resolved to the same deterministic seller/show state.
- **Exact reproduction command:** `uv run pytest tests/e2e/test_marketplace_ui.py -q`
- **Tenant, fixture, seed, and trace ID:** `sel_velocity_kicks`; default prepared-chat seed `20260817`; session IDs were intentionally omitted from the log; no reply-agent trace exists because Copilot is off.
- **Log, trace, screenshot, or artifact:** Playwright failed the post-reload token equality assertion while the active SKU and two chat events had already converged correctly.
- **Impact:** Durable marketplace state was not lost, but reconnect semantics were weaker than the UI implied: every reload reset session identity and opened a fresh SSE subscription instead of restoring the established projection boundary.
- **Hypotheses considered:** `sessionStorage` was cleared on reload; the server forgot the session; seller state was reconstructed from browser storage; application boot ignored the stored opaque token.
- **First incorrect pipeline stage:** Browser bootstrap before snapshot restoration and SSE connection.
- **Root cause:** `boot()` populated sellers and unconditionally called `setActiveSeller()`, which always POSTed `/api/demo/sessions`; it never attempted the stored token's snapshot endpoint.
- **Fix:** Added `restoreSession()`. Boot now asks the backend for the stored token's authoritative snapshot, renders it, and reconnects SSE; only an absent or rejected token falls back to issuing a new demo session. Browser marketplace state remains absent from `localStorage`.
- **Files and functions changed:** `src/sidestage/web/static/app.js::boot` and `restoreSession`; `tests/e2e/test_marketplace_ui.py`.
- **Verification commands and results:** Against `734d151`, the focused M2.3 gate passed with `11 passed in 3.35s`; the complete deterministic suite passed with `161 passed, 2 deselected in 4.50s`; and the complete M2 gate passed again during closeout with `75 passed in 4.71s`. With workstation port `8000` occupied by an unrelated Uvicorn process, the same application command on port `8766` returned `200` for `/app/` and `/api/sellers`, including all three approved seller personas.
- **Regression test:** `test_non_ai_marketplace_flow_is_server_owned_and_reconnectable` asserts stable opaque session identity, unchanged active SKU and chat after reload, zero browser-local marketplace records, and second-page convergence through snapshot plus SSE.
- **Remaining risk:** Demo sessions are intentionally in-process and synthetic; a full process restart requires a newly issued opaque session, while persisted seller/show/chat/receipt state remains in SQLite. Production authentication is outside this prototype.
- **What I personally did:** The builder required server-owned state, reconnect correctness, and no browser-local authority.
- **What AI suggested:** Restore the opaque token before issuing a session and add a second-page SSE convergence assertion.
- **What I rewrote or rejected:** Did not weaken the test to accept state-only convergence, because that would hide session churn and fail to prove the intended reconnect path.
- **60-second interview explanation:** The first browser reconnect test looked healthy—the SKU and chat survived—but it compared the opaque token and exposed that every reload silently created a new session. The deterministic show ID hid the bug. I changed boot to restore the existing token through the server snapshot first, then reconnect SSE from the persisted offset. A new token is created only when restoration genuinely fails.

### DBG-015 — Runtime debugger sent its placeholder label as an actual-route filter

- **Date and commit:** 2026-08-17; uncommitted M3B.4 working tree on `734d151`
- **Status:** Fixed
- **Expected:** Opening the debugger after accepting messages fetches the unfiltered runtime projection, then replaces the placeholder with the backend's allowed actual-route filters.
- **Observed:** The runtime trace panel reported `Unable to load runtime data (400)` even though two complete traces were persisted and directly readable through the API.
- **Exact reproduction command:** `.venv/bin/pytest tests/e2e/test_debugger.py -q`
- **Tenant, fixture, seed, and trace ID:** `sel_velocity_kicks`; custom eligible and noise messages; no generated-fixture oracle or seed; trace IDs were runtime-generated and intentionally omitted from this log.
- **Log, trace, screenshot, or artifact:** Playwright expected `2 persisted traces` but observed the HTTP 400 UI message. The backend integration projection test passed independently, isolating the error to browser bootstrap.
- **Impact:** The new persisted trace API worked, but a fresh debugger page could not display any M3B trace until a valid filter value existed.
- **Hypotheses considered:** Missing session token; trace projection schema mismatch; invalid tenant scope; browser placeholder accidentally treated as a request value.
- **First incorrect pipeline stage:** Debugger browser bootstrap before the read-only projection request; the eight-stage reply pipeline had already completed correctly.
- **Root cause:** The disabled placeholder `<option>` had no explicit value. The DOM therefore exposed its display label, `Loading runtime filters…`, and `renderRuntimeTraces()` sent that text as `actual_route`; the backend correctly rejected the unknown filter.
- **Fix:** Give the initial placeholder the neutral value `all`, which intentionally omits `actual_route` on the first request. The backend response then supplies the only selectable route filters.
- **Files and functions changed:** `src/sidestage/web/static/debug.html` initial `#trace-scenario` option; browser regression test in `tests/e2e/test_debugger.py`.
- **Verification commands and results:** The immediate `.venv/bin/pytest tests/e2e/test_debugger.py -q` rerun passed with `1 passed in 2.00s`; the backend projection contract separately passed with `1 passed in 0.49s`.
- **Regression test:** `test_debugger_renders_and_filters_real_eight_stage_runtime_traces` requires the fresh page to show two traces, switch between actual eligible/noise routes, render eight stages and the registered-agent identity, and make no request for the old presentation fixture.
- **Remaining risk:** The debugger is intentionally session-scoped and read-only; opening it without first creating a seller session shows a bounded empty-state message.
- **What I personally did:** The builder required the debugger to associate registration and workflow behavior with inspectable runtime evidence.
- **What AI suggested:** Source filter values from the backend projection and make the pre-fetch value explicitly neutral.
- **What I rewrote or rejected:** Did not loosen backend filter validation, because accepting arbitrary labels would hide client bugs and weaken the actual-versus-expected route boundary.
- **60-second interview explanation:** The persisted traces were correct, but the browser sent its loading label as though it were a real route. The API rejected it, which was the right behavior. I made the initial value explicitly `all`, so the first request is unfiltered and every later filter comes from the backend's allowlist.

### DBG-016 — Product-mention routing helper accidentally ended the router class

- **Date and commit:** 2026-08-18; uncommitted M3B.5 working tree on `734d151`
- **Status:** Fixed
- **Expected:** A unique product or listing name should bind exactly like a unique explicit SKU, while every existing router method remains callable.
- **Observed:** All seven focused routing tests failed with `AttributeError: 'CopilotRouter' object has no attribute '_insert_question_row'` immediately after adding product-name recognition.
- **Exact reproduction command:** `.venv/bin/pytest tests/integration/test_copilot_routing.py -q`
- **Tenant, fixture, seed, and trace ID:** Synthetic `sel_velocity_kicks`; custom messages; no generated seed; runtime-generated trace IDs were omitted.
- **Log, trace, screenshot, or artifact:** Pytest reported seven failures from `CopilotRouter.normalize_and_deduplicate`; the first missing method was `_insert_question_row`.
- **Impact:** The dirty development tree could not route any message. No committed or retained evaluation evidence was affected.
- **Hypotheses considered:** Stale import cache; misspelled method; incorrect indentation after inserting a module helper.
- **First incorrect pipeline stage:** Stage 2 normalization/deduplication before any analysis or model request.
- **Root cause:** The new module-level `_explicit_product_mention` helper was inserted between class methods at zero indentation, ending `CopilotRouter`; the following indented methods became nested in the helper rather than members of the class.
- **Fix:** Moved the helper above `CopilotRouter` and restored the existing methods to the class body.
- **Files and functions changed:** `src/sidestage/copilot/routing.py`; the focused name-binding regression in `tests/integration/test_copilot_routing.py`.
- **Verification commands and results:** `.venv/bin/pytest tests/integration/test_copilot_routing.py -q` passed with `7 passed in 0.42s`.
- **Regression test:** `test_unique_product_name_cannot_be_answered_from_the_wrong_active_listing` also proves an unseen named product needs seller clarification and a previously shown named product is not silently rebound.
- **Remaining risk:** Recognition intentionally uses only exact SKU, model name, listing title, or brand-plus-model aliases; nicknames and fuzzy references remain uncertain and fail closed.
- **What AI suggested:** Extend the accepted explicit-reference rule with exact seller-owned aliases and add the negative wrong-listing case before running pressure.
- **What I rewrote or rejected:** Rejected fuzzy matching and colorway-only matching because either could create false product authority.
- **60-second interview explanation:** While closing a genuine wrong-product safety gap, I placed a helper at the wrong indentation and accidentally ended the router class. The focused suite failed every route immediately, so nothing unsafe progressed. Moving the helper above the class restored the router, and the new regression now proves named products cannot borrow evidence from the active listing.

### DBG-017 — Debugger SSE refresh displaced the stage being inspected

- **Date and commit:** 2026-08-18; uncommitted M3B.5 working tree on `734d151`
- **Status:** Fixed
- **Expected:** Selecting stage 5 on a persisted research trace continues to show its evidence snapshot while routine SSE-driven projection refreshes arrive.
- **Observed:** The stage title briefly showed `Evidence Retrieval`, but its output changed to stage 8 publication and end-to-end latency artifacts during the golden browser test.
- **Exact reproduction command:** `.venv/bin/pytest tests/e2e/test_golden_demo.py -q`
- **Tenant, fixture, seed, and trace ID:** Synthetic `sel_velocity_kicks`; custom Aero Dash research question; no generated seed; runtime trace ID omitted.
- **Log, trace, screenshot, or artifact:** Playwright expected `synthetic_seller_data` in `#trace-stage-output` but observed `publication` and `end_to_end_latency` artifacts even though the direct backend projection contained the correct stage-5 `release_date` evidence.
- **Impact:** Runtime evidence remained correct and persisted, but a developer could be moved away from the selected stage while reading it and misinterpret which artifacts belonged to the visible title.
- **Hypotheses considered:** Artifact-stage persistence corruption; projection grouping defect; stale locator; SSE refresh resetting client selection.
- **First incorrect pipeline stage:** Read-only debugger rendering after all eight backend stages had completed correctly.
- **Root cause:** `renderRuntimeTraces()` preserved the selected trace ID but unconditionally reset `activeStageNumber` to the trace's decisive stage on every refresh.
- **Fix:** Preserve the prior stage number when the same trace remains selected and still contains that stage; choose the decisive stage only for a genuinely new trace.
- **Files and functions changed:** `src/sidestage/web/static/debugger.js::renderRuntimeTraces`; `tests/e2e/test_golden_demo.py`.
- **Verification commands and results:** The localhost/Chromium golden path passed with `1 passed in 3.24s`, including stage-5 provenance inspection and screenshot capture.
- **Regression test:** `test_golden_demo_proves_review_auto_research_race_and_debugger` selects the research trace and stage 5 while the debugger's live connection is active, then requires the rendered `release_date` and `synthetic_seller_data` provenance.
- **Remaining risk:** Changing filters or selecting a different trace intentionally chooses that trace's decisive stage; the debugger does not preserve separate per-trace stage selections.
- **What AI suggested:** Preserve the selected stage only when the same trace survives refresh, avoiding a global or stale stage index.
- **What I rewrote or rejected:** Rejected adding an arbitrary browser delay, because it would hide the refresh race instead of fixing the interaction.
- **60-second interview explanation:** The backend trace was right, but the live debugger kept resetting to stage 8 whenever SSE refreshed. That made the heading and payload look mismatched during inspection. I preserved the stage number only for the same trace, so live refreshes update data without stealing the developer's place.

### DBG-018 — Two-call Luna pressure runs missed correctness and latency gates

- **Date and commit:** 2026-08-18; uncommitted dirty M3B.5 tree on `734d151`
- **Status:** Diagnosed
- **Expected:** The 360-chat, three-seller live workload should reach at least 95% supported answerable suggestions, preserve exact route labels, and keep real-model end-to-end p95 below two seconds.
- **Observed:** The first `gpt-5.6-luna` run at `reasoning_effort=none` produced 19/72 supported answerable suggestions, 31 route mismatches, 86 SLO misses, six hard timeouts, and 3,709.36 ms total p95. After prompt/fixture diagnostics, the second run improved to 48/72 supported answerable suggestions and three route mismatches, but produced 94 SLO misses, 17 hard timeouts, and 4,981.32 ms total p95. After the separate strict-schema compatibility incident in DBG-020 was fixed, the latest valid run reached 54/72 supported suggestions with zero route mismatches, 91 SLO misses, 14 hard timeouts, and 4,530.28 ms p95. It safely handled 24/24 ambiguous or unsupported cases, 24/24 prompt injections, and 60/60 duplicate children, with every hard safety/trace invariant at zero.
- **Exact reproduction commands:** First: `set -a; source .env >/dev/null 2>&1; set +a; SIDESTAGE_MODEL_ID=gpt-5.6-luna SIDESTAGE_MODEL_REASONING_EFFORT=none .venv/bin/python -m sidestage.trace.evaluator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --model live --output runs/exploratory/evaluation_live_precommit.json`. Second: the same command with output `runs/exploratory/evaluation_live_precommit_v2.json`. These historical commands are retained exactly, but `.env` is a bare-key file and was not the effective exported credential source; do not reuse the `source .env` prefix. Follow the current README no-echo mapping instead.
- **Tenant, fixture, seed, and trace ID:** All three synthetic sellers; `pressure_v1`; seed `20260817`; individual trace IDs are retained only in the sanitized report's mismatch records.
- **Log, trace, screenshot, or artifact:** `runs/exploratory/evaluation_live_precommit.json`, `evaluation_live_precommit_v2.json`, and the latest valid `evaluation_live_precommit_v4.json`; credential scans found no API key, bearer token, or authorization value. The v3 fast-failure artifact is documented separately in DBG-020 and is not latency evidence.
- **Impact:** Luna compatibility is established, but this run cannot support the final correctness or sub-two-second claim. It remains dirty `Implemented` evidence, never `Measured` evidence.
- **Hypotheses considered:** Unclear classification instructions; natural paraphrases failing exact deterministic support; queue pressure alone; one slow provider stage; the fundamental sum of two sequential model calls.
- **First incorrect pipeline stage:** Correctness first diverged at stage 4 classification and stage 7 support validation. Latency accumulated across stage 4, stage 6, and queue wait rather than a local database stage.
- **Root cause:** The initial analysis policy did not spell out the accepted intent/fact taxonomy, and the reply profile allowed paraphrases that the deterministic claim checker could reject. The first workload also allowed multi-product questions to be evaluated while only one current listing was active, which correctly exposed wrong-product binding rather than stable answer coverage. Tightening those contracts improved correctness, but the latest valid run confirms the latency problem is architectural for this model/workload: median analysis was 1,130.13 ms, median registered reply-agent time was 1,080.50 ms, and burst queue p95 was 2,568.65 ms. Two sequential calls already exceed the two-second target near the median before burst queueing.
- **Fix applied and remaining:** Tightened the analysis taxonomy, required the bounded reply agent to copy one relevant evidence value and ID exactly, separated exactly 24 stable `pressure_answerable` candidates per seller from broader presentation/temporal pools, added per-bucket diagnostics, added provider-compatible strict schemas, made high-certainty reaction routing deterministic, and made tenant/listing/fact-scoped research fall back from unmatched FTS vocabulary to the one trusted exact record. The latest valid live run removes all route mismatches and improves supported coverage to 54/72 before the final retrieval fallback, but cannot remove the sequential latency sum. A call-path or model change requires builder review.
- **Files and functions changed:** `fixtures/chat_messages.json`; `src/sidestage/copilot/analysis.py::_SYSTEM_POLICY`; `src/sidestage/copilot/profile.py::build_livesell_reply_profile`; `src/sidestage/copilot/routing.py`; `src/sidestage/fixtures/generator.py`; `src/sidestage/agent_core/model.py`; `src/sidestage/trace/pressure.py::_pressure_report`.
- **Verification commands and results:** Offline profile, routing, analysis, retrieval, scheduler, provider-map, and scripted pressure regressions pass. The latest valid live report (`evaluation_live_precommit_v4.json`) has every hard invariant at zero and zero route mismatches, but still fails coverage and p95 as described above. The final deterministic audit passes with `262 passed, 3 deselected in 40.28s`; scripted pressure and all ten scripted safety cases pass.
- **Regression test:** The scripted pressure test requires 72/72 supported answerable parents and explicit zero-valued safety invariants; live behavior remains an external measurement rather than a deterministic regression.
- **Remaining risk:** Even perfect correctness leaves the two sequential Luna calls over budget under the approved burst profile. Changing the common-path call count or selected model is an architecture/product decision; removing queue time, weakening the workload, or relaxing guardrails would only hide the failure.
- **What AI suggested:** First remove avoidable prompt/claim-contract errors and rerun the same fixed workload; keep the latency result separate from correctness.
- **What I rewrote or rejected:** Rejected weakening the broker, relabeling safe-but-different model routes as passes, excluding queue time, or claiming accelerated scripted latency as the SLO.
- **60-second interview explanation:** The first real SideStage pressure run was safe but not good enough. I separated wrong-product fixture problems from model-contract problems, tightened both, and reran the identical fixed workload. The latest valid run improved coverage from 19/72 to 54/72, removed every route mismatch, and kept all safety buckets clean, but p95 remained 4.53 seconds because the two sequential calls each take about 1.1 seconds at the median and the burst queues. The honest conclusion is that the accepted two-call Luna common path cannot currently meet two seconds; I did not hide queue time or weaken the broker.

### DBG-019 — Documented Uvicorn factory silently used an empty scripted runner

- **Date and commit:** 2026-08-18; uncommitted M3B.5 audit tree on `734d151`
- **Status:** Fixed
- **Expected:** The reviewer-facing end-to-end Uvicorn command constructs the selected live runner from exported configuration, fails before accepting chat when required configuration is absent, and never records the credential.
- **Observed:** The documented command targeted `create_app()`, whose deliberate deterministic default is `ScriptedModelRunner(())`. The UI and M3B pipeline started, but every eligible un-injected Copilot request exhausted the empty runner instead of reaching the configured live provider.
- **Exact reproduction command:** `rg -n "configured_runner|ScriptedModelRunner|create_app" src/sidestage/app.py README.md docs/TDD.md`
- **Tenant, fixture, seed, and trace ID:** No tenant or message was required; the mismatch existed at application construction before session/chat acceptance.
- **Log, trace, screenshot, or artifact:** Source inspection showed `configured_runner = model_runner or ScriptedModelRunner(())` while the only documented Uvicorn factory supplied no injected runner.
- **Impact:** Deterministic tests and the explicit live pressure evaluator were unaffected, but the claimed reviewer run command was not a live-model prototype command.
- **Hypotheses considered:** Uvicorn injects a runner automatically; `create_app()` loads `.env`; an environment-based wrapper already exists; the empty runner is intentional only for tests.
- **First incorrect pipeline stage:** Deployment construction before startup profile registration.
- **Root cause:** Dependency injection correctly kept credentials out of the generic factory, but there was no separate environment adapter joining that port to the reviewer process.
- **Fix:** Added `create_live_app()`. It requires `OPENAI_API_KEY` or scoped `SIDESTAGE_MODEL_API_KEY` plus `SIDESTAGE_MODEL_ID`, builds one shared strict OpenAI-compatible runner, records only sanitized model metadata, closes the owned HTTP client at shutdown, and fails before database initialization when configuration is incomplete. `create_app()` remains the credential-free deterministic injection factory.
- **Files and functions changed:** `src/sidestage/app.py::create_live_app`; `tests/integration/test_live_app_factory.py`; run commands and boundaries in `README.md`, `docs/TDD.md`, and both M3B plans.
- **Verification commands and results:** The RED import failed because `create_live_app` did not exist. The focused factory test then passed with `3 passed in 0.37s`; the expanded M3B.5 latency/factory/golden gate passed with `10 passed, 1 deselected in 19.39s` without a network call or persisted secret. The separately marked reviewer-path smoke then exercised both Luna calls, the R2 card, and the complete debugger trace with `1 passed in 2.67s`.
- **Regression test:** Missing-key pre-database failure, strict Luna configuration mapping, scoped-key precedence, sanitized state/repr, seller endpoint startup, shutdown cleanup, and the separately marked full two-call path execute in `tests/integration/test_live_app_factory.py`.
- **Remaining risk:** The live factory makes the prototype runnable but does not fix the two-call Luna correctness or latency release failure recorded in DBG-018.
- **What AI suggested:** Keep deterministic dependency injection and add one narrow deployment adapter rather than teaching the domain pipeline to read environment variables.
- **What I rewrote or rejected:** Rejected silently switching `create_app()` to live behavior because that would make the default deterministic suite credential-dependent and blur test versus deployment modes.
- **60-second interview explanation:** The model adapter worked in tests and the pressure harness, but the README command used the generic factory with an intentionally empty scripted runner. The app looked complete while eligible replies failed closed. I added a separate fail-fast live factory that owns environment parsing and HTTP cleanup, kept secrets out of application state, and retained the generic factory for deterministic injection. The reviewer command now actually wires the chosen model.

### DBG-020 — Strict provider schema rejected every live analysis request

- **Date and commit:** 2026-08-18; uncommitted M3B.5 audit tree on `734d151`
- **Status:** Fixed
- **Expected:** Enabling `strict=true` adds provider-side structural enforcement while the complete local Draft 2020-12 schema remains authoritative for every returned terminal call.
- **Observed:** The v3 live run returned `provider_error` for all 135 analysis requests. No request reached evidence retrieval or the registered reply agent. The resulting 915.97 ms p95 had zero SLO misses only because work failed early, while answerable coverage was 0/72 and 60 expected-route comparisons failed.
- **Exact reproduction command:** `set -a; source .env >/dev/null 2>&1; set +a; SIDESTAGE_MODEL_ID=gpt-5.6-luna SIDESTAGE_MODEL_REASONING_EFFORT=none .venv/bin/python -m sidestage.trace.evaluator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --model live --output runs/exploratory/evaluation_live_precommit_v3.json`. This historical command is retained exactly, but `.env` is a bare-key file and was not the effective exported credential source; do not reuse the `source .env` prefix. Follow the current README no-echo mapping instead.
- **Tenant, fixture, seed, and trace ID:** All three synthetic sellers; `pressure_v1`; seed `20260817`; failing trace IDs are retained in the sanitized v3 report.
- **Log, trace, screenshot, or artifact:** `runs/exploratory/evaluation_live_precommit_v3.json`; the credential scan remained clean.
- **Impact:** Safety failed closed, but strict mode made the live product unusable and produced a misleadingly low latency number that cannot be treated as SLO evidence.
- **Hypotheses considered:** Provider outage; rate limit; unsupported model; strict-schema keyword rejection; invalid endpoint reasoning setting.
- **First incorrect pipeline stage:** Stage 4 provider request before analysis decoding or retrieval.
- **Root cause:** SideStage sent its complete local JSON Schema as the provider strict schema. The local contract uses `uniqueItems`, `minLength`, `maxLength`, and `const`; [OpenAI Structured Outputs accepts only a subset and rejects unsupported strict schemas](https://developers.openai.com/api/docs/guides/structured-outputs).
- **Fix:** Preserve the complete immutable schema for startup compilation and local terminal validation, but recursively project a provider-only strict subset: omit local-only length/uniqueness constraints and map `const` to a one-value `enum`. The projection never mutates or weakens the local registered schema.
- **Files and functions changed:** `src/sidestage/agent_core/model.py::_openai_strict_schema`; `tests/unit/agent_core/test_model_runner.py`.
- **Verification commands and results:** The RED provider-map tests failed on the unprojected keywords. The focused runner suite passed with `11 passed in 0.21s`; the combined model/analysis/profile suite passed with `28 passed in 0.32s`. The identical v4 live workload progressed through retrieval and reply generation, reached 54/72 supported suggestions, had zero route mismatches and zero hard-invariant violations, and exposed the genuine 4,530.28 ms p95 instead of the fast-failure artifact.
- **Regression test:** `test_strict_provider_projection_preserves_local_only_schema_validation` checks recursive keyword projection, one-value enum conversion, non-mutation of the registered schema, and secret-free provider payloads.
- **Remaining risk:** Strict structural output cannot enforce semantic equality between `reply_text`, claim spans, and evidence values; local decoding and the independent broker continue to fail those cases closed. The two-call latency gate remains open.
- **What AI suggested:** Treat the v3 low latency as invalid, inspect the first failed stage, and project the documented provider subset without deleting local validation constraints.
- **What I rewrote or rejected:** Rejected disabling local constraints, accepting provider errors as safe scorecard passes, or reporting the fast-failure p95 as a performance improvement.
- **60-second interview explanation:** Turning on strict tools made every analysis call fail before retrieval. The API only supports a JSON Schema subset, while our local contract was deliberately richer. I kept the full schema for local enforcement and generated a smaller provider copy. The next identical run reached the real pipeline with zero route mismatches, proving the fix; its 4.53-second p95 also confirmed that the earlier 916 ms number was only fast failure.

### DBG-021 — Stale SSE refresh intermittently overwrote a newer R3 response

- **Date and commit:** 2026-08-18; uncommitted M3B.5 audit tree on `734d151`
- **Status:** Fixed
- **Expected:** After the authenticated R3-enable POST returns a snapshot with capability version 2, the browser keeps that newer projection and renders `Auto-reply on`.
- **Observed:** One full deterministic run failed the golden demo because the label returned to `Review first` after the click. The same test passed immediately in isolation, indicating an ordering-sensitive browser projection rather than a deterministic authorization refusal.
- **Exact reproduction command:** `.venv/bin/pytest -q`; observed result `1 failed, 261 passed, 3 deselected in 43.64s`, failing at `tests/e2e/test_golden_demo.py:230`.
- **Tenant, fixture, seed, and trace ID:** Velocity Kicks synthetic seller in the fixed golden demo; no retained trace ID because the defect was in browser snapshot ordering after successful server operations.
- **Log, trace, screenshot, or artifact:** Pytest traceback in the active Codex task; focused rerun passed before the fix, confirming intermittence.
- **Impact:** The backend capability remained versioned and safe, but the browser could display stale R2 state after an R3 change and issue later commands from an old capability projection.
- **Hypotheses considered:** R3 authorization refusal; stale expected version; seller-decision transaction failure; an older SSE-triggered snapshot read completing after the POST response.
- **First incorrect pipeline stage:** Browser projection after a successful HTTP command and concurrent SSE refresh.
- **Root cause:** `refreshSnapshot()` unconditionally installed any completed snapshot. A request started before the R3 transaction could return after the POST handler had already rendered its newer snapshot, overwriting it despite carrying a lower persisted `stream_offset`.
- **Fix:** Reject an asynchronous refresh whose `stream_offset` is lower than the currently rendered snapshot. Server offsets remain the monotonic ordering authority; direct POST responses continue to render normally.
- **Files and functions changed:** `src/sidestage/web/static/app.js::refreshSnapshot`; streaming-order text in `docs/TDD.md`.
- **Verification commands and results:** Focused golden/R3 browser tests passed with `2 passed in 4.60s`; the complete deterministic suite then passed with `262 passed, 3 deselected in 40.28s`; the expanded M3B.5 group passed with `10 passed, 1 deselected in 19.39s`.
- **Regression test:** Existing golden and R3 browser tests exercise capability enable/disable amid SSE-backed state changes; the monotonic guard makes an observed stale response unable to replace a newer projection.
- **Remaining risk:** The browser trusts the server-issued offset and does not merge snapshots field by field. A future remote projection service would need the same or stronger monotonic revision contract.
- **What AI suggested:** Treat the isolated pass as evidence of a race, inspect direct-response and SSE refresh ordering, and use the already persisted stream offset as the projection fence.
- **What I rewrote or rejected:** Rejected adding sleeps or retrying the assertion because either would hide the stale-state bug without enforcing ordering.
- **60-second interview explanation:** HTTP commands and SSE both refresh the same screen. An older SSE read could finish after the R3-enable response and redraw the old capability. The backend was correct, but the screen regressed. Every snapshot already has a monotonic stream offset, so the browser now ignores a refresh older than what it has rendered. The full suite passes without timing sleeps.

### DBG-022 — Sandbox network and localhost restrictions produced false validation failures

- **Date and commit:** 2026-08-18; uncommitted M3B.5 audit tree on `734d151`
- **Status:** Fixed operationally
- **Expected:** The explicit live smoke can contact the configured provider, and deterministic browser/server tests can bind ephemeral loopback ports.
- **Observed:** Without the required execution permission, the live smoke returned a sanitized `provider_error` in under half a second and a single-call smoke reported about 2 ms provider time. The full suite separately produced six `PermissionError: [Errno 1] Operation not permitted` failures while binding `127.0.0.1`; `uv lock --check` was also denied access to uv's read-only cache.
- **Exact reproduction commands:** `SIDESTAGE_MODEL_ID=gpt-5.6-luna SIDESTAGE_MODEL_REASONING_EFFORT=none .venv/bin/pytest tests/integration/test_live_app_factory.py::test_live_app_factory_executes_the_real_two_call_r2_path -m live_model -q -s`; `.venv/bin/pytest -q`; and `uv lock --check` in the restricted sandbox.
- **Tenant, fixture, seed, and trace ID:** Velocity Kicks for the live smoke; normal deterministic test fixtures for loopback failures; no product trace established for the blocked provider request.
- **Log, trace, screenshot, or artifact:** Sanitized pytest output in the active Codex task; no response body or credential was recorded.
- **Impact:** The first outputs looked like provider and product regressions but did not exercise the intended external or loopback boundaries, so they are excluded from correctness and latency evidence.
- **Hypotheses considered:** Provider schema failure; rate limit; invalid credential; R3/golden regression; restricted outbound networking and socket binding.
- **First incorrect pipeline stage:** Execution environment before provider connection or local-server startup.
- **Root cause:** The managed sandbox denied outbound provider access and local socket binding for those commands.
- **Fix:** Rerun the same bounded pytest commands with explicit network/localhost permission; do not change product code to work around the sandbox.
- **Files and functions changed:** This incident entry only.
- **Verification commands and results:** With the required permission, the two-call live smoke passed with `1 passed in 2.67s`; after the separate DBG-021 UI fix, the complete deterministic suite passed with `262 passed, 3 deselected in 40.28s`; the lock check resolved 47 packages successfully.
- **Regression test:** Operational verification must grant the declared provider or localhost boundary; default tests still exclude `live_model`.
- **Remaining risk:** A fast `provider_error` remains intentionally sanitized, so execution-boundary denial must be distinguished using the command environment and elapsed time rather than provider response text.
- **What AI suggested:** Rerun the exact command with only the missing execution boundary enabled before diagnosing application behavior.
- **What I rewrote or rejected:** Rejected treating blocked fast failures as provider latency or changing fail-closed product behavior to expose raw provider errors.
- **60-second interview explanation:** Two validations failed before reaching the system boundary: the live test could not access the network, and browser tests could not bind localhost. The error handling correctly failed closed, which made them resemble product failures. Running the same bounded commands with the necessary permission separated environment denial from real behavior; the live path and full suite then passed.

### DBG-023 — Natural-language size wording is not deterministically bound to one trusted variant

- **Date and commit:** 2026-08-18; fixed and committed at `12f3bab`
- **Status:** Fixed, not commit-bound `Verified`
- **Expected:** Semantically equivalent size requests `US M 9`, `9 M US`, `Men's US 9`, `9 for men`, and `9 for man` resolve to the same trusted variant of the immutable bound listing. Attribute order must not matter. A missing sizing system or audience may be inferred only through a unique trusted candidate; zero candidates must produce `missing_evidence` and multiple candidates `ambiguous`. Exact questions may expose at most that one resolved variant record to a model. General questions such as `What sizes are available?` and `How many pairs are left across all sizes?` must not expose the complete per-variant evidence array.
- **Observed:** On `two_call_draft`, the evidence-planner model was instructed to manufacture a canonical free-text label, and retrieval performed case-insensitive exact-label membership. A reordered phrase could fail, while a wrong-but-real label could retrieve the wrong grounded row. On `one_call_template`, application code supplied every bounded variant record and allowed the model to choose among them; evidence membership did not prove semantic correspondence to buyer wording. General availability also required selecting the complete variant array.
- **Exact reproduction command:** `rg -n "For a size, emit|variant_mentions|requested_labels|len\\(matches\\) != 1|copy only the matching trusted variant_id|selected variant is absent or ambiguous|size 9|US M 9\\.5" src/sidestage/copilot/analysis.py src/sidestage/copilot/retrieval.py src/sidestage/copilot/profile.py src/sidestage/copilot/templates.py fixtures/chat_messages.json tests/integration/test_analysis.py tests/integration/test_retrieval.py tests/integration/test_latency_accounting.py`
- **RED test evidence:** `uv run pytest tests/unit/test_variant_resolution.py -q` produced `ModuleNotFoundError: No module named 'sidestage.copilot.variants'`. After the test contract existed, `uv run pytest tests/integration/test_retrieval.py -q` produced `5 failed, 4 passed`, with both retrieval contexts rejecting the new trusted raw-question field. The first combined GREEN attempt, `uv run pytest tests/unit/test_variant_resolution.py tests/integration/test_retrieval.py -q`, produced `1 failed, 25 passed` because `size 99` was incorrectly classified as a general summary. The regex was narrowed to explicit plural/all-size wording. A later anti-model-number refinement run, `uv run pytest tests/unit/test_variant_resolution.py tests/integration/test_retrieval.py tests/integration/test_template_workflow.py tests/integration/test_variant_workflows.py -q`, produced `1 failed, 45 passed`: the alternation matched `men` before `men's`, leaving the possessive suffix outside the audience token. Ordering possessive/plural forms before prefixes restored `men's 9` and the same command then passed `46 passed in 3.59s`.
- **Tenant, fixture, seed, and trace ID:** Velocity Kicks synthetic tenant, `show_velocity_kicks`, and bound listing `lst_velocity_aero_dash`; no random seed. Focused FastAPI tests create isolated trace IDs in temporary SQLite databases; this fix is represented by retained pytest cases rather than one retained runtime trace artifact.
- **Log, trace, screenshot, or artifact:** The RED behavior and final contracts are retained in the focused pytest cases and this incident entry. No provider credential, model transcript, or full inventory array is retained as evidence.
- **Impact:** A legitimate availability question may unnecessarily become `Needs seller`, increasing operator load, or may produce a factually grounded answer for the wrong existing variant. The issue does not grant cross-tenant access, database-write authority, or direct send authority: retrieval remains bound to the trusted listing and all effects still pass through the broker. It is nevertheless a material semantic-correctness defect for the primary live-selling workflow.
- **Hypotheses considered:** Case-folding or token reordering alone would be sufficient; the model could canonicalize labels reliably; membership in trusted evidence would prove semantic correspondence; passing a compact candidate-ID list would be safe enough; all availability could bypass the workflows; typed application-owned candidate resolution plus one exact or aggregate record was required.
- **First incorrect pipeline stage:** Before the fix, stage 4 on `two_call_draft` created variant identity from untrusted free text, while stage 6 on `one_call_template` selected among all real variants without a deterministic question-to-variant proof. The corrected boundary runs inside application-owned stage-5 evidence retrieval before either reply model can see inventory evidence.
- **Root cause:** The application had no shared typed representation or deterministic resolver between raw buyer wording and trusted catalog variants. Variant identity therefore depended on model semantic accuracy even though tenant/listing membership was validated later.
- **Fix:** Added `src/sidestage/copilot/variants.py` with closed size-system, audience, decimal-size, resolution-status, and summary-kind types. Trusted labels and buyer wording are parsed into the same attributes; numbers require size/system/audience context so product/model numbers are ignored. Candidate filtering uses only the bound listing and accepts exactly one result. Both retrieval contexts now carry application-owned raw question text. `variant_mentions` was removed from the `two_call_draft` planner schema and contract; old responses containing it are malformed. `one_call_template` resolves before model projection. Exact resolution yields one inventory record, ambiguity/missing fails before the reply model, unrelated questions yield no inventory record, and general availability yields one aggregate `availability_summary` record containing available labels and total quantity. The aggregate is R2-only, uses monotonic `show_seq` as its version, and is recomputed during freshness validation. Renderer/profile/broker contracts require one exact or one aggregate evidence ID. Wrong or fabricated IDs fail local rendering; wrong model prose fails broker semantic support.
- **Files and functions changed:** New `src/sidestage/copilot/variants.py`; `src/sidestage/copilot/retrieval.py` contexts, exact/summary retrieval, and revalidation; `src/sidestage/copilot/pipeline.py` raw-question handoff; `src/sidestage/domain/replies.py` aggregate fact and one-ID contracts; `src/sidestage/copilot/analysis.py`, `profile.py`, `templates.py`, and `broker.py` model, rendering, and validation boundaries; `src/sidestage/trace/pressure.py` aggregate scripted selection; focused unit/integration/end-to-end tests; PRD, TDD, and debugging documentation. Existing dirty projection compression and removal of model-returned `variant_id` were preserved.
- **Verification commands and results:** `uv run pytest tests/unit/test_variant_resolution.py tests/integration/test_retrieval.py -q` → `26 passed in 0.38s` before the additional invalid-size and aggregate-freshness cases; `uv run pytest tests/unit/test_reply_templates.py tests/unit/test_livesell_profile.py tests/unit/test_reply_contracts.py tests/integration/test_reply_broker.py -q` → `35 passed in 0.52s` before the stricter system/audience/quantity cases; `uv run pytest tests/integration/test_template_workflow.py -q` → `11 passed in 2.55s`; `uv run pytest tests/integration/test_variant_workflows.py -q` → `4 passed in 1.69s`; final parser/workflow focus `uv run pytest tests/unit/test_variant_resolution.py tests/integration/test_retrieval.py tests/integration/test_template_workflow.py tests/integration/test_variant_workflows.py -q` → `46 passed in 3.59s`; planner-field removal focus `uv run pytest tests/integration/test_analysis.py tests/integration/test_retrieval.py tests/integration/test_variant_workflows.py tests/unit/test_reply_contracts.py -q` → `28 passed in 1.43s`; final resolver-only check `uv run pytest tests/unit/test_variant_resolution.py -q` → `22 passed in 0.11s`; final `uv run pytest -q` → `351 passed, 5 deselected in 55.40s`. These results are dirty-tree evidence and are not commit-bound `Verified` evidence.
- **Regression test:** `tests/unit/test_variant_resolution.py` covers all five equivalent expressions, typed trusted labels, decimal separation, unique inference, mixed-system/audience ambiguity, unknown sizes, product/model-number exclusion, and general-summary classification. `tests/integration/test_analysis.py` proves the removed planner variant field is rejected; `tests/integration/test_retrieval.py` proves exact projection has one variant and general projection has one aggregate with no per-variant records. `tests/integration/test_template_workflow.py` and `test_variant_workflows.py` prove both workflows end to end, including fabricated/wrong-real render rejection, wrong-real draft-claim rejection, missing-size early exit, and no outbound publication.
- **Remaining risk:** The buyer parser intentionally uses a closed English v1 lexicon; multilingual size phrases, unusual regional systems, widths, half-size formats other than one decimal digit, and malformed trusted catalog labels fail closed rather than invoking an LLM. Aggregate freshness conservatively invalidates on any intervening show-sequence change, which can create extra seller review but cannot authorize stale output. The code is committed at `12f3bab`, but latency/token effects and the complete deterministic suite have not yet been rerun as clean M3B.6 commit-bound evidence.
- **What I personally did:** The builder identified the failure mode by challenging the assumption that model-produced variant labels would preserve canonical token order and then extended the challenge to omitted sizing systems and colloquial or multilingual buyer wording. Repository inspection traced the gap through both workflow implementations.
- **What AI suggested:** Put a typed resolver before both workflows, retain model calls only for fact/template/draft decisions, and represent general availability as one application-owned aggregate rather than a per-variant model array.
- **What I rewrote or rejected:** Rejected LLM canonicalization, compact candidate-list selection, and membership-only validation because each still delegates semantic identity to a model. During implementation, the `size 99` regression also rejected an overly broad singular/plural summary regex; summary detection now requires explicit plural/all-size wording.
- **60-second interview explanation:** The models no longer decide which shoe-size entity a buyer means. Python parses `US M 9`, `9 M US`, and `9 for man` into the same nullable attributes and intersects them with only the already-bound listing. One match produces one trusted inventory record; zero or multiple matches stop safely. The one-call agent never sees other variants, and the two-call planner's label is ignored. General size questions receive one recomputable summary instead of all rows. A model can still choose a reply template or draft wording, but it cannot create, substitute, render, or publish another variant identity.

### DBG-024 — Empty-stage chat accumulated Needs You cards and the seller workspace lacked reset/volume controls

- **Date and commit:** 2026-08-18; fixed in `b5823cc`.
- **Status:** Fixed; the feature commit exists, while final clean M3B.6 verification remains open because DBG-025 was found immediately afterward.
- **Expected:** Buyer questions enter the reply workflows only after Push establishes an immutable listing epoch. The seller can reset one authenticated synthetic seller/show after manual testing, inspect newest questions without losing older unresolved work, scroll chat and both Inbox buckets independently, and see every durable seller reply in the chat timeline with its source buyer quote.
- **Observed:** Manual `/app/` testing accepted buyer chat while `active_listing_id=null` and the show had zero epochs. Fifteen question cards accumulated as `Needs You`; the corresponding traces exited at stage 3 with `uncertain_listing_binding`, so retrieval and registered-agent stages 4-8 were correctly skipped. The safe backend behavior therefore looked like a broken workflow. Separately, Inbox cards were oldest-first in one growing column, chat required whole-page scrolling, sent seller replies were absent from the visible timeline, and the synthetic session had no full reset control. Final visual inspection also found that a fresh session opened on an already-active show could leave chat controls disabled: the snapshot rendered while `sellerSwitchPending=true`, but releasing that flag did not re-render availability.
- **Exact reproduction commands:** The deterministic contracts were captured with `uv run pytest tests/integration/test_streaming_api.py tests/integration/test_demo_reset.py -q` and `uv run pytest tests/e2e/test_r2_inbox.py::test_fresh_r2_suggestion_needs_one_seller_decision_and_one_atomic_receipt tests/e2e/test_r3_controls.py::test_r3_warning_persists_and_disable_immediately_restores_r2_review tests/e2e/test_marketplace_ui.py::test_reset_recent_earlier_and_independent_scroll_workflow -q`. Before implementation, the API/reset group had four failing contracts and the UI group failed all three cases at their first missing reset/timeline assertions.
- **Tenant, fixture, seed, and trace ID:** The original manual symptom was the active synthetic seller session shown in `/app/`; its opaque session and trace IDs were not retained before Reset was designed. Regression coverage uses isolated Velocity Kicks and default-seller SQLite fixtures with prepared seed `20260817`.
- **Log, trace, screenshot, or artifact:** Browser and API evidence is retained in the focused pytest cases and this incident entry; no customer or external marketplace data is involved.
- **Impact:** No unsafe reply was sent—the router failed closed—but manual testing could not distinguish missing show setup from a failed agent workflow, and repeated attempts increased apparent operator load. Long sessions also obscured current questions and durable seller replies. Without reset, test residue could contaminate subsequent debugger/latency inspection.
- **Hypotheses considered:** The worker was not running; the model/provider failed; R2 cards were expected for all questions; routing should guess the selected catalog card; Push must establish the only trusted epoch; reset could be a sixth marketplace operation; reset needed a separate exclusive developer authority boundary.
- **First incorrect pipeline stage:** Input admission. The application allowed chat acceptance before the temporal-binding precondition existed. Stage 3 then behaved correctly by refusing to invent listing identity.
- **Root cause:** The custom/prepared endpoints and browser controls did not enforce the same active-epoch prerequisite assumed by routing. The demo also had no show-scoped mutation barrier or restoration transaction, and its browser projection treated inbound chat, open questions, and outbound replies as separate incomplete views. On seller changes, the final pending-state release updated header flags but did not re-render controls derived from the new authoritative snapshot.
- **Fix:** Added a per-show shared/exclusive `DemoMutationGate`; all mutable endpoints take a normal lease and `POST /api/sessions/{session_token}/demo/reset` takes the exclusive lease. Chat checks the active listing inside its lease and returns typed HTTP 409 `active_slot_empty` before ingestion/model work. `DemoResetService` flushes traces, deletes dependent show rows and restores fixture values in one SQLite transaction, advances versions, disables R3, resets prepared/runtime in-memory state, and publishes `demo.reset`. The seller UI confirms reset, disables chat on an empty stage, orders open questions newest-first into twenty-second Now/Earlier panels, gives chat and both panels independent scrolling, removes terminal questions from the open Inbox, and renders durable R2/R3 seller replies from one stream-offset-ordered backend timeline with the exact source buyer quote. Releasing seller-switch pending state now re-renders the server snapshot, so an already-active show immediately enables its input controls.
- **Files and functions changed:** `src/sidestage/marketplace/demo_reset.py`; reset/mutation endpoints and snapshot projection in `src/sidestage/app.py`; `RuntimeSelector.reset`; `PreparedChatSource.reset`; `copilot_projection` and `_chat_timeline`; seller `index.html`, `app.js`, and `styles.css`; focused integration and Playwright tests; PRD, TDD, and debugging documentation.
- **Verification commands and results:** The reset/streaming contract command passed with `14 passed in 3.22s`; the complete reset/streaming/R2/R3/browser focus passed with `24 passed in 30.16s`. `node --check src/sidestage/web/static/app.js` and `git diff --check` passed. After correcting an initial constrained-grid overlap and an empty-signature reset-render defect, the reset browser case passed with `1 passed in 4.97s`. The added active-show seller-switch regression and complete marketplace flow passed together with `2 passed in 24.36s`. The pre-commit exact full command `uv run pytest -q` passed with `356 passed, 5 deselected in 73.51s`, and the implementation was committed as `b5823cc`. A credentialed local live run on port 8001 reset and Pushed Velocity Kicks, resolved `9 for man` to `US M 9`, produced a one-call R2 draft, exposed eight completed debugger stages including Evidence Retrieval and Registered Reply Agent, switched the same show to `two_call_draft`, and produced one quoted R2 plus one quoted R3 reply. That manual compatibility diagnostic was not the fixed pressure workload and is not `Measured`; the first clean post-commit gate exposed DBG-025 before M3B.6 could promote the feature evidence.
- **Regression test:** `tests/integration/test_demo_reset.py` covers full restoration, tenant isolation, monotonic versions, prepared/runtime/R3 state, SSE, and an admitted delayed-model race. `tests/integration/test_streaming_api.py` covers both empty-stage chat paths. `tests/e2e/test_marketplace_ui.py`, `test_r2_inbox.py`, and `test_r3_controls.py` cover gating, newest-first age migration, independent scroll, reset/recovery, and exact quoted R2/R3 timeline entries.
- **Remaining risk:** Reset is intentionally local synthetic-demo tooling and is not a production account-data deletion protocol. Its in-memory gate coordinates one process only. The twenty-second presentation boundary uses browser time and a bounded clock-skew fallback; server question state and send authority are unaffected. Cross-tab visual reset convergence and final clean committed-tree verification remain pending; the manual live run does not replace M3B.6 pressure measurement.
- **What I personally did:** The builder reported the mismatch between visible Needs You cards and the expected agent workflow, then specified reset scope, time buckets, scroll behavior, and quoted reply requirements while preserving the active-listing authority boundary.
- **What AI suggested:** Treat empty-stage admission as the primary defect, make reset exclusive and session-authoritative, and derive the visible chat timeline from persisted stream order instead of browser-local reply insertion.
- **What I rewrote or rejected:** Rejected listing guessing, clearing only browser state, caller-supplied reset scope, resetting version counters backward, allowing in-flight late writes, and sending all historical variants/messages back through a model. The first fixed-grid layout also made Earlier rows overlap following controls; it was replaced with a bounded independently scrolling show surface plus fixed-height independent Inbox panels.
- **60-second interview explanation:** The agent had not stopped—it was refusing every question safely because the show had no active listing epoch. I moved that precondition to input admission so the UI cannot create misleading work, then added an exclusive synthetic reset that cannot race model or seller mutations. The browser now separates current and older unresolved questions, keeps high-volume regions scrollable, and shows each durable seller reply beside the exact buyer message it answered. Tests prove reset cannot leak across sellers or let a late model result reappear.

### DBG-025 — Fresh FastAPI removed the shutdown-registration API used by both app factories

- **Date and commit:** 2026-08-18; reproduced from clean worktree `/tmp/sidestage-m3b6-b5823cc` at `b5823cc`; fixed and committed in `62a44ae`.
- **Status:** Fixed, not commit-bound `Verified`.
- **Expected:** The documented clean sequence `uv sync --group dev`, `uv run playwright install chromium`, and `uv run pytest -q` constructs both application factories and reaches the deterministic/browser gate.
- **Observed:** Clean sync selected CPython 3.13.11 and FastAPI 0.141.1. The full suite stopped at app construction with `AttributeError: 'FastAPI' object has no attribute 'add_event_handler'`, reporting `50 failed, 287 passed, 5 deselected, 19 errors in 7.57s`. The reused repository `.venv` had Python 3.9.6 and FastAPI 0.128.8, so the earlier pre-commit suite did not expose the removed method.
- **Exact reproduction command:** In `/tmp/sidestage-m3b6-b5823cc`: `uv sync --group dev`, `uv run playwright install chromium`, then `uv run pytest -q`.
- **Tenant, fixture, seed, and trace ID:** Failure occurred during app construction before tenant/session issuance or trace creation; no seller, fixture event, or trace ID applies.
- **Log, trace, screenshot, or artifact:** The exact exception points to `src/sidestage/app.py` at both `application.add_event_handler("shutdown", trace_sink.close)` and the corresponding live-runner cleanup registration. Terminal evidence is retained in the active build task; no provider request or credential value was emitted.
- **Impact:** A reviewer following the documented clean setup could not start or test the prototype. Runtime safety logic did not execute; this was lifecycle compatibility rather than a reply-authority failure.
- **Hypotheses considered:** Broken fixture/database initialization; FastAPI import mismatch; sandbox socket restrictions; stale editable install; and removal of the legacy event API. Directly printing the clean interpreter's FastAPI version and the missing class attribute isolated the last hypothesis.
- **First incorrect pipeline stage:** Process/application lifecycle construction, before chat ingestion stage 1.
- **Root cause:** Both factories registered owned-resource cleanup through a framework method that existed in the reused environment but was removed from the fresh dependency resolution. The dependency range allowed the newer compatible FastAPI version, and no regression prohibited use of the legacy API.
- **Fix:** `create_app()` now supplies one supported async lifespan context to the FastAPI constructor. Shutdown deduplicates reusable registered runners, invokes and awaits each `aclose()` result, retains the first model-close error, and always closes the buffered trace sink. `create_live_app()` no longer attaches separate legacy event handlers.
- **Files and functions changed:** `src/sidestage/app.py::create_app`, `src/sidestage/app.py::create_live_app`, and `tests/integration/test_live_app_factory.py`.
- **Verification commands and results:** RED: `.venv/bin/python -m pytest -q tests/integration/test_live_app_factory.py::test_live_app_lifespan_owns_trace_and_model_cleanup_without_legacy_events` failed at the prohibited legacy call. GREEN on the old environment: the focused lifecycle test passed. GREEN on FastAPI 0.141.1: the lifecycle plus representative streaming test passed `2 passed`. Final existing-environment gate: `.venv/bin/python -m pytest -q` passed `357 passed, 5 deselected in 79.24s`. Final clean-interpreter gate with edited source: `PYTHONPATH=/Users/qiguo/Projects/AIFund/LiveSell-Copilot/src /tmp/sidestage-m3b6-b5823cc/.venv/bin/python -m pytest -q` passed `357 passed, 5 deselected, 1 warning in 42.16s`.
- **Regression test:** `test_live_app_lifespan_owns_trace_and_model_cleanup_without_legacy_events` makes the removed method raise when present, also works when the installed FastAPI lacks it, enters/exits a real `TestClient`, and proves exactly one trace sink and one shared live model runner close.
- **Remaining risk:** The fresh suite emits a Starlette warning that its `httpx`-based `TestClient` path is deprecated in favor of `httpx2`; it does not fail today but should be tracked before the next major test-client upgrade. The fix is committed, but the passing full-suite commands were not rerun from `62a44ae` and therefore are not commit-bound verification.
- **60-second interview explanation:** The normal virtual environment masked a clean-install break. Fresh FastAPI had removed the method we used to register shutdown callbacks, so every app-based test failed before the product ran. I replaced both callback registrations with FastAPI's supported lifespan contract and made that single owner close all shared model clients exactly once plus the trace sink. A regression simulates the old API being unavailable, and the full suite now passes under both dependency generations.

### DBG-026 — Scripted pressure saturation depended on interpreter scheduling behavior

- **Date and commit:** 2026-08-18; discovered while verifying DBG-025 under the clean CPython 3.13.11 environment; fixed and committed in `62a44ae`.
- **Status:** Fixed, not commit-bound `Verified`.
- **Expected:** The scripted harness proves semantic/accounting behavior for both workflows, and the release `one_call_template` cell deterministically exercises its configured five-per-show/fifteen-global lanes without using real wall-clock sleeps.
- **Observed:** After lifecycle construction was fixed, CPython 3.13 reported outer peak `13` instead of `15` in the integration cap test and peak `1` in the immediate scripted pressure replay. The reused CPython 3.9 event loop had happened to suspend on already-resolved scheduler futures, producing the expected peak. A first attempted all-at-once replay made Python 3.9 processing consume the shared five-second deadlines, reducing two-call semantic support to `36/72` and one-call provider requests to `48/72`.
- **Exact reproduction commands:** `PYTHONPATH=/Users/qiguo/Projects/AIFund/LiveSell-Copilot/src /tmp/sidestage-m3b6-b5823cc/.venv/bin/python -m pytest -q tests/integration/test_latency_accounting.py::test_three_sellers_are_capped_at_five_each_and_fifteen_globally tests/integration/test_latency_accounting.py::test_scripted_pressure_replays_three_exact_workloads_with_full_accounting`; the failed all-at-once attempt was caught by `.venv/bin/python -m pytest -q`.
- **Tenant, fixture, seed, and trace ID:** Three synthetic sellers, `fixtures/scenarios/pressure_v1.json`, seed `20260817`; aggregate scheduler/evaluator evidence rather than one trace ID.
- **Impact:** Product limits were not exceeded, but the test could claim saturation or fail solely from interpreter scheduling. The all-at-once attempt also demonstrated that synthetic semantic failures could be manufactured by test-machine throughput rather than model/workflow behavior.
- **Hypotheses considered:** Product scheduler off-by-one; incorrect five/show constants; two-call planner's intentional independent 12-call lane; immediate scripted provider never yielding; and replay batching consuming absolute deadlines. Direct snapshots and cross-interpreter runs separated capacity enforcement from observed saturation.
- **First incorrect pipeline stage:** Evaluation scheduling before/at the registered-agent provider boundary; live application routing and authority were unchanged.
- **Root cause:** Exact peak assertions relied on incidental suspension behavior of `asyncio.wait_for()` around already-completed futures. The immediate scripted runner had no asynchronous provider boundary, while a naive full batch changed the workload's deadline behavior.
- **Fix:** The direct 15-global integration proof now uses the release one-call workflow whose outer and core lanes are both 15. The general two-call scripted cell asserts the actual upper-bound contract, not accidental saturation of its independent 12-call planner. The one-call scripted pressure runner gives only its first 15 calls a bounded 32-turn cooperative event-loop probe, after which all remaining calls execute immediately. This fills five calls for each of three shows without wall-clock sleep, preserves the original time-ordered replay, and keeps all 72 parent deadlines/semantics intact.
- **Files and functions changed:** `src/sidestage/trace/pressure.py::CountingModelRunner`, `_evaluate_replay`, and `tests/integration/test_latency_accounting.py`.
- **Verification commands and results:** Focused lifecycle/scheduler set under CPython 3.13 passed `4 passed`; both workflow pressure cells passed under CPython 3.9 (`2 passed`) and CPython 3.13 (`2 passed`). The final full gates passed with `357 passed, 5 deselected in 79.24s` on Python 3.9 and `357 passed, 5 deselected, 1 warning in 42.16s` on the clean Python 3.13/FastAPI 0.141.1 environment.
- **Regression test:** The one-call pressure test requires exactly 72 provider requests, all semantic/safety gates, and observed maxima of exactly 15 global and 5 per show. The two-call accounting test still requires 72/72 semantic correctness while proving no configured outer limit is exceeded.
- **Remaining risk:** The bounded cooperative probe is synthetic scheduler evidence, not a latency measurement and not evidence that a provider sustains 15 concurrent requests. Only the final live pressure run may establish the release p95 and provider behavior. The fix is committed in `62a44ae`; M3B.6 remains open until a clean committed-tree rerun.
- **60-second interview explanation:** The scheduler was enforcing its caps, but the test's observed peak changed across Python versions because the fake provider could complete without yielding. Batching everything fixed the peak but created fake deadline failures on a slower interpreter. The final harness keeps real event order and gives only the first 15 one-call requests a bounded event-loop yield, enough to fill 5×3 lanes without sleeping. The semantic count remains 72/72, and both Python environments pass.

## 4. Incident record template

```md
### DBG-___ — Short symptom

- **Date and commit:**
- **Status:** Open | Diagnosed | Fixed | Verified | Deferred
- **Expected:**
- **Observed:**
- **Exact reproduction command:**
- **Tenant, fixture, seed, and trace ID:**
- **Log, trace, screenshot, or artifact:**
- **Impact:**
- **Hypotheses considered:**
- **First incorrect pipeline stage:**
- **Root cause:**
- **Fix:**
- **Files and functions changed:**
- **Verification commands and results:**
- **Regression test:**
- **Remaining risk:**
- **What I personally did:**
- **What AI suggested:**
- **What I rewrote or rejected:**
- **60-second interview explanation:**
```

## 5. Streaming debugging checklist

- Confirm raw event acceptance before checking downstream processing.
- Compare event, seller, show, sequence, idempotency, and trace identifiers across stages.
- Check queue depth, backpressure decisions, task cancellation, reconnect, and replay offsets.
- Separate a lost raw event from a deliberately deduplicated or noise-routed event.
- Filter the tracer by actual routing outcome and compare generated fixtures' evaluator-only expected route with the actual route.
- Reproduce races with a fixed seed and controlled clock.
- Verify per-show ordering and cross-question concurrency independently.

## 6. Grounding and guardrail debugging checklist

- Inspect the exact versioned evidence bundle seen by the model.
- Confirm tenant filtering happened before retrieval or ranking.
- Distinguish retrieval failure, context assembly failure, model error, and validator error.
- Identify the exact unsupported claim or conflicting source.
- Verify stale or missing evidence fails closed.
- Preserve adversarial input verbatim while keeping it outside trusted instructions and memory.

## 7. Latency debugging checklist

- Use a monotonic clock for every stage.
- Report queue wait, retrieval, model, validation, emission, and total latency separately.
- Compare p50, p95, maximum, and timeout counts; do not report averages alone.
- Attribute cold starts, retries, and injected delays explicitly.
- Confirm tracing itself does not block reply delivery.
- Preserve the workload, seed, model, configuration, and commit for every benchmark.

## 8. Action, audit, and compensation debugging checklist

- Confirm actor authentication and tenant scope before parameter validation.
- Inspect expected and current listing or inventory versions.
- Verify idempotency behavior under retry and duplicate events.
- Distinguish execution success from read-after-write verification success.
- Ensure an audit receipt exists for success, refusal, partial failure, and compensation.
- Treat rollback as a new conditional compensating event; never erase the original record.

## 9. Failed attempts and reverted fixes

Record fixes that appeared plausible but failed, degraded another invariant, or were reverted. Link the relevant incident and commit.

### 2026-08-18: OpenRouter pressure run accidentally used the OpenAI transport

- **Command:** `SIDESTAGE_MODEL_ID=deepseek/deepseek-v4-flash-0731 SIDESTAGE_MODEL_REASONING_EFFORT=low uv run --env-file .env python -m sidestage.trace.evaluator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --model live --strategy one_call_template --output runs/exploratory/openrouter_deepseek_v4_flash_one_call.json`
- **Observed evidence:** the generated report identified `model.provider` as `openai`, contained no OpenRouter routing configuration or successful provider-call metadata, answered `0/72` supported cases, and recorded 60 route mismatches. Its low reported latency measured provider-error handling, not DeepSeek inference.
- **Root cause:** the evaluator intentionally defaults `SIDESTAGE_MODEL_PROVIDER` to `openai`; setting an OpenRouter model ID and key does not select the OpenRouter transport. The command omitted `SIDESTAGE_MODEL_PROVIDER=openrouter`.
- **Fix:** pin `SIDESTAGE_MODEL_PROVIDER=openrouter` in every OpenRouter benchmark command and verify the report's sanitized provider, base URL, and fallback-disabled routing configuration before accepting its metrics.
- **Verification:** reran with `SIDESTAGE_MODEL_PROVIDER=openrouter` at the same artifact path. The corrected report identifies the OpenRouter transport, fallback-disabled routing, the requested and resolved DeepSeek model, and Inceptron as the resolved provider. It failed the pressure gate with `7/72` supported answerable suggestions, 88 hard timeouts, 55 route mismatches, and `5,022.008 ms` p95. The transport-selection fix is verified; the model/provider cell itself is a valid failed benchmark, not a latency candidate.

### 2026-08-18: OpenRouter rejected tool-capable Kimi and GLM endpoints

- **Commands:** `SIDESTAGE_MODEL_PROVIDER=openrouter SIDESTAGE_MODEL_ID=moonshotai/kimi-k3 SIDESTAGE_MODEL_REASONING_EFFORT=low uv run --env-file .env pytest tests/integration/test_live_app_factory.py::test_live_openrouter_factory_executes_one_template_call -m live_model -q` and the same command with `SIDESTAGE_MODEL_ID=z-ai/glm-5.2 SIDESTAGE_MODEL_REASONING_EFFORT=high`.
- **Observed evidence:** both one-call smokes failed closed with `provider_error`. Sanitized diagnostics returned HTTP 404 with `No endpoints found that can handle the requested parameters`; OpenRouter reported 13 otherwise available Kimi endpoints and 31 otherwise available GLM endpoints.
- **Root cause:** the shared Chat Completions payload always included the optional OpenAI parameter `parallel_tool_calls=false`. With OpenRouter `require_parameters=true`, that parameter excluded Kimi K3, whose model catalog advertises `tools` and `tool_choice` but not `parallel_tool_calls`. Removing only that hint made the same Kimi strict 15-tool diagnostic return exactly one call through Together. GLM remains a screening failure until the corrected shared transport is retested.
- **Fix:** omit `parallel_tool_calls` for OpenRouter requests while retaining it for direct OpenAI. This does not relax the agent contract: the provider-neutral decoder independently requires exactly one registered terminal call and fails closed on multiple calls.
- **Verification:** focused offline regressions passed with `17 passed, 2 deselected`. The corrected Kimi workflow smoke passed with `1 passed in 2.15s`; GLM still failed closed with `provider_error` and was not promoted. The full offline suite then passed with `288 passed, 4 deselected in 48.16s`.

### 2026-08-18: One-call Luna improved the baseline but still missed the release gate

- **Command:** `SIDESTAGE_MODEL_PROVIDER=openai SIDESTAGE_MODEL_ID=gpt-5.6-luna SIDESTAGE_MODEL_REASONING_EFFORT=none uv run --env-file .env python -m sidestage.trace.evaluator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --model live --strategy one_call_template --output runs/exploratory/openai_luna_one_call.json`
- **Observed evidence:** `one_call_template` reached 66/72 supported answerable suggestions, zero hard timeouts, and `3,414.368583 ms` end-to-end p95. It improved over the matching two-call Luna result of 54/72, 14 hard timeouts, and `4,530.28 ms` p95, but failed the 95% coverage and two-second latency gates. The report recorded 45 SLO misses, `1,548.327167 ms` queue p95, and 18 provider-error outcomes across 135 requests while preserving the safety/no-effect scorecards.
- **Root cause:** removing the sequential second model call reduced latency and timeout exposure, but the approved 20-chat/two-second burst still exceeded the combined endpoint capacity and four-worker-per-show queue budget. Six answerable requests and twelve safe-terminal requests failed at the provider boundary; later waves accumulated queue delay.
- **Fix:** no release fix has been accepted. The evaluator, workload, queue time, safety gates, and hard timeout remain unchanged; the cell is retained as a valid failed diagnostic instead of weakening the benchmark.
- **Verification:** artifact `runs/exploratory/openai_luna_one_call.json`; the report is dirty-tree `Implemented` evidence and has `passed=false`.

### 2026-08-18: Reused pressure fixture retained the baseline profile digest

- **Command:** `jq '{fixture_profile: .fixture_manifest.profile_digest, evaluation_profile: .profile_digest}' runs/exploratory/openai_luna_one_call.json`
- **Observed evidence:** the nested fixture manifest records baseline digest `sha256:5385...57b8`, while the one-call evaluation records challenger digest `sha256:db3d...3133`.
- **Root cause:** `pressure_v1` events and oracle are deliberately reused across workflows for comparability, but their retained fixture manifest was generated while bound to the baseline profile. The evaluator adds the active challenger digest at the report level without rejecting or explaining the nested mismatch.
- **Impact:** event/oracle digests still identify the fixed workload, but the combined artifact cannot be treated as a single internally profile-bound manifest. This weakens reproducibility claims if the distinction is not disclosed.
- **Fix:** the v2 workload manifest now contains only scenario/fixture identity; `profile_digest` and `model_config_ref` are report-level evaluation identity. `pressure_v1` no longer declares a model configuration, and the evaluator derives a strategy-specific configuration reference.
- **Verification:** `tests/unit/test_scenario_generator.py` asserts both fields are absent from the workload manifest. Scripted two-call and one-call pressure tests pass with distinct report-level configuration/profile identity. The legacy artifact remains mismatched and is not rewritten or promoted.

### 2026-08-18: Broker acceptance could count a grounded but semantically wrong reply

- **Command:** review of `scorecard.answerable_supported_suggestions` in `src/sidestage/trace/pressure.py`, followed by `.venv/bin/pytest -q tests/unit/test_scenario_generator.py tests/integration/test_fixture_replay.py tests/integration/test_latency_accounting.py -x`.
- **Observed evidence:** the old numerator checked only whether an answerable question reached `awaiting_review` or `auto_answered`; it did not compare the selected category, evidence fact type, approved template, or exact variant with the authored question. The same report computed release p95 from all 360 events, so fast noise/duplicate paths and answerable/model-backed paths shared one denominator.
- **Root cause:** the v1 oracle described routing and duplicate identity only. It had no expected semantic answer contract, and the latency report had one backward-compatible all-event aggregate with no declared release denominator.
- **Fix:** added explicit evaluator-only semantic contracts for all 72 answerable parents, semantic tamper reconstruction during replay, separate broker-acceptance and semantic-correctness gates, category/evidence/template/variant component metrics, and all-event/answerable/model-backed/R2/R3 latency slices. The release SLO now uses answerable-parent acceptance-to-publication p95. Semantic labels remain absent from runtime events and model input.
- **Verification:** the focused generator/replay/latency suite passes. Both scripted workflows score 72/72 semantic correctness; the one-call run retains 135 model-backed traces; tampering with an oracle category and rehashing the artifact is rejected; and an exact-variant regression proves `US M 9` cannot match `US M 9.5`. The exact full offline command `.venv/bin/pytest -q -m 'not live_model'` passes with `300 passed, 5 deselected in 53.98s`. No legacy live artifact is retroactively rescored.

### 2026-08-18: Commit verification initially used the wrong interpreter and a restricted localhost sandbox

- **Commands:** `pytest -q tests/unit tests/integration tests/e2e --ignore=tests/unit/test_scenario_generator.py --ignore=tests/integration/test_fixture_replay.py --ignore=tests/integration/test_latency_accounting.py --ignore=tests/integration/test_trace_evaluator.py`, followed by the same selection with `.venv/bin/pytest`.
- **Observed evidence:** the first command stopped during collection because the desktop base interpreter lacked `jsonschema`, FastAPI, and Uvicorn. The project interpreter then ran 256 tests successfully, but six localhost server/browser cases failed with `PermissionError: [Errno 1] Operation not permitted` while binding `127.0.0.1` ephemeral ports.
- **Root cause:** the first invocation bypassed the repository virtual environment. The second used the correct dependencies but remained inside a filesystem-only sandbox that prohibits local socket binding.
- **Fix:** use the repository environment and authorize localhost binding for server/browser verification; no application or test code changed.
- **Verification:** the selected runtime suite passed with `262 passed, 4 deselected in 18.42s`. After commits `7d6c349` and `6ba208a`, the exact full command `.venv/bin/pytest -q` passed with `288 passed, 4 deselected in 43.52s`.

### 2026-08-18: Playwright option matcher misreported a disabled compatibility choice

- **Command:** `uv run pytest -q tests/integration/test_runtime_switching.py tests/e2e/test_debugger.py`
- **Observed evidence:** the debugger browser test failed at the new compatibility assertion. Playwright's log showed the resolved element as `<option disabled value="template-only">`, while `expect(locator).to_be_disabled()` still reported the option as enabled.
- **Root cause:** the generic enabled/disabled matcher applies control semantics that are unreliable for an individual `<option>` in this browser binding; the application had correctly written the DOM `disabled` property.
- **Fix:** assert the exact option's `disabled` DOM property before and after changing the workflow selector. No application behavior or compatibility rule changed.
- **Verification:** `uv run pytest -q tests/e2e/test_debugger.py` passed with `1 passed in 2.54s`; the earlier full pre-commit gate passed with `296 passed, 4 deselected in 50.30s`. After adding the separately marked live switch smoke and correcting catalog reasoning effort, the full gate passed again with `296 passed, 5 deselected in 56.79s`.

### 2026-08-18: Local `.env` could not start the live multi-model app

- **Command:** `uv run --env-file .env python -c '<create_live_app sanitized-catalog startup check>'` after printing only dotenv variable names with `awk`; no credential value or provider request was emitted.
- **Observed evidence:** the file defines `OPEN_API_KEY` and `OPENROUTER_API_KEY`, but not `SIDESTAGE_MODEL_ID`. `create_live_app()` failed before database initialization with `RuntimeError: live app requires SIDESTAGE_MODEL_ID`.
- **Root cause:** `OPEN_API_KEY` is not the supported OpenAI variable name (`OPENAI_API_KEY` or `SIDESTAGE_MODEL_API_KEY`), and the default model/profile settings are absent. The application intentionally does not guess a provider model or accept the misspelled key alias.
- **Fix:** pending builder credential-file correction. Keep one `KEY=value` per line, rename the OpenAI variable, and add the startup default shown in `README.md`. Do not put credentials in committed catalog JSON.
- **Verification:** the builder's `.env` has not yet passed default startup. A command-scoped OpenRouter/Kimi override separately passed the real one-call workflow smoke with `1 passed in 2.28s`; that proves the OpenRouter credential and one live workflow contract, not multi-model startup or the M3B.6 pressure gate.

### 2026-08-18: Selectable OpenRouter profiles drifted from their tested reasoning effort

- **Commands:** `SIDESTAGE_MODEL_PROVIDER=openrouter SIDESTAGE_MODEL_ID=moonshotai/kimi-k3 SIDESTAGE_MODEL_REASONING_EFFORT=none SIDESTAGE_WORKFLOW_STRATEGY=one_call_template uv run --env-file .env pytest tests/integration/test_live_app_factory.py::test_live_openrouter_factory_executes_one_template_call -m live_model -q -s`, followed by the same command with `SIDESTAGE_MODEL_REASONING_EFFORT=low`.
- **Observed evidence:** the `none` run failed closed as `provider_error` with `1 failed in 0.86s`; its persisted trace pinned `one_call_template`, `moonshotai/kimi-k3`, OpenRouter, selection version 1, and the cold sample. The `low` run completed the real evidence/template/broker path with `1 passed in 2.28s`.
- **Root cause:** `config/runtime_model_profiles.json` registered Kimi and DeepSeek with `reasoning_effort=none`, while the accepted Kimi compatibility smoke and both retained OpenRouter pressure cells used `low`. The debugger could therefore select a startup profile that did not match the configuration it claimed to expose as tested.
- **Fix:** align the enabled Kimi and DeepSeek startup profiles to `reasoning_effort=low` and assert both values in the sanitized live-catalog integration test. No provider fallback, model fallback, workflow fallback, or timeout was changed.
- **Verification:** the corrected direct command passed with `1 passed in 2.28s`. A new live runtime-switch test then started the multi-model app, changed the show from version 1 to Kimi version 2 through `/api/debug/runtime`, and pinned the resulting cold trace to `openrouter-kimi-k3`; the provider request failed closed. A temporary test-only response capture, removed immediately after diagnosis, identified HTTP 429 `Provider returned error`. The switch path and fail-closed behavior reached the live provider, but a successful switched response is not yet claimed. The full deterministic/browser gate passed after the correction with `296 passed, 5 deselected in 56.79s`; one-request compatibility does not establish p95 or close M3B.6.

### 2026-08-18: Seller action could race a pending seller-session change

- **Command:** `.venv/bin/pytest -q -m 'not live_model'`.
- **Observed evidence:** `test_non_ai_marketplace_flow_is_server_owned_and_reconnectable` failed after confirming Push because `#active-sku` remained `Stage clear`; the full run reported `1 failed, 299 passed, 5 deselected in 61.99s`. The isolated test then passed, showing the failure depended on timing rather than a deterministic marketplace-service refusal.
- **Root cause:** the final seller selection dispatched an asynchronous `/api/demo/sessions` request, but the old seller's workspace controls remained actionable. Under full-suite load, Playwright could observe the old empty-show Push button as enabled and click it before the new VelocityKicks session arrived. The operation was therefore scoped to the prior opaque session token, after which the arriving VelocityKicks snapshot correctly replaced the view with its still-empty show.
- **Fix:** mark the workspace `inert` and `aria-busy=true`, disable the seller selector and header R3 control, and reject operation-dialog opening while a seller-session change is pending. The authoritative backend tenant boundary did not change.
- **Verification:** the browser test now deliberately pauses the final `/api/demo/sessions` fetch, proves the workspace is inert and busy during the gap, releases it, proves the VelocityKicks show is active, and completes the full marketplace flow. The focused regression passes, and the exact full command passes with `300 passed, 5 deselected in 53.98s`.

### 2026-08-18: Non-answerable provider traffic and redundant variant output kept the release cell queue-bound

- **Commands:** `env SIDESTAGE_MODEL_PROVIDER=openrouter SIDESTAGE_MODEL_ID=google/gemini-3.5-flash-lite SIDESTAGE_MODEL_REASONING_EFFORT=minimal uv run --env-file .env python -m sidestage.trace.evaluator --scenario fixtures/scenarios/pressure_v1.json --seed 20260817 --model live --strategy one_call_template --output <artifact>` with the exact artifacts `openrouter_gemini_3_5_flash_lite_minimal_scope_gates_one_call_v2.json`, `openrouter_gemini_3_5_flash_lite_minimal_scope_gates_72_one_call_v2.json`, `openrouter_gemini_3_5_flash_lite_minimal_slim_scope_gates_one_call_v2.json`, `openrouter_gemini_3_5_flash_lite_minimal_evidence_derived_variant_one_call_v2.json`, and `openrouter_gemini_3_5_flash_lite_minimal_evidence_variant_c5_one_call_v2.json` beneath `runs/exploratory/`.
- **Observed evidence:** Closed deterministic scope gates reduced model requests from 135 to 75 and produced one narrow passing run at 1,995.54 ms answerable-parent p95. Repeating after eliminating the final three apostrophe-normalization noise calls produced one provider hard timeout and 2,121.41 ms p95. The slim projection reduced median prompt tokens from roughly 3.3k to 2,575 but four exact-size terminals became `malformed_arguments`, leaving 68/72 semantic correctness and 2,068.72 ms p95. Removing the redundant model-authored `variant_id` restored 72/72 semantics at four/show and twelve/global, but queue p95 was 1,444.24 ms and total p95 was 2,303.72 ms. With five/show and fifteen/global, the same 72-call workload passed: 72/72 semantic, 14/14 exact variants, every hard invariant zero, zero SLO misses/timeouts, 976.73 ms queue p95, and 1,848.92 ms answerable-parent p95.
- **Root cause:** The queue admitted obvious off-topic, ambiguous, unsupported, and pure authority/prompt-injection traffic even though the accepted v1 policy can classify those closed cases deterministically. The one-call model payload also carried timestamps, provenance, versions, and authority-adjacent identifiers unnecessary for semantic selection. Exact availability asked the model to return both the selected trusted evidence ID and a duplicate internal variant ID, creating an avoidable malformed-output path. After those issues were removed, the original four/show and twelve/global scheduler still left too much wait during the fixed burst.
- **Fix:** Add closed deterministic typed exits for the accepted v1 patterns while leaving mixed/uncertain questions on the model path; project only question text, listing ID/SKU, and evidence ID/type/value; derive exact variant identity from the one selected trusted availability record; and set the measured scheduler candidate to five/show and fifteen/global while retaining 64/show capacity and the five-second hard timeout. Queue trace metadata now reads the scheduler snapshot instead of embedding stale constants.
- **Verification:** `uv run pytest tests/unit/test_reply_templates.py tests/unit/test_livesell_profile.py tests/integration/test_template_workflow.py tests/integration/test_latency_accounting.py tests/integration/test_copilot_routing.py -q` passed after the contract changes except for two intentionally stale concurrency assertions; after correcting the assertions to distinguish the outer 15-call scheduler from the baseline core's independent 12-call lane, the two targeted scheduler regressions passed with `2 passed in 5.75s`. The final exploratory live artifact passed as described above. These are dirty-tree `Implemented` diagnostics; commit-bound full-suite and clean final live verification remain pending.
- **Failed approaches retained:** Increasing concurrency under the original 135-call workload did not pass; 6/18 reached 2,064.98 ms, 7/21 reached 2,193.74 ms, and 8/24 regressed to 2,357.74 ms. A Flash-Lite `reasoning=none` cell was rejected for all calls and is excluded as false-low error handling. The first slim-projection cell improved token count but failed semantic quality until the redundant variant output was removed. None of these failed cells is release evidence.

### DBG-027 — Grounded questions stayed in Manual review or Needs seller, and repeated text was over-grouped

- **Incident state:** Fixed and committed in `62a44ae` on 2026-08-18.
- **Evidence maturity:** `Implemented`, not `Verified` or `Measured`; the passing full-suite commands preceded the commit.
- **Builder observations:** `Is US M 6.5 available?` required seller input despite complete trusted inventory; automatic mode worked only for some phrasings/categories; a prior-listing question did not explain that another item was now on stage; and repeating `Is US 9 available?` after ten seconds was still grouped. The builder also required default-on **Auto-message**, a **Manual review** toggle, and no R2/R3 labels in the seller UI.
- **Initial commands:** `pytest -q tests/unit/test_variant_resolution.py tests/integration/test_copilot_routing.py tests/integration/test_template_workflow.py tests/integration/test_variant_workflows.py tests/integration/test_r3_safety.py tests/e2e/test_r3_controls.py tests/e2e/test_marketplace_ui.py` stopped at collection because the desktop base interpreter lacked `jsonschema`, FastAPI, and Uvicorn. The corrected command `/tmp/sidestage-m3b6-b5823cc/.venv/bin/python -m pytest -q <same files>` produced the intended red evidence: eight behavioral failures, 62 passes, and three sandbox-localhost errors.
- **Observed evidence:** The typed resolver had no exact-absence state, the capability was seeded/reset off, `_r3_question_matches()` required literal canonical-label tokens and a five-category wording allowlist after Python had already resolved the fact, the SQLite unique index allowed only one canonical normalized question for an entire listing epoch, and previous-listing routing terminated before retrieval/broker/result with `needs_seller`.
- **Root cause:** Four independent conservative mechanisms were treated as product policy rather than separate safety layers. Catalog nonmatch was conflated with untrusted missing evidence; post-validation automatic eligibility reclassified already validated facts through surface wording; canonical identity omitted a time boundary; and previous-listing disclosure was incorrectly modeled as content generation even though current listing identity is application-owned.
- **Fix:** Added typed deterministic exact absence when system/audience are explicit or inferable from unanimous trusted candidates, with one `variant_availability` negative record and final catalog/completeness revalidation. Auto-message now defaults on and accepts any supported one-fact reply only after the existing broker checks, while application code still renders the automatic text. Event-ID replay remains indefinitely idempotent, but normalization-equivalent text grouping uses a transactional five-second window and a non-unique lookup index. Previous-listing questions use a zero-model current-stage notice and respect Auto-message versus Manual review. Seller-visible copy uses only those two mode names; internal `r2`/`r3` storage and API identifiers remain compatible.
- **Regression coverage:** Equivalent and decimal sizes, unanimous inference, mixed-candidate ambiguity, implausible/product-number failure, one-record projections in both workflows, exact-absence final revalidation, `US 9` automatic send, aggregate automatic send, nonlegacy condition automatic send, wrong/fabricated variant rejection, within-window grouping, ten-second independent replies, previous-listing notices in both modes with zero model calls, reset default, safety evaluator authorization accounting, and seller-browser terminology/toggle behavior.
- **Verification commands:** `/tmp/sidestage-m3b6-b5823cc/.venv/bin/python -m pytest -q tests/integration/test_r3_safety.py tests/integration/test_template_workflow.py tests/integration/test_copilot_routing.py` passed with `48 passed in 2.70s`. The authorized browser command over the focused debugger/golden/R2/control tests passed with `10 passed in 6.23s`. After the independent DBG-028 SSE correction, the canonical dirty-tree `uv run pytest -q` passed with `368 passed, 5 deselected in 80.61s`, and the clean Python 3.13/FastAPI 0.141.1 command passed with `368 passed, 5 deselected, 1 warning in 44.16s`.
- **Remaining risks:** This is synthetic trusted-catalog behavior and assumes the bound listing's variant/inventory set is complete. The five-second window is an accepted prototype threshold, not marketplace-derived production evidence. No live provider pressure rerun has measured the latency effect, and the results do not become commit-bound `Verified` evidence until the clean committed tree is rerun.

### DBG-028 — Concurrent SSE listeners could violate Python 3.9 condition-lock ownership

- **Incident state:** Fixed and committed in `62a44ae` on 2026-08-18.
- **Evidence maturity:** `Implemented`, not `Verified`; the passing commands preceded the commit.
- **Observed command and evidence:** The first canonical `uv run pytest -q` after the Auto-message correction failed `test_reset_recent_earlier_and_independent_scroll_workflow` with `1 failed, 366 passed, 5 deselected in 78.76s`. Chromium reported `ERR_INCOMPLETE_CHUNKED_ENCODING`; the server traceback ended at `asyncio.Condition.wait()` with `RuntimeError: cannot wait on un-acquired lock` after reset and seller-session SSE reconnection.
- **Root cause:** `SseHub.stream()` acquired one shared `asyncio.Condition`, then passed `condition.wait()` to Python 3.9 `asyncio.wait_for()`. `wait_for()` runs that awaitable in a child task. With simultaneous or disconnecting listeners, the parent and child tasks could violate the condition lock's ownership assumption even though persisted replay remained correct.
- **Fix:** SQLite remains the sole replay authority. The hub now uses a per-show `asyncio.Event` only as a wakeup hint: it clears the event, performs a second durable read to close the commit-to-wait race, and then waits. Notifications persist first and set the event. No shared condition lock or child-task lock ownership remains.
- **Regression coverage:** Added an eight-listener same-show fan-out test while retaining the existing commit-between-reads test. The focused command `uv run pytest -q tests/integration/test_streaming_api.py::test_sse_listener_closes_the_commit_to_wait_race tests/integration/test_streaming_api.py::test_sse_hub_wakes_multiple_same_show_listeners_without_lock_ownership_races tests/e2e/test_marketplace_ui.py::test_reset_recent_earlier_and_independent_scroll_workflow` passed with `3 passed in 5.00s`.
- **Full verification commands:** `uv run pytest -q` passed with `368 passed, 5 deselected in 80.61s` on Python 3.9. `/tmp/sidestage-m3b6-b5823cc/.venv/bin/python -m pytest -q` passed with `368 passed, 5 deselected, 1 warning in 44.16s` on Python 3.13/FastAPI 0.141.1.
- **Remaining risk:** The hub is an in-process wakeup optimization; horizontal production deployment would require a cross-process notification mechanism, while SQLite offsets or an equivalent durable log remain authoritative.

### DBG-029 — Vercel classified CLI uploads as Production and the legacy rewrite destroyed FastAPI paths

- **Date and commit:** 2026-08-18; discovered during the first protected Vercel deployment after `3fda622`; the routing correction is uncommitted.
- **Incident state:** Fixed in the dirty tree and in one protected staged deployment; superseded deployments were removed.
- **Evidence maturity:** `Implemented`, not `Verified` or `Measured`; the passing commands and remote smoke evidence are not yet bound to a correction commit.
- **Expected:** A CLI upload should use Preview configuration unless explicitly promoted, preserve `/healthz`, `/`, and `/api/*` as the ASGI request paths, and remain inaccessible until the builder intentionally shares credentials.
- **Observed:** `vercel deploy --yes` and `vercel deploy --yes --target preview` both returned deployment JSON with `"target":"production"` and assigned production aliases. The first builds lacked Production secrets and returned `FUNCTION_INVOCATION_FAILED`; all were removed immediately. A protected staged build then started, but `vercel curl /healthz --deployment <deployment>` returned the app's Basic-Auth `401`, showing that the catch-all rewrite had changed the application-visible path from `/healthz` to `/api/index`.
- **Exact reproduction commands:** `vercel deploy --yes`; `vercel deploy --yes --target preview`; `vercel deploy --yes --prod --skip-domain -e OPENAI_API_KEY -e SIDESTAGE_MODEL_PROVIDER -e SIDESTAGE_MODEL_ID -e SIDESTAGE_MODEL_REASONING_EFFORT -e SIDESTAGE_DEMO_USERNAME -e SIDESTAGE_DEMO_PASSWORD -e SIDESTAGE_DEMO_MAX_REQUESTS_PER_SESSION -e SIDESTAGE_DEMO_MAX_REQUESTS_PER_DAY`; and `vercel curl /healthz --deployment <deployment> -- --include`. Values came from local process environment and were not printed or committed.
- **Log, trace, screenshot, or artifact:** Vercel build output warned that internal backend rewrites now route using the rewritten destination path. Removed deployment IDs were retained only in the private CLI transcript. `vercel list --environment production` showed one final ready staged build; anonymous HTTP returned Vercel SSO `302`, while the shorter stable project domain returned `DEPLOYMENT_NOT_FOUND` `404`.
- **Impact:** The first deployment configuration could not serve the marketplace UI or health route correctly. Misclassification also risked creating a stable alias before the access boundary was checked, although the failed builds never exposed a working application or provider key and were removed.
- **Hypotheses considered:** Missing runtime variables; local `master` metadata overriding Preview; a stale CLI; app middleware incorrectly protecting `/healthz`; and Vercel's changed backend rewrite behavior. Detached-HEAD deployment still classified as Production, while the warning plus the `/healthz` `401` isolated routing as an independent legacy-rewrite defect.
- **First incorrect pipeline stage:** Vercel deployment targeting and edge-to-ASGI routing, before SideStage application routing.
- **Root cause:** The new CLI-linked project classified every upload as its production target despite the requested Preview target. Separately, `vercel.json` used an obsolete catch-all rewrite to `/api/index`; Vercel's current zero-configuration FastAPI runtime already detects `api/index.py`, and the new backend rewrite behavior exposes the destination path to FastAPI.
- **Fix:** Use a staged production build with `--skip-domain` for this private pre-share check, verify Vercel deployment protection before retaining it, and keep a second app-level Basic-Auth boundary with an undisclosed random password. Remove the catch-all rewrite and let Vercel detect `api/index.py` directly. Add a regression test that rejects any `rewrites` key in `vercel.json`.
- **Files and functions changed:** `vercel.json`, `tests/integration/test_challenge_deployment.py::test_vercel_config_preserves_fastapi_request_paths`, `.gitignore`, `README.md`, `docs/TDD.md`, and this incident record.
- **Verification commands and results:** The new regression first failed with one assertion against the legacy rewrite. `uv run pytest tests/integration/test_challenge_deployment.py -q` then passed with `9 passed in 0.73s`; `git diff --check` passed. Through Vercel's authenticated tunnel, `/healthz` returned `200`, anonymous `/` returned app Basic-Auth `401`, and authenticated `/api/sellers` returned `200` with `challenge_mode=true`. Direct anonymous HTTP returned Vercel SSO `302`; the shorter stable domain returned `404`. These are deployment-smoke and dirty-tree implementation results, not commit-bound verification.
- **Regression test:** The Vercel configuration must contain no catch-all or other rewrite that replaces the FastAPI request path; the existing entrypoint test still proves `/healthz` and authenticated `/api/sellers` locally.
- **Remaining risk:** The retained build is target-labeled Production even though it was staged with `--skip-domain`; Vercel still assigns an account-scoped system URL, so privacy currently depends on Vercel SSO plus application Basic Auth. The generated app password was intentionally not retained, so it must be rotated before builder or reviewer use. Vercel `/tmp` SQLite, in-memory sessions, and SSE wakeups remain non-durable and non-shared across function instances.
- **60-second interview explanation:** Vercel's first CLI uploads unexpectedly landed in the production target, so I removed them before exposing a working app. Once the protected function started, even `/healthz` hit Basic Auth. The build warning explained why: our old rewrite changed every FastAPI path to `/api/index`, but current Vercel detects FastAPI directly. I removed the rewrite, added a regression, redeployed without a stable domain, and verified Vercel SSO, app Basic Auth, health, and an authenticated API independently. The result remains Implemented until a commit-bound rerun.

### DBG-030 — Vercel function recycling invalidated an otherwise active demo session

- **Date and commit:** 2026-08-18; observed on the protected Vercel deployment built from the dirty tree after `3fda622`.
- **Incident state:** Reproduced twice on Vercel; fixed for the accepted single-instance persistent topology. Vercel preview remains intentionally unsupported for reviewer sessions.
- **Evidence maturity:** `Implemented` with dirty-tree app-restart and container-restart evidence; not commit-bound `Verified` or latency `Measured` evidence.
- **Expected:** A server-issued demo session remains valid for the browser's active testing period, and later seller questions continue through the bound seller/show authority.
- **Observed:** The builder initially submitted questions successfully and later received `Message refused: unknown or expired demo session`. The same session had completed live OpenAI calls before a later custom-chat request stopped before provider work. Reloading caused the browser to reject the stored token and issue a new demo session. After Mock livesell and Preview credentials were corrected, the builder reproduced the same expiration again after only a few chats, disproving the Preview as a reviewer-safe topology.
- **Exact diagnostic commands:** `vercel logs --deployment <protected-deployment> --since 30m --limit 100 --expand`; `rg -n "unknown or expired demo session|session_token|DemoSession" src tests`; and inspection of `DemoSessionRegistry`, `restoreSession()`, and `api/index.py`.
- **Log, trace, screenshot, or artifact:** At 22:45:43 and 22:46:06 the same redacted session token reached OpenAI and received HTTP 200. At 22:46:16 another custom-chat request for that token produced no provider request. At 22:47:58 a reload requested the old token's snapshot and immediately followed with `POST /api/demo/sessions`, matching the frontend's fail-and-reissue branch.
- **Impact:** A reviewer can lose the active seller/show session during an ordinary demo. Reloading recovers the UI with a new token but can also expose reset or divergent marketplace state, so the current Vercel deployment is not reviewer-reliable.
- **First incorrect pipeline stage:** Session authority resolution before ingestion or model dispatch.
- **Root cause:** The original `DemoSessionRegistry` stored opaque tokens only in one process-local Python dictionary. Vercel Functions can recycle an instance or route a later request to another instance. Persisting the registry alone on Vercel is insufficient because each function's `/tmp` SQLite database, SSE wakeups, marketplace state, and usage ledger are still non-shared.
- **Rejected quick fix:** Automatically issuing a new session and retrying the message would hide the error but would not restore the same listing, chat, quota, or SSE state. Retrying a write after an uncertain transport failure could also duplicate effects. A stateless signed token alone would fix token recognition but not shared application state.
- **Accepted fix:** Add a `demo_sessions` SQLite table containing only the SHA-256 token digest and application-derived seller/show/actor authority; resolve every request from that trusted row and fail closed on scope inconsistency. Make `create_challenge_app()` honor `SIDESTAGE_DATABASE_PATH`. Add a pinned Docker runtime and a Render Blueprint with one paid Starter instance, one 1 GB `/var/data` disk, and `/healthz`. Keep Vercel explicitly diagnostic-only.
- **Verification:** The new two-test RED command first failed with app-restart HTTP `404` and a missing `Dockerfile`; it then passed. The complete challenge file passed `12 passed in 0.73s`, the broader challenge/stream/reset/browser focus passed `29 passed in 26.87s`, and the exact full command `uv run pytest -q` passed `380 passed, 5 deselected in 77.03s`. `render.yaml` passed Render's official current Blueprint JSON Schema. The pinned Python 3.12.14 image `sidestage-challenge:test` built successfully. Container A created one session, pushed `lst_velocity_aero_dash`, and accepted deterministic chat `hello`; after container A was stopped and deleted, container B mounted the same directory and the original token returned HTTP `200` with the listing, chat, receipt, stream offset, and quota intact. The long-running localhost container then completed one real Luna exact-availability call, restarted, and returned the same token, grounded auto-reply, and receipt with HTTP `200`. Replacing that container with the final rebuilt image preserved the same token and the clean post-reset state. On 2026-08-19, `docker inspect --format '<restart-policy> <port-bindings> <mounts>' sidestage-local` reported `unless-stopped`, loopback-only `127.0.0.1:8768`, and the repository's `var/stateful-demo` directory mounted at `/var/data`. The first authenticated Playwright container smoke (credential value redacted) deliberately used `page.goto(..., wait_until='networkidle')` and timed out at 30 seconds because the loaded application correctly kept its SSE request open. Replacing that generic readiness condition with `domcontentloaded` plus authoritative assertions for three seller options, `show_velocity_kicks`, `Auto-message`, `Mock livesell`, and an opaque `ses_` token passed with HTTP `200` and zero browser errors. No application change was required for that harness-only failure. After Docker itself restarted, the previously issued session still returned HTTP `200` with its clean reset snapshot and durable stream offset. `docker image inspect`, `docker history --no-trunc`, and an image-filesystem assertion found no provider/reviewer credential, `.env`, Git metadata, `AGENTS.md`, internal docs, or local state in the image. Because the development Docker engine is Linux/AArch64, `docker build --platform linux/amd64 --tag sidestage-challenge:amd64 .` independently exercised the hosted Linux/AMD64 dependency path and succeeded. A temporary container from that image returned `/healthz` `200`, anonymous API `401`, and authenticated API `200`; its dummy-credential container and synthetic database were then deleted. The final focused command `uv run pytest -q tests/integration/test_challenge_deployment.py::test_challenge_session_and_marketplace_state_survive_app_restart tests/integration/test_challenge_deployment.py::test_stateful_deployment_contract_uses_one_instance_and_persistent_sqlite tests/integration/test_challenge_deployment.py::test_challenge_factory_honors_deployment_database_path` initially stopped before collection because the restricted shell could not open uv's cache metadata; the identical command with cache permission passed `3 passed in 0.57s`.
- **Live smoke latency:** The one real cold request returned the correct `Yes — US M 9 is available (2 left).` auto-message in about 2,524.54 ms backend total and 2.56 seconds HTTP total. It missed the two-second target and is retained as compatibility/deployment evidence, not a passing SLO measurement.
- **Remaining risk:** The persistent-disk topology is intentionally one instance and has a few seconds of deploy downtime. Prepared-chat cursor, fixed runtime-selection timestamp, scheduler queues, and wake events remain in memory; committed show/chat/reply/quota/session data and durable stream offsets survive. Demo-session rows currently have no retention job, which is acceptable for the bounded challenge quotas but would require expiry and cleanup in a production service. Vercel `/tmp` remains non-durable and must not be sent to reviewers. Horizontal scale requires a shared transactional database and cross-instance notifications.
- **60-second interview explanation:** The model and key were healthy; Vercel lost the state before model dispatch because a later function did not share the first function's memory or `/tmp`. Retrying or signing the token would not restore the listing, chat, or write history. I moved session authority into the same SQLite transaction domain as the show, stored only a token digest, and packaged one container with one persistent disk. A destructive container-replacement test proved the original token, listing, chat, quota, and receipt all survived.

### DBG-031 — Challenge mode disabled the reviewer traffic simulator

- **Date and commit:** 2026-08-18; current dirty tree after `3fda622`.
- **Incident state:** Fixed locally and deployed to the protected Preview target; builder UI confirmation pending.
- **Evidence maturity:** `Implemented`, not `Verified` or `Measured`; no commit-bound command or evidence exists yet.
- **Expected:** A reviewer can start **Mock livesell** and observe single buyer messages entering the real Agent Core FIFO queue at the prepared cadence, while the high-cost `Burst ×8` path remains unavailable.
- **Observed:** The control was labeled **Play fixture** and disabled whenever challenge mode was active, so no prepared stream could be started from the protected seller UI.
- **Initial red command and evidence:** `uv run pytest -q tests/integration/test_challenge_deployment.py::test_challenge_runtime_is_one_call_read_only_with_mock_stream_and_no_burst tests/e2e/test_marketplace_ui.py::test_non_ai_marketplace_flow_is_server_owned_and_reconnectable` failed both tests: `prepared_stream` was `false`, and the browser rendered `Play fixture` instead of `Mock livesell`.
- **Root cause:** The challenge capability gate treated the single-message continuous simulator and the eight-message batch burst as one cost-risk category. That contradicted the existing FIFO pressure design and removed an important reviewer test path.
- **Rejected approach:** Wait for each model workflow to finish before submitting the next prepared message. The builder rejected this because the Agent Core FIFO scheduler should own the queue and expose queue-inclusive latency.
- **Fix:** Expose `prepared_stream=true` in challenge mode, preserve `prepared_burst=false`, keep the existing 1.65-second browser cadence with `count=1`, and rename seller-visible fixture playback text and failures to **Mock livesell**. Session, quota, or endpoint errors stop the timer and remain visible.
- **Focused verification:** The same two-test command passed with `2 passed in 20.18s`; the complete challenge-deployment plus marketplace-browser files passed `11 passed in 24.46s`; `node --check src/sidestage/web/static/app.js` and `git diff --check` passed; and `uv run pytest -q` passed `377 passed, 5 deselected in 77.28s`. Vercel deployment `dpl_3iNqXqJY7pJjTApK1mZtEebpW6nq` reported target `preview` and Ready; direct anonymous HTTP returned Vercel SSO `302`, tunneled `/healthz` returned `200`, and tunneled anonymous `/api/sellers` remained behind application Basic Auth. These are dirty-tree implementation and deployment-smoke results only.
- **Remaining risk:** Mock livesell is restart-safe only on the accepted persistent single-instance topology. Vercel function recycling can still split its `/tmp` state while playback is running. Continuous playback consumes the configured per-session allowance one admitted model request at a time.

### DBG-032 — Production-scoped Basic credentials were incorrectly given for the Preview deployment

- **Date and commit:** 2026-08-18; current dirty tree after `3fda622`.
- **Incident state:** Fixed on a new protected Preview deployment.
- **Evidence maturity:** Deployment-smoke `Implemented`, not commit-bound `Verified`.
- **Expected:** The credentials supplied to the builder authenticate the exact protected URL being tested.
- **Observed:** The builder could not log in. A tunneled request using the supplied credentials returned application HTTP `401`.
- **Root cause:** The supplied username/password belonged to the earlier production-targeted deployment's command-scoped environment. The new target was a real Preview and loaded a different encrypted `SIDESTAGE_DEMO_USERNAME` and `SIDESTAGE_DEMO_PASSWORD` pair from the Vercel Preview environment. The AI incorrectly assumed the credentials were shared across targets.
- **Rejected diagnostic:** Pulling the complete Preview environment locally merely to read two Basic Auth values was rejected because it would also expose the OpenAI key. No credential bundle was downloaded.
- **Fix:** Rotate only `SIDESTAGE_DEMO_USERNAME` and `SIDESTAGE_DEMO_PASSWORD` in the Vercel Preview environment, keep them Sensitive, and create a new Preview deployment. The OpenAI key and model variables were neither read nor changed. The password is communicated out of band and is not retained in repository documentation.
- **Verification:** Deployment `dpl_9nYnHsB2ihNLrry8KX8PfEp9dJNP` reached Ready. `vercel curl /api/sellers --deployment <new-preview> -- --user <rotated-credentials>` returned HTTP `200`, `challenge_mode=true`, `prepared_stream=true`, and `prepared_burst=false`.
- **Prevention:** Treat deployment-target credentials as scoped configuration. Verify the exact URL with the exact supplied credentials before handing it to a builder or reviewer; never infer that Production and Preview encrypted values match.

## 10. Known issues and limitations

- M2.3 uses synthetic shared-credential demo sessions rather than production authentication. Their opaque token authority now persists as a digest in SQLite and survives a restart on the accepted single-instance persistent-disk topology; it is not a horizontally shared identity service.
- The credential-free `create_app()` factory uses an empty fail-closed scripted runner unless code injects a `ModelRunner`; use the explicit `create_live_app()` factory for the credentialed reviewer path.
- The M3B eight-stage debugger reads persisted runtime observations. The full deterministic feature and safety surface through protected deployment commit `3fda622` is `Verified` by the current-tree suite; this does not turn any prior live timing artifact into final `Measured` release evidence.
- One exploratory Gemini Flash-Lite cell passes the current live gates at 72/72 semantic correctness and 1,848.92 ms answerable-parent p95, but it is not commit-bound and provider latency varied across repeats. A clean committed-tree rerun is required before selecting the release configuration.
- Port `8000` was occupied by an unrelated local Uvicorn process during the documentation closeout. This is an environment conflict rather than an application defect; the committed app was smoke-tested on port `8766` without changing application code.

## 11. Interview quick reference

Before submission, populate:

- Exact end-to-end and test commands.
- Up to three strongest real debugging incidents.
- Exact files and functions involved in each incident.
- The trace or test evidence proving each fix.
- One failed approach and why it was rejected.
- One remaining limitation and the next diagnostic step.
- A concise explanation of what was personally built, reused, AI-generated, rewritten, and rejected.

## 12. P0 implementation audit — 2026-08-18

- **Target code commit:** `3fda622` (`Add protected challenge deployment and usage limits`). At the time of the full-suite run, runtime source and tests matched this commit; the worktree also contained unrelated `.gitignore` and repository-instruction changes. The later uncommitted Vercel request-path correction is recorded separately in DBG-029 and is not part of the 376-test commit-bound result.
- **Full deterministic command:** `uv run pytest -q`.
- **Full deterministic result:** `376 passed, 5 deselected in 77.61s`. The five deselected tests are marked `live_model` and require external provider credentials: one core terminal smoke, one core live matrix, the real two-call R2 path, one OpenRouter template call, and one live Kimi runtime-switch case.
- **Focused browser command:** `uv run pytest tests/e2e/test_golden_demo.py tests/e2e/test_marketplace_ui.py tests/e2e/test_debugger.py tests/e2e/test_r2_inbox.py tests/e2e/test_r3_controls.py -q`.
- **Focused browser result:** `12 passed in 32.04s`. The run generated desktop seller-workspace, 390 px seller-workspace, marketplace-ledger, and eight-stage debugger captures in Pytest's temporary evidence directory. Visual inspection confirmed the two-primary-surface hierarchy, stacked mobile layout without horizontal overflow, active listing/current price/variant stock/policy projection, five marketplace controls, Manual review/Auto-message supervision, and the separate detailed debugger.
- **Protected reviewer command:** `uv run pytest tests/integration/test_challenge_deployment.py -q`.
- **Protected reviewer result:** After the later working-tree routing correction added one regression, the focused file passed `9 passed in 0.55s`. The local protected-factory behavior is covered by the earlier commit-bound full suite; the no-rewrite Vercel correction remains `Implemented`, not `Verified`, until committed and rerun.
- **Current working-tree regression result:** After the routing, Mock livesell, session-persistence, and stateful-deployment corrections, `uv run pytest -q` passed `380 passed, 5 deselected in 77.03s`. This proves the dirty-tree corrections do not regress the deterministic suite, but they are not promoted to commit-bound `Verified` evidence.
- **Audit conclusion:** The original P0 UI/marketplace design plus the approved Copilot, trace, reset, runtime-selection, and local protected-reviewer extensions are implemented and deterministically `Verified`. The remaining live semantic/safety/latency run is release qualification, not missing UI or domain functionality. Vercel-specific routing is a separate dirty-tree deployment closeout item.
- **Open P0 gate:** Run the current committed `one_call_template` release configuration against the fixed three-seller workload and retain one artifact with at least 95% semantic correctness, zero hard safety violations, and answerable-parent p95 below two seconds. Do not reclassify this as P1 because it is an explicit challenge target.
- **P1 / out-of-scope split:** R0 Shadow plus real pilot timing belongs to P1. External marketplace APIs, open-web research, production commerce, and a general agent runtime remain out of scope. Shared database/session/notification infrastructure is P1 only if the reviewer deployment must scale beyond one persistent ASGI process.

## 13. Related documents

- [Product Requirements Document](PRD.md)
- [Technical Design Document](TDD.md)
- [AI proposal and rejection history](ai-proposal-rejection-history.md)
