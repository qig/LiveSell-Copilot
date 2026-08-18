"""Browser verification for the static M2 marketplace UI slice.

Run from the repository root while it is served on port 8000:
    python tests/e2e/verify_m2_ui.py
"""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


BASE_URL = os.environ.get("SIDESTAGE_BASE_URL", "http://127.0.0.1:8000")
WORKSPACE_URL = f"{BASE_URL}/src/sidestage/web/static/"
SCREENSHOT_DIR = Path(os.environ.get("SIDESTAGE_SCREENSHOT_DIR", "/tmp/sidestage-m2-ui"))


def confirm_dialog(page: Page) -> None:
    expect(page.locator("#operation-dialog")).to_be_visible()
    page.locator("#dialog-confirm").click()


def run_seller_flow(page: Page) -> None:
    page.goto(WORKSPACE_URL)
    page.wait_for_load_state("networkidle")
    page.evaluate("localStorage.clear()")
    page.reload()
    page.wait_for_load_state("networkidle")

    expect(page.locator("#seller-select option")).to_have_count(3)
    expect(page.locator("#active-sku")).to_have_text("Stage clear")
    expect(page.locator("[data-operation]")).to_have_count(5)
    expect(page.locator('[data-operation="push"]')).to_be_enabled()
    expect(page.locator('[data-operation="swap"]')).to_be_disabled()

    page.locator("#empty-push").click()
    confirm_dialog(page)
    expect(page.locator("#active-sku")).not_to_have_text("Stage clear")
    original_sku = page.locator("#active-sku").inner_text()

    page.locator("#seller-select").select_option("sel_vault_consign")
    expect(page.locator("#active-sku")).to_have_text("Stage clear")
    expect(page.locator(".catalog-card")).to_have_count(3)
    page.locator("#seller-select").select_option("sel_rotation_kicks")
    expect(page.locator("#active-sku")).to_have_text("Stage clear")
    expect(page.locator(".catalog-card")).to_have_count(4)
    page.locator("#seller-select").select_option("sel_velocity_kicks")
    expect(page.locator("#active-sku")).to_have_text(original_sku)

    page.locator("#chat-input").fill("Is the pair on stage available in size 9?")
    page.locator("#chat-form button[type=submit]").click()
    expect(page.locator(".chat-item")).to_have_count(1)
    expect(page.locator(".chat-text")).to_contain_text("available in size 9")

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
        expect(page.locator("#stat-event-count")).to_have_text("1")
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
        mobile_page.screenshot(path=SCREENSHOT_DIR / "seller-workspace-mobile.png", full_page=True)

        context.close()
        browser.close()

    if browser_errors:
        raise AssertionError(f"Browser console/page errors: {browser_errors}")

    print(f"M2 UI browser flow passed. Screenshots: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()
