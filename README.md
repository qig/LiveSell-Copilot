# SideStage

SideStage is a synthetic real-time copilot prototype for sneaker live sellers. The accepted product and technical contracts are in [`docs/PRD.md`](docs/PRD.md) and [`docs/TDD.md`](docs/TDD.md).

## Preview the M2 marketplace UI

The current UI slice runs without a frontend build step:

```bash
python3 -m http.server 8000
```

Open [http://127.0.0.1:8000/src/sidestage/web/static/](http://127.0.0.1:8000/src/sidestage/web/static/).

The preview loads the approved synthetic fixtures and uses a browser-local demo adapter so the seller interactions are executable before the FastAPI/SQLite M2 kernel exists. It is not backend safety or durability evidence. Use **Reset this seller show** to clear the active seller's local demo state.

The separate developer projection is available at [http://127.0.0.1:8000/src/sidestage/web/static/debug.html](http://127.0.0.1:8000/src/sidestage/web/static/debug.html).
