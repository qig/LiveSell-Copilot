# SideStage

SideStage is a synthetic real-time copilot prototype for sneaker live sellers. The accepted product and technical contracts are in [`docs/PRD.md`](docs/PRD.md) and [`docs/TDD.md`](docs/TDD.md).

## Run the local prototype

Install the locked development environment, then start the authoritative M2.3 server:

```bash
uv sync --group dev
uv run playwright install chromium
uv run uvicorn sidestage.app:create_app --factory --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/app/](http://127.0.0.1:8000/app/). The debugger ledger is at [http://127.0.0.1:8000/app/debug.html](http://127.0.0.1:8000/app/debug.html).

The browser holds only an opaque demo-session token. SQLite is authoritative for show, chat, listing, inventory, epoch, question, trace, reply, and receipt state; Server-Sent Events keep multiple projections synchronized. The current application includes the M3B Copilot Inbox, R2 review controls, bounded R3 controls, and the persisted eight-stage debugger.

The `create_app` Uvicorn factory deliberately starts with a fail-closed empty scripted model runner unless a runner is injected by a test or harness. This makes the UI and marketplace safe to inspect without credentials.

For the live-model prototype, keep one `KEY=value` per line in the ignored `.env`. A direct OpenAI configuration can be:

```bash
OPENAI_API_KEY=your-openai-key
SIDESTAGE_MODEL_PROVIDER=openai
SIDESTAGE_MODEL_ID=gpt-5.6-luna
SIDESTAGE_MODEL_REASONING_EFFORT=none
SIDESTAGE_WORKFLOW_STRATEGY=two_call_draft
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

Then run `uv run --env-file .env uvicorn sidestage.app:create_live_app --factory --host 127.0.0.1 --port 8000`. `create_live_app` requires the key matching the selected provider, uses strict function schemas, and exits before database initialization on a missing or mismatched key, model, provider, or strategy. OpenRouter requests disable fallbacks, require parameter support, sort by latency for screening, and opt into router metadata. Credentials never enter application state, model-visible input, or trace metadata.

Run the deterministic test suite with:

```bash
uv run pytest -q
```

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

No current live cell passes the release gate. On pre-commit direct OpenAI runs, `one_call_template` improved to 66/72 supported answerable suggestions, zero hard timeouts, and 3,414.37 ms end-to-end workload p95, compared with 54/72, 14 hard timeouts, and 4,530.28 ms for `two_call_draft`. Fallback-disabled OpenRouter pressure runs reached 7/72 and 5,022.01 ms p95 for DeepSeek V4 Flash/Inceptron and 17/72 and 5,024.85 ms for Kimi K3/Together; GLM 5.2 failed the strict compatibility smoke and was not pressure-tested. Safety/no-effect scorecards remained intact, but quality and latency did not. These remain pre-commit implementation diagnostics, not `Measured` evidence. The committed deterministic suite passes at code head `6ba208a`; the eight debugger stages are persisted backend observations from the real hardcoded reply path, and the frontend does not synthesize reply-stage success.
