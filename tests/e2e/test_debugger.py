from __future__ import annotations

import socket
import re
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from typing import Iterator

import pytest
import uvicorn
from playwright.sync_api import Page, expect, sync_playwright

from sidestage.app import create_app
from sidestage.copilot.runtime import RuntimeModelProfile, RuntimeModelRegistration
from ..integration.test_r3_safety import R3ScenarioRunner


FIXED_TIME = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def debugger_live_server(tmp_path: Path) -> Iterator[str]:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    runner = R3ScenarioRunner()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(
                database_path=tmp_path / "sidestage-debugger-browser.sqlite3",
                wall_clock=lambda: FIXED_TIME,
                workflow_strategy="two_call_draft",
                runtime_model_registrations=(
                    RuntimeModelRegistration(
                        RuntimeModelProfile(
                            profile_id="baseline",
                            display_name="Baseline scripted",
                            provider="scripted",
                            requested_model_id="scripted-baseline",
                            model_config_ref="debug-baseline-v1",
                            reasoning_effort="none",
                            request_timeout_s=5.0,
                            supported_workflows=("one_call_template", "two_call_draft"),
                        ),
                        runner,
                    ),
                    RuntimeModelRegistration(
                        RuntimeModelProfile(
                            profile_id="template-only",
                            display_name="Template-only scripted",
                            provider="scripted",
                            requested_model_id="scripted-template",
                            model_config_ref="debug-template-v1",
                            reasoning_effort="none",
                            request_timeout_s=5.0,
                            supported_workflows=("one_call_template",),
                        ),
                        runner,
                    ),
                ),
                default_model_profile_id="baseline",
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
        raise RuntimeError("M3B.4 debugger browser test server did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.fixture()
def debugger_page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1200})
        page = context.new_page()
        yield page
        context.close()
        browser.close()


def test_debugger_renders_and_filters_real_eight_stage_runtime_traces(
    debugger_live_server: str,
    debugger_page: Page,
    tmp_path: Path,
) -> None:
    page = debugger_page
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

    page.goto(f"{debugger_live_server}/app/")
    page.locator("#r3-toggle").click()
    expect(page.locator("#r3-toggle-label")).to_have_text("Manual review")
    page.locator("#empty-push").click()
    page.locator("#dialog-confirm").click()
    expect(page.locator("#operation-dialog")).to_be_hidden()

    page.locator("#chat-input").fill("How much is this pair?")
    page.locator("#chat-form button[type=submit]").click()
    expect(page.locator(".copilot-card")).to_have_count(1)
    page.locator("#chat-input").fill("Hi")
    page.locator("#chat-form button[type=submit]").click()
    expect(page.locator(".chat-item")).to_have_count(2)

    page.goto(f"{debugger_live_server}/app/debug.html")
    expect(page.get_by_text("Live backend projection", exact=True)).to_be_visible()
    expect(page.locator("#runtime-active-version")).to_have_text("v1")
    expect(page.locator("#runtime-active-workflow")).to_have_text("two_call_draft")
    expect(page.locator("#runtime-next-phase")).to_have_text("Next · steady")
    expect(page.locator("#runtime-metrics-table")).to_contain_text(
        "Two Call Draft"
    )
    expect(page.locator("#trace-status")).to_contain_text("2 persisted traces")
    expect(page.locator("#trace-scenario option")).to_have_count(6)
    expect(page.locator("[data-trace-stage]")).to_have_count(8)
    expect(page.locator("#trace-event-meta")).to_contain_text("eligible")
    expect(page.locator("#trace-event-meta")).to_contain_text("custom / no oracle")
    expect(page.locator("#trace-event-meta")).to_contain_text(
        "two_call_draft · baseline · v1 · cold"
    )
    assert page.locator(
        '#runtime-model option[value="template-only"]'
    ).evaluate("(option) => option.disabled") is True

    page.locator("#runtime-workflow").select_option("one_call_template")
    assert page.locator(
        '#runtime-model option[value="template-only"]'
    ).evaluate("(option) => option.disabled") is False
    page.locator("#runtime-model").select_option("template-only")
    expect(page.locator("#runtime-apply")).to_be_enabled()
    page.locator("#runtime-apply").click()
    expect(page.locator("#runtime-active-version")).to_have_text("v2")
    expect(page.locator("#runtime-active-workflow")).to_have_text(
        "one_call_template"
    )
    expect(page.locator("#runtime-next-phase")).to_have_text("Next · cold")

    page.locator('[data-trace-stage="6"]').click()
    expect(page.locator("#trace-stage-title")).to_have_text("Registered Reply Agent")
    expect(page.locator("#trace-stage-summary")).to_contain_text(
        "copilot.profile.LivesellReplyAgent.run"
    )
    expect(page.locator("#trace-stage-summary")).to_contain_text("obs_")
    expect(page.locator("#trace-stage-input")).to_contain_text('"agent_run_id": "')
    expect(page.locator("#trace-stage-output")).to_contain_text("agent_run_result")

    page.locator("#trace-scenario").select_option("noise")
    expect(page.locator("#trace-status")).to_contain_text("actual route noise")
    expect(page.locator("#trace-event-meta")).to_contain_text("noise")
    expect(page.locator("[data-trace-stage]")).to_have_count(8)
    expect(page.locator('[data-trace-stage="3"]')).to_have_class(
        re.compile(r"\bis-exited\b")
    )
    expect(page.locator('[data-trace-stage="4"]')).to_have_class(
        re.compile(r"\bis-skipped\b")
    )

    page.locator("#trace-scenario").select_option("eligible")
    expect(page.locator("#trace-status")).to_contain_text("actual route eligible")
    expect(page.locator('[data-trace-stage="6"]')).to_have_class(
        re.compile(r"\bis-completed\b")
    )

    screenshot = tmp_path / "m3b-4-runtime-debugger.png"
    page.screenshot(path=screenshot, full_page=True)
    assert screenshot.stat().st_size > 0

    page.goto(f"{debugger_live_server}/app/")
    expect(page.locator("#runtime-badge")).to_contain_text("One-call")
    expect(page.locator("#runtime-badge")).to_contain_text("Template-only scripted")
    expect(page.locator("#runtime-badge")).to_contain_text("v2")
    assert not browser_errors
    assert not any("reply_trace_scenarios.json" in url for url in requested_urls)
