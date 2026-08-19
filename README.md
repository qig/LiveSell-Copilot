# SideStage

SideStage is a real-time AI copilot prototype for sneaker live sellers. It combines buyer chat, grounded replies, active listings, inventory, seller operations, and an auditable execution ledger in one demo.

## Try the hosted demo

Open [https://livesell-copilot.onrender.com/app/](https://livesell-copilot.onrender.com/app/). Use username `qiguo`; the reviewer password is supplied separately in the submission access notes.

### Reviewer walkthrough

1. **Push a listing first.** Select an in-stock product from the Catalog rail and use **Push**. Buyer chat stays disabled until the show has a trusted active listing. Use **Reset demo** first if you want a clean show.
2. **Generate buyer traffic.** Start **Mock livesell** for prepared messages and a lightweight FIFO pressure demonstration, or type your own buyer message in Live Room.
3. **Try the five seller operations.** The seller panel supports **Push**, **Swap**, **Unlist**, **Mark down**, and **Inventory**. Only the seller controls can execute them.
4. **Observe Auto-message.** New and reset shows start with **Auto-message** enabled. Switch to **Manual review** whenever you want to approve or edit replies yourself.
5. **Compare AI-handled and seller-needed questions.** Grounded questions move through **Drafting** to **Auto answered** or **Ready for review**. Missing, conflicting, stale, ambiguous, unsupported, or judgment-heavy questions show **Needs you**.
6. **Use the question panes.** On desktop, questions from the last twenty seconds appear newest-first in **Now** on the left. Older unresolved questions move to collapsed **Earlier** rows on the right. Live Room keeps the chronological chat and sent replies.
7. **Switch sellers.** VelocityKicks, VaultConsign, and RotationKicks each provide isolated catalog, inventory, policy, show, and mock-message data for different scenarios.
8. **Open Ledger.** Inspect the event history, listing epochs, receipts, routing, evidence, guardrails, workflow stages, and latency behind each result.

SideStage implements and benchmarks both `one_call_template` and `two_call_draft`. The hosted reviewer demo uses the lower-latency `one_call_template` workflow with GPT-5.6 Luna as the default real-time copilot model.

## Run locally

Install [uv](https://docs.astral.sh/uv/), then create an ignored `.env` file:

```bash
OPENAI_API_KEY=your-openai-key
SIDESTAGE_MODEL_PROVIDER=openai
SIDESTAGE_MODEL_ID=gpt-5.6-luna
SIDESTAGE_MODEL_REASONING_EFFORT=none
SIDESTAGE_WORKFLOW_STRATEGY=one_call_template
```

Install dependencies and run the live-model application:

```bash
uv sync --group dev
uv run --env-file .env uvicorn sidestage.app:create_live_app \
  --factory --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/app/](http://127.0.0.1:8000/app/). Ledger is at [http://127.0.0.1:8000/app/debug.html](http://127.0.0.1:8000/app/debug.html).

To run the complete deterministic and browser test suite:

```bash
uv run playwright install chromium
uv run pytest -q
```

Keep provider keys only in `.env` or server-side deployment secrets. Never commit them or send them to the browser.

## Product and technical specifications

- [Product Requirements Document](docs/PRD.md)
- [Technical Design Document](docs/TDD.md)
