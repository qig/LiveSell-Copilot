# SideStage

SideStage is a synthetic real-time copilot prototype for sneaker live sellers. The accepted product and technical contracts are in [`docs/PRD.md`](docs/PRD.md) and [`docs/TDD.md`](docs/TDD.md).

## Run the non-AI marketplace emulator

Install the locked development environment, then start the authoritative M2.3 server:

```bash
uv sync --group dev
uv run playwright install chromium
uv run uvicorn sidestage.app:create_app --factory --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/app/](http://127.0.0.1:8000/app/). The debugger ledger is at [http://127.0.0.1:8000/app/debug.html](http://127.0.0.1:8000/app/debug.html).

The browser holds only an opaque demo-session token. SQLite is authoritative for show, chat, listing, inventory, epoch, and receipt state; Server-Sent Events keep multiple projections synchronized. Copilot is intentionally off in M2.3, so running this slice makes no model call.

Run the deterministic test suite with:

```bash
uv run pytest -q
```

The seven-stage reply trace remains explicitly simulated until the M3B livesell reply adapter is connected. Marketplace events, epochs, and receipts in the lower debugger ledger are live backend projections.
