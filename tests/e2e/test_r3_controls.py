from __future__ import annotations

import socket
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from typing import Iterator

import pytest
import uvicorn
from playwright.sync_api import Page, expect, sync_playwright

from sidestage.app import create_app
from ..integration.test_r3_safety import R3ScenarioRunner


FIXED_TIME = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def r3_live_server(tmp_path: Path) -> Iterator[str]:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(
                database_path=tmp_path / "sidestage-r3-browser.sqlite3",
                wall_clock=lambda: FIXED_TIME,
                model_runner=R3ScenarioRunner(),
            ),
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
        raise RuntimeError("M3B.3 browser test server did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.fixture()
def r3_browser_page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1200})
        page = context.new_page()
        yield page
        context.close()
        browser.close()


def test_auto_message_is_default_and_toggle_switches_to_manual_review(
    r3_live_server: str,
    r3_browser_page: Page,
) -> None:
    page = r3_browser_page
    browser_errors: list[str] = []
    page.on(
        "console",
        lambda message: browser_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: browser_errors.append(str(error)))

    page.goto(f"{r3_live_server}/app/")
    expect(page.locator("#r3-toggle-label")).to_have_text("Auto-message")
    expect(page.locator("#r3-warning")).to_be_visible()
    expect(page.locator("#r3-warning")).to_contain_text(
        "fully grounded answer sends automatically"
    )

    page.reload()
    expect(page.locator("#r3-toggle-label")).to_have_text("Auto-message")
    expect(page.locator("#r3-warning")).to_be_visible()

    page.locator("#empty-push").click()
    page.locator("#dialog-confirm").click()
    expect(page.locator("#operation-dialog")).to_be_hidden()
    page.locator("#chat-input").fill("How much is this pair?")
    page.locator("#chat-form button[type=submit]").click()
    expect(page.locator(".copilot-card")).to_have_count(0)
    auto_reply = page.locator('.chat-item[data-timeline-kind="seller"]')
    expect(auto_reply).to_have_count(1)
    expect(auto_reply.locator(".chat-reply-quote")).to_contain_text(
        "demo_tester · How much is this pair?"
    )

    page.locator("#r3-disable").click()
    expect(page.locator("#r3-toggle-label")).to_have_text("Manual review")
    expect(page.locator("#r3-warning")).to_be_hidden()

    page.locator("#chat-input").fill("What is the price right now?")
    page.locator("#chat-form button[type=submit]").click()
    expect(page.locator(".copilot-card")).to_have_count(1)
    current = page.locator(".copilot-card").first
    expect(current.locator(".copilot-state")).to_have_text("Ready for review")
    expect(current.locator('[data-copilot-action="accept"]')).to_be_visible()

    token = page.evaluate("sessionStorage.getItem('sidestage.m2.session')")
    projection = page.evaluate(
        """async ({token}) => {
          const response = await fetch(`/api/sessions/${encodeURIComponent(token)}/snapshot`);
          return response.json();
        }""",
        {"token": token},
    )
    assert projection["r3_capability"]["enabled"] is False
    assert projection["r3_capability"]["version"] == 2
    assert len(projection["outbound_replies"]) == 1
    assert projection["reply_receipts"][0]["mode"] == "r3"
    assert [item["kind"] for item in projection["chat_timeline"]] == [
        "buyer",
        "seller",
        "buyer",
    ]
    assert projection["chat_timeline"][1]["quote"] == {
        "event_id": projection["chat_timeline"][0]["event_id"],
        "customer_display_name": "demo_tester",
        "text": "How much is this pair?",
    }
    visible_text = page.locator("body").inner_text()
    assert "R2" not in visible_text
    assert "R3" not in visible_text
    assert not browser_errors
