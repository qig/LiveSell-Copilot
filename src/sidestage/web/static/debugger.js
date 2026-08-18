(() => {
  "use strict";

  const SESSION_KEY = "sidestage.m2.session";
  const IMPORT_TRACE_URL = "/api/debug/import-trace";
  const IMPORT_STAGE_CATALOG = [
    {number: 1, key: "source_read", label: "Read source"},
    {number: 2, key: "contract_validation", label: "Validate contract"},
    {number: 3, key: "approved_seller_set", label: "Approve sellers"},
    {number: 4, key: "tenant_index_build", label: "Build tenant indexes"},
  ];
  const dom = {};
  let runtimeProjection = null;
  let activeTrace = null;
  let activeStageNumber = 1;
  let marketplaceEventSource = null;

  document.addEventListener("DOMContentLoaded", boot);

  async function boot() {
    cacheDom();
    bindEvents();
    initializeImportTrace();
    await Promise.all([renderRuntimeTraces(), renderMarketplace()]);
    connectMarketplaceEvents();
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
    dom.refresh.addEventListener("click", () => Promise.all([renderRuntimeTraces(), renderMarketplace()]));
    dom.traceRun.addEventListener("click", renderRuntimeTraces);
    dom.traceReset.addEventListener("click", () => {
      dom.traceScenario.value = "all";
      renderRuntimeTraces();
    });
    dom.traceScenario.addEventListener("change", renderRuntimeTraces);
    dom.traceEvent.addEventListener("change", () => {
      activeTrace = runtimeProjection?.traces.find((trace) => trace.trace_id === dom.traceEvent.value) || null;
      activeStageNumber = decisiveStage(activeTrace);
      renderTrace();
    });
    dom.importRun.addEventListener("click", runImportTrace);
    document.querySelectorAll("[data-ledger-tab]").forEach((tab) => {
      tab.addEventListener("click", () => activateTab(tab.dataset.ledgerTab));
    });
    window.addEventListener("beforeunload", () => marketplaceEventSource?.close());
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {...options, cache: "no-store"});
    if (!response.ok) throw new Error(`Unable to load runtime data (${response.status})`);
    return response.json();
  }

  function sessionToken() {
    return sessionStorage.getItem(SESSION_KEY);
  }

  async function renderRuntimeTraces() {
    const token = sessionToken();
    if (!token) {
      renderTraceEmpty("Open the seller workspace first to create a server-owned session.");
      return;
    }
    dom.traceRun.disabled = true;
    try {
      const route = dom.traceScenario.value && dom.traceScenario.value !== "all"
        ? `&actual_route=${encodeURIComponent(dom.traceScenario.value)}`
        : "";
      const projection = await fetchJson(
        `/api/debug/copilot?session_token=${encodeURIComponent(token)}${route}`,
      );
      if (
        projection.schema_version !== "sidestage.runtime_trace_projection.v1" ||
        projection.runtime_source !== "process_customer_reply.sqlite"
      ) {
        throw new Error("Unexpected runtime trace source.");
      }
      runtimeProjection = projection;
      initializeRouteFilters(projection);
      const priorTraceId = activeTrace?.trace_id;
      const priorStageNumber = activeStageNumber;
      activeTrace = projection.traces.find((trace) => trace.trace_id === priorTraceId)
        || projection.traces[0]
        || null;
      activeStageNumber = activeTrace?.trace_id === priorTraceId
        && activeTrace.stages.some((stage) => stage.stage_number === priorStageNumber)
        ? priorStageNumber
        : decisiveStage(activeTrace);
      renderTraceSelector();
      renderTrace();
      dom.traceStatus.textContent = projection.trace_count
        ? `${projection.trace_count} persisted trace${projection.trace_count === 1 ? "" : "s"} · actual route ${projection.actual_route_filter}.`
        : `No persisted traces match actual route ${projection.actual_route_filter}.`;
    } catch (error) {
      renderTraceEmpty(error.message);
    } finally {
      dom.traceRun.disabled = false;
    }
  }

  function initializeRouteFilters(projection) {
    const current = projection.actual_route_filter || "all";
    const labels = {
      all: "All actual routes",
      eligible: "Eligible",
      noise: "Noise",
      duplicate: "Duplicate",
      ambiguous_or_unsupported: "Ambiguous / unsupported",
      adversarial: "Adversarial",
    };
    dom.traceScenario.innerHTML = ["all", ...Object.keys(projection.route_counts)]
      .map((route) => {
        const count = route === "all"
          ? Object.values(projection.route_counts).reduce((sum, value) => sum + value, 0)
          : projection.route_counts[route];
        return `<option value="${escapeHtml(route)}">${escapeHtml(labels[route])} · ${count}</option>`;
      })
      .join("");
    dom.traceScenario.value = current;
    dom.traceScenario.disabled = false;
    dom.traceReset.disabled = false;
  }

  function renderTraceSelector() {
    if (!runtimeProjection?.traces.length) {
      dom.traceEvent.innerHTML = "<option>No matching runtime traces</option>";
      dom.traceEvent.disabled = true;
      return;
    }
    dom.traceEvent.innerHTML = runtimeProjection.traces
      .map(
        (trace, index) => `<option value="${escapeHtml(trace.trace_id)}">${index + 1}/${runtimeProjection.traces.length} · #${trace.show_seq} · ${escapeHtml(trace.actual_route)} · ${escapeHtml(trace.customer_display_name)}</option>`,
      )
      .join("");
    dom.traceEvent.value = activeTrace.trace_id;
    dom.traceEvent.disabled = false;
  }

  function decisiveStage(trace) {
    if (!trace?.stages?.length) return 1;
    const decisive = trace.stages.find((stage) => !["completed", "skipped"].includes(stage.status));
    return decisive?.stage_number || trace.stages.at(-1).stage_number;
  }

  function renderTrace() {
    if (!activeTrace) {
      clearTracePanels();
      return;
    }
    renderTraceEvent();
    renderStageRail();
    renderDiagnosis();
    renderStageInspector();
    renderDestinations();
  }

  function renderTraceEvent() {
    const index = runtimeProjection.traces.findIndex((trace) => trace.trace_id === activeTrace.trace_id);
    dom.traceEventIndex.textContent = `${String(index + 1).padStart(2, "0")} / ${String(runtimeProjection.traces.length).padStart(2, "0")}`;
    dom.traceEventCustomer.textContent = activeTrace.customer_display_name;
    dom.traceEventTitle.textContent = `Question #${activeTrace.show_seq} · ${humanize(activeTrace.state || activeTrace.actual_route)}`;
    dom.traceEventText.textContent = activeTrace.raw_text;
    dom.traceEventMeta.innerHTML = `
      <div><dt>Trace</dt><dd><code>${escapeHtml(activeTrace.trace_id)}</code></dd></div>
      <div><dt>Actual route</dt><dd>${escapeHtml(activeTrace.actual_route)}</dd></div>
      <div><dt>Expected oracle</dt><dd>${escapeHtml(activeTrace.expected_route || "custom / no oracle")}</dd></div>`;
  }

  function renderStageRail() {
    dom.traceStageRail.innerHTML = activeTrace.stages
      .map(
        (stage) => `<button class="trace-stage is-${escapeHtml(stage.status)} ${activeStageNumber === stage.stage_number ? "is-selected" : ""}" data-trace-stage="${stage.stage_number}" type="button" aria-pressed="${activeStageNumber === stage.stage_number}">
          <span class="trace-stage-number">${stage.stage_number}</span>
          <span class="trace-stage-label">${escapeHtml(humanize(stage.stage))}</span>
          <span class="trace-stage-state">${escapeHtml(stage.status)}</span>
        </button>`,
      )
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
    const decisive = activeTrace.stages.find((stage) => !["completed", "skipped"].includes(stage.status));
    dom.traceDiagnosis.className = `trace-diagnosis is-${decisive?.status || (activeTrace.complete ? "passed" : "failed")}`;
    dom.traceDiagnosisIcon.textContent = decisive ? "!" : activeTrace.complete ? "✓" : "!";
    dom.traceDiagnosisTitle.textContent = decisive
      ? `${humanize(decisive.status)} at stage ${decisive.stage_number} · ${humanize(decisive.stage)}`
      : activeTrace.complete
        ? "Complete backend trace"
        : "Incomplete backend trace";
    dom.traceDiagnosisMessage.textContent = decisive?.reason_code
      || activeTrace.reason_code
      || "Every stage has one authoritative terminal observation.";
    dom.traceTotalDuration.textContent = `${activeTrace.total_duration_ms.toFixed(2)} ms`;
  }

  function renderStageInspector() {
    const stage = activeTrace.stages.find((item) => item.stage_number === activeStageNumber);
    if (!stage) return;
    dom.traceStageKicker.textContent = `Stage ${stage.stage_number} / ${activeTrace.stages.length}`;
    dom.traceStageTitle.textContent = humanize(stage.stage);
    dom.traceStageState.textContent = stage.status.toUpperCase();
    dom.traceStageState.className = `is-${stage.status}`;
    dom.traceStageDuration.textContent = `${Number(stage.duration_ms || 0).toFixed(3)} ms`;
    dom.traceStageSummary.textContent = `${stage.component_id} emitted observation ${stage.observation_id}.`;
    dom.traceStageReason.textContent = stage.reason_code || "—";
    dom.traceStageInput.textContent = prettyJson({
      observation_id: stage.observation_id,
      started_observation_id: stage.started_observation_id,
      component_id: stage.component_id,
      input_ref: stage.input_ref,
      output_ref: stage.output_ref,
      verdict: stage.verdict,
      analysis_call_id: stage.analysis_call_id,
      snapshot_id: stage.snapshot_id,
      agent_run_id: stage.agent_run_id,
      profile_digest: stage.profile_digest,
    });
    dom.traceStageOutput.textContent = prettyJson(stage.artifacts);
  }

  function renderDestinations() {
    const destinations = [
      {label: "Lifecycle", status: activeTrace.state || "none", payload: activeTrace.transitions},
      {label: "Review suggestion", status: activeTrace.suggestion ? "recorded" : "none", payload: activeTrace.suggestion},
      {label: "Outbound reply", status: activeTrace.outbound_reply ? "sent" : "none", payload: activeTrace.outbound_reply},
      {label: "Reply receipt", status: activeTrace.reply_receipt ? "recorded" : "none", payload: activeTrace.reply_receipt},
    ];
    dom.traceDestinationGrid.innerHTML = destinations
      .map(
        (item) => `<article class="trace-destination"><header><span>${escapeHtml(item.label)}</span><strong class="destination-status">${escapeHtml(item.status)}</strong></header><p>Backend-owned runtime projection.</p><details><summary>Inspect persisted payload</summary><pre>${escapeHtml(prettyJson(item.payload))}</pre></details></article>`,
      )
      .join("");
  }

  function renderTraceEmpty(message) {
    runtimeProjection = null;
    activeTrace = null;
    dom.traceStatus.textContent = message;
    dom.traceEvent.innerHTML = "<option>No runtime traces</option>";
    dom.traceEvent.disabled = true;
    clearTracePanels();
  }

  function clearTracePanels() {
    dom.traceEventIndex.textContent = "—";
    dom.traceEventCustomer.textContent = "Runtime";
    dom.traceEventTitle.textContent = "No trace selected";
    dom.traceEventText.textContent = "Accept a chat message from the seller workspace to create a trace.";
    dom.traceStageRail.replaceChildren();
    dom.traceDiagnosisTitle.textContent = "No persisted trace";
    dom.traceDiagnosisMessage.textContent = "The frontend does not synthesize missing stage results.";
    dom.traceTotalDuration.textContent = "—";
    dom.traceStageTitle.textContent = "Stage detail";
    dom.traceStageInput.textContent = "null";
    dom.traceStageOutput.textContent = "null";
    dom.traceDestinationGrid.replaceChildren();
  }

  function initializeImportTrace() {
    renderImportStages(IMPORT_STAGE_CATALOG.map((stage) => ({...stage, state: "ready", duration_ms: 0})));
  }

  async function runImportTrace() {
    dom.importRun.disabled = true;
    try {
      const trace = await fetchJson(IMPORT_TRACE_URL);
      if (trace?.schema_version !== "sidestage.import_trace.v1" || !Array.isArray(trace.stages)) {
        throw new Error("Import trace identity is invalid.");
      }
      dom.importRuntime.className = `import-runtime-badge ${trace.status === "accepted" ? "is-runtime" : "is-rejected"}`;
      dom.importRuntime.textContent = "LIVE BACKEND CHECK";
      dom.importStatus.textContent = trace.status === "accepted" ? "Backend catalog check completed." : "Catalog import rejected.";
      renderImportStages(trace.stages);
      const counts = trace.outcome?.counts;
      dom.importDiagnosis.className = `import-trace-diagnosis ${trace.status === "accepted" ? "is-accepted" : "is-rejected"}`;
      dom.importDiagnosis.querySelector(".import-trace-mark").textContent = trace.status === "accepted" ? "✓" : "!";
      dom.importDiagnosis.querySelector("div > span").textContent = "Import outcome";
      dom.importDiagnosis.querySelector("strong").textContent = trace.status === "accepted" ? "Typed fixture accepted" : "Fixture rejected";
      dom.importCounts.textContent = counts ? `${counts.sellers} sellers · ${counts.listings} listings · ${counts.variants} variants` : "No catalog emitted";
      dom.importTraceId.textContent = trace.trace_id;
      dom.importSource.textContent = trace.source?.filename || "—";
      dom.importDigest.textContent = trace.source?.sha256 ? `${trace.source.sha256.slice(0, 12)}…` : "—";
      dom.importPayload.textContent = prettyJson(trace);
    } catch (error) {
      dom.importRuntime.className = "import-runtime-badge is-offline";
      dom.importRuntime.textContent = "BACKEND UNAVAILABLE";
      dom.importStatus.textContent = error.message;
    } finally {
      dom.importRun.disabled = false;
    }
  }

  function renderImportStages(stages) {
    dom.importStageRail.innerHTML = stages.map((stage) => `<article class="import-stage is-${escapeHtml(stage.state)}"><span class="import-stage-number">${stage.number}</span><span class="import-stage-copy"><strong>${escapeHtml(stage.label)}</strong><small>${escapeHtml(stage.state)}${stage.state === "ready" ? "" : ` · ${escapeHtml(stage.duration_ms)} ms`}</small></span></article>`).join("");
  }

  async function renderMarketplace() {
    const token = sessionToken();
    if (!token) {
      renderMarketplaceEmpty("Open the seller workspace first to start a server-owned demo session.");
      return;
    }
    try {
      const response = await fetchJson(`/api/debug/marketplace?session_token=${encodeURIComponent(token)}`);
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
    marketplaceEventSource = new EventSource(`/api/sessions/${encodeURIComponent(token)}/events`);
    ["chat.accepted", "chat.reply", "marketplace.changed", "copilot.question.changed", "copilot.r3.changed"].forEach((type) => {
      marketplaceEventSource.addEventListener(type, () => Promise.all([renderRuntimeTraces(), renderMarketplace()]));
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
    dom.eventLedger.innerHTML = state.chat_events.length
      ? [...state.chat_events].sort((a, b) => a.show_seq - b.show_seq).map((event) => `<article class="event-row"><code>#${String(event.show_seq).padStart(3, "0")}</code><div><strong>${escapeHtml(event.customer_display_name)}</strong><span class="ledger-badge">${escapeHtml(event.input_origin)}</span></div><p class="event-raw">${escapeHtml(event.raw_text)}</p><div><code>${escapeHtml(event.source_epoch_id ? shortEpoch(event.source_epoch_id) : "No cue")}</code><span class="ledger-badge">${escapeHtml(event.source_listing_id || "slot empty")}</span></div><code>${escapeHtml(formatClock(event.accepted_at))}</code></article>`).join("")
      : '<p class="ledger-empty">No raw chat events have been accepted.</p>';
  }

  function renderEpochs(state) {
    dom.epochLedger.innerHTML = state.epochs.length
      ? state.epochs.map((epoch, index) => { const listing = listingForId(state, epoch.listing_id); return `<article class="epoch-row ${epoch.end_seq === null ? "is-open" : ""}"><div class="epoch-cell"><span>Epoch</span><strong>E${String(index + 1).padStart(2, "0")}</strong></div><div class="epoch-cell"><span>Listing</span><strong>${escapeHtml(listing?.title || epoch.listing_id)}</strong><code>${escapeHtml(listing?.sku || epoch.listing_id)}</code></div><div class="epoch-cell"><span>Sequence boundary</span><strong>${epoch.start_seq} → ${epoch.end_seq ?? "open"}</strong><code>${escapeHtml(epoch.epoch_id)}</code></div><div class="epoch-cell"><span>State</span><strong>${epoch.end_seq === null ? "Active" : "Closed"}</strong></div></article>`; }).join("")
      : '<p class="ledger-empty">No listing epoch has opened.</p>';
  }

  function renderReceipts(state) {
    dom.receiptLedger.innerHTML = state.receipts.length
      ? [...state.receipts].reverse().map((receipt, index) => `<article class="receipt-row"><code>#${String(state.receipts.length - index).padStart(3, "0")}</code><div class="receipt-cell"><span>Operation</span><strong>${escapeHtml(humanize(receipt.operation_type))}</strong><span class="receipt-status">${escapeHtml(receipt.status)}</span></div><div class="receipt-cell"><span>Subject</span><strong>${escapeHtml(receipt.listing_id || receipt.show_id)}</strong><code>${escapeHtml(receipt.receipt_id)}</code></div><div class="receipt-cell"><span>Recorded</span><strong>${escapeHtml(formatClock(receipt.recorded_at))}</strong></div><details class="receipt-details"><summary>Inspect state projection</summary><pre>${escapeHtml(prettyJson(receipt))}</pre></details></article>`).join("")
      : '<p class="ledger-empty">No marketplace operation has been attempted.</p>';
  }

  function activateTab(name) {
    document.querySelectorAll("[data-ledger-tab]").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.ledgerTab === name));
    document.querySelectorAll("[data-ledger-panel]").forEach((panel) => { panel.hidden = panel.dataset.ledgerPanel !== name; });
  }

  function listingForId(state, listingId) { return state?.listings?.find((item) => item.listing_id === listingId) || null; }
  function shortEpoch(epochId) { return `E${epochId.split("_").at(-1)}`; }
  function formatClock(value) { return new Intl.DateTimeFormat("en-US", {hour: "numeric", minute: "2-digit", second: "2-digit"}).format(new Date(value)); }
  function humanize(value) { return String(value || "none").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
  function prettyJson(value) { return JSON.stringify(value, null, 2); }
  function escapeHtml(value) { return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }
})();
