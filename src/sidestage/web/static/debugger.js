(() => {
  "use strict";

  const SESSION_KEY = "sidestage.m2.session";
  const TRACE_FIXTURE_URL = "/fixtures/debugger/reply_trace_scenarios.json";
  const IMPORT_TRACE_URL = "/api/debug/import-trace";
  const IMPORT_STAGE_CATALOG = [
    {number: 1, key: "source_read", label: "Read source"},
    {number: 2, key: "contract_validation", label: "Validate contract"},
    {number: 3, key: "approved_seller_set", label: "Approve sellers"},
    {number: 4, key: "tenant_index_build", label: "Build tenant indexes"},
  ];
  const dom = {};

  let traceDocument = null;
  let activeScenario = null;
  let activeEvent = null;
  let activeStageNumber = 1;
  let traceHasRun = false;
  let marketplaceEventSource = null;

  document.addEventListener("DOMContentLoaded", boot);

  async function boot() {
    cacheDom();
    bindEvents();
    initializeImportTrace();

    const [traceResult] = await Promise.allSettled([fetchJson(TRACE_FIXTURE_URL)]);

    if (traceResult.status === "fulfilled") {
      try {
        validateTraceDocument(traceResult.value);
        traceDocument = traceResult.value;
        initializeTraceControls();
      } catch (error) {
        renderTraceError(error);
      }
    } else {
      renderTraceError(traceResult.reason);
    }

    await renderMarketplace();
    connectMarketplaceEvents();
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`Unable to load ${url} (${response.status})`);
    return response.json();
  }

  function validateTraceDocument(documentValue) {
    if (
      documentValue?.schema_version !== "sidestage.debugger_projection.v1" ||
      documentValue?.synthetic !== true ||
      documentValue?.runtime_source !== "presentation_fixture"
    ) {
      throw new Error("Trace fixture identity or evidence labeling is invalid.");
    }

    if (documentValue.stage_catalog?.length !== 7 || !documentValue.scenarios?.length) {
      throw new Error("Trace fixture must provide seven stages and at least one scenario.");
    }

    const stageKeys = documentValue.stage_catalog.map((stage) => stage.key).join("|");
    documentValue.scenarios.forEach((scenario) => {
      if (!scenario.events?.length) throw new Error(`Scenario ${scenario.scenario_id} has no events.`);
      scenario.events.forEach((event) => {
        const eventKeys = event.stages?.map((stage) => stage.key).join("|");
        if (eventKeys !== stageKeys) throw new Error(`Trace ${event.trace_id} has an invalid stage order.`);
        if (!event.first_stop) throw new Error(`Trace ${event.trace_id} must identify where the current build stops.`);
        if (event.stages.some((stage) => stage.state === "passed")) {
          throw new Error(`Trace ${event.trace_id} cannot mark simulated reply work as passed.`);
        }
      });
    });
  }

  function cacheDom() {
    Object.assign(dom, {
      seller: document.querySelector("#debug-seller"),
      activeSku: document.querySelector("#debug-active-sku"),
      showId: document.querySelector("#debug-show-id"),
      showVersion: document.querySelector("#stat-show-version"),
      eventCount: document.querySelector("#stat-event-count"),
      epochCount: document.querySelector("#stat-epoch-count"),
      receiptCount: document.querySelector("#stat-receipt-count"),
      tabEventCount: document.querySelector("#tab-event-count"),
      tabEpochCount: document.querySelector("#tab-epoch-count"),
      tabReceiptCount: document.querySelector("#tab-receipt-count"),
      eventLedger: document.querySelector("#event-ledger"),
      epochLedger: document.querySelector("#epoch-ledger"),
      receiptLedger: document.querySelector("#receipt-ledger"),
      ledgerEmpty: document.querySelector("#debug-empty"),
      refresh: document.querySelector("#refresh-ledger"),
      traceScenario: document.querySelector("#trace-scenario"),
      traceEvent: document.querySelector("#trace-event"),
      traceRun: document.querySelector("#run-trace"),
      traceReset: document.querySelector("#reset-trace"),
      traceStatus: document.querySelector("#trace-status"),
      traceEventIndex: document.querySelector("#trace-event-index"),
      traceEventCustomer: document.querySelector("#trace-event-customer"),
      traceEventTitle: document.querySelector("#trace-event-title"),
      traceEventText: document.querySelector("#trace-event-text"),
      traceEventMeta: document.querySelector("#trace-event-meta"),
      traceStageRail: document.querySelector("#trace-stage-rail"),
      traceDiagnosis: document.querySelector("#trace-diagnosis"),
      traceDiagnosisIcon: document.querySelector("#trace-diagnosis-icon"),
      traceDiagnosisTitle: document.querySelector("#trace-diagnosis-title"),
      traceDiagnosisMessage: document.querySelector("#trace-diagnosis-message"),
      traceTotalDuration: document.querySelector("#trace-total-duration"),
      traceStageKicker: document.querySelector("#trace-stage-kicker"),
      traceStageTitle: document.querySelector("#trace-stage-title"),
      traceStageState: document.querySelector("#trace-stage-state"),
      traceStageDuration: document.querySelector("#trace-stage-duration"),
      traceStageSummary: document.querySelector("#trace-stage-summary"),
      traceStageReason: document.querySelector("#trace-stage-reason"),
      traceStageInput: document.querySelector("#trace-stage-input"),
      traceStageOutput: document.querySelector("#trace-stage-output"),
      traceDestinationGrid: document.querySelector("#trace-destination-grid"),
      importRun: document.querySelector("#run-import-trace"),
      importRuntime: document.querySelector("#import-trace-runtime"),
      importStatus: document.querySelector("#import-trace-status"),
      importStageRail: document.querySelector("#import-stage-rail"),
      importDiagnosis: document.querySelector("#import-trace-diagnosis"),
      importCounts: document.querySelector("#import-trace-counts"),
      importTraceId: document.querySelector("#import-trace-id"),
      importSource: document.querySelector("#import-trace-source"),
      importDigest: document.querySelector("#import-trace-digest"),
      importPayload: document.querySelector("#import-trace-payload"),
    });
  }

  function bindEvents() {
    dom.refresh.addEventListener("click", () => renderMarketplace());
    document.querySelectorAll("[data-ledger-tab]").forEach((tab) => {
      tab.addEventListener("click", () => activateTab(tab.dataset.ledgerTab));
    });
    window.addEventListener("beforeunload", () => marketplaceEventSource?.close());

    dom.traceScenario.addEventListener("change", () => {
      selectScenario(dom.traceScenario.value);
    });
    dom.traceEvent.addEventListener("change", () => {
      activeEvent = activeScenario.events.find((event) => event.event_id === dom.traceEvent.value);
      activeStageNumber = decisiveStage(activeEvent);
      renderTrace();
    });
    dom.traceRun.addEventListener("click", runTrace);
    dom.importRun.addEventListener("click", runImportTrace);
    dom.traceReset.addEventListener("click", () => {
      selectScenario(traceDocument.scenarios[0].scenario_id);
      dom.traceStatus.textContent = "Reset to the first prepared projection. Run it when ready.";
    });
  }

  function initializeImportTrace() {
    renderImportStages(
      IMPORT_STAGE_CATALOG.map((stage) => ({...stage, state: "ready", duration_ms: 0})),
    );
  }

  async function runImportTrace() {
    dom.importRun.disabled = true;
    dom.importRuntime.className = "import-runtime-badge";
    dom.importRuntime.textContent = "CONNECTING";
    dom.importStatus.textContent = "Checking catalog data with the backend loader…";

    try {
      const trace = await fetchJson(IMPORT_TRACE_URL, {cache: "no-store"});
      validateImportTrace(trace);
      renderImportTrace(trace);
    } catch (_error) {
      renderImportOffline();
    } finally {
      dom.importRun.disabled = false;
    }
  }

  function validateImportTrace(trace) {
    if (
      trace?.schema_version !== "sidestage.import_trace.v1" ||
      trace?.runtime_source !== "m2_1_typed_loader" ||
      trace?.durability !== "ephemeral"
    ) {
      throw new Error("Import trace identity is invalid.");
    }
    if (!Array.isArray(trace.stages) || trace.stages.length !== IMPORT_STAGE_CATALOG.length) {
      throw new Error("Import trace has an invalid stage count.");
    }
    const expectedKeys = IMPORT_STAGE_CATALOG.map((stage) => stage.key).join("|");
    if (trace.stages.map((stage) => stage.key).join("|") !== expectedKeys) {
      throw new Error("Import trace has an invalid stage order.");
    }
    if (!trace.stages.every((stage) => ["passed", "failed", "skipped"].includes(stage.state))) {
      throw new Error("Import trace has an invalid stage state.");
    }
  }

  function renderImportTrace(trace) {
    const accepted = trace.status === "accepted";
    dom.importRuntime.className = `import-runtime-badge ${accepted ? "is-runtime" : "is-rejected"}`;
    dom.importRuntime.textContent = "LIVE BACKEND CHECK";
    dom.importStatus.textContent = accepted
      ? "Backend catalog check completed."
      : `Catalog import stopped at stage ${trace.first_stop?.stage || "unknown"}.`;
    renderImportStages(trace.stages);

    dom.importDiagnosis.className = `import-trace-diagnosis ${accepted ? "is-accepted" : "is-rejected"}`;
    dom.importDiagnosis.querySelector(".import-trace-mark").textContent = accepted ? "✓" : "!";
    dom.importDiagnosis.querySelector("div > span").textContent = accepted
      ? "Import accepted"
      : "First rejected stage";

    const counts = trace.outcome?.counts;
    if (accepted && counts) {
      dom.importDiagnosis.querySelector("strong").textContent = `Accepted ${counts.sellers} sellers · tenant indexes ready`;
      dom.importCounts.textContent = `${counts.sellers} sellers · ${counts.listings} listings · ${counts.variants} variants`;
    } else {
      dom.importDiagnosis.querySelector("strong").textContent = trace.first_stop
        ? `Stage ${trace.first_stop.stage} · ${trace.first_stop.reason_code}`
        : "Import rejected without a stage result";
      dom.importCounts.textContent = "No catalog emitted";
    }

    dom.importTraceId.textContent = trace.trace_id;
    dom.importSource.textContent = trace.source?.filename || "—";
    dom.importDigest.textContent = trace.source?.sha256
      ? `${trace.source.sha256.slice(0, 12)}…`
      : "—";
    dom.importPayload.textContent = prettyJson(trace);
  }

  function renderImportStages(stages) {
    dom.importStageRail.innerHTML = stages
      .map(
        (stage) => `
          <article class="import-stage is-${escapeHtml(stage.state)}" data-import-stage="${stage.number}">
            <span class="import-stage-number">${stage.number}</span>
            <span class="import-stage-copy">
              <strong>${escapeHtml(stage.label)}</strong>
              <small>${escapeHtml(stage.state)}${stage.state === "ready" ? "" : ` · ${escapeHtml(stage.duration_ms)} ms`}</small>
            </span>
          </article>
        `,
      )
      .join("");
  }

  function renderImportOffline() {
    dom.importRuntime.className = "import-runtime-badge is-offline";
    dom.importRuntime.textContent = "BACKEND OFFLINE";
    dom.importStatus.textContent = "Backend check unavailable. Start the local SideStage server and retry.";
    dom.importDiagnosis.className = "import-trace-diagnosis is-offline";
    dom.importDiagnosis.querySelector(".import-trace-mark").textContent = "×";
    dom.importDiagnosis.querySelector("div > span").textContent = "Transport unavailable";
    dom.importDiagnosis.querySelector("strong").textContent = "No backend import was observed";
    dom.importCounts.textContent = "No catalog emitted";
    dom.importTraceId.textContent = "—";
    dom.importSource.textContent = "—";
    dom.importDigest.textContent = "—";
    dom.importPayload.textContent = "null";
    initializeImportTrace();
  }

  function initializeTraceControls() {
    dom.traceScenario.innerHTML = traceDocument.scenarios
      .map(
        (scenario) =>
          `<option value="${escapeHtml(scenario.scenario_id)}">${escapeHtml(scenario.label)}</option>`,
      )
      .join("");
    dom.traceScenario.disabled = false;
    dom.traceRun.disabled = false;
    dom.traceReset.disabled = false;
    selectScenario(traceDocument.scenarios[0].scenario_id);
  }

  function selectScenario(scenarioId) {
    activeScenario = traceDocument.scenarios.find((scenario) => scenario.scenario_id === scenarioId);
    if (!activeScenario) return;

    dom.traceScenario.value = activeScenario.scenario_id;
    dom.traceEvent.innerHTML = activeScenario.events
      .map(
        (event, index) =>
          `<option value="${escapeHtml(event.event_id)}">${index + 1}/${activeScenario.events.length} · ${escapeHtml(event.title)} · ${escapeHtml(event.customer_display_name)}</option>`,
      )
      .join("");
    dom.traceEvent.disabled = false;
    activeEvent = activeScenario.events[0];
    activeStageNumber = 1;
    traceHasRun = false;
    dom.traceStatus.textContent = `Prepared ${activeScenario.events.length} demo message${activeScenario.events.length === 1 ? "" : "s"}.`;
    renderTrace();
  }

  function runTrace() {
    if (!activeEvent) return;
    traceHasRun = true;
    activeStageNumber = decisiveStage(activeEvent);
    dom.traceStatus.textContent = activeScenario.mode === "bulk"
      ? `Ran ${activeScenario.events.length} simulated paths. Select a message to inspect where it stops.`
      : "Ran one simulated path until the first unavailable or rejected step.";
    renderTrace();
    dom.traceDiagnosis.classList.remove("trace-pulse");
    window.requestAnimationFrame(() => dom.traceDiagnosis.classList.add("trace-pulse"));
  }

  function decisiveStage(event) {
    return event?.first_stop?.stage || 7;
  }

  function renderTrace() {
    if (!activeEvent || !traceDocument) return;
    renderTraceEvent();
    renderStageRail();
    renderDiagnosis();
    renderStageInspector();
    renderDestinations();
  }

  function renderTraceEvent() {
    const index = activeScenario.events.findIndex((event) => event.event_id === activeEvent.event_id);
    dom.traceEvent.value = activeEvent.event_id;
    dom.traceEventIndex.textContent = `${String(index + 1).padStart(2, "0")} / ${String(activeScenario.events.length).padStart(2, "0")}`;
    dom.traceEventCustomer.textContent = activeEvent.customer_display_name;
    dom.traceEventTitle.textContent = activeEvent.title;
    dom.traceEventText.textContent = activeEvent.raw_text;
    dom.traceEventMeta.innerHTML = `
      <div><dt>Trace</dt><dd><code>${escapeHtml(activeEvent.trace_id)}</code></dd></div>
      <div><dt>Bound SKU</dt><dd>${escapeHtml(activeEvent.source_context.sku)}</dd></div>
      <div><dt>Expected</dt><dd>${escapeHtml(activeEvent.expected_result)}</dd></div>
    `;
  }

  function renderStageRail() {
    dom.traceStageRail.innerHTML = traceDocument.stage_catalog
      .map((catalogStage) => {
        const stage = activeEvent.stages[catalogStage.number - 1];
        const shownState = traceHasRun ? stage.state : "ready";
        const selected = activeStageNumber === catalogStage.number;
        return `
          <button
            class="trace-stage is-${escapeHtml(shownState)} ${selected ? "is-selected" : ""}"
            data-trace-stage="${catalogStage.number}"
            type="button"
            aria-pressed="${selected}"
          >
            <span class="trace-stage-number">${catalogStage.number}</span>
            <span class="trace-stage-label">${escapeHtml(catalogStage.short_label)}</span>
            <span class="trace-stage-state">${escapeHtml(shownState)}</span>
          </button>
        `;
      })
      .join("");

    dom.traceStageRail.querySelectorAll("[data-trace-stage]").forEach((button) => {
      button.addEventListener("click", () => {
        activeStageNumber = Number(button.dataset.traceStage);
        renderStageRail();
        renderStageInspector();
      });
    });
  }

  function renderDiagnosis() {
    dom.traceDiagnosis.className = "trace-diagnosis";
    if (!traceHasRun) {
      dom.traceDiagnosis.classList.add("is-ready");
      dom.traceDiagnosisIcon.textContent = "→";
      dom.traceDiagnosisTitle.textContent = `Prepared · ${activeEvent.title}`;
      dom.traceDiagnosisMessage.textContent = "Run the demo to reveal simulated, stopped, and skipped stages.";
      dom.traceTotalDuration.textContent = "—";
      return;
    }

    dom.traceTotalDuration.textContent = `${activeEvent.total_duration_ms} ms`;
    if (!activeEvent.first_stop) {
      dom.traceDiagnosis.classList.add("is-failed");
      dom.traceDiagnosisIcon.textContent = "!";
      dom.traceDiagnosisTitle.textContent = "Trace is incomplete";
      dom.traceDiagnosisMessage.textContent = "Every current-build trace must identify a stopping stage.";
      return;
    }

    const stop = activeEvent.first_stop;
    dom.traceDiagnosis.classList.add(`is-${stop.state}`);
    dom.traceDiagnosisIcon.textContent = stop.state === "exited" ? "↗" : "!";
    dom.traceDiagnosisTitle.textContent = `${stop.state === "exited" ? "Exited" : "Stopped"} at stage ${stop.stage} · ${stop.reason_code}`;
    dom.traceDiagnosisMessage.textContent = stop.message;
  }

  function renderStageInspector() {
    const stage = activeEvent.stages[activeStageNumber - 1];
    const catalog = traceDocument.stage_catalog[activeStageNumber - 1];
    const shownState = traceHasRun ? stage.state : "ready";
    dom.traceStageKicker.textContent = `Stage ${catalog.number} / 7`;
    dom.traceStageTitle.textContent = catalog.label;
    dom.traceStageState.textContent = shownState.toUpperCase();
    dom.traceStageState.className = `is-${shownState}`;
    dom.traceStageDuration.textContent = traceHasRun ? `${stage.duration_ms} ms` : "not run";
    dom.traceStageSummary.textContent = traceHasRun
      ? stage.summary
      : "Run the demo to inspect this stage's simulated input and output.";
    dom.traceStageReason.textContent = traceHasRun ? stage.reason_code || "—" : "—";
    dom.traceStageInput.textContent = prettyJson(traceHasRun ? stage.input : null);
    dom.traceStageOutput.textContent = prettyJson(traceHasRun ? stage.output : null);
  }

  function renderDestinations() {
    dom.traceDestinationGrid.innerHTML = activeEvent.destinations
      .map(
        (destination) => `
          <article class="trace-destination" data-destination="${escapeHtml(destination.key)}">
            <header>
              <span>${escapeHtml(destination.label)}</span>
              <strong class="destination-status destination-status--${escapeHtml(destination.status.toLowerCase())}">${escapeHtml(destination.status)}</strong>
            </header>
            <p>${escapeHtml(destination.summary)}</p>
            <details>
              <summary>Inspect destination payload</summary>
              <pre>${escapeHtml(prettyJson(destination.payload))}</pre>
            </details>
          </article>
        `,
      )
      .join("");
  }

  function renderTraceError(error) {
    dom.traceStatus.textContent = "Demo messages unavailable. Marketplace activity remains usable.";
    dom.traceScenario.innerHTML = '<option>Demo messages unavailable</option>';
    dom.traceEvent.innerHTML = '<option>No trace events</option>';
    dom.traceDiagnosis.className = "trace-diagnosis is-failed";
    dom.traceDiagnosisIcon.textContent = "!";
    dom.traceDiagnosisTitle.textContent = "Message trace could not load";
    dom.traceDiagnosisMessage.textContent = error?.message || "Unknown fixture error";
    dom.traceTotalDuration.textContent = "—";
  }

  function sessionToken() {
    return sessionStorage.getItem(SESSION_KEY);
  }

  async function renderMarketplace() {
    const token = sessionToken();
    if (!token) {
      renderMarketplaceEmpty("Open the seller workspace first to start a server-owned demo session.");
      return;
    }

    try {
      const response = await fetchJson(
        `/api/debug/marketplace?session_token=${encodeURIComponent(token)}`,
        {cache: "no-store"},
      );
      if (response.runtime_source !== "m2_3_sqlite") {
        throw new Error("Unexpected marketplace ledger source.");
      }
      const state = response.snapshot;
      const active = listingForId(state, state.show.active_listing_id);
      dom.ledgerEmpty.hidden = true;
      dom.seller.textContent = state.seller.display_name;
      dom.showId.textContent = state.show.show_id;
      dom.activeSku.textContent = active?.sku || "Stage clear";
      setMarketplaceCounts(state);
      renderEvents(state);
      renderEpochs(state);
      renderReceipts(state);
    } catch (error) {
      renderMarketplaceEmpty(error.message);
    }
  }

  function connectMarketplaceEvents() {
    marketplaceEventSource?.close();
    const token = sessionToken();
    if (!token) return;
    marketplaceEventSource = new EventSource(
      `/api/sessions/${encodeURIComponent(token)}/events`,
    );
    ["chat.accepted", "marketplace.changed"].forEach((type) => {
      marketplaceEventSource.addEventListener(type, () => renderMarketplace());
    });
  }

  function renderMarketplaceEmpty(message) {
    dom.ledgerEmpty.hidden = false;
    dom.ledgerEmpty.querySelector("p").textContent = message;
    dom.seller.textContent = "No seller state";
    dom.activeSku.textContent = "Stage clear";
    dom.showId.textContent = "—";
    const empty = {show: {version: 0}, chat_events: [], epochs: [], receipts: []};
    setMarketplaceCounts(empty);
    renderEvents(empty);
    renderEpochs(empty);
    renderReceipts(empty);
  }

  function setMarketplaceCounts(state) {
    dom.showVersion.textContent = String(state.show.version);
    dom.eventCount.textContent = String(state.chat_events.length);
    dom.epochCount.textContent = String(state.epochs.length);
    dom.receiptCount.textContent = String(state.receipts.length);
    dom.tabEventCount.textContent = String(state.chat_events.length);
    dom.tabEpochCount.textContent = String(state.epochs.length);
    dom.tabReceiptCount.textContent = String(state.receipts.length);
  }

  function renderEvents(state) {
    if (state.chat_events.length === 0) {
      dom.eventLedger.innerHTML = '<p class="ledger-empty">No raw chat events have been accepted.</p>';
      return;
    }

    dom.eventLedger.innerHTML = [...state.chat_events]
      .sort((a, b) => a.show_seq - b.show_seq)
      .map(
        (event) => `
          <article class="event-row">
            <code>#${String(event.show_seq).padStart(3, "0")}</code>
            <div><strong>${escapeHtml(event.customer_display_name)}</strong><span class="ledger-badge">${escapeHtml(event.input_origin)}</span></div>
            <p class="event-raw">${escapeHtml(event.raw_text)}</p>
            <div><code>${escapeHtml(event.source_epoch_id ? shortEpoch(event.source_epoch_id) : "No cue")}</code><span class="ledger-badge">${escapeHtml(event.source_listing_id || "slot empty")}</span></div>
            <code>${escapeHtml(formatClock(event.accepted_at))}</code>
          </article>
        `,
      )
      .join("");
  }

  function renderEpochs(state) {
    if (state.epochs.length === 0) {
      dom.epochLedger.innerHTML = '<p class="ledger-empty">No listing epoch has opened. Push a listing from the seller workspace.</p>';
      return;
    }

    dom.epochLedger.innerHTML = state.epochs
      .map((epoch, index) => {
        const listing = listingForId(state, epoch.listing_id);
        return `
          <article class="epoch-row ${epoch.end_seq === null ? "is-open" : ""}">
            <div class="epoch-cell"><span>Epoch</span><strong>${escapeHtml(`E${String(index + 1).padStart(2, "0")}`)}</strong></div>
            <div class="epoch-cell"><span>Listing</span><strong>${escapeHtml(listing?.title || epoch.listing_id)}</strong><code>${escapeHtml(listing?.sku || epoch.listing_id)}</code></div>
            <div class="epoch-cell"><span>Sequence boundary</span><strong>${epoch.start_seq} → ${epoch.end_seq ?? "open"}</strong><code>${escapeHtml(epoch.epoch_id)}</code></div>
            <div class="epoch-cell"><span>State</span><strong>${epoch.end_seq === null ? "Active" : "Closed"}</strong><code>ordered by show_seq</code></div>
          </article>
        `;
      })
      .join("");
  }

  function renderReceipts(state) {
    if (state.receipts.length === 0) {
      dom.receiptLedger.innerHTML = '<p class="ledger-empty">No marketplace operation has been attempted.</p>';
      return;
    }

    dom.receiptLedger.innerHTML = [...state.receipts]
      .reverse()
      .map((receipt, index) => {
        const isRejected = receipt.status === "rejected";
        const compensation = state.receipts.find(
          (candidate) => candidate.compensation_for_receipt_id === receipt.receipt_id,
        );
        const relationship = receipt.compensation_for_receipt_id
          ? `Compensates ${receipt.compensation_for_receipt_id}`
          : compensation
            ? `Compensated by ${compensation.receipt_id}`
            : "Original operation";
        const listing = listingForId(state, receipt.listing_id);
        const subject = listing
          ? `${listing.title} · ${listing.sku}`
          : receipt.variant_id || receipt.listing_id || state.show.show_id;
        return `
          <article class="receipt-row">
            <code>#${String(state.receipts.length - index).padStart(3, "0")}</code>
            <div class="receipt-cell"><span>Operation</span><strong>${escapeHtml(formatOperation(receipt.operation_type))}</strong><span class="receipt-status ${isRejected ? "receipt-status--rejected" : ""}">${escapeHtml(receipt.status)}</span></div>
            <div class="receipt-cell"><span>Subject</span><strong>${escapeHtml(subject)}</strong><code>${escapeHtml(receipt.receipt_id)}</code></div>
            <div class="receipt-cell"><span>Relationship</span><strong>${escapeHtml(relationship)}</strong><code>${escapeHtml(receipt.error_code || "no error")}</code></div>
            <div class="receipt-cell"><span>Recorded</span><strong>${escapeHtml(formatClock(receipt.recorded_at))}</strong><code>show v${receipt.resulting_versions?.show_version ?? "—"}</code></div>
            <details class="receipt-details"><summary>Inspect state projection</summary><pre>${escapeHtml(prettyJson({request: receipt.request, expected_versions: receipt.expected_versions, resulting_versions: receipt.resulting_versions, before: receipt.before, after: receipt.after}))}</pre></details>
          </article>
        `;
      })
      .join("");
  }

  function activateTab(name) {
    document.querySelectorAll("[data-ledger-tab]").forEach((tab) => {
      const active = tab.dataset.ledgerTab === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll("[data-ledger-panel]").forEach((panel) => {
      const active = panel.dataset.ledgerPanel === name;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });
  }

  function listingForId(state, listingId) {
    return state?.listings?.find((listing) => listing.listing_id === listingId) || null;
  }

  function formatOperation(value) {
    return value
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }

  function shortEpoch(epochId) {
    return `E${epochId.split("_").at(-1)}`;
  }

  function formatClock(isoString) {
    return new Intl.DateTimeFormat("en-US", {hour: "numeric", minute: "2-digit", second: "2-digit"}).format(new Date(isoString));
  }

  function prettyJson(value) {
    return JSON.stringify(value, null, 2);
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
})();
