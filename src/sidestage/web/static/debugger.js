(() => {
  "use strict";

  const STORAGE_KEY = "sidestage.m2.demo.v2";
  const dom = {};
  let sellerFixture = null;

  document.addEventListener("DOMContentLoaded", boot);

  async function boot() {
    cacheDom();
    bindEvents();

    try {
      const response = await fetch("/fixtures/sellers.json");
      if (response.ok) sellerFixture = await response.json();
    } catch (_error) {
      // IDs remain inspectable if the optional label lookup fails.
    }

    render();
  }

  function cacheDom() {
    Object.assign(dom, {
      main: document.querySelector("#debug-main"),
      empty: document.querySelector("#debug-empty"),
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
      refresh: document.querySelector("#refresh-ledger"),
    });
  }

  function bindEvents() {
    dom.refresh.addEventListener("click", render);
    document.querySelectorAll("[data-ledger-tab]").forEach((tab) => {
      tab.addEventListener("click", () => activateTab(tab.dataset.ledgerTab));
    });
    window.addEventListener("storage", (event) => {
      if (event.key === STORAGE_KEY) render();
    });
  }

  function readCurrentState() {
    try {
      const store = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (!store?.activeSellerId || !store.shows?.[store.activeSellerId]) return null;
      return {
        store,
        show: store.shows[store.activeSellerId],
        seller: sellerFixture?.sellers?.find(
          (item) => item.seller_id === store.activeSellerId,
        ),
      };
    } catch (_error) {
      return null;
    }
  }

  function render() {
    const state = readCurrentState();
    if (!state) {
      dom.main.hidden = true;
      dom.empty.hidden = false;
      return;
    }

    const { show, seller } = state;
    dom.main.hidden = false;
    dom.empty.hidden = true;
    dom.seller.textContent = seller?.display_name || show.sellerId;
    dom.showId.textContent = show.showId;
    dom.showVersion.textContent = String(show.showVersion);
    dom.eventCount.textContent = String(show.chat.length);
    dom.epochCount.textContent = String(show.epochs.length);
    dom.receiptCount.textContent = String(show.receipts.length);
    dom.tabEventCount.textContent = String(show.chat.length);
    dom.tabEpochCount.textContent = String(show.epochs.length);
    dom.tabReceiptCount.textContent = String(show.receipts.length);
    dom.activeSku.textContent = show.activeListingId
      ? productForListing(seller, show.activeListingId)?.sku || show.activeListingId
      : "Stage clear";

    renderEvents(show);
    renderEpochs(show, seller);
    renderReceipts(show);
  }

  function renderEvents(show) {
    if (show.chat.length === 0) {
      dom.eventLedger.innerHTML = '<p class="ledger-empty">No raw chat events have been accepted.</p>';
      return;
    }

    dom.eventLedger.innerHTML = [...show.chat]
      .sort((a, b) => a.showSeq - b.showSeq)
      .map(
        (event) => `
          <article class="event-row">
            <code>#${String(event.showSeq).padStart(3, "0")}</code>
            <div>
              <strong>${escapeHtml(event.customerDisplayName)}</strong>
              <span class="ledger-badge">${escapeHtml(event.inputOrigin)}</span>
            </div>
            <p class="event-raw">${escapeHtml(event.rawText)}</p>
            <div>
              <code>${escapeHtml(event.sourceEpochId ? shortEpoch(event.sourceEpochId) : "No cue")}</code>
              <span class="ledger-badge">${escapeHtml(event.sourceListingId || "slot empty")}</span>
            </div>
            <code>${escapeHtml(formatClock(event.acceptedAt))}</code>
          </article>
        `,
      )
      .join("");
  }

  function renderEpochs(show, seller) {
    if (show.epochs.length === 0) {
      dom.epochLedger.innerHTML = '<p class="ledger-empty">No listing epoch has opened. Push a listing from the seller workspace.</p>';
      return;
    }

    dom.epochLedger.innerHTML = show.epochs
      .map((epoch, index) => {
        const product = productForListing(seller, epoch.listingId);
        return `
          <article class="epoch-row ${epoch.endSeq === null ? "is-open" : ""}">
            <div class="epoch-cell">
              <span>Epoch</span>
              <strong>${escapeHtml(`E${String(index + 1).padStart(2, "0")}`)}</strong>
            </div>
            <div class="epoch-cell">
              <span>Listing</span>
              <strong>${escapeHtml(product?.listing?.title || epoch.listingId)}</strong>
              <code>${escapeHtml(product?.sku || epoch.listingId)}</code>
            </div>
            <div class="epoch-cell">
              <span>Sequence boundary</span>
              <strong>${epoch.startSeq} → ${epoch.endSeq ?? "open"}</strong>
              <code>${escapeHtml(epoch.epochId)}</code>
            </div>
            <div class="epoch-cell">
              <span>Wall clock</span>
              <strong>${escapeHtml(formatClock(epoch.openedAt))}</strong>
              <code>${epoch.closedAt ? `closed ${escapeHtml(formatClock(epoch.closedAt))}` : "active epoch"}</code>
            </div>
          </article>
        `;
      })
      .join("");
  }

  function renderReceipts(show) {
    if (show.receipts.length === 0) {
      dom.receiptLedger.innerHTML = '<p class="ledger-empty">No marketplace operation has been attempted.</p>';
      return;
    }

    dom.receiptLedger.innerHTML = [...show.receipts]
      .reverse()
      .map((receipt, index) => {
        const isRejected = receipt.status === "rejected";
        const relationship = receipt.compensationForReceiptId
          ? `Compensates ${receipt.compensationForReceiptId}`
          : receipt.compensatedByReceiptId
            ? `Compensated by ${receipt.compensatedByReceiptId}`
            : "Original operation";
        return `
          <article class="receipt-row">
            <code>#${String(show.receipts.length - index).padStart(3, "0")}</code>
            <div class="receipt-cell">
              <span>Operation</span>
              <strong>${escapeHtml(formatOperation(receipt.operationType))}</strong>
              <span class="receipt-status ${isRejected ? "receipt-status--rejected" : ""}">${escapeHtml(receipt.status)}</span>
            </div>
            <div class="receipt-cell">
              <span>Subject</span>
              <strong>${escapeHtml(receipt.subjectLabel)}</strong>
              <code>${escapeHtml(receipt.receiptId)}</code>
            </div>
            <div class="receipt-cell">
              <span>Relationship</span>
              <strong>${escapeHtml(relationship)}</strong>
              <code>${escapeHtml(receipt.errorCode || "no error")}</code>
            </div>
            <div class="receipt-cell">
              <span>Recorded</span>
              <strong>${escapeHtml(formatClock(receipt.recordedAt))}</strong>
              <code>show v${receipt.after?.versions?.showVersion ?? "—"}</code>
            </div>
            <details class="receipt-details">
              <summary>Inspect state projection</summary>
              <pre>${escapeHtml(JSON.stringify({
                requestedParameters: receipt.requestedParameters,
                expectedVersions: receipt.expectedVersions,
                resultingVersions: receipt.resultingVersions,
                before: receipt.before,
                after: receipt.after,
              }, null, 2))}</pre>
            </details>
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

  function productForListing(seller, listingId) {
    return seller?.products?.find((product) => product.listing.listing_id === listingId) || null;
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
    return new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(isoString));
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
