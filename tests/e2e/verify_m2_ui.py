"""Browser verification for the static M2 marketplace UI slice.

Run from the repository root while it is served on port 8000:
    SIDESTAGE_BASE_URL=http://127.0.0.1:8000 uv run python tests/e2e/verify_m2_ui.py
"""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright
from sidestage.fixtures.loader import load_seller_fixture


BASE_URL = os.environ.get("SIDESTAGE_BASE_URL", "http://127.0.0.1:8000")
WORKSPACE_URL = f"{BASE_URL}/src/sidestage/web/static/"
SCREENSHOT_DIR = Path(os.environ.get("SIDESTAGE_SCREENSHOT_DIR", "/tmp/sidestage-m2-ui"))
SELLER_ORDER = ["sel_velocity_kicks", "sel_vault_consign", "sel_rotation_kicks"]


def format_money(cents: int) -> str:
    return f"${cents / 100:,.0f}"


def confirm_dialog(page: Page) -> None:
    expect(page.locator("#operation-dialog")).to_be_visible()
    page.locator("#dialog-confirm").click()


def assert_m2_1_data_projection(page: Page) -> str:
    seller_fixture = load_seller_fixture().document.model_dump(mode="json")
    sellers_by_id = {seller["seller_id"]: seller for seller in seller_fixture["sellers"]}

    page.goto(WORKSPACE_URL)
    page.wait_for_load_state("networkidle")
    page.evaluate("localStorage.clear()")
    page.reload()
    page.wait_for_load_state("networkidle")

    expect(page.locator("#seller-select option")).to_have_count(3)
    expect(page.locator("#seller-select option")).to_have_text(
        [
            f'{sellers_by_id[seller_id]["display_name"]} · '
            f'{sellers_by_id[seller_id]["persona"].replace("_", " ")}'
            for seller_id in SELLER_ORDER
        ]
    )
    expect(page.locator("#active-sku")).to_have_text("Stage clear")
    expect(page.get_by_text("Copilot off", exact=True)).to_be_visible()
    expect(page.locator("[data-operation]")).to_have_count(5)
    expect(page.locator('[data-operation="push"]')).to_be_enabled()
    expect(page.locator('[data-operation="swap"]')).to_be_disabled()

    for seller_id in SELLER_ORDER:
        seller = sellers_by_id[seller_id]
        page.locator("#seller-select").select_option(seller_id)
        cards = page.locator(".catalog-card")
        expect(cards).to_have_count(len(seller["products"]))
        for product_index, product in enumerate(seller["products"]):
            card = page.locator(f'[data-listing-id="{product["listing"]["listing_id"]}"]')
            expect(card.locator(".catalog-card-title")).to_have_text(product["listing"]["title"])
            expect(card.locator(".catalog-card-meta")).to_contain_text(product["sku"])
            expect(card.locator(".catalog-card-meta")).to_contain_text(
                format_money(product["listing"]["price_cents"])
            )
            expect(card.locator(".catalog-card-status")).to_have_text(
                "Selected" if product_index == 0 else "Available"
            )

    velocity = sellers_by_id["sel_velocity_kicks"]
    page.locator("#seller-select").select_option("sel_velocity_kicks")
    expected_product = velocity["products"][0]
    page.locator("#empty-push").click()
    confirm_dialog(page)
    expect(page.locator("#active-sku")).to_have_text(expected_product["sku"])
    expect(page.locator(".price-block strong")).to_have_text(
        format_money(expected_product["listing"]["price_cents"])
    )
    expect(page.locator(".policy-line p")).to_have_text(velocity["policies"]["price_floor"])
    expect(page.locator(".variant-pill")).to_have_text(
        [f'{variant["label"]} · {variant["available_quantity"]}' for variant in expected_product["variants"]]
    )
    original_sku = page.locator("#active-sku").inner_text()

    page.locator("#step-stream").click()
    expect(page.locator(".chat-item")).to_have_count(1)
    expect(page.locator(".chat-origin")).to_have_text("prepared")

    page.locator("#chat-input").fill("Is the pair on stage available in size 9?")
    page.locator("#chat-form button[type=submit]").click()
    expect(page.locator(".chat-item")).to_have_count(2)
    expect(page.locator(".chat-item").last.locator(".chat-origin")).to_have_text("custom")
    expect(page.locator(".chat-item").last.locator(".chat-text")).to_contain_text(
        "available in size 9"
    )

    page.locator("#seller-select").select_option("sel_vault_consign")
    expect(page.locator(".chat-item")).to_have_count(0)
    page.locator("#seller-select").select_option("sel_velocity_kicks")
    expect(page.locator(".chat-item")).to_have_count(2)

    page.screenshot(path=SCREENSHOT_DIR / "m2-1-data-projection-desktop.png", full_page=True)
    return original_sku


