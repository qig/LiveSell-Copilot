# SideStage

SideStage is a synthetic real-time copilot prototype for sneaker live sellers. The accepted product and technical contracts are in [`docs/PRD.md`](docs/PRD.md) and [`docs/TDD.md`](docs/TDD.md).

## Preview the M2 marketplace UI and debugger

Run the local review server to use the M2.1 typed-import trace:

```bash
uv run python -m sidestage.web.server --port 8000
```

Open [http://127.0.0.1:8000/src/sidestage/web/static/](http://127.0.0.1:8000/src/sidestage/web/static/).

The preview loads the approved synthetic fixtures and uses a browser-local demo adapter so the seller interactions are executable before the FastAPI/SQLite M2 kernel exists. It is not backend marketplace-safety or durability evidence. Use **Reset this seller show** to clear the active seller's local demo state.

The separate developer projection is available at [http://127.0.0.1:8000/src/sidestage/web/static/debug.html](http://127.0.0.1:8000/src/sidestage/web/static/debug.html).
Select **Check import** there to execute the real typed catalog loader and inspect its ephemeral four-stage backend trace. The seven-stage message flow remains simulated: evidence-ready examples stop at **Agent** with `AGENT_NOT_CONNECTED`, and later steps remain skipped until the livesell reply adapter is connected.

For projection-only review, `python3 -m http.server 8000` still serves the static UI. In that mode the import panel remains unexecuted and cannot claim backend evidence.
