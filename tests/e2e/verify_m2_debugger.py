"""Browser verification for the M2 reply-trace debugger projection.

Run from the repository root while it is served over HTTP:
    SIDESTAGE_BASE_URL=http://127.0.0.1:8000 uv run python tests/e2e/verify_m2_debugger.py
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


BASE_URL = os.environ.get("SIDESTAGE_BASE_URL", "http://127.0.0.1:8000")
DEBUGGER_URL = f"{BASE_URL}/src/sidestage/web/static/debug.html"
SCREENSHOT_DIR = Path(
    os.environ.get("SIDESTAGE_DEBUGGER_SCREENSHOT_DIR", "/tmp/sidestage-m2-debugger")
)
EXPECT_IMPORT_RUNTIME = os.environ.get("SIDESTAGE_EXPECT_IMPORT_RUNTIME") == "1"


def select_and_run(page: Page, scenario_id: str) -> None:
    page.locator("#trace-scenario").select_option(scenario_id)
    page.locator("#run-trace").click()


def verify_trace_flow(page: Page) -> None:
    page.goto(DEBUGGER_URL)
    page.wait_for_load_state("networkidle")

    expect(page.get_by_role("heading", name="Where did this message stop?")).to_be_visible()
    expect(page.get_by_role("heading", name="Catalog data import")).to_be_visible()
    expect(page.locator("#import-trace-status")).to_contain_text("Not checked")
    expect(page.locator("body")).not_to_contain_text("M2.1")
    expect(page.locator("body")).not_to_contain_text("M2.debugger")
    expect(page.locator("body")).not_to_contain_text("M3B")

    if EXPECT_IMPORT_RUNTIME:
        page.locator("#run-import-trace").click()
        expect(page.locator("#import-trace-runtime")).to_have_text("LIVE BACKEND CHECK")
        expect(page.locator("[data-import-stage]")).to_have_count(4)
        expect(page.locator("[data-import-stage].is-passed")).to_have_count(4)
        expect(page.locator("#import-trace-diagnosis")).to_contain_text("Accepted 3 sellers")
        expect(page.locator("#import-trace-counts")).to_contain_text("10 listings")
        expect(page.locator("#import-trace-counts")).to_contain_text("18 variants")
        first_trace_id = page.locator("#import-trace-id").inner_text()
        page.locator("#run-import-trace").click()
        expect(page.locator("#import-trace-id")).not_to_have_text(first_trace_id)
        page.locator("#import-trace-payload-disclosure").click()
        expect(page.locator("#import-trace-payload")).to_contain_text(
            '"runtime_source": "m2_1_typed_loader"'
        )
        page.locator("#import-trace-payload-disclosure").click()

    expect(page.get_by_text("Simulated flow · agent not connected", exact=True)).to_be_visible()
    expect(page.locator("[data-trace-stage]")).to_have_count(7)
    expect(page.locator("#trace-scenario option")).to_have_count(5)

    select_and_run(page, "single_agent_unavailable")
    expect(page.locator("#trace-diagnosis-title")).to_contain_text("Stopped at stage 5")
    expect(page.locator('[data-trace-stage="1"]')).to_have_class(
        re.compile(r"\bis-simulated\b")
    )
    expect(page.locator('[data-trace-stage="5"]')).to_have_class(
        re.compile(r"\bis-blocked\b")
    )
    expect(page.locator('[data-trace-stage="6"]')).to_have_class(
        re.compile(r"\bis-skipped\b")
    )
    page.locator('[data-trace-stage="5"]').click()
    expect(page.locator("#trace-stage-reason")).to_have_text("AGENT_NOT_CONNECTED")
    expect(page.locator("#trace-stage-summary")).to_contain_text("not connected")
    expect(page.locator("#trace-stage-rail .is-passed")).to_have_count(0)
    expect(page.locator('[data-destination="copilot_inbox"]')).to_contain_text("NOT_EMITTED")

    select_and_run(page, "single_missing_evidence")
    expect(page.locator("#trace-diagnosis-title")).to_contain_text("Stopped at stage 4")
    expect(page.locator('[data-trace-stage="4"]')).to_have_class(
        re.compile(r"\bis-blocked\b")
    )
    expect(page.locator('[data-trace-stage="5"]')).to_have_class(
        re.compile(r"\bis-skipped\b")
    )
    page.locator('[data-trace-stage="4"]').click()
    expect(page.locator("#trace-stage-reason")).to_have_text("MISSING_EVIDENCE")
    expect(page.locator("#trace-stage-output")).to_contain_text("missing_fields")

    select_and_run(page, "single_prompt_injection")
    expect(page.locator("#trace-diagnosis-title")).to_contain_text("Stopped at stage 5")
    expect(page.locator('[data-trace-stage="6"]')).to_have_class(
        re.compile(r"\bis-skipped\b")
    )
    expect(page.locator("#trace-stage-summary")).to_contain_text("not connected")

    select_and_run(page, "bulk_mixed")
    expect(page.locator("#trace-event option")).to_have_count(4)
    page.locator("#trace-event").select_option("evt_debug_bulk_004")
    expect(page.locator("#trace-diagnosis-title")).to_contain_text("Exited at stage 3")
    expect(page.locator("#trace-stage-reason")).to_have_text("NO_RESPONSE_NEEDED")
    expect(page.locator('[data-destination="chat_response"]')).to_contain_text(
        "NOT_EMITTED"
    )

    expect(page.locator("#stat-event-count")).to_be_visible()
    expect(page.locator('[data-ledger-tab="events"]')).to_be_visible()
    expect(page.locator('[data-ledger-tab="epochs"]')).to_be_visible()
    expect(page.locator('[data-ledger-tab="receipts"]')).to_be_visible()

    select_and_run(page, "single_agent_unavailable")
    expect(page.locator("#trace-diagnosis-title")).to_contain_text("Stopped at stage 5")


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )

        verify_trace_flow(page)
        page.evaluate("scrollTo(0, 0)")
        page.screenshot(path=SCREENSHOT_DIR / "reply-trace-desktop.png", full_page=True)

        narrow = context.new_page()
        narrow.set_viewport_size({"width": 430, "height": 932})
        narrow.goto(DEBUGGER_URL)
        narrow.wait_for_load_state("networkidle")
        if EXPECT_IMPORT_RUNTIME:
            narrow.locator("#run-import-trace").click()
            expect(narrow.locator("[data-import-stage].is-passed")).to_have_count(4)
        select_and_run(narrow, "single_agent_unavailable")
        expect(narrow.locator('[data-trace-stage="5"]')).to_have_class(
            re.compile(r"\bis-blocked\b")
        )
        assert narrow.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        narrow.evaluate("scrollTo(0, 0)")
        narrow.screenshot(path=SCREENSHOT_DIR / "reply-trace-narrow.png", full_page=True)

        context.close()
        browser.close()

    assert not console_errors, console_errors
    print(f"M2 debugger browser flow passed. Screenshots: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()
