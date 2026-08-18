"""End-to-end browser gate for the server-owned M2.3 marketplace emulator."""

from __future__ import annotations

import json
import socket
from contextlib import closing
from pathlib import Path
from threading import Thread
from typing import Iterator
from urllib.parse import urlparse

import pytest
import uvicorn
from playwright.sync_api import Page, expect, sync_playwright

from sidestage.app import create_app
from sidestage.fixtures.loader import load_seller_fixture


SELLER_ORDER = ["sel_velocity_kicks", "sel_vault_consign", "sel_rotation_kicks"]


@pytest.fixture()
def live_server(tmp_path: Path) -> Iterator[str]:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(database_path=tmp_path / "sidestage.sqlite3"),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        thread.join(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2)
        raise RuntimeError("M2.3 test server did not start")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.fixture()
def browser_page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        yield page
        context.close()
        browser.close()


def _confirm(page: Page) -> None:
    expect(page.locator("#operation-dialog")).to_be_visible()
    page.locator("#dialog-confirm").click()


def _session_token(page: Page) -> str:
    token = page.evaluate("sessionStorage.getItem('sidestage.m2.session')")
    assert isinstance(token, str) and token.startswith("ses_")
    return token


def _format_money(cents: int) -> str:
    return f"${cents / 100:,.0f}"


