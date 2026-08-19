from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Event
import time

from fastapi.testclient import TestClient

from sidestage.agent_core import (
    ModelResponse,
    ModelTerminalCall,
    ScriptedModelRunner,
)
from sidestage.app import create_app
from sidestage.copilot.runtime import RuntimeModelProfile, RuntimeModelRegistration


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
SELLER = "sel_velocity_kicks"
OTHER_SELLER = "sel_vault_consign"
AERO = "lst_velocity_aero_dash"
AERO_8 = "var_velocity_aero_dash_8"
VAULT = "lst_vault_heritage_high"


def _session(client: TestClient, seller_id: str = SELLER) -> tuple[str, dict]:
    response = client.post("/api/demo/sessions", json={"seller_id": seller_id})
    assert response.status_code == 201
    payload = response.json()
    return payload["session_token"], payload["snapshot"]


def _push(
    client: TestClient,
    token: str,
    listing_id: str,
    expected_show_version: int,
    key: str,
) -> dict:
    response = client.post(
        f"/api/sessions/{token}/actions/push",
        json={
            "target_listing_id": listing_id,
            "expected_show_version": expected_show_version,
        },
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200
    assert response.json()["receipt"]["status"] == "applied"
    return response.json()["snapshot"]


def _profile(
    profile_id: str,
    runner: ScriptedModelRunner,
) -> RuntimeModelRegistration:
    return RuntimeModelRegistration(
        RuntimeModelProfile(
            profile_id=profile_id,
            display_name=profile_id.title(),
            provider="scripted",
            requested_model_id=f"model-{profile_id}",
            model_config_ref=f"config-{profile_id}",
            reasoning_effort="none",
            request_timeout_s=5.0,
            supported_workflows=("one_call_template",),
        ),
        runner,
    )


def test_full_reset_restores_fixture_state_and_preserves_other_seller(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_path=tmp_path / "reset.sqlite3",
        wall_clock=lambda: NOW,
        prepared_seed=20260817,
    )
    with TestClient(app) as client:
        token, _ = _session(client)
        other_token, _ = _session(client, OTHER_SELLER)
        _push(client, other_token, VAULT, 1, "push-vault")
        _push(client, token, AERO, 1, "push-aero")

        first_prepared = client.post(
            f"/api/sessions/{token}/chat/prepared",
            json={"count": 1},
        )
        assert first_prepared.status_code == 201
        first_event = first_prepared.json()["events"][0]

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
        inventory = client.post(
            f"/api/sessions/{token}/actions/inventory-change",
            json={
                "listing_id": AERO,
                "variant_id": AERO_8,
                "new_available_quantity": 0,
                "expected_inventory_version": 1,
            },
            headers={"Idempotency-Key": "inventory-aero"},
        )
        assert inventory.json()["receipt"]["status"] == "applied"
        enabled = client.post(
            f"/api/sessions/{token}/copilot/r3",
            json={"enabled": True, "expected_version": 1},
        )
        assert enabled.status_code == 200

        before = client.get(f"/api/sessions/{token}/snapshot").json()
        before_listing = next(
            item for item in before["listings"] if item["listing_id"] == AERO
        )
        before_variant = next(
            item for item in before_listing["variants"] if item["variant_id"] == AERO_8
        )

        response = client.post(f"/api/sessions/{token}/demo/reset")

        assert response.status_code == 200
        reset = response.json()
        snapshot = reset["snapshot"]
        listing = next(item for item in snapshot["listings"] if item["listing_id"] == AERO)
        variant = next(item for item in listing["variants"] if item["variant_id"] == AERO_8)
        assert reset["status"] == "reset"
        assert snapshot["show"]["active_listing_id"] is None
        assert snapshot["chat_events"] == []
        assert snapshot["epochs"] == []
        assert snapshot["receipts"] == []
        assert snapshot["copilot_questions"] == []
        assert snapshot["outbound_replies"] == []
        assert snapshot["reply_receipts"] == []
        assert snapshot["r3_capability"]["enabled"] is True
        assert listing["price_cents"] == 16000
        assert listing["status"] == "available"
        assert variant["available_quantity"] == 4
        assert snapshot["show"]["version"] > before["show"]["version"]
        assert listing["version"] > before_listing["version"]
        assert variant["version"] > before_variant["version"]
        assert snapshot["r3_capability"]["version"] > before["r3_capability"]["version"]

        other = client.get(f"/api/sessions/{other_token}/snapshot").json()
        assert other["show"]["active_listing_id"] == VAULT

        stream = client.get(
            f"/api/sessions/{token}/events?after=0&once=true"
        ).text
        assert stream.count("event: demo.reset") == 1
        assert "event: chat.accepted" not in stream

        _push(
            client,
            token,
            AERO,
            snapshot["show"]["version"],
            "push-aero-after-reset",
        )
        repeated = client.post(
            f"/api/sessions/{token}/chat/prepared",
            json={"count": 1},
        )
        assert repeated.status_code == 201
        repeated_event = repeated.json()["events"][0]
        assert (
            repeated_event["customer_display_name"],
            repeated_event["raw_text"],
        ) == (
            first_event["customer_display_name"],
            first_event["raw_text"],
        )


def test_reset_restores_default_runtime_with_monotonic_selection_version(
    tmp_path: Path,
) -> None:
    first = ScriptedModelRunner(())
    second = ScriptedModelRunner(())
    app = create_app(
        database_path=tmp_path / "runtime-reset.sqlite3",
        wall_clock=lambda: NOW,
        workflow_strategy="one_call_template",
        runtime_model_registrations=(
            _profile("first", first),
            _profile("second", second),
        ),
        default_model_profile_id="first",
    )
    with TestClient(app) as client:
        token, _ = _session(client)
        changed = client.put(
            "/api/debug/runtime",
            params={"session_token": token},
            json={
                "workflow_id": "one_call_template",
                "model_profile_id": "second",
                "expected_selection_version": 1,
            },
        )
        assert changed.status_code == 200
        assert changed.json()["active_selection"]["selection_version"] == 2

        reset = client.post(f"/api/sessions/{token}/demo/reset")

        assert reset.status_code == 200
        active = reset.json()["snapshot"]["active_runtime_selection"]
        assert active["model_profile_id"] == "first"
        assert active["workflow_id"] == "one_call_template"
        assert active["selection_version"] == 3
        runtime = client.get(
            "/api/debug/runtime", params={"session_token": token}
        ).json()
        assert runtime["latency"]["groups"] == []
        assert runtime["next_sample_phase"] == "cold"


class BlockingTemplateRunner:
    def __init__(self) -> None:
        self.calls = []
        self.started = Event()
        self.release = Event()

    async def run(self, invocation):
        self.calls.append(invocation)
        self.started.set()
        await asyncio.to_thread(self.release.wait)
        evidence = invocation.request.model_input.to_dict()["evidence"]
        price = next(item for item in evidence if item["fact_type"] == "current_price")
        return ModelResponse(
            model_id="blocking-template",
            terminal_calls=(
                ModelTerminalCall(
                    tool_name="reply_current_price",
                    arguments_json=json.dumps(
                        {"evidence_ids": [price["evidence_id"]]}
                    ),
                ),
            ),
        )


def test_reset_waits_for_admitted_work_and_no_late_result_reappears(
    tmp_path: Path,
) -> None:
    runner = BlockingTemplateRunner()
    app = create_app(
        database_path=tmp_path / "reset-race.sqlite3",
        wall_clock=lambda: NOW,
        model_runner=runner,
        workflow_strategy="one_call_template",
    )
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as executor:
        token, _ = _session(client)
        _push(client, token, AERO, 1, "push-race")
        question = executor.submit(
            client.post,
            f"/api/sessions/{token}/chat/custom",
            json={"raw_text": "How much is this pair?"},
        )
        assert runner.started.wait(timeout=2)

        reset = executor.submit(
            client.post,
            f"/api/sessions/{token}/demo/reset",
        )
        try:
            time.sleep(0.05)
            assert not reset.done()
        finally:
            runner.release.set()
        assert question.result(timeout=2).status_code == 201
        reset_response = reset.result(timeout=2)
        assert reset_response.status_code == 200
        time.sleep(0.05)
        snapshot = client.get(f"/api/sessions/{token}/snapshot").json()
        assert snapshot["chat_events"] == []
        assert snapshot["copilot_questions"] == []
        assert snapshot["outbound_replies"] == []
        assert snapshot["reply_receipts"] == []