def run_seller_flow(page: Page) -> None:
    original_sku = assert_m2_1_data_projection(page)

    page.locator(".catalog-card:not(.is-active):not([disabled])").first.click()
    page.locator('[data-operation="swap"]').click()
    confirm_dialog(page)
    expect(page.locator("#active-sku")).not_to_have_text(original_sku)
    swapped_sku = page.locator("#active-sku").inner_text()

    price_before = page.locator(".price-block strong").inner_text()
    page.locator('[data-operation="price_markdown"]').click()
    confirm_dialog(page)
    expect(page.locator(".price-block strong")).not_to_have_text(price_before)
    page.locator("#undo-button").click()
    expect(page.locator(".price-block strong")).to_have_text(price_before)

    page.locator('[data-operation="inventory_change"]').click()
    page.locator("#inventory-quantity").fill("0")
    confirm_dialog(page)
    expect(page.locator("#active-sku")).to_have_text(swapped_sku)
    expect(page.locator(".live-label")).to_contain_text("On stage")
    page.locator("#undo-button").click()

    page.locator('[data-operation="unlist"]').click()
    confirm_dialog(page)
    expect(page.locator("#active-sku")).to_have_text("Stage clear")
    page.locator("#undo-button").click()
    expect(page.locator("#active-sku")).to_have_text(swapped_sku)

    active_price = page.locator(".price-block strong").inner_text()
    page.locator('[data-operation="price_markdown"]').click()
    page.locator("#markdown-price").fill("1")
    page.locator("#dialog-confirm").click()
    expect(page.locator("#dialog-error")).to_contain_text("seller floor")
    expect(page.locator(".price-block strong")).to_have_text(active_price)
    page.locator('.dialog-actions button[value="cancel"]').click()


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    browser_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("console", lambda message: browser_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: browser_errors.append(str(error)))

        run_seller_flow(page)
        page.locator("#notice-close").click()
        page.wait_for_timeout(500)
        page.screenshot(path=SCREENSHOT_DIR / "seller-workspace-desktop.png", full_page=True)

        page.goto(f"{WORKSPACE_URL}debug.html")
        page.wait_for_load_state("networkidle")
        expect(page.locator("#stat-event-count")).to_have_text("2")
        expect(page.locator("#stat-epoch-count")).not_to_have_text("0")
        expect(page.locator("#stat-receipt-count")).not_to_have_text("0")
        page.locator('[data-ledger-tab="epochs"]').click()
        expect(page.locator(".epoch-row").first).to_be_visible()
        page.locator('[data-ledger-tab="receipts"]').click()
        expect(page.locator(".receipt-row").first).to_be_visible()
        expect(page.locator(".receipt-status--rejected")).to_contain_text("rejected")
        page.screenshot(path=SCREENSHOT_DIR / "developer-ledger-desktop.png", full_page=True)

        mobile_page = context.new_page()
        mobile_page.set_viewport_size({"width": 390, "height": 844})
        mobile_page.goto(WORKSPACE_URL)
        mobile_page.wait_for_load_state("networkidle")
        expect(mobile_page.locator("#active-sku")).to_have_text(page.locator("#debug-active-sku").inner_text())
        assert mobile_page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        mobile_page.screenshot(path=SCREENSHOT_DIR / "seller-workspace-mobile.png", full_page=True)

        context.close()
        browser.close()

    if browser_errors:
        raise AssertionError(f"Browser console/page errors: {browser_errors}")

    print(f"M2 UI browser flow passed. Screenshots: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()
