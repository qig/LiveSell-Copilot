(() => {
  "use strict";

  const SESSION_KEY = "sidestage.m2.session";
  const SELLER_ORDER = ["sel_velocity_kicks", "sel_vault_consign", "sel_rotation_kicks"];
  const OPERATION_LABELS = {
    push: "Push",
    swap: "Swap",
    unlist: "Unlist",
    price_markdown: "Price Markdown",
    inventory_change: "Inventory Change",
  };
  const OPERATION_INDEX = {
    push: "01",
    swap: "02",
    unlist: "03",
    price_markdown: "04",
    inventory_change: "05",
  };

  const dom = {};
  let sellers = [];
  let sessionToken = null;
  let snapshot = null;
  let selectedListingId = null;
  let currentOperation = null;
  let streamTimer = null;
  let eventSource = null;
  let noticeTimer = null;
  let idempotencyCounter = 0;
  let snapshotRefresh = null;

  document.addEventListener("DOMContentLoaded", boot);

  async function boot() {
    cacheDom();
    bindEvents();
    try {
      const response = await api("/api/sellers");
      sellers = [...response.sellers].sort(
        (a, b) => SELLER_ORDER.indexOf(a.seller_id) - SELLER_ORDER.indexOf(b.seller_id),
      );
      populateSellerSelect();
      const restored = await restoreSession();
      if (!restored) await setActiveSeller(sellers[0].seller_id, {announce: false});
    } catch (error) {
      renderFatalError(error);
    }
  }

  function cacheDom() {
    Object.assign(dom, {
      sellerSelect: document.querySelector("#seller-select"),
      showId: document.querySelector("#show-id"),
      streamChip: document.querySelector("#stream-chip"),
      streamStatus: document.querySelector("#stream-status"),
      activeSku: document.querySelector("#active-sku"),
      eventCount: document.querySelector("#event-count"),
      toggleStream: document.querySelector("#toggle-stream"),
      stepStream: document.querySelector("#step-stream"),
      burstStream: document.querySelector("#burst-stream"),
      chatFeed: document.querySelector("#chat-feed"),
      chatForm: document.querySelector("#chat-form"),
      chatInput: document.querySelector("#chat-input"),
      activeCue: document.querySelector("#active-cue"),
      operationDock: document.querySelector("#operation-dock"),
      catalogRail: document.querySelector("#catalog-rail"),
      catalogNote: document.querySelector("#catalog-note"),
      undoBar: document.querySelector("#undo-bar"),
      undoSummary: document.querySelector("#undo-summary"),
      undoButton: document.querySelector("#undo-button"),
      dialog: document.querySelector("#operation-dialog"),
      operationForm: document.querySelector("#operation-form"),
      dialogIndex: document.querySelector("#dialog-index"),
      dialogTitle: document.querySelector("#dialog-title"),
      dialogDescription: document.querySelector("#dialog-description"),
      dialogFields: document.querySelector("#dialog-fields"),
      dialogError: document.querySelector("#dialog-error"),
      dialogConfirm: document.querySelector("#dialog-confirm"),
      notice: document.querySelector("#notice"),
      noticeTitle: document.querySelector("#notice-title"),
      noticeMessage: document.querySelector("#notice-message"),
      noticeClose: document.querySelector("#notice-close"),
    });
  }

  function bindEvents() {
    dom.sellerSelect.addEventListener("change", async (event) => {
      stopFixture();
      await setActiveSeller(event.target.value, {announce: true});
    });
    dom.toggleStream.addEventListener("click", () => {
      if (streamTimer) stopFixture();
      else startFixture();
    });
    dom.stepStream.addEventListener("click", () => appendPrepared(1));
    dom.burstStream.addEventListener("click", () => appendPrepared(8));
    dom.chatForm.addEventListener("submit", submitCustomChat);
    dom.operationDock.addEventListener("click", (event) => {
      const button = event.target.closest("[data-operation]");
      if (button && !button.disabled) openOperationDialog(button.dataset.operation);
    });
    dom.operationForm.addEventListener("submit", submitOperation);
    dom.undoButton.addEventListener("click", performUndo);
    dom.noticeClose.addEventListener("click", hideNotice);
    window.addEventListener("beforeunload", () => {
      stopFixture();
      eventSource?.close();
    });
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        ...(options.body ? {"Content-Type": "application/json"} : {}),
        ...(options.headers || {}),
      },
      cache: "no-store",
    });
    const payload = response.headers.get("content-type")?.includes("application/json")
      ? await response.json()
      : null;
    if (!response.ok) {
      const detail = Array.isArray(payload?.detail)
        ? payload.detail.map((item) => item.msg).join("; ")
        : payload?.detail;
      throw new Error(detail || `Request failed (${response.status})`);
    }
    return payload;
  }

  function populateSellerSelect() {
    dom.sellerSelect.innerHTML = sellers
      .map(
        (seller) =>
          `<option value="${escapeHtml(seller.seller_id)}">${escapeHtml(seller.display_name)} · ${escapeHtml(formatPersona(seller.persona))}</option>`,
      )
      .join("");
  }

  async function restoreSession() {
    const storedToken = sessionStorage.getItem(SESSION_KEY);
    if (!storedToken) return false;
    try {
      const restoredSnapshot = await api(
        `/api/sessions/${encodeURIComponent(storedToken)}/snapshot`,
      );
      sessionToken = storedToken;
      snapshot = restoredSnapshot;
      selectedListingId = defaultSelectableListingId();
      dom.sellerSelect.value = snapshot.seller.seller_id;
      renderAll();
      connectEvents();
      return true;
    } catch (_error) {
      sessionStorage.removeItem(SESSION_KEY);
      return false;
    }
  }

  async function setActiveSeller(sellerId, {announce}) {
    eventSource?.close();
    dom.sellerSelect.disabled = true;
    try {
      const response = await api("/api/demo/sessions", {
        method: "POST",
        body: JSON.stringify({seller_id: sellerId}),
      });
      sessionToken = response.session_token;
      sessionStorage.setItem(SESSION_KEY, sessionToken);
      snapshot = response.snapshot;
      selectedListingId = defaultSelectableListingId();
      dom.sellerSelect.value = sellerId;
      renderAll();
      connectEvents();
      if (announce) {
        showNotice("Seller session changed", `${snapshot.seller.display_name} is now backed by the server-owned show.`);
      }
    } finally {
      dom.sellerSelect.disabled = false;
    }
  }

  function connectEvents() {
    eventSource?.close();
    if (!sessionToken || !snapshot) return;
    eventSource = new EventSource(
      `/api/sessions/${encodeURIComponent(sessionToken)}/events?after=${snapshot.stream_offset}`,
    );
    eventSource.onopen = () => {
      dom.streamChip.classList.add("is-running");
      dom.streamStatus.textContent = streamTimer ? "Fixture playing" : "Live sync";
    };
    eventSource.onerror = () => {
      dom.streamChip.classList.remove("is-running");
      dom.streamStatus.textContent = "Reconnecting";
    };
    ["chat.accepted", "marketplace.changed"].forEach((type) => {
      eventSource.addEventListener(type, () => scheduleSnapshotRefresh());
    });
  }

  function scheduleSnapshotRefresh() {
    if (snapshotRefresh) return;
    snapshotRefresh = refreshSnapshot()
      .catch(() => {})
      .finally(() => {
        snapshotRefresh = null;
      });
  }

  async function refreshSnapshot() {
    const token = sessionToken;
    const next = await api(`/api/sessions/${encodeURIComponent(token)}/snapshot`);
    if (token !== sessionToken) return;
    snapshot = next;
    renderAll();
  }

  function renderAll() {
    if (!snapshot) return;
    dom.showId.textContent = snapshot.show.show_id;
    dom.eventCount.textContent = String(snapshot.chat_events.length).padStart(2, "0");
    dom.activeSku.textContent = activeListing()?.sku || "Stage clear";
    renderActiveCue();
    renderOperationDock();
    renderCatalog();
    renderUndo();
    renderChat();
    renderFixtureState();
  }

  function listingById(listingId) {
    return snapshot?.listings.find((listing) => listing.listing_id === listingId) || null;
  }

  function activeListing() {
    return listingById(snapshot?.show.active_listing_id);
  }

  function totalStock(listing) {
    return listing.variants.reduce((total, variant) => total + variant.available_quantity, 0);
  }

  function selectableListings(excludedId = null) {
    return snapshot.listings.filter(
      (listing) =>
        listing.listing_id !== excludedId &&
        listing.status === "available" &&
        totalStock(listing) > 0,
    );
  }

  function defaultSelectableListingId() {
    return selectableListings(snapshot?.show.active_listing_id)[0]?.listing_id || null;
  }

  function renderActiveCue() {
    const listing = activeListing();
    if (!listing) {
      dom.activeCue.innerHTML = `
        <div class="empty-cue">
          <div class="empty-stage-mark" aria-hidden="true"></div>
          <div class="empty-cue-copy">
            <p class="eyebrow">Empty active slot</p>
            <h3>The stage is clear.</h3>
            <p>Choose an in-stock pair from the catalog rail, then use Push to open the first listing epoch.</p>
            <button class="button button--signal" id="empty-push" type="button">Push selected pair</button>
          </div>
        </div>`;
      document.querySelector("#empty-push").addEventListener("click", () => openOperationDialog("push"));
      return;
    }

    const epoch = snapshot.epochs.find((item) => item.end_seq === null);
    const variants = listing.variants
      .map(
        (variant) => `
          <span class="variant-pill ${variant.available_quantity === 0 ? "is-empty" : ""}">
            ${escapeHtml(variant.label)} · ${variant.available_quantity}
          </span>`,
      )
      .join("");
    dom.activeCue.innerHTML = `
      <div class="cue-card">
        ${productArt(listing, productHue(listing.sku))}
        <div class="cue-information">
          <div class="cue-topline">
            <span class="live-label"><span class="live-pip" aria-hidden="true"></span> On stage</span>
            <span class="epoch-label">${escapeHtml(shortEpoch(epoch?.epoch_id))} · v${snapshot.show.version}</span>
          </div>
          <h3>${escapeHtml(listing.title)}</h3>
          <div class="cue-sku-line">
            <span>${escapeHtml(listing.sku)}</span>
            <span class="cue-condition">${escapeHtml(formatCondition(listing.condition))}</span>
          </div>
          <div class="cue-facts">
            <div class="price-block"><span>Current price</span><strong>${formatMoney(listing.price_cents)}</strong></div>
            <div class="stock-block"><span>Variant stock</span><div class="variant-pills">${variants}</div></div>
            <div class="policy-line"><span>Applicable seller rule</span><p>${escapeHtml(snapshot.seller.policies.price_floor)}</p></div>
          </div>
        </div>
      </div>`;
  }

  function renderOperationDock() {
    const active = activeListing();
    const states = {
      push: Boolean(!active && selectableListings().length),
      swap: Boolean(active && selectableListings(active.listing_id).length),
      unlist: Boolean(active),
      price_markdown: Boolean(active && active.price_cents > active.floor_price_cents),
      inventory_change: Boolean(active),
    };
    dom.operationDock.querySelectorAll("[data-operation]").forEach((button) => {
      button.disabled = !states[button.dataset.operation];
      button.setAttribute("aria-disabled", String(button.disabled));
    });
  }

  function renderCatalog() {
    const activeId = snapshot.show.active_listing_id;
    const selected = listingById(selectedListingId);
    if (
      !selected ||
      selected.status !== "available" ||
      totalStock(selected) <= 0 ||
      selected.listing_id === activeId
    ) {
      selectedListingId = defaultSelectableListingId();
    }
    dom.catalogNote.textContent = activeId
      ? "Select a different pair for Swap"
      : "Select a pair for Push";
    dom.catalogRail.replaceChildren();
    snapshot.listings.forEach((listing) => {
      const isActive = listing.listing_id === activeId;
      const isSelected = listing.listing_id === selectedListingId;
      const unavailable = listing.status === "unlisted" || totalStock(listing) === 0;
      const status = isActive
        ? "On stage"
        : listing.status === "unlisted"
          ? "Unlisted"
          : totalStock(listing) === 0
            ? "Out of stock"
            : isSelected
              ? "Selected"
              : "Available";
      const button = document.createElement("button");
      button.type = "button";
      button.className = `catalog-card${isActive ? " is-active" : ""}${isSelected ? " is-selected" : ""}`;
      button.dataset.listingId = listing.listing_id;
      button.setAttribute("role", "listitem");
      button.setAttribute("aria-pressed", String(isSelected));
      button.disabled = isActive || unavailable;
      button.innerHTML = `
        ${productArt(listing, productHue(listing.sku))}
        <span class="catalog-card-copy">
          <strong class="catalog-card-title">${escapeHtml(listing.title)}</strong>
          <span class="catalog-card-meta"><span>${escapeHtml(listing.sku)}</span><span>${formatMoney(listing.price_cents)}</span></span>
          <span class="catalog-card-status">${status}</span>
        </span>`;
      button.addEventListener("click", () => {
        selectedListingId = listing.listing_id;
        renderCatalog();
      });
      dom.catalogRail.append(button);
    });
  }

  function renderUndo() {
    const receipt = snapshot.receipts.find(
      (item) => item.receipt_id === snapshot.latest_undoable_receipt_id,
    );
    if (!receipt) {
      dom.undoBar.hidden = true;
      return;
    }
    dom.undoBar.hidden = false;
    dom.undoSummary.textContent = `${operationPastTense(receipt.operation_type)} · ${receipt.listing_id || "show"}`;
    dom.undoButton.dataset.receiptId = receipt.receipt_id;
  }

  function renderChat() {
    const nearBottom = dom.chatFeed.scrollHeight - dom.chatFeed.scrollTop - dom.chatFeed.clientHeight < 80;
    dom.chatFeed.replaceChildren();
    if (!snapshot.chat_events.length) {
      dom.chatFeed.innerHTML = `
        <div class="feed-empty"><span class="empty-index">00</span><div>
          <strong>The room is quiet.</strong><p>Play the prepared fixture or enter a custom buyer message below.</p>
        </div></div>`;
      return;
    }
    snapshot.chat_events.forEach((event) => {
      const item = document.createElement("article");
      item.className = "chat-item";
      item.innerHTML = `
        <span class="chat-index">${String(event.show_seq).padStart(2, "0")}</span>
        <div class="chat-body">
          <div class="chat-meta"><strong class="chat-customer">${escapeHtml(event.customer_display_name)}</strong><span class="chat-origin ${event.input_origin === "custom" ? "chat-origin--custom" : ""}">${escapeHtml(event.input_origin)}</span></div>
          <p class="chat-text">${escapeHtml(event.raw_text)}</p>
        </div>
        <div class="chat-binding"><time datetime="${escapeHtml(event.accepted_at)}">${escapeHtml(formatClock(event.accepted_at))}</time><span>${escapeHtml(shortEpoch(event.source_epoch_id))}</span></div>`;
      dom.chatFeed.append(item);
    });
    if (nearBottom || snapshot.chat_events.length === 1) {
      requestAnimationFrame(() => {
        dom.chatFeed.scrollTop = dom.chatFeed.scrollHeight;
      });
    }
  }

  async function submitCustomChat(event) {
    event.preventDefault();
    const rawText = dom.chatInput.value.trim();
    if (!rawText || !sessionToken) return;
    dom.chatInput.disabled = true;
    try {
      await api(`/api/sessions/${encodeURIComponent(sessionToken)}/chat/custom`, {
        method: "POST",
        body: JSON.stringify({raw_text: rawText}),
      });
      dom.chatInput.value = "";
      await refreshSnapshot();
    } catch (error) {
      showNotice("Message refused", error.message, {error: true});
    } finally {
      dom.chatInput.disabled = false;
      dom.chatInput.focus();
    }
  }

  async function appendPrepared(count) {
    if (!sessionToken) return;
    dom.stepStream.disabled = true;
    dom.burstStream.disabled = true;
    try {
      await api(`/api/sessions/${encodeURIComponent(sessionToken)}/chat/prepared`, {
        method: "POST",
        body: JSON.stringify({count}),
      });
      await refreshSnapshot();
    } catch (error) {
      stopFixture();
      showNotice("Prepared stream stopped", error.message, {error: true});
    } finally {
      dom.stepStream.disabled = false;
      dom.burstStream.disabled = false;
    }
  }

  function startFixture() {
    if (streamTimer) return;
    appendPrepared(1);
    streamTimer = window.setInterval(() => appendPrepared(1), 1650);
    renderFixtureState();
  }

  function stopFixture() {
    if (streamTimer) window.clearInterval(streamTimer);
    streamTimer = null;
    if (dom.streamStatus) renderFixtureState();
  }

  function renderFixtureState() {
    const playing = Boolean(streamTimer);
    dom.streamStatus.textContent = playing ? "Fixture playing" : eventSource ? "Live sync" : "Room ready";
    dom.toggleStream.querySelector("span").textContent = playing ? "Pause fixture" : "Play fixture";
    dom.toggleStream.querySelector("svg").innerHTML = playing
      ? '<path d="M8 5h3v14H8zM14 5h3v14h-3z" />'
      : '<path d="M8 5v14l11-7z" />';
  }

  function openOperationDialog(operationType) {
    currentOperation = operationType;
    dom.dialogError.hidden = true;
    dom.dialogError.textContent = "";
    dom.dialogIndex.textContent = OPERATION_INDEX[operationType];
    dom.dialogTitle.textContent = dialogTitle(operationType);
    dom.dialogDescription.textContent = dialogDescription(operationType);
    dom.dialogConfirm.textContent = confirmLabel(operationType);
    dom.dialogFields.innerHTML = dialogFields(operationType);
    dom.dialog.showModal();
  }

  function dialogFields(operationType) {
    const active = activeListing();
    if (operationType === "push" || operationType === "swap") {
      const options = selectableListings(snapshot.show.active_listing_id)
        .map(
          (listing) => `<option value="${escapeHtml(listing.listing_id)}" ${listing.listing_id === selectedListingId ? "selected" : ""}>${escapeHtml(listing.title)} · ${escapeHtml(listing.sku)} · ${formatMoney(listing.price_cents)}</option>`,
        )
        .join("");
      return `<label class="dialog-field"><span>${operationType === "push" ? "Listing to push" : "Replacement listing"}</span><select id="operation-listing" required>${options}</select><small>${operationType === "push" ? "Valid only while the active slot is empty." : "Closes the current epoch and opens a new one."}</small></label>`;
    }
    if (operationType === "unlist") {
      return `<div class="dialog-field"><span>Active listing</span><strong>${escapeHtml(active.title)} · ${escapeHtml(active.sku)}</strong><small>The active epoch closes and inventory remains unchanged.</small></div>`;
    }
    if (operationType === "price_markdown") {
      const suggested = Math.max(active.floor_price_cents, active.price_cents - 500);
      return `<label class="dialog-field"><span>New price (USD)</span><input id="markdown-price" type="number" inputmode="decimal" min="0.01" step="0.01" value="${(suggested / 100).toFixed(2)}" required /><small>Current ${formatMoney(active.price_cents)} · seller floor ${formatMoney(active.floor_price_cents)}.</small></label>`;
    }
    if (operationType === "inventory_change") {
      const options = active.variants
        .map((variant) => `<option value="${escapeHtml(variant.variant_id)}">${escapeHtml(variant.label)} · currently ${variant.available_quantity}</option>`)
        .join("");
      return `<label class="dialog-field"><span>Active variant</span><select id="inventory-variant" required>${options}</select></label><label class="dialog-field"><span>New available quantity</span><input id="inventory-quantity" type="number" inputmode="numeric" min="0" step="1" value="${active.variants[0].available_quantity}" required /><small>Absolute quantity. Zero does not unlist the pair.</small></label>`;
    }
    return "";
  }

  async function submitOperation(event) {
    event.preventDefault();
    if (!event.submitter || event.submitter.value === "cancel") {
      dom.dialog.close("cancel");
      currentOperation = null;
      return;
    }
    const operation = currentOperation;
    dom.dialogConfirm.disabled = true;
    try {
      const response = await executeOperation(operation);
      snapshot = response.snapshot;
      if (response.receipt.status !== "applied") {
        const message = refusalMessage(response.receipt.error_code);
        dom.dialogError.textContent = message;
        dom.dialogError.hidden = false;
        showNotice("Operation refused", message, {error: true});
        renderAll();
        return;
      }
      dom.dialog.close("applied");
      currentOperation = null;
      selectedListingId = defaultSelectableListingId();
      renderAll();
      showNotice(`${OPERATION_LABELS[operation]} applied`, "The verified server state and receipt are now available.");
    } catch (error) {
      dom.dialogError.textContent = error.message;
      dom.dialogError.hidden = false;
      showNotice("Operation failed", error.message, {error: true});
    } finally {
      dom.dialogConfirm.disabled = false;
    }
  }

  async function executeOperation(operation) {
    const active = activeListing();
    let route = operation.replaceAll("_", "-");
    let body;
    if (operation === "push") {
      body = {
        target_listing_id: document.querySelector("#operation-listing").value,
        expected_show_version: snapshot.show.version,
      };
    } else if (operation === "swap") {
      body = {
        target_listing_id: document.querySelector("#operation-listing").value,
        expected_active_listing_id: snapshot.show.active_listing_id,
        expected_show_version: snapshot.show.version,
      };
    } else if (operation === "unlist") {
      body = {
        expected_active_listing_id: snapshot.show.active_listing_id,
        expected_show_version: snapshot.show.version,
      };
    } else if (operation === "price_markdown") {
      body = {
        listing_id: active.listing_id,
        new_price_cents: Math.round(Number(document.querySelector("#markdown-price").value) * 100),
        expected_listing_version: active.version,
      };
    } else {
      const variantId = document.querySelector("#inventory-variant").value;
      const variant = active.variants.find((item) => item.variant_id === variantId);
      body = {
        listing_id: active.listing_id,
        variant_id: variantId,
        new_available_quantity: Number(document.querySelector("#inventory-quantity").value),
        expected_inventory_version: variant.version,
      };
    }
    return api(`/api/sessions/${encodeURIComponent(sessionToken)}/actions/${route}`, {
      method: "POST",
      headers: {"Idempotency-Key": nextIdempotencyKey(operation)},
      body: JSON.stringify(body),
    });
  }

  async function performUndo() {
    const receiptId = snapshot.latest_undoable_receipt_id;
    if (!receiptId) return;
    dom.undoButton.disabled = true;
    try {
      const response = await api(
        `/api/sessions/${encodeURIComponent(sessionToken)}/receipts/${encodeURIComponent(receiptId)}/compensate`,
        {method: "POST", headers: {"Idempotency-Key": nextIdempotencyKey("undo")}},
      );
      snapshot = response.snapshot;
      renderAll();
      if (response.receipt.status === "applied") {
        showNotice("Change undone", "A linked compensating receipt restored the prior safe state.");
      } else {
        showNotice("Undo refused", refusalMessage(response.receipt.error_code), {error: true});
      }
    } catch (error) {
      showNotice("Undo unavailable", error.message, {error: true});
    } finally {
      dom.undoButton.disabled = false;
    }
  }

  function nextIdempotencyKey(kind) {
    idempotencyCounter += 1;
    return `ui-${kind}-${Date.now()}-${idempotencyCounter}`;
  }

  function refusalMessage(code) {
    return {
      active_slot_not_empty: "Push requires an empty active slot.",
      active_slot_empty: "This operation requires an active listing.",
      swap_target_is_active: "Choose a different listing for Swap.",
      listing_out_of_stock: "The target listing is out of stock.",
      listing_unavailable: "The target listing is unavailable.",
      below_price_floor: "The new price is below the seller floor.",
      markdown_must_lower_price: "The new price must be strictly lower.",
      stale_show_version: "The show changed. Review the latest active listing and retry.",
      stale_listing_version: "The listing changed. Review the latest price and retry.",
      stale_inventory_version: "Inventory changed. Review the latest quantity and retry.",
      stale_compensation: "A newer state change prevents this Undo.",
      variant_not_in_listing: "Choose a variant from the active listing.",
      idempotency_conflict: "This request key was already used for another action.",
    }[code] || `The server refused this operation (${code || "unknown_reason"}).`;
  }

  function showNotice(title, message, {error = false} = {}) {
    window.clearTimeout(noticeTimer);
    dom.noticeTitle.textContent = title;
    dom.noticeMessage.textContent = message;
    dom.notice.classList.toggle("is-error", error);
    dom.notice.hidden = false;
    noticeTimer = window.setTimeout(hideNotice, 5200);
  }

  function hideNotice() {
    window.clearTimeout(noticeTimer);
    dom.notice.hidden = true;
  }

  function renderFatalError(error) {
    dom.sellerSelect.disabled = true;
    dom.toggleStream.disabled = true;
    dom.stepStream.disabled = true;
    dom.burstStream.disabled = true;
    dom.operationDock.querySelectorAll("button").forEach((button) => {
      button.disabled = true;
    });
    dom.activeCue.innerHTML = `<div class="empty-cue"><div class="empty-stage-mark" aria-hidden="true"></div><div class="empty-cue-copy"><p class="eyebrow">Backend unavailable</p><h3>The show cannot start.</h3><p>${escapeHtml(error.message)}</p><button class="button button--signal" type="button" id="retry-app">Retry</button></div></div>`;
    document.querySelector("#retry-app").addEventListener("click", () => window.location.reload());
  }

  function dialogTitle(operation) {
    return {
      push: "Push a listing",
      swap: "Swap the active pair",
      unlist: "Unlist the active pair",
      price_markdown: "Mark down the price",
      inventory_change: "Set variant inventory",
    }[operation];
  }

  function dialogDescription(operation) {
    return {
      push: "Choose one available, in-stock listing. Push is valid only from an empty stage.",
      swap: "Replace the current cue with a different pair and open a new listing epoch.",
      unlist: "Explicitly unlist the pair on stage. Stock does not change.",
      price_markdown: "Lower the current price without crossing the seller-configured floor.",
      inventory_change: "Set one active variant to a nonnegative absolute quantity.",
    }[operation];
  }

  function confirmLabel(operation) {
    return {
      push: "Push listing",
      swap: "Swap listing",
      unlist: "Unlist pair",
      price_markdown: "Apply markdown",
      inventory_change: "Set inventory",
    }[operation];
  }

  function operationPastTense(operation) {
    return {
      push: "Pushed",
      swap: "Swapped",
      unlist: "Unlisted",
      price_markdown: "Marked down",
      inventory_change: "Inventory changed",
    }[operation];
  }

  function productArt(product, hue) {
    return `<div class="product-art" style="--product-hue:${hue}" aria-hidden="true"><span class="product-art-orbit"></span><span class="product-art-sole"></span><span class="product-art-upper"></span><span class="product-art-code">${escapeHtml(product.sku)}</span></div>`;
  }

  function productHue(sku) {
    const total = [...sku].reduce((sum, character) => sum + character.charCodeAt(0), 0);
    return 25 + (total * 17) % 295;
  }

  function formatMoney(cents) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(cents / 100);
  }

  function formatClock(value) {
    return new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(value));
  }

  function shortEpoch(epochId) {
    if (!epochId) return "No cue";
    return `E${epochId.split("_").at(-1)}`;
  }

  function formatCondition(condition) {
    return condition.charAt(0).toUpperCase() + condition.slice(1);
  }

  function formatPersona(persona) {
    return persona.replaceAll("_", " ");
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
