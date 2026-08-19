# SideStage

SideStage is a synthetic real-time copilot prototype for sneaker live sellers. The accepted product and technical contracts are in [`docs/PRD.md`](docs/PRD.md) and [`docs/TDD.md`](docs/TDD.md).

## Run the local prototype

Install the locked development environment, then start the credential-free deterministic SideStage server:

```bash
uv sync --group dev
uv run playwright install chromium
uv run uvicorn sidestage.app:create_app --factory --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/app/](http://127.0.0.1:8000/app/). The debugger ledger is at [http://127.0.0.1:8000/app/debug.html](http://127.0.0.1:8000/app/debug.html).

The browser holds only an opaque demo-session token. SQLite is authoritative for show, chat, listing, inventory, epoch, question, trace, reply, and receipt state; Server-Sent Events keep multiple projections synchronized. The current application includes the M3B Copilot Inbox, R2 review controls, bounded R3 controls, the persisted eight-stage debugger, and developer-only session Reset. Push a listing before sending prepared or custom buyer chat; without an active immutable listing epoch, both UI paths are disabled and the server returns typed `active_slot_empty` before model work. Open questions appear newest-first in **Now**, move to collapsed **Earlier** rows after twenty seconds, and leave the open Inbox when answered or dismissed. Durable R2/R3 replies appear in Live Chat with the exact source buyer quote.

The `create_app` Uvicorn factory deliberately starts with a fail-closed empty scripted model runner unless a runner is injected by a test or harness. It still registers both closed workflows, which makes the UI, marketplace, and runtime selector safe to inspect without credentials.

For the live-model prototype, keep one `KEY=value` per line in the ignored `.env`. A direct OpenAI configuration can be:

```bash
OPENAI_API_KEY=your-openai-key
SIDESTAGE_MODEL_PROVIDER=openai
SIDESTAGE_MODEL_ID=gpt-5.6-luna
SIDESTAGE_MODEL_REASONING_EFFORT=none
# Optional direct-OpenAI scheduling tier; omit for standard service.
# SIDESTAGE_MODEL_SERVICE_TIER=priority
SIDESTAGE_WORKFLOW_STRATEGY=one_call_template
```

Environment variable names are exact: `OPEN_API_KEY` is not read. Use `OPENAI_API_KEY` or the provider-scoped override `SIDESTAGE_MODEL_API_KEY` for direct OpenAI.

For an OpenRouter one-call benchmark, use the current exact model slug from OpenRouter rather than an alias guessed in code:

```bash
OPENROUTER_API_KEY=your-openrouter-key
SIDESTAGE_MODEL_PROVIDER=openrouter
SIDESTAGE_MODEL_ID=provider/exact-model-slug
SIDESTAGE_MODEL_REASONING_EFFORT=none
SIDESTAGE_WORKFLOW_STRATEGY=one_call_template
```

To expose the approved multi-model catalog in the debugger, keep both provider keys in the same `.env` while retaining one startup default:

```bash
OPENAI_API_KEY=your-openai-key
OPENROUTER_API_KEY=your-openrouter-key
SIDESTAGE_MODEL_PROVIDER=openai
SIDESTAGE_MODEL_ID=gpt-5.6-luna
SIDESTAGE_MODEL_REASONING_EFFORT=none
SIDESTAGE_WORKFLOW_STRATEGY=one_call_template
```

With both keys present, `create_live_app` loads [`config/runtime_model_profiles.json`](config/runtime_model_profiles.json). The debugger can switch new chat among startup-approved compatible pairs without a restart. The catalog distinguishes Luna `none`, Luna `low`, and direct-OpenAI Luna `none` with `service_tier=priority`; it also includes OpenRouter Gemini 3.7 Flash `low` and Gemini 3.5 Flash-Lite `minimal`. DeepSeek V4 Flash and Kimi K3 remain enabled for one-call comparison; GLM 5.2 remains visible but disabled because it failed strict tool compatibility. OpenAI priority service and reasoning effort are independent settings. OpenRouter profiles send reasoning through its unified `reasoning.effort` request field and never use OpenAI's service tier. The seller workspace shows the exact active profile display name and selection version read-only, so Luna reasoning/service variants remain distinguishable after a debugger switch. The UI never accepts model IDs, base URLs, credentials, prompts, tools, or templates.

Then run `uv run --env-file .env uvicorn sidestage.app:create_live_app --factory --host 127.0.0.1 --port 8000`. `create_live_app` requires the key matching the selected provider, uses strict function schemas, and exits before database initialization on a missing or mismatched key, model, provider, or strategy. OpenRouter requests disable fallbacks, require parameter support, sort by latency for screening, and opt into router metadata. Credentials never enter application state, model-visible input, or trace metadata.

Run the deterministic test suite with:

```bash
uv run pytest -q
```

For a manual end-to-end seller/debugger check:

1. Open the seller workspace and select **Reset demo** for a clean authenticated seller/show.
2. Push one in-stock listing, then submit a buyer question. Review the resulting R2 card or enable bounded R3 for an approved category.
3. Confirm the sent seller reply appears in Live Chat and quotes the original buyer message.
4. Open the debugger, select the trace, and inspect Evidence Retrieval, Registered Reply Agent, Broker Guardrails, and Result.
5. Change the debugger workflow/model selection, return to the seller workspace, and verify only newly accepted chat uses the new read-only badge/version.

Generate and replay the fixed livesell workload with:

```bash
uv run python -m sidestage.fixtures.generator \
  --scenario fixtures/scenarios/pressure_v1.json \
  --seed 20260817 \
  --output runs/regression_v1
```

Run the deterministic SideStage safety evaluator with:

```bash
uv run python -m sidestage.trace.evaluator \
  --scenario fixtures/scenarios/safety_races_v1.json \
  --seed 20260817 \
  --model scripted \
  --output runs/exploratory/evaluation_scripted.json
```

For an exploratory pressure run, use the same `.env` and select the workflow explicitly:

```bash
uv run --env-file .env python -m sidestage.trace.evaluator \
  --scenario fixtures/scenarios/pressure_v1.json \
  --seed 20260817 \
  --model live \
  --strategy one_call_template \
  --output runs/exploratory/evaluation_live.json
```

Run the separately marked two-call reviewer-path smoke test with the same exported environment:

```bash
uv run pytest \
  tests/integration/test_live_app_factory.py::test_live_app_factory_executes_the_real_two_call_r2_path \
  -m live_model -q
```

Legacy pre-commit direct OpenAI artifacts report `one_call_template` at 66/72 broker-accepted suggestions and 3,414.37 ms all-event workload p95, compared with 54/72 and 4,530.28 ms for `two_call_draft`; those artifacts predate semantic scoring and denominator separation, so they are not answer-correctness or final product-SLO measurements. The current evaluator adds explicit expected category/evidence/template labels for all 72 answerable cases, a semantic-correctness gate, and separate all-event, answerable-parent, model-backed, R2, and R3 latency denominators. It uses answerable-parent p95 for the release SLO and keeps the workload manifest independent of evaluation profile. One later dirty-tree OpenRouter Gemini 3.5 Flash-Lite `minimal` diagnostic reached 72/72 semantic correctness and 1,848.92 ms answerable-parent p95 with all hard invariants at zero, but its retained artifact identifies `39885e4` and predates the final optimization/DBG-023 commit `12f3bab`. It is therefore diagnostic rather than final `Measured` evidence. M3B.6 remains open until the reset/UI extension receives a builder-approved commit and the clean resulting tree passes the deterministic suite and fixed live pressure evaluation into `runs/final_evaluation/`.