def test_non_ai_marketplace_flow_is_server_owned_and_reconnectable(
    live_server: str,
    browser_page: Page,
    tmp_path: Path,
) -> None:
    page = browser_page
    browser_errors: list[str] = []
    requested_urls: list[str] = []
    page.on(
        "console",
        lambda message: browser_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: browser_errors.append(str(error)))
    page.on("request", lambda request: requested_urls.append(request.url))

    page.goto(f"{live_server}/app/")
    seller_document = load_seller_fixture().document.model_dump(mode="json")
    sellers_by_id = {
        seller["seller_id"]: seller for seller in seller_document["sellers"]
    }
    expect(page.locator("#seller-select option")).to_have_count(3)
    expect(page.locator("#seller-select option")).to_have_text(
        [
            f'{sellers_by_id[seller_id]["display_name"]} · '
            f'{sellers_by_id[seller_id]["persona"].replace("_", " ")}'
            for seller_id in SELLER_ORDER
        ]
    )
    expect(page.get_by_text("Copilot off", exact=True)).to_be_visible()
    expect(page.locator("[data-operation]")).to_have_count(5)
    assert page.evaluate("localStorage.length") == 0

    # The authoritative adapter preserves the approved M2.1 projection for all sellers.
    for seller_id in SELLER_ORDER:
        seller = sellers_by_id[seller_id]
        page.locator("#seller-select").select_option(seller_id)
        expect(page.locator("#show-id")).to_have_text(
            f"show_{seller_id.removeprefix('sel_')}"
        )
        expect(page.locator("#active-sku")).to_have_text("Stage clear")
        expect(page.locator(".catalog-card")).to_have_count(len(seller["products"]))
        for product in seller["products"]:
            card = page.locator(
                f'[data-listing-id="{product["listing"]["listing_id"]}"]'
            )
            expect(card.locator(".catalog-card-title")).to_have_text(
                product["listing"]["title"]
            )
            expect(card.locator(".catalog-card-meta")).to_contain_text(product["sku"])
            expect(card.locator(".catalog-card-meta")).to_contain_text(
                _format_money(product["listing"]["price_cents"])
            )

    page.locator("#seller-select").select_option("sel_velocity_kicks")
    expect(page.locator('[data-operation="push"]')).to_be_enabled()
    expect(page.locator('[data-operation="swap"]')).to_be_disabled()

    # Push fills an empty active slot and opens the first listing epoch.
    page.locator("#empty-push").click()
    _confirm(page)
    expect(page.locator("#active-sku")).not_to_have_text("Stage clear")
    pushed_sku = page.locator("#active-sku").inner_text()
    expected_product = sellers_by_id["sel_velocity_kicks"]["products"][0]
    expect(page.locator(".price-block strong")).to_have_text(
        _format_money(expected_product["listing"]["price_cents"])
    )
    expect(page.locator(".variant-pill")).to_have_text(
        [
            f'{variant["label"]} · {variant["available_quantity"]}'
            for variant in expected_product["variants"]
        ]
    )
    expect(page.locator(".policy-line p")).to_have_text(
        sellers_by_id["sel_velocity_kicks"]["policies"]["price_floor"]
    )

    # Prepared and tester-entered messages share one accepted chat feed.
    page.locator("#toggle-stream").click()
    expect(page.locator("#stream-status")).to_have_text("Fixture playing")
    expect(page.locator(".chat-item")).to_have_count(1)
    page.locator("#toggle-stream").click()
    expect(page.locator("#stream-status")).to_have_text("Live sync")
    page.locator("#chat-input").fill("Is the pair on stage available in size 9?")
    page.locator("#chat-form button[type=submit]").click()
    expect(page.locator(".chat-item")).to_have_count(2)
    expect(page.locator(".chat-origin")).to_have_text(["prepared", "custom"])

    # Inventory Change is reversible and never clears the active listing.
    page.locator('[data-operation="inventory_change"]').click()
    page.locator("#inventory-quantity").fill("0")
    _confirm(page)
    expect(page.locator("#active-sku")).to_have_text(pushed_sku)
    expect(page.locator(".variant-pill").first).to_contain_text("· 0")
    page.locator("#undo-button").click()
    expect(page.locator(".variant-pill").first).not_to_contain_text("· 0")

    # Swap changes the active SKU atomically.
    page.locator(".catalog-card:not(.is-active):not([disabled])").first.click()
    page.locator('[data-operation="swap"]').click()
    _confirm(page)
    expect(page.locator("#active-sku")).not_to_have_text(pushed_sku)
    swapped_sku = page.locator("#active-sku").inner_text()

    # Price Markdown is floor checked and the latest safe change is undoable.
    original_price = page.locator(".price-block strong").inner_text()
    page.locator('[data-operation="price_markdown"]').click()
    _confirm(page)
    expect(page.locator(".price-block strong")).not_to_have_text(original_price)
    page.locator("#undo-button").click()
    expect(page.locator(".price-block strong")).to_have_text(original_price)

    # A rejected markdown remains unchanged and gives the seller a concrete reason.
    page.locator('[data-operation="price_markdown"]').click()
    page.locator("#markdown-price").fill("1")
    page.locator("#dialog-confirm").click()
    expect(page.locator("#dialog-error")).to_contain_text("seller floor")
    expect(page.locator(".price-block strong")).to_have_text(original_price)
    page.locator('.dialog-actions button[value="cancel"]').click()

    # Unlist clears the slot; Undo restores the prior listing through compensation.
    page.locator('[data-operation="unlist"]').click()
    _confirm(page)
    expect(page.locator("#active-sku")).to_have_text("Stage clear")
    page.locator("#undo-button").click()
    expect(page.locator("#active-sku")).to_have_text(swapped_sku)

    # Browser reload reconstructs from SQLite, not a browser copy of the marketplace.
    token = _session_token(page)
    page.reload()
    expect(page.locator("#active-sku")).to_have_text(swapped_sku)
    expect(page.locator(".chat-item")).to_have_count(2)
    assert _session_token(page) == token
    assert page.evaluate("localStorage.length") == 0

    # A second page using the same opaque session converges via snapshot + SSE.
    peer = page.context.new_page()
    peer.add_init_script(
        f"sessionStorage.setItem('sidestage.m2.session', {json.dumps(token)})",
    )
    peer.goto(f"{live_server}/app/")
    expect(peer.locator("#active-sku")).to_have_text(swapped_sku)
    page.locator("#chat-input").fill("Does this colorway fit true to size?")
    page.locator("#chat-form button[type=submit]").click()
    expect(peer.locator(".chat-item")).to_have_count(3)

    workspace_screenshot = tmp_path / "m2-3-marketplace-workspace.png"
    page.screenshot(path=workspace_screenshot, full_page=True)
    assert workspace_screenshot.stat().st_size > 0

    mobile = page.context.new_page()
    mobile.on(
        "console",
        lambda message: browser_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    mobile.on("pageerror", lambda error: browser_errors.append(str(error)))
    mobile.add_init_script(
        f"sessionStorage.setItem('sidestage.m2.session', {json.dumps(token)})",
    )
    mobile.set_viewport_size({"width": 390, "height": 844})
    mobile.goto(f"{live_server}/app/")
    expect(mobile.locator("#active-sku")).to_have_text(swapped_sku)
    assert mobile.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    mobile_screenshot = tmp_path / "m2-3-marketplace-mobile.png"
    mobile.screenshot(path=mobile_screenshot, full_page=True)
    assert mobile_screenshot.stat().st_size > 0

    # The debugger reads the backend ledger and exposes the full receipt history.
    page.goto(f"{live_server}/app/debug.html")
    expect(page.locator("#stat-event-count")).to_have_text("3")
    expect(page.locator("#stat-epoch-count")).not_to_have_text("0")
    expect(page.locator("#stat-receipt-count")).not_to_have_text("0")
    page.locator('[data-ledger-tab="receipts"]').click()
    expect(page.locator(".receipt-row").first).to_be_visible()
    expect(page.locator(".receipt-row")).to_have_count(9)

    screenshot = tmp_path / "m2-3-marketplace-ledger.png"
    page.screenshot(path=screenshot, full_page=True)
    assert screenshot.stat().st_size > 0

    assert not browser_errors
    assert all(url.startswith(live_server) for url in requested_urls)
    api_paths = [urlparse(url).path for url in requested_urls if urlparse(url).path.startswith("/api/")]
    assert not any(
        path.startswith(("/api/copilot", "/api/reply", "/api/provider", "/api/model"))
        for path in api_paths
    )
