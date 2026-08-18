(() => {
  "use strict";

  const STORAGE_KEY = "sidestage.m2.demo.v2";
  const SCHEMA_VERSION = 2;
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
  let fixtureData = null;
  let store = null;
  let activeSeller = null;
  let selectedListingId = null;
  let currentOperation = null;
  let streamTimer = null;
  let noticeTimer = null;

  document.addEventListener("DOMContentLoaded", boot);

  async function boot() {
    cacheDom();
    bindStaticEvents();

    try {
      const [sellerResponse, chatResponse] = await Promise.all([
        fetch("/fixtures/sellers.json"),
        fetch("/fixtures/chat_messages.json"),
      ]);

      if (!sellerResponse.ok || !chatResponse.ok) {
        throw new Error("The approved synthetic fixtures could not be loaded.");
      }

      const [sellerFixture, chatFixture] = await Promise.all([
        sellerResponse.json(),
        chatResponse.json(),
      ]);

      fixtureData = {
        sellers: [...sellerFixture.sellers].sort(
          (a, b) => SELLER_ORDER.indexOf(a.seller_id) - SELLER_ORDER.indexOf(b.seller_id),
        ),
        chat: chatFixture,
      };

      store = loadStore();
      const initialSellerId = fixtureData.sellers.some(
        (seller) => seller.seller_id === store.activeSellerId,
      )
        ? store.activeSellerId
        : fixtureData.sellers[0].seller_id;

      populateSellerSelect(initialSellerId);
      setActiveSeller(initialSellerId, { announce: false });
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
      resetDemo: document.querySelector("#reset-demo"),
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

  function bindStaticEvents() {
    dom.sellerSelect.addEventListener("change", (event) => {
      stopStream();
      setActiveSeller(event.target.value, { announce: true });
    });

    dom.toggleStream.addEventListener("click", () => {
      if (streamTimer) {
        stopStream();
      } else {
        startStream();
      }
    });

    dom.stepStream.addEventListener("click", () => appendNextPreparedMessage());
    dom.burstStream.addEventListener("click", () => {
      for (let index = 0; index < 8; index += 1) {
        appendNextPreparedMessage({ render: index === 7 });
      }
    });

    dom.chatForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const text = dom.chatInput.value.trim();
      if (!text) return;
      appendChatEvent({
        customerDisplayName: "demo_buyer",
        rawText: text,
        inputOrigin: "custom",
      });
      dom.chatInput.value = "";
      dom.chatInput.focus();
    });

    dom.operationDock.addEventListener("click", (event) => {
      const button = event.target.closest("[data-operation]");
      if (!button || button.disabled) return;
      openOperationDialog(button.dataset.operation);
    });

    dom.undoButton.addEventListener("click", performUndo);
    dom.operationForm.addEventListener("submit", handleDialogSubmit);
    dom.noticeClose.addEventListener("click", hideNotice);

    dom.resetDemo.addEventListener("click", () => {
      if (!activeSeller) return;
      const accepted = window.confirm(
        `Reset the synthetic ${activeSeller.display_name} show, including chat, epochs, and UI receipts?`,
      );
      if (!accepted) return;
      stopStream();
      store.shows[activeSeller.seller_id] = createShowState(activeSeller);
      selectedListingId = null;
      saveStore();
      renderAll();
      showNotice("Show reset", "The seller-scoped synthetic browser state is back to an empty stage.");
    });

    window.addEventListener("beforeunload", stopStream);
  }

  function loadStore() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (
        parsed &&
        parsed.schemaVersion === SCHEMA_VERSION &&
        parsed.shows &&
        typeof parsed.shows === "object"
      ) {
        return parsed;
      }
    } catch (_error) {
      // A corrupt disposable demo snapshot is safely replaced.
    }

    return {
      schemaVersion: SCHEMA_VERSION,
      activeSellerId: null,
      shows: {},
      updatedAt: null,
    };
  }

  function saveStore() {
    store.updatedAt = new Date().toISOString();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  }

  function populateSellerSelect(selectedSellerId) {
    dom.sellerSelect.replaceChildren();
    fixtureData.sellers.forEach((seller) => {
      const option = document.createElement("option");
      option.value = seller.seller_id;
      option.textContent = `${seller.display_name} · ${formatPersona(seller.persona)}`;
      option.selected = seller.seller_id === selectedSellerId;
      dom.sellerSelect.append(option);
    });
  }

  function setActiveSeller(sellerId, { announce }) {
    const seller = fixtureData.sellers.find((item) => item.seller_id === sellerId);
    if (!seller) return;

    activeSeller = seller;
    store.activeSellerId = sellerId;
    if (!store.shows[sellerId]) {
      store.shows[sellerId] = createShowState(seller);
    }

    selectedListingId = getDefaultSelectableListingId(store.shows[sellerId]);
    saveStore();
    renderAll();

    if (announce) {
      showNotice(
        `${seller.display_name} loaded`,
        "Seller-scoped show state and synthetic catalog are isolated from the other fixtures.",
      );
    }
  }

  function createShowState(seller) {
    const slug = seller.seller_id.replace(/^sel_/, "");
    const listings = {};

    seller.products.forEach((product) => {
      listings[product.listing.listing_id] = {
        listingId: product.listing.listing_id,
        productId: product.product_id,
        status: product.listing.status,
        priceCents: product.listing.price_cents,
        floorPriceCents: product.listing.floor_price_cents,
        listingVersion: 1,
        inventory: Object.fromEntries(
          product.variants.map((variant) => [
            variant.variant_id,
            {
              variantId: variant.variant_id,
              label: variant.label,
              availableQuantity: variant.available_quantity,
              inventoryVersion: 1,
            },
          ]),
        ),
      };
    });

    return {
      sellerId: seller.seller_id,
      showId: `show_${slug}_m2_demo`,
      showVersion: 1,
      activeListingId: null,
      currentEpochId: null,
      sequence: 0,
      eventCounter: 0,
      receiptCounter: 0,
      epochCounter: 0,
      messageCursor: 0,
      listings,
      chat: [],
      epochs: [],
      receipts: [],
      latestUndoableReceiptId: null,
      startedAt: new Date().toISOString(),
    };
  }

  function getShow() {
    return activeSeller ? store.shows[activeSeller.seller_id] : null;
  }

  function getProductByListingId(listingId) {
    return activeSeller.products.find((product) => product.listing.listing_id === listingId) || null;
  }

  function getDefaultSelectableListingId(show) {
    const available = activeSeller.products.find((product) => {
      const listing = show.listings[product.listing.listing_id];
      return listing.status === "available" && totalStock(listing) > 0;
    });
    return available?.listing.listing_id || show.activeListingId || null;
  }

  function totalStock(listing) {
    return Object.values(listing.inventory).reduce(
      (total, inventory) => total + inventory.availableQuantity,
      0,
    );
  }

  function renderAll() {
    const show = getShow();
    if (!show) return;

    dom.sellerSelect.value = activeSeller.seller_id;
    dom.showId.textContent = show.showId;
    dom.eventCount.textContent = String(show.chat.length).padStart(2, "0");
    dom.activeSku.textContent = show.activeListingId
      ? getProductByListingId(show.activeListingId).sku
      : "Stage clear";

    renderActiveCue();
    renderOperationDock();
    renderCatalog();
    renderUndo();
    renderChat();
    renderStreamState();
  }

  function renderActiveCue() {
    const show = getShow();
    if (!show.activeListingId) {
      dom.activeCue.innerHTML = `
        <div class="empty-cue">
          <div class="empty-stage-mark" aria-hidden="true"></div>
          <div class="empty-cue-copy">
            <p class="eyebrow">Empty active slot</p>
            <h3>The stage is clear.</h3>
            <p>Choose an in-stock pair from the catalog rail, then use Push to open the first listing epoch.</p>
            <button class="button button--signal" id="empty-push" type="button">Push selected pair</button>
          </div>
        </div>
      `;
      document.querySelector("#empty-push").addEventListener("click", () => openOperationDialog("push"));
      return;
    }

    const product = getProductByListingId(show.activeListingId);
    const listing = show.listings[show.activeListingId];
    const epoch = show.epochs.find((item) => item.epochId === show.currentEpochId);
    const hue = productHue(product.sku);
    const variants = Object.values(listing.inventory)
      .map(
        (variant) => `
          <span class="variant-pill ${variant.availableQuantity === 0 ? "is-empty" : ""}">
            ${escapeHtml(variant.label)} · ${variant.availableQuantity}
          </span>
        `,
      )
      .join("");

    dom.activeCue.innerHTML = `
      <div class="cue-card">
        ${productArt(product, hue)}
        <div class="cue-information">
          <div class="cue-topline">
            <span class="live-label"><span class="live-pip" aria-hidden="true"></span> On stage</span>
            <span class="epoch-label">${escapeHtml(shortEpoch(epoch?.epochId))} · v${show.showVersion}</span>
          </div>
          <h3>${escapeHtml(product.listing.title)}</h3>
          <div class="cue-sku-line">
            <span>${escapeHtml(product.sku)}</span>
            <span class="cue-condition">${escapeHtml(formatCondition(product.listing.condition))}</span>
          </div>
          <div class="cue-facts">
            <div class="price-block">
              <span>Current price</span>
              <strong>${formatMoney(listing.priceCents)}</strong>
            </div>
            <div class="stock-block">
              <span>Variant stock</span>
              <div class="variant-pills">${variants}</div>
            </div>
            <div class="policy-line">
              <span>Applicable seller rule</span>
              <p>${escapeHtml(activeSeller.policies.price_floor)}</p>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function renderOperationDock() {
    const show = getShow();
    const hasActive = Boolean(show.activeListingId);
    const activeListing = hasActive ? show.listings[show.activeListingId] : null;
    const canPush = !hasActive && hasSelectableListing(show, null);
    const canSwap = hasActive && hasSelectableListing(show, show.activeListingId);
    const canMarkdown = hasActive && activeListing.priceCents > activeListing.floorPriceCents;
    const states = {
      push: { enabled: canPush, reason: hasActive ? "Push requires an empty active slot" : "No available in-stock listing" },
      swap: { enabled: canSwap, reason: hasActive ? "No different in-stock listing is available" : "Swap requires an active listing" },
      unlist: { enabled: hasActive, reason: "Unlist requires an active listing" },
      price_markdown: {
        enabled: canMarkdown,
        reason: hasActive ? "The active listing is already at its seller floor" : "Markdown requires an active listing",
      },
      inventory_change: { enabled: hasActive, reason: "Inventory Change requires an active listing" },
    };

    dom.operationDock.querySelectorAll("[data-operation]").forEach((button) => {
      const state = states[button.dataset.operation];
      button.disabled = !state.enabled;
      button.title = state.enabled ? "" : state.reason;
      button.setAttribute("aria-disabled", String(!state.enabled));
    });
  }

  function hasSelectableListing(show, excludedListingId) {
    return activeSeller.products.some((product) => {
      const listing = show.listings[product.listing.listing_id];
      return (
        product.listing.listing_id !== excludedListingId &&
        listing.status === "available" &&
        totalStock(listing) > 0
      );
    });
  }

  function renderCatalog() {
    const show = getShow();
    const activeListingId = show.activeListingId;
    const selectedListing = selectedListingId ? show.listings[selectedListingId] : null;
    const selectionStillValid =
      selectedListing &&
      selectedListing.status === "available" &&
      totalStock(selectedListing) > 0 &&
      selectedListingId !== activeListingId;
    if (!selectionStillValid || selectedListingId === activeListingId) {
      selectedListingId = getDefaultSelectableListingId(show);
      if (selectedListingId === activeListingId) selectedListingId = null;
    }

    dom.catalogNote.textContent = activeListingId ? "Select a different pair for Swap" : "Select a pair for Push";
    dom.catalogRail.replaceChildren();

    activeSeller.products.forEach((product) => {
      const listingId = product.listing.listing_id;
      const listing = show.listings[listingId];
      const isActive = activeListingId === listingId;
      const isSelected = selectedListingId === listingId;
      const isUnavailable = listing.status === "unlisted" || totalStock(listing) === 0;
      const button = document.createElement("button");
      button.type = "button";
      button.className = [
        "catalog-card",
        isActive ? "is-active" : "",
        isSelected ? "is-selected" : "",
      ]
        .filter(Boolean)
        .join(" ");
      button.dataset.listingId = listingId;
      button.setAttribute("role", "listitem");
      button.disabled = isActive || isUnavailable;
      button.setAttribute("aria-pressed", String(isSelected));
      const status = isActive
        ? "On stage"
        : listing.status === "unlisted"
          ? "Unlisted"
          : totalStock(listing) === 0
            ? "Out of stock"
            : isSelected
              ? "Selected"
              : "Available";
      button.innerHTML = `
        ${productArt(product, productHue(product.sku))}
        <span class="catalog-card-copy">
          <strong class="catalog-card-title">${escapeHtml(product.listing.title)}</strong>
          <span class="catalog-card-meta">
            <span>${escapeHtml(product.sku)}</span>
            <span>${formatMoney(listing.priceCents)}</span>
          </span>
          <span class="catalog-card-status">${status}</span>
        </span>
      `;
      button.addEventListener("click", () => {
        selectedListingId = listingId;
        renderCatalog();
      });
      dom.catalogRail.append(button);
    });
  }

  function renderUndo() {
    const show = getShow();
    const receipt = show.receipts.find(
      (item) => item.receiptId === show.latestUndoableReceiptId,
    );

    if (!receipt || receipt.compensatedByReceiptId) {
      dom.undoBar.hidden = true;
      return;
    }

    dom.undoBar.hidden = false;
    dom.undoSummary.textContent = `${operationPastTense(receipt.operationType)} · ${receipt.subjectLabel}`;
    dom.undoButton.dataset.receiptId = receipt.receiptId;
  }

  function renderChat() {
    const show = getShow();
    const wasNearBottom =
      dom.chatFeed.scrollHeight - dom.chatFeed.scrollTop - dom.chatFeed.clientHeight < 80;
    dom.chatFeed.replaceChildren();

    if (show.chat.length === 0) {
      const empty = document.createElement("div");
      empty.className = "feed-empty";
      empty.innerHTML = `
        <span class="empty-index">00</span>
        <div>
          <strong>The room is quiet.</strong>
          <p>Play the prepared fixture or enter a custom buyer message below.</p>
        </div>
      `;
      dom.chatFeed.append(empty);
      return;
    }

    show.chat.forEach((event) => {
      const item = document.createElement("article");
      item.className = "chat-item";

      const index = document.createElement("span");
      index.className = "chat-index";
      index.textContent = String(event.showSeq).padStart(2, "0");

      const body = document.createElement("div");
      body.className = "chat-body";
      const meta = document.createElement("div");
      meta.className = "chat-meta";
      const customer = document.createElement("strong");
      customer.className = "chat-customer";
      customer.textContent = event.customerDisplayName;
      const origin = document.createElement("span");
      origin.className = `chat-origin ${event.inputOrigin === "custom" ? "chat-origin--custom" : ""}`;
      origin.textContent = event.inputOrigin;
      meta.append(customer, origin);
      const text = document.createElement("p");
      text.className = "chat-text";
      text.textContent = event.rawText;
      body.append(meta, text);

      const binding = document.createElement("div");
      binding.className = "chat-binding";
      const time = document.createElement("time");
      time.dateTime = event.acceptedAt;
      time.textContent = formatClock(event.acceptedAt);
      const epoch = document.createElement("span");
      epoch.textContent = event.sourceEpochId ? shortEpoch(event.sourceEpochId) : "No cue";
      binding.append(time, epoch);

      item.append(index, body, binding);
      dom.chatFeed.append(item);
    });

    if (wasNearBottom || show.chat.length === 1) {
      requestAnimationFrame(() => {
        dom.chatFeed.scrollTop = dom.chatFeed.scrollHeight;
      });
    }
  }

  function renderStreamState() {
    const running = Boolean(streamTimer);
    dom.streamChip.classList.toggle("is-running", running);
    dom.streamStatus.textContent = running ? "Fixture playing" : "Room ready";
    dom.toggleStream.querySelector("span").textContent = running ? "Pause fixture" : "Play fixture";
    dom.toggleStream.querySelector("svg").innerHTML = running
      ? '<path d="M8 5h3v14H8zM14 5h3v14h-3z" />'
      : '<path d="M8 5v14l11-7z" />';
  }

  function startStream() {
    if (streamTimer || !activeSeller) return;
    appendNextPreparedMessage();
    streamTimer = window.setInterval(() => appendNextPreparedMessage(), 1650);
    renderStreamState();
  }

  function stopStream() {
    if (streamTimer) window.clearInterval(streamTimer);
    streamTimer = null;
    if (dom.streamStatus) renderStreamState();
  }

  function preparedQueueForSeller() {
    const texts = [];
    fixtureData.chat.pools
      .filter(
        (pool) => pool.seller_scope === "all" || pool.seller_scope === activeSeller.seller_id,
      )
      .forEach((pool) => {
        if (Array.isArray(pool.messages)) texts.push(...pool.messages);
        if (Array.isArray(pool.message_pairs)) {
          pool.message_pairs.forEach((pair) => texts.push(...pair));
        }
      });

    // Interleave deterministic thirds so the visible feed does not arrive category-by-category.
    const interleaved = [];
    const stride = Math.ceil(texts.length / 3);
    for (let offset = 0; offset < stride; offset += 1) {
      [offset, offset + stride, offset + stride * 2].forEach((index) => {
        if (texts[index]) interleaved.push(texts[index]);
      });
    }
    return interleaved;
  }

  function appendNextPreparedMessage({ render = true } = {}) {
    if (!activeSeller) return;
    const show = getShow();
    const queue = preparedQueueForSeller();
    if (queue.length === 0) return;
    const cursor = show.messageCursor % queue.length;
    const customerNames = fixtureData.chat.customer_names;
    const customerDisplayName = customerNames[show.messageCursor % customerNames.length];
    show.messageCursor += 1;
    appendChatEvent(
      {
        customerDisplayName,
        rawText: queue[cursor],
        inputOrigin: "prepared",
      },
      { render },
    );
  }

  function appendChatEvent(eventInput, { render = true } = {}) {
    const show = getShow();
    show.sequence += 1;
    show.eventCounter += 1;
    const slug = activeSeller.seller_id.replace(/^sel_/, "");
    const event = {
      eventId: `evt_${slug}_${String(show.eventCounter).padStart(4, "0")}`,
      sellerId: activeSeller.seller_id,
      showId: show.showId,
      showSeq: show.sequence,
      acceptedAt: new Date().toISOString(),
      customerDisplayName: eventInput.customerDisplayName,
      rawText: eventInput.rawText,
      inputOrigin: eventInput.inputOrigin,
      sourceEpochId: show.currentEpochId,
      sourceListingId: show.activeListingId,
    };
    show.chat.push(event);
    saveStore();
    if (render) {
      dom.eventCount.textContent = String(show.chat.length).padStart(2, "0");
      renderChat();
    }
  }

  function openOperationDialog(operationType) {
    const show = getShow();
    currentOperation = operationType;
    dom.dialogError.hidden = true;
    dom.dialogError.textContent = "";
    dom.dialogIndex.textContent = OPERATION_INDEX[operationType];
    dom.dialogTitle.textContent = dialogTitle(operationType);
    dom.dialogDescription.textContent = dialogDescription(operationType);
    dom.dialogConfirm.textContent = confirmLabel(operationType);
    dom.dialogFields.innerHTML = dialogFields(operationType, show);
    dom.dialog.showModal();
  }

  function dialogFields(operationType, show) {
    if (operationType === "push" || operationType === "swap") {
      const options = activeSeller.products
        .filter((product) => {
          const listing = show.listings[product.listing.listing_id];
          return (
            listing.status === "available" &&
            totalStock(listing) > 0 &&
            product.listing.listing_id !== show.activeListingId
          );
        })
        .map((product) => {
          const listing = show.listings[product.listing.listing_id];
          const selected = product.listing.listing_id === selectedListingId ? "selected" : "";
          return `<option value="${escapeHtml(product.listing.listing_id)}" ${selected}>${escapeHtml(product.listing.title)} · ${escapeHtml(product.sku)} · ${formatMoney(listing.priceCents)}</option>`;
        })
        .join("");
      return `
        <label class="dialog-field">
          <span>${operationType === "push" ? "Listing to push" : "Replacement listing"}</span>
          <select id="operation-listing" name="listingId" required>${options}</select>
          <small>${operationType === "push" ? "Push is valid only while the active slot is empty." : "Swap atomically closes the current epoch and opens a new one."}</small>
        </label>
      `;
    }

    if (operationType === "unlist") {
      const product = getProductByListingId(show.activeListingId);
      return `
        <div class="dialog-field">
          <span>Active listing</span>
          <strong>${escapeHtml(product.listing.title)} · ${escapeHtml(product.sku)}</strong>
          <small>The active epoch will close and the slot will become empty. Inventory is unchanged.</small>
        </div>
      `;
    }

    if (operationType === "price_markdown") {
      const listing = show.listings[show.activeListingId];
      const suggested = Math.max(listing.floorPriceCents, listing.priceCents - 500);
      return `
        <label class="dialog-field">
          <span>New price (USD)</span>
          <input id="markdown-price" name="price" type="number" inputmode="decimal" min="0.01" step="0.01" value="${(suggested / 100).toFixed(2)}" required />
          <small>Current ${formatMoney(listing.priceCents)} · seller floor ${formatMoney(listing.floorPriceCents)}. The new price must be strictly lower.</small>
        </label>
      `;
    }

    if (operationType === "inventory_change") {
      const listing = show.listings[show.activeListingId];
      const options = Object.values(listing.inventory)
        .map(
          (variant) => `<option value="${escapeHtml(variant.variantId)}">${escapeHtml(variant.label)} · currently ${variant.availableQuantity}</option>`,
        )
        .join("");
      const firstVariant = Object.values(listing.inventory)[0];
      return `
        <label class="dialog-field">
          <span>Active variant</span>
          <select id="inventory-variant" name="variantId" required>${options}</select>
        </label>
        <label class="dialog-field">
          <span>New available quantity</span>
          <input id="inventory-quantity" name="quantity" type="number" inputmode="numeric" min="0" step="1" value="${firstVariant.availableQuantity}" required />
          <small>This sets an absolute quantity. Zero stock does not unlist the active listing.</small>
        </label>
      `;
    }

    return "";
  }

  function handleDialogSubmit(event) {
    event.preventDefault();
    const submitter = event.submitter;
    if (!submitter || submitter.value === "cancel") {
      dom.dialog.close("cancel");
      currentOperation = null;
      return;
    }

    const params = {};
    if (currentOperation === "push" || currentOperation === "swap") {
      params.targetListingId = document.querySelector("#operation-listing")?.value;
    } else if (currentOperation === "price_markdown") {
      params.newPriceCents = Math.round(Number(document.querySelector("#markdown-price")?.value) * 100);
    } else if (currentOperation === "inventory_change") {
      params.variantId = document.querySelector("#inventory-variant")?.value;
      params.newAvailableQuantity = Number(document.querySelector("#inventory-quantity")?.value);
    }

    const result = executeOperation(currentOperation, params);
    if (!result.ok) {
      dom.dialogError.textContent = result.message;
      dom.dialogError.hidden = false;
      showNotice("Operation refused", result.message, { error: true });
      return;
    }

    const operationLabel = OPERATION_LABELS[currentOperation];
    dom.dialog.close("applied");
    currentOperation = null;
    selectedListingId = getDefaultSelectableListingId(getShow());
    saveStore();
    renderAll();
    showNotice(`${operationLabel} applied`, result.message);
  }

  function executeOperation(operationType, params) {
    const show = getShow();
    const before = snapshotShow(show);
    let subjectLabel = "Seller show";
    let undoData = null;

    if (operationType === "push") {
      const listing = show.listings[params.targetListingId];
      const product = getProductByListingId(params.targetListingId);
      if (show.activeListingId) {
        return rejectOperation(operationType, params, before, "ACTIVE_SLOT_OCCUPIED", "Push requires an empty active slot.");
      }
      if (!listing || listing.status !== "available" || totalStock(listing) <= 0) {
        return rejectOperation(operationType, params, before, "TARGET_UNAVAILABLE", "Choose an available listing with at least one unit in stock.");
      }

      const sequence = nextActionSequence(show);
      listing.status = "active";
      listing.listingVersion += 1;
      show.activeListingId = listing.listingId;
      show.showVersion += 1;
      openEpoch(show, listing.listingId, sequence);
      subjectLabel = product.sku;
      undoData = {
        kind: "push",
        listingId: listing.listingId,
        expectedShowVersion: show.showVersion,
        expectedListingVersion: listing.listingVersion,
      };
    }

    if (operationType === "swap") {
      const previousListingId = show.activeListingId;
      const previous = show.listings[previousListingId];
      const target = show.listings[params.targetListingId];
      const targetProduct = getProductByListingId(params.targetListingId);
      if (!previous) {
        return rejectOperation(operationType, params, before, "ACTIVE_SLOT_EMPTY", "Swap requires an active listing. Use Push from an empty slot.");
      }
      if (!target || target.listingId === previousListingId) {
        return rejectOperation(operationType, params, before, "SAME_TARGET", "Choose a different listing for Swap.");
      }
      if (target.status !== "available" || totalStock(target) <= 0) {
        return rejectOperation(operationType, params, before, "TARGET_UNAVAILABLE", "The replacement must be available and in stock.");
      }

      const sequence = nextActionSequence(show);
      closeCurrentEpoch(show, sequence);
      previous.status = "available";
      previous.listingVersion += 1;
      target.status = "active";
      target.listingVersion += 1;
      show.activeListingId = target.listingId;
      show.showVersion += 1;
      openEpoch(show, target.listingId, sequence);
      subjectLabel = `${getProductByListingId(previousListingId).sku} → ${targetProduct.sku}`;
      undoData = {
        kind: "swap",
        previousListingId,
        targetListingId: target.listingId,
        expectedShowVersion: show.showVersion,
        expectedPreviousVersion: previous.listingVersion,
        expectedTargetVersion: target.listingVersion,
      };
    }

    if (operationType === "unlist") {
      const listingId = show.activeListingId;
      const listing = show.listings[listingId];
      if (!listing) {
        return rejectOperation(operationType, params, before, "ACTIVE_SLOT_EMPTY", "Unlist requires an active listing.");
      }

      const sequence = nextActionSequence(show);
      closeCurrentEpoch(show, sequence);
      listing.status = "unlisted";
      listing.listingVersion += 1;
      show.activeListingId = null;
      show.showVersion += 1;
      subjectLabel = getProductByListingId(listingId).sku;
      undoData = {
        kind: "unlist",
        listingId,
        expectedShowVersion: show.showVersion,
        expectedListingVersion: listing.listingVersion,
      };
    }

    if (operationType === "price_markdown") {
      const listingId = show.activeListingId;
      const listing = show.listings[listingId];
      if (!listing) {
        return rejectOperation(operationType, params, before, "ACTIVE_SLOT_EMPTY", "Price Markdown requires an active listing.");
      }
      if (!Number.isInteger(params.newPriceCents)) {
        return rejectOperation(operationType, params, before, "INVALID_PRICE", "Enter a valid price in dollars and cents.");
      }
      if (params.newPriceCents >= listing.priceCents) {
        return rejectOperation(operationType, params, before, "NOT_A_MARKDOWN", "The new price must be strictly lower than the current price.");
      }
      if (params.newPriceCents < listing.floorPriceCents) {
        return rejectOperation(operationType, params, before, "BELOW_SELLER_FLOOR", `The seller floor is ${formatMoney(listing.floorPriceCents)}.`);
      }

      const previousPriceCents = listing.priceCents;
      nextActionSequence(show);
      listing.priceCents = params.newPriceCents;
      listing.listingVersion += 1;
      subjectLabel = `${getProductByListingId(listingId).sku} · ${formatMoney(listing.priceCents)}`;
      undoData = {
        kind: "price_markdown",
        listingId,
        previousPriceCents,
        expectedListingVersion: listing.listingVersion,
        expectedPriceCents: listing.priceCents,
      };
    }

    if (operationType === "inventory_change") {
      const listingId = show.activeListingId;
      const listing = show.listings[listingId];
      const inventory = listing?.inventory[params.variantId];
      if (!listing || !inventory) {
        return rejectOperation(operationType, params, before, "VARIANT_NOT_ACTIVE", "Choose a variant on the active listing.");
      }
      if (!Number.isInteger(params.newAvailableQuantity) || params.newAvailableQuantity < 0) {
        return rejectOperation(operationType, params, before, "INVALID_QUANTITY", "Available quantity must be a nonnegative whole number.");
      }
      if (params.newAvailableQuantity === inventory.availableQuantity) {
        return rejectOperation(operationType, params, before, "NO_CHANGE", "Choose a quantity different from the current value.");
      }

      const previousAvailableQuantity = inventory.availableQuantity;
      nextActionSequence(show);
      inventory.availableQuantity = params.newAvailableQuantity;
      inventory.inventoryVersion += 1;
      subjectLabel = `${getProductByListingId(listingId).sku} · ${inventory.label} → ${inventory.availableQuantity}`;
      undoData = {
        kind: "inventory_change",
        listingId,
        variantId: inventory.variantId,
        previousAvailableQuantity,
        expectedInventoryVersion: inventory.inventoryVersion,
        expectedAvailableQuantity: inventory.availableQuantity,
      };
    }

    const after = snapshotShow(show);
    const receipt = recordReceipt({
      show,
      operationType,
      status: "applied",
      requestedParameters: params,
      before,
      after,
      subjectLabel,
      undoData,
    });
    show.latestUndoableReceiptId = receipt.receiptId;
    saveStore();

    const suffix = operationType === "inventory_change" && params.newAvailableQuantity === 0
      ? " The listing remains active at zero stock."
      : "";
    return { ok: true, message: `${subjectLabel} is now reflected in the synthetic show state.${suffix}` };
  }

  function rejectOperation(operationType, params, before, errorCode, message) {
    const show = getShow();
    recordReceipt({
      show,
      operationType,
      status: "rejected",
      requestedParameters: params,
      before,
      after: before,
      errorCode,
      subjectLabel: "No state change",
      undoData: null,
    });
    saveStore();
    return { ok: false, message };
  }

  function recordReceipt({
    show,
    operationType,
    status,
    requestedParameters,
    before,
    after,
    errorCode = null,
    subjectLabel,
    undoData,
    compensationForReceiptId = null,
  }) {
    show.receiptCounter += 1;
    const timestamp = new Date().toISOString();
    const slug = activeSeller.seller_id.replace(/^sel_/, "");
    const receipt = {
      receiptId: `receipt_${slug}_${String(show.receiptCounter).padStart(4, "0")}`,
      operationId: `op_${slug}_${String(show.receiptCounter).padStart(4, "0")}`,
      operationType,
      status,
      actorType: "synthetic_seller_ui",
      actorId: activeSeller.seller_id,
      sellerId: activeSeller.seller_id,
      showId: show.showId,
      requestedParameters,
      before,
      after,
      expectedVersions: before.versions,
      resultingVersions: after.versions,
      errorCode,
      subjectLabel,
      undoData,
      compensationForReceiptId,
      compensatedByReceiptId: null,
      executedAt: status === "applied" ? timestamp : null,
      recordedAt: timestamp,
    };
    show.receipts.push(receipt);
    return receipt;
  }

  function snapshotShow(show) {
    const listingProjection = {};
    Object.values(show.listings).forEach((listing) => {
      listingProjection[listing.listingId] = {
        status: listing.status,
        priceCents: listing.priceCents,
        listingVersion: listing.listingVersion,
        inventory: Object.fromEntries(
          Object.values(listing.inventory).map((inventory) => [
            inventory.variantId,
            {
              availableQuantity: inventory.availableQuantity,
              inventoryVersion: inventory.inventoryVersion,
            },
          ]),
        ),
      };
    });
    return {
      activeListingId: show.activeListingId,
      currentEpochId: show.currentEpochId,
      showSeq: show.sequence,
      versions: {
        showVersion: show.showVersion,
        listings: Object.fromEntries(
          Object.values(show.listings).map((listing) => [listing.listingId, listing.listingVersion]),
        ),
      },
      listings: listingProjection,
    };
  }

  function nextActionSequence(show) {
    show.sequence += 1;
    return show.sequence;
  }

  function openEpoch(show, listingId, startSeq) {
    show.epochCounter += 1;
    const slug = activeSeller.seller_id.replace(/^sel_/, "");
    const epoch = {
      epochId: `epoch_${slug}_${String(show.epochCounter).padStart(3, "0")}`,
      listingId,
      startSeq,
      endSeq: null,
      openedAt: new Date().toISOString(),
      closedAt: null,
    };
    show.epochs.push(epoch);
    show.currentEpochId = epoch.epochId;
  }

  function closeCurrentEpoch(show, endSeq) {
    const epoch = show.epochs.find((item) => item.epochId === show.currentEpochId);
    if (epoch) {
      epoch.endSeq = endSeq;
      epoch.closedAt = new Date().toISOString();
    }
    show.currentEpochId = null;
  }

  function performUndo() {
    const show = getShow();
    const receipt = show.receipts.find(
      (item) => item.receiptId === show.latestUndoableReceiptId,
    );
    if (!receipt || !receipt.undoData || receipt.compensatedByReceiptId) {
      showNotice("Undo unavailable", "The latest operation is no longer rollback-eligible.", { error: true });
      return;
    }

    const before = snapshotShow(show);
    const undo = receipt.undoData;
    let refusal = null;

    if (undo.kind === "push") {
      const listing = show.listings[undo.listingId];
      if (
        show.activeListingId !== undo.listingId ||
        show.showVersion !== undo.expectedShowVersion ||
        listing.listingVersion !== undo.expectedListingVersion
      ) {
        refusal = "Newer show state prevents this Push compensation.";
      } else {
        const sequence = nextActionSequence(show);
        closeCurrentEpoch(show, sequence);
        listing.status = "available";
        listing.listingVersion += 1;
        show.activeListingId = null;
        show.showVersion += 1;
      }
    }

    if (undo.kind === "swap") {
      const previous = show.listings[undo.previousListingId];
      const target = show.listings[undo.targetListingId];
      if (
        show.activeListingId !== undo.targetListingId ||
        show.showVersion !== undo.expectedShowVersion ||
        previous.listingVersion !== undo.expectedPreviousVersion ||
        target.listingVersion !== undo.expectedTargetVersion
      ) {
        refusal = "Newer listing state prevents this Swap compensation.";
      } else {
        const sequence = nextActionSequence(show);
        closeCurrentEpoch(show, sequence);
        target.status = "available";
        target.listingVersion += 1;
        previous.status = "active";
        previous.listingVersion += 1;
        show.activeListingId = previous.listingId;
        show.showVersion += 1;
        openEpoch(show, previous.listingId, sequence);
      }
    }

    if (undo.kind === "unlist") {
      const listing = show.listings[undo.listingId];
      if (
        show.activeListingId !== null ||
        show.showVersion !== undo.expectedShowVersion ||
        listing.listingVersion !== undo.expectedListingVersion ||
        listing.status !== "unlisted"
      ) {
        refusal = "Newer show state prevents this Unlist compensation.";
      } else {
        const sequence = nextActionSequence(show);
        listing.status = "active";
        listing.listingVersion += 1;
        show.activeListingId = listing.listingId;
        show.showVersion += 1;
        openEpoch(show, listing.listingId, sequence);
      }
    }

    if (undo.kind === "price_markdown") {
      const listing = show.listings[undo.listingId];
      if (
        listing.listingVersion !== undo.expectedListingVersion ||
        listing.priceCents !== undo.expectedPriceCents
      ) {
        refusal = "A newer listing version prevents this Markdown compensation.";
      } else {
        nextActionSequence(show);
        listing.priceCents = undo.previousPriceCents;
        listing.listingVersion += 1;
      }
    }

    if (undo.kind === "inventory_change") {
      const listing = show.listings[undo.listingId];
      const inventory = listing.inventory[undo.variantId];
      if (
        inventory.inventoryVersion !== undo.expectedInventoryVersion ||
        inventory.availableQuantity !== undo.expectedAvailableQuantity
      ) {
        refusal = "A newer inventory version prevents this Inventory Change compensation.";
      } else {
        nextActionSequence(show);
        inventory.availableQuantity = undo.previousAvailableQuantity;
        inventory.inventoryVersion += 1;
      }
    }

    if (refusal) {
      const rejected = recordReceipt({
        show,
        operationType: receipt.operationType,
        status: "rejected",
        requestedParameters: { compensationForReceiptId: receipt.receiptId },
        before,
        after: before,
        errorCode: "COMPENSATION_VERSION_CONFLICT",
        subjectLabel: receipt.subjectLabel,
        undoData: null,
        compensationForReceiptId: receipt.receiptId,
      });
      show.latestUndoableReceiptId = null;
      saveStore();
      renderAll();
      showNotice("Undo refused", `${refusal} Receipt ${rejected.receiptId} records the refusal.`, { error: true });
      return;
    }

    const after = snapshotShow(show);
    const compensation = recordReceipt({
      show,
      operationType: receipt.operationType,
      status: "applied",
      requestedParameters: { compensationForReceiptId: receipt.receiptId },
      before,
      after,
      subjectLabel: receipt.subjectLabel,
      undoData: null,
      compensationForReceiptId: receipt.receiptId,
    });
    receipt.compensatedByReceiptId = compensation.receiptId;
    show.latestUndoableReceiptId = null;
    selectedListingId = getDefaultSelectableListingId(show);
    saveStore();
    renderAll();
    showNotice(
      `${OPERATION_LABELS[receipt.operationType]} undone`,
      `A new compensating receipt restored the prior safe state without erasing history.`,
    );
  }

  function showNotice(title, message, { error = false } = {}) {
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
    dom.activeCue.innerHTML = `
      <div class="empty-cue">
        <div class="empty-stage-mark" aria-hidden="true"></div>
        <div class="empty-cue-copy">
          <p class="eyebrow">Fixture load failed</p>
          <h3>The show cannot start.</h3>
          <p>${escapeHtml(error.message)} Serve the repository root over HTTP so <code>/fixtures</code> is available.</p>
          <button class="button button--signal" type="button" onclick="window.location.reload()">Retry</button>
        </div>
      </div>
    `;
  }

  function dialogTitle(operationType) {
    return {
      push: "Push a listing",
      swap: "Swap the active pair",
      unlist: "Clear the active slot",
      price_markdown: "Mark down the price",
      inventory_change: "Set variant inventory",
    }[operationType];
  }

  function dialogDescription(operationType) {
    return {
      push: "Choose one available, in-stock listing. Push is valid only from an empty stage.",
      swap: "Replace the current cue with a different pair and open a new listing epoch.",
      unlist: "Explicitly unlist the pair on stage. Stock does not change.",
      price_markdown: "Lower the current listing price without crossing the seller-configured floor.",
      inventory_change: "Set one active variant to a nonnegative absolute quantity.",
    }[operationType];
  }

  function confirmLabel(operationType) {
    return {
      push: "Push listing",
      swap: "Swap listing",
      unlist: "Unlist pair",
      price_markdown: "Apply markdown",
      inventory_change: "Set inventory",
    }[operationType];
  }

  function operationPastTense(operationType) {
    return {
      push: "Pushed",
      swap: "Swapped",
      unlist: "Unlisted",
      price_markdown: "Marked down",
      inventory_change: "Inventory changed",
    }[operationType];
  }

  function productArt(product, hue) {
    return `
      <div class="product-art" style="--product-hue:${hue}" aria-hidden="true">
        <span class="product-art-orbit"></span>
        <span class="product-art-sole"></span>
        <span class="product-art-upper"></span>
        <span class="product-art-code">${escapeHtml(product.sku)}</span>
      </div>
    `;
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

  function formatClock(isoString) {
    return new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(isoString));
  }

  function shortEpoch(epochId) {
    if (!epochId) return "No epoch";
    const suffix = epochId.split("_").at(-1);
    return `E${suffix}`;
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
