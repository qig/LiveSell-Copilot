# M2.1 Import Trace Bridge Design

> Status: Accepted for implementation by the builder; working-tree evidence only until reviewed and committed

## Purpose and boundary

M2.debugger must show whether the approved seller fixture actually passed through the M2.1 typed importer, where that import stopped, and what bounded output it produced. This bridge covers fixture reading, typed contract validation, approved-seller validation, and tenant-index construction. It does not trace marketplace actions, reply generation, or M3B effects.

The existing reply flight recorder remains a presentation fixture. The new import panel is a separate runtime observation and must not make the reply scenarios appear to be backend evidence.

## Approaches considered

1. **Duplicate M2.1 validation inside a debugger endpoint.** Rejected because the debugger could report success while the real importer would reject the same data.
2. **Instrument the existing loader with a bounded observer — selected.** The production import path remains authoritative, while a recorder receives sanitized stage transitions and counts. The observer cannot alter the imported document or tenant indexes.
3. **Wait for the complete FastAPI marketplace runtime.** Rejected for this slice because it delays useful import diagnosis and couples M2.debugger to unfinished M2.2/M2.3 work.

## Architecture and data flow

```text
Debugger "Run typed import"
  -> GET /api/debug/import-trace
  -> trace_seller_fixture_import()
  -> load_seller_fixture(observer=recorder)
       1. source_read
       2. contract_validation
       3. approved_seller_set
       4. tenant_index_build
  -> ephemeral sanitized trace JSON
  -> compact import diagnosis in M2.debugger
```

The local review server uses Python's standard HTTP server so this slice does not claim or pre-empt the planned FastAPI/SQLite marketplace runtime. It serves the repository's existing static URLs and one same-origin diagnostic endpoint. A future application server can reuse `trace_seller_fixture_import()` and replace the transport without changing the browser view contract.

## Trace contract and safety

The response identifies `schema_version=sidestage.import_trace.v1`, `runtime_source=m2_1_typed_loader`, ephemeral durability, a unique trace ID, source filename and digest, ordered stage states, first failure when present, and accepted catalog counts. It never includes absolute paths, source JSON, policy text, credentials, Pydantic input echoes, or stack traces.

Successful stages are `passed`. The first rejected stage is `failed`; later stages are `skipped`. A rejected import still returns a trace document so the debugger can explain the failure. The diagnostic observer is optional, and existing `load_seller_fixture()` callers retain the same result and exception behavior.

## UI and fallback

A compact **M2.1 typed import** panel sits between the reply hero and the synthetic reply controls. It shows transport state, four import stages, first-stop diagnosis, counts, source digest, and expandable sanitized JSON. It uses the established flight-recorder visual system and wraps into a two-column stage grid on narrow screens.

The import runs only when the developer selects **Run typed import**. This prevents the legacy static preview from producing a false backend claim. If the endpoint is unavailable, the panel says that the backend bridge is offline while the reply fixture and marketplace ledger remain usable.

## Testing

- Unit tests cover accepted, contract-rejected, and missing-source traces, exact stage ordering, use of the real M2.1 loader, digest/count output, and payload sanitization.
- An HTTP integration test covers the runtime endpoint, no-store response, and continued static-file serving.
- The debugger browser test runs against the review server and verifies runtime labeling, four passed stages, counts, rerun behavior, reply scenarios, ledger preservation, console cleanliness, and narrow layout.
- The exact M2.1 unit and browser gates run again after the bridge is connected.
