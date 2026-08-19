from __future__ import annotations

import json
import socket
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from typing import Iterator

import pytest
import uvicorn
from fastapi.testclient import TestClient
from playwright.sync_api import Page, expect, sync_playwright

from sidestage.agent_core import ModelResponse, ModelTerminalCall
from sidestage.app import create_app


SELLER = "sel_velocity_kicks"
AERO = "lst_velocity_aero_dash"
COURT = "lst_velocity_court_pulse"
FIXED_TIME = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


class AdaptiveReplyRunner:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, invocation):
        self.calls.append(invocation)
        tool_names = [tool.name for tool in invocation.request.terminal_tools]
        if tool_names == ["request_evidence"]:
            return ModelResponse(
                model_id="scripted-analysis",
                terminal_calls=(
                    ModelTerminalCall(
                        tool_name="request_evidence",
                        arguments_json=json.dumps(
                            {
                                "intent": "answerable",
                                "answer_category": "price",
                                "product_mentions": ["Aero Dash"],
                                "required_fact_types": ["current_price"],
                                "query_terms": [],
                            }
                        ),
                    ),
                ),
            )
        model_input = invocation.request.model_input.to_dict()
        price = next(
            evidence
            for evidence in model_input["evidence"]
            if evidence["fact_type"] == "current_price"
        )
        return ModelResponse(
            model_id="scripted-reply",
            terminal_calls=(
                ModelTerminalCall(
                    tool_name="request_reply_send",
                    arguments_json=json.dumps(
                        {
                            "reply_text": "It is $160.",
                            "answer_category": "price",
                            "claims": [
                                {
                                    "reply_span": "It is $160.",
                                    "evidence_ids": [price["evidence_id"]],
                                }
                            ],
                        }
                    ),
                ),
            ),
        )


@pytest.fixture()
def app_client(tmp_path: Path):
    runner = AdaptiveReplyRunner()
    app = create_app(
        database_path=tmp_path / "sidestage.sqlite3",
        wall_clock=lambda: FIXED_TIME,
        prepared_seed=20260817,
        model_runner=runner,
        model_config_ref="scripted-livesell-v1",
    )
    with TestClient(app) as client:
        yield client, runner


@pytest.fixture()
def r2_live_server(tmp_path: Path) -> Iterator[str]:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(
                database_path=tmp_path / "sidestage-browser.sqlite3",
                wall_clock=lambda: FIXED_TIME,
                model_runner=AdaptiveReplyRunner(),
                model_config_ref="scripted-livesell-v1",
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
        raise RuntimeError("M3B.2 browser test server did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.fixture()
def r2_browser_page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        yield page
        context.close()
        browser.close()


def _session(client: TestClient) -> tuple[str, dict]:
    response = client.post("/api/demo/sessions", json={"seller_id": SELLER})
    assert response.status_code == 201
    token = response.json()["session_token"]
    snapshot = response.json()["snapshot"]
    manual = client.post(
        f"/api/sessions/{token}/copilot/r3",
        json={
            "enabled": False,
            "expected_version": snapshot["r3_capability"]["version"],
        },
    )
    assert manual.status_code == 200
    return token, manual.json()["snapshot"]


def _push(client: TestClient, token: str) -> None:
    response = client.post(
        f"/api/sessions/{token}/actions/push",
        json={"target_listing_id": AERO, "expected_show_version": 1},
        headers={"Idempotency-Key": "push-aero"},
    )
    assert response.json()["receipt"]["status"] == "applied"


def _ask_price(client: TestClient, token: str) -> dict:
    response = client.post(
        f"/api/sessions/{token}/chat/custom",
        json={"raw_text": "How much is this pair?"},
    )
    assert response.status_code == 201
    return response.json()


def test_fresh_r2_suggestion_needs_one_seller_decision_and_one_atomic_receipt(
    app_client,
) -> None:
    client, runner = app_client
    token, _ = _session(client)
    _push(client, token)

    accepted = _ask_price(client, token)

    assert accepted["pipeline_results"][0]["status"] == "completed"
    assert len(runner.calls) == 2
    snapshot = accepted["snapshot"]
    assert len(snapshot["copilot_questions"]) == 1
    card = snapshot["copilot_questions"][0]
    assert card["state"] == "awaiting_review"
    assert card["suggestion"]["reply_text"] == "It is $160."
    assert snapshot["outbound_replies"] == []
    with client.app.state.database.read() as connection:
        transitions = connection.execute(
            """SELECT from_state, to_state FROM copilot_question_transitions
               WHERE question_id = ? ORDER BY transition_number""",
            (card["question_id"],),
        ).fetchall()
    assert [(row["from_state"], row["to_state"]) for row in transitions] == [
        (None, "queued"),
        ("queued", "ai_working"),
        ("ai_working", "awaiting_review"),
    ]

    sent = client.post(
        f"/api/sessions/{token}/copilot/questions/{card['question_id']}/decision",
        json={"action": "accept"},
        headers={"Idempotency-Key": "accept-price"},
    )
    assert sent.status_code == 200
    payload = sent.json()
    assert payload["status"] == "sent"
    assert payload["reply"]["reply_text"] == "It is $160."
    assert payload["receipt"]["question_id"] == card["question_id"]
    assert payload["snapshot"]["copilot_questions"][0]["state"] == "answered_by_seller"
    assert payload["snapshot"]["chat_timeline"] == [
        {
            "timeline_id": f"buyer:{card['event_id']}",
            "stream_offset": payload["snapshot"]["chat_timeline"][0]["stream_offset"],
            "kind": "buyer",
            "occurred_at": card["asked_at"],
            "event_id": card["event_id"],
            "show_seq": 2,
            "customer_display_name": "demo_tester",
            "text": "How much is this pair?",
            "input_origin": "custom",
        },
        {
            "timeline_id": f"seller:{payload['reply']['reply_id']}",
            "stream_offset": payload["snapshot"]["chat_timeline"][1]["stream_offset"],
            "kind": "seller",
            "occurred_at": payload["reply"]["created_at"],
            "reply_id": payload["reply"]["reply_id"],
            "question_id": card["question_id"],
            "mode": "r2",
            "text": "It is $160.",
            "quote": {
                "event_id": card["event_id"],
                "customer_display_name": "demo_tester",
                "text": "How much is this pair?",
            },
        },
    ]
    assert (
        payload["snapshot"]["chat_timeline"][0]["stream_offset"]
        < payload["snapshot"]["chat_timeline"][1]["stream_offset"]
    )

    duplicate = client.post(
        f"/api/sessions/{token}/copilot/questions/{card['question_id']}/decision",
        json={"action": "accept"},
        headers={"Idempotency-Key": "accept-price"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["idempotent_replay"] is True
    assert duplicate.json()["receipt"]["receipt_id"] == payload["receipt"]["receipt_id"]
    assert len(duplicate.json()["snapshot"]["outbound_replies"]) == 1
    assert len(duplicate.json()["snapshot"]["reply_receipts"]) == 1

    stream = client.get(f"/api/sessions/{token}/events?after=0&once=true").text
    assert "chat.reply" in stream
    assert "copilot.question.changed" in stream


def test_unchanged_stale_suggestion_returns_for_another_decision(app_client) -> None:
    client, _runner = app_client
    token, _ = _session(client)
    _push(client, token)
    card = _ask_price(client, token)["snapshot"]["copilot_questions"][0]
    markdown = client.post(
        f"/api/sessions/{token}/actions/price-markdown",
        json={
            "listing_id": AERO,
            "new_price_cents": 15000,
            "expected_listing_version": 1,
        },
        headers={"Idempotency-Key": "markdown-aero"},
    )
    assert markdown.json()["receipt"]["status"] == "applied"

    response = client.post(
        f"/api/sessions/{token}/copilot/questions/{card['question_id']}/decision",
        json={"action": "accept"},
        headers={"Idempotency-Key": "accept-stale"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "stale"
    assert response.json()["reason_code"] == "stale_evidence"
    assert response.json()["snapshot"]["outbound_replies"] == []
    assert response.json()["snapshot"]["copilot_questions"][0]["state"] == "awaiting_review"


def test_seller_edit_is_sent_byte_for_byte_with_nonblocking_warnings(app_client) -> None:
    client, _runner = app_client
    token, _ = _session(client)
    _push(client, token)
    card = _ask_price(client, token)["snapshot"]["copilot_questions"][0]
    seller_text = "My call: $999, cheapest anywhere."

    response = client.post(
        f"/api/sessions/{token}/copilot/questions/{card['question_id']}/decision",
        json={"action": "reply", "reply_text": seller_text},
        headers={"Idempotency-Key": "seller-edit"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert response.json()["reply"]["reply_text"] == seller_text
    assert set(response.json()["warnings"]) >= {"price_conflict", "tone_conflict"}
    assert response.json()["receipt"]["guardrail_verdict"] == "seller_override_warning_only"


def test_previous_listing_can_receive_manual_reply_without_ai_draft(app_client) -> None:
    client, _runner = app_client
    token, _ = _session(client)
    _push(client, token)
    app = client.app
    session = app.state.sessions.require(token)
    event = app.state.ingestor.ingest(
        session.authority,
        customer_display_name="tester",
        raw_text="Still have the Aero Dash?",
        input_origin="custom",
    )
    swap = client.post(
        f"/api/sessions/{token}/actions/swap",
        json={
            "target_listing_id": COURT,
            "expected_active_listing_id": AERO,
            "expected_show_version": 2,
        },
        headers={"Idempotency-Key": "swap-court"},
    )
    assert swap.json()["receipt"]["status"] == "applied"
    decision = app.state.copilot_router.route(event)
    assert decision.reason_code == "previous_listing"

    response = client.post(
        f"/api/sessions/{token}/copilot/questions/{decision.question_id}/decision",
        json={"action": "reply", "reply_text": "That was the previous pair."},
        headers={"Idempotency-Key": "manual-previous"},
    )

    assert response.status_code == 200
    assert response.json()["reply"]["reply_text"] == "That was the previous pair."
    card = next(
        item
        for item in response.json()["snapshot"]["copilot_questions"]
        if item["question_id"] == decision.question_id
    )
    assert card["previous_sku"] == "VK-AD-RC-001"
    assert card["suggestion"] is None


def test_reply_receipt_failure_rolls_back_reply_and_terminal_state(tmp_path: Path) -> None:
    runner = AdaptiveReplyRunner()

    def fail_before_receipt() -> None:
        raise RuntimeError("injected receipt persistence failure")

    app = create_app(
        database_path=tmp_path / "sidestage.sqlite3",
        wall_clock=lambda: FIXED_TIME,
        model_runner=runner,
        model_config_ref="scripted-livesell-v1",
        before_reply_receipt_insert=fail_before_receipt,
    )
    with TestClient(app) as client:
        token, _ = _session(client)
        _push(client, token)
        card = _ask_price(client, token)["snapshot"]["copilot_questions"][0]
        response = client.post(
            f"/api/sessions/{token}/copilot/questions/{card['question_id']}/decision",
            json={"action": "accept"},
            headers={"Idempotency-Key": "fail-receipt"},
        )

        assert response.status_code == 500
        snapshot = client.get(f"/api/sessions/{token}/snapshot").json()
        assert snapshot["outbound_replies"] == []
        assert snapshot["reply_receipts"] == []
        assert snapshot["copilot_questions"][0]["state"] == "awaiting_review"


def test_typed_analysis_failure_becomes_needs_seller_without_a_partial_draft(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_path=tmp_path / "sidestage-failure.sqlite3",
        wall_clock=lambda: FIXED_TIME,
    )
    with TestClient(app) as client:
        token, _ = _session(client)
        _push(client, token)
        response = _ask_price(client, token)

    result = response["pipeline_results"][0]
    card = response["snapshot"]["copilot_questions"][0]
    assert result["status"] == "failed"
    assert result["publication"] == {
        "question_id": card["question_id"],
        "state": "needs_seller",
        "reason_code": result["reason_code"],
    }
    assert card["state"] == "needs_seller"
    assert card["suggestion"] is None


def test_browser_inbox_requires_one_visible_seller_decision(
    r2_live_server: str,
    r2_browser_page: Page,
) -> None:
    page = r2_browser_page
    browser_errors: list[str] = []
    page.on(
        "console",
        lambda message: browser_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: browser_errors.append(str(error)))

    page.goto(f"{r2_live_server}/app/")
    page.locator("#r3-toggle").click()
    expect(page.get_by_text("Manual review", exact=True)).to_be_visible()
    page.locator("#empty-push").click()
    expect(page.locator("#operation-dialog")).to_be_visible()
    page.locator("#dialog-confirm").click()
    expect(page.locator("#operation-dialog")).to_be_hidden()
    expect(page.locator("#active-sku")).to_have_text("VK-AD-RC-001")

    page.locator("#chat-input").fill("How much is this pair?")
    page.locator("#chat-form button[type=submit]").click()
    expect(page.locator("#event-count")).to_have_text("01")

    card = page.locator(".copilot-card").first
    expect(card).to_be_visible()
    expect(card.locator(".copilot-question")).to_have_text("How much is this pair?")
    expect(card.locator(".copilot-state")).to_have_text("Ready for review")
    expect(card.locator("[data-copilot-reply]")).to_have_value("It is $160.")
    expect(card.locator('[data-copilot-action="accept"]')).to_be_visible()
    expect(page.locator(".copilot-card")).to_have_count(1)

    card.locator('[data-copilot-action="accept"]').click()
    expect(page.locator(".copilot-card")).to_have_count(0)
    seller_reply = page.locator('.chat-item[data-timeline-kind="seller"]')
    expect(seller_reply).to_have_count(1)
    expect(seller_reply.locator(".chat-reply-quote")).to_contain_text(
        "demo_tester · How much is this pair?"
    )
    expect(seller_reply.locator(".chat-text")).to_have_text("It is $160.")

    token = page.evaluate("sessionStorage.getItem('sidestage.m2.session')")
    projection = page.evaluate(
        """async ({token}) => {
          const response = await fetch(`/api/sessions/${encodeURIComponent(token)}/snapshot`);
          return response.json();
        }""",
        {"token": token},
    )
    assert len(projection["outbound_replies"]) == 1
    assert len(projection["reply_receipts"]) == 1
    assert projection["outbound_replies"][0]["reply_text"] == "It is $160."
    assert [item["kind"] for item in projection["chat_timeline"]] == [
        "buyer",
        "seller",
    ]
    assert not browser_errors
