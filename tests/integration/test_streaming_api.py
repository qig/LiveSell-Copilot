from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sidestage.app import create_app
from sidestage.streaming.hub import SseHub, StreamEvent


SELLER = "sel_velocity_kicks"
OTHER_SELLER = "sel_vault_consign"
AERO = "lst_velocity_aero_dash"
COURT = "lst_velocity_court_pulse"
AERO_8 = "var_velocity_aero_dash_8"
FIXED_TIME = datetime(2026, 8, 17, 12, 0, 0, 123000, tzinfo=timezone.utc)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        database_path=tmp_path / "sidestage.sqlite3",
        wall_clock=lambda: FIXED_TIME,
        prepared_seed=20260817,
    )
    with TestClient(app) as test_client:
        yield test_client


def create_session(client: TestClient, seller_id: str = SELLER) -> tuple[str, dict]:
    response = client.post("/api/demo/sessions", json={"seller_id": seller_id})
    assert response.status_code == 201
    payload = response.json()
    return payload["session_token"], payload["snapshot"]


def headers(key: str) -> dict[str, str]:
    return {"Idempotency-Key": key}


def push(client: TestClient, token: str, listing_id: str = AERO) -> dict:
    response = client.post(
        f"/api/sessions/{token}/actions/push",
        json={"target_listing_id": listing_id, "expected_show_version": 1},
        headers=headers(f"push-{listing_id}"),
    )
    assert response.status_code == 200
    return response.json()


def test_bootstrap_issues_tenant_bound_session_and_server_owned_empty_state(
    client: TestClient,
) -> None:
    sellers = client.get("/api/sellers")
    assert sellers.status_code == 200
    assert [seller["seller_id"] for seller in sellers.json()["sellers"]] == [
        "sel_rotation_kicks",
        "sel_vault_consign",
        "sel_velocity_kicks",
    ]

    token, snapshot = create_session(client)

    assert token.startswith("ses_")
    assert snapshot["seller"]["seller_id"] == SELLER
    assert snapshot["show"]["active_listing_id"] is None
    assert snapshot["show"]["version"] == 1
    assert snapshot["chat_events"] == []
    assert snapshot["receipts"] == []
    assert all("session_token" not in listing for listing in snapshot["listings"])


def test_action_authority_is_session_owned_and_cross_tenant_target_rejects(
    client: TestClient,
) -> None:
    token, _ = create_session(client)
    response = client.post(
        f"/api/sessions/{token}/actions/push",
        json={
            "target_listing_id": "lst_vault_heritage_high",
            "expected_show_version": 1,
            "seller_id": OTHER_SELLER,
        },
        headers=headers("untrusted-identity"),
    )
    assert response.status_code == 422

    scoped_response = client.post(
        f"/api/sessions/{token}/actions/push",
        json={
            "target_listing_id": "lst_vault_heritage_high",
            "expected_show_version": 1,
        },
        headers=headers("foreign-listing"),
    )
    assert scoped_response.status_code == 200
    assert scoped_response.json()["receipt"]["status"] == "rejected"
    assert scoped_response.json()["receipt"]["error_code"] == "listing_not_in_scope"
    assert scoped_response.json()["snapshot"]["show"]["active_listing_id"] is None


def test_custom_and_prepared_messages_use_one_metadata_free_ingestion_path(
    client: TestClient,
) -> None:
    token, _ = create_session(client)
    push(client, token)

    custom = client.post(
        f"/api/sessions/{token}/chat/custom",
        json={"raw_text": "Do you have size 9?"},
    )
    prepared = client.post(
        f"/api/sessions/{token}/chat/prepared",
        json={"count": 1},
    )

    assert custom.status_code == prepared.status_code == 201
    custom_event = custom.json()["events"][0]
    prepared_event = prepared.json()["events"][0]
    assert custom_event["input_origin"] == "custom"
    assert prepared_event["input_origin"] == "prepared"
    assert custom_event["source_listing_id"] == prepared_event["source_listing_id"] == AERO
    assert custom_event["source_epoch_id"] == prepared_event["source_epoch_id"]
    assert custom_event["show_seq"] < prepared_event["show_seq"]

    forbidden = {
        "pool_id",
        "fixture_class",
        "seller_scope",
        "weight",
        "emission_mode",
        "requirements",
    }
    assert forbidden.isdisjoint(custom_event)
    assert forbidden.isdisjoint(prepared_event)

    contaminated = client.post(
        f"/api/sessions/{token}/chat/custom",
        json={"raw_text": "hello", "fixture_class": "answerable_listing"},
    )
    assert contaminated.status_code == 422


def test_chat_is_rejected_before_an_active_listing_epoch_exists(
    client: TestClient,
) -> None:
    token, _ = create_session(client)

    custom = client.post(
        f"/api/sessions/{token}/chat/custom",
        json={"raw_text": "Do you have size 9?"},
    )
    prepared = client.post(
        f"/api/sessions/{token}/chat/prepared",
        json={"count": 1},
    )

    assert custom.status_code == prepared.status_code == 409
    assert custom.json()["detail"]["code"] == "active_slot_empty"
    assert prepared.json()["detail"]["code"] == "active_slot_empty"
    snapshot = client.get(f"/api/sessions/{token}/snapshot").json()
    assert snapshot["chat_events"] == []
    assert snapshot["copilot_questions"] == []
    assert client.app.state.model_runner.calls == ()


def test_equal_wall_clock_messages_bind_by_atomic_show_sequence_across_swap(
    client: TestClient,
) -> None:
    token, _ = create_session(client)
    push(client, token)
    before = client.post(
        f"/api/sessions/{token}/chat/custom",
        json={"raw_text": "How much is this pair?"},
    ).json()["events"][0]

    swap = client.post(
        f"/api/sessions/{token}/actions/swap",
        json={
            "target_listing_id": COURT,
            "expected_active_listing_id": AERO,
            "expected_show_version": 2,
        },
        headers=headers("swap-court"),
    )
    assert swap.json()["receipt"]["status"] == "applied"

    after = client.post(
        f"/api/sessions/{token}/chat/custom",
        json={"raw_text": "How much is the current pair?"},
    ).json()["events"][0]

    assert before["accepted_at"] == after["accepted_at"] == "2026-08-17T12:00:00.123Z"
    assert before["show_seq"] < after["show_seq"]
    assert before["source_listing_id"] == AERO
    assert after["source_listing_id"] == COURT
    assert before["source_epoch_id"] != after["source_epoch_id"]


def test_sse_replay_respects_offset_and_snapshot_survives_new_session(
    client: TestClient,
) -> None:
    token, _ = create_session(client)
    push(client, token)
    client.post(
        f"/api/sessions/{token}/chat/custom",
        json={"raw_text": "first"},
    )
    client.post(
        f"/api/sessions/{token}/chat/custom",
        json={"raw_text": "second"},
    )

    all_events = client.get(f"/api/sessions/{token}/events?after=0&once=true")
    assert all_events.status_code == 200
    assert all_events.headers["content-type"].startswith("text/event-stream")
    event_ids = [
        int(line.removeprefix("id: "))
        for line in all_events.text.splitlines()
        if line.startswith("id: ")
    ]
    assert event_ids == sorted(event_ids)
    assert len(event_ids) >= 3

    replay = client.get(
        f"/api/sessions/{token}/events?after={event_ids[-2]}&once=true"
    )
    replay_ids = [
        int(line.removeprefix("id: "))
        for line in replay.text.splitlines()
        if line.startswith("id: ")
    ]
    assert replay_ids == [event_ids[-1]]

    _, reconnected = create_session(client)
    assert reconnected["show"]["active_listing_id"] == AERO
    assert [event["raw_text"] for event in reconnected["chat_events"]] == [
        "first",
        "second",
    ]


def test_sse_listener_closes_the_commit_to_wait_race() -> None:
    event = StreamEvent(
        stream_offset=1,
        seller_id=SELLER,
        show_id="show_velocity_kicks",
        event_type="chat.accepted",
        payload={"event_id": "evt_race"},
        created_at="2026-08-17T12:00:00.123Z",
    )

    class StoreWithCommitBetweenReads:
        def __init__(self) -> None:
            self.calls = 0

        def after(self, _show_id: str, _offset: int) -> tuple[StreamEvent, ...]:
            self.calls += 1
            return () if self.calls == 1 else (event,)

    store = StoreWithCommitBetweenReads()
    hub = SseHub(store)  # type: ignore[arg-type]

    async def receive() -> str:
        stream = hub.stream("show_velocity_kicks", after=0)
        return await asyncio.wait_for(stream.__anext__(), timeout=0.1)

    message = asyncio.run(receive())

    assert "id: 1" in message
    assert store.calls >= 3


def test_chat_snapshots_and_sse_replay_are_tenant_isolated(client: TestClient) -> None:
    velocity_token, _ = create_session(client)
    vault_token, _ = create_session(client, OTHER_SELLER)
    push(client, velocity_token)
    push(client, vault_token, "lst_vault_heritage_high")

    client.post(
        f"/api/sessions/{velocity_token}/chat/custom",
        json={"raw_text": "velocity only"},
    )
    client.post(
        f"/api/sessions/{vault_token}/chat/custom",
        json={"raw_text": "vault only"},
    )

    velocity = client.get(f"/api/sessions/{velocity_token}/snapshot").json()
    vault = client.get(f"/api/sessions/{vault_token}/snapshot").json()
    velocity_stream = client.get(
        f"/api/sessions/{velocity_token}/events?after=0&once=true"
    ).text
    vault_stream = client.get(
        f"/api/sessions/{vault_token}/events?after=0&once=true"
    ).text

    assert [event["raw_text"] for event in velocity["chat_events"]] == ["velocity only"]
    assert [event["raw_text"] for event in vault["chat_events"]] == ["vault only"]
    assert "velocity only" in velocity_stream and "vault only" not in velocity_stream
    assert "vault only" in vault_stream and "velocity only" not in vault_stream


def test_all_five_http_actions_and_compensation_return_authoritative_snapshots(
    client: TestClient,
) -> None:
    token, _ = create_session(client)
    push_response = push(client, token)

    inventory = client.post(
        f"/api/sessions/{token}/actions/inventory-change",
        json={
            "listing_id": AERO,
            "variant_id": AERO_8,
            "new_available_quantity": 0,
            "expected_inventory_version": 1,
        },
        headers=headers("inventory-zero"),
    ).json()
    assert inventory["receipt"]["operation_type"] == "inventory_change"
    assert inventory["snapshot"]["show"]["active_listing_id"] == AERO

    undo_inventory = client.post(
        f"/api/sessions/{token}/receipts/{inventory['receipt']['receipt_id']}/compensate",
        headers=headers("undo-inventory"),
    ).json()
    assert undo_inventory["receipt"]["compensation_for_receipt_id"] == inventory["receipt"]["receipt_id"]

    swap = client.post(
        f"/api/sessions/{token}/actions/swap",
        json={
            "target_listing_id": COURT,
            "expected_active_listing_id": AERO,
            "expected_show_version": 2,
        },
        headers=headers("swap-http"),
    ).json()
    court = next(item for item in swap["snapshot"]["listings"] if item["listing_id"] == COURT)

    markdown = client.post(
        f"/api/sessions/{token}/actions/price-markdown",
        json={
            "listing_id": COURT,
            "new_price_cents": court["price_cents"] - 500,
            "expected_listing_version": court["version"],
        },
        headers=headers("markdown-http"),
    ).json()
    undo_markdown = client.post(
        f"/api/sessions/{token}/receipts/{markdown['receipt']['receipt_id']}/compensate",
        headers=headers("undo-markdown"),
    ).json()
    assert undo_markdown["receipt"]["status"] == "applied"

    unlist = client.post(
        f"/api/sessions/{token}/actions/unlist",
        json={
            "expected_active_listing_id": COURT,
            "expected_show_version": 3,
        },
        headers=headers("unlist-http"),
    ).json()
    assert unlist["snapshot"]["show"]["active_listing_id"] is None
    undo_unlist = client.post(
        f"/api/sessions/{token}/receipts/{unlist['receipt']['receipt_id']}/compensate",
        headers=headers("undo-unlist"),
    ).json()
    assert undo_unlist["snapshot"]["show"]["active_listing_id"] == COURT

    assert push_response["receipt"]["operation_type"] == "push"
    assert {item["operation_type"] for item in undo_unlist["snapshot"]["receipts"]} == {
        "push",
        "swap",
        "unlist",
        "price_markdown",
        "inventory_change",
    }


def test_only_chat_is_exposed_to_tester_and_no_excluded_commerce_routes_exist(
    client: TestClient,
) -> None:
    token, _ = create_session(client)
    for route in ("purchase", "bid", "cancel", "clear", "relist", "reset"):
        response = client.post(f"/api/sessions/{token}/{route}", json={})
        assert response.status_code == 404

    schema = client.get("/openapi.json").json()
    paths = "\n".join(schema["paths"])
    for excluded in ("purchase", "bid", "cancel", "clear", "relist"):
        assert excluded not in paths
    assert f"/api/sessions/{{session_token}}/demo/reset" in schema["paths"]


def test_debug_state_is_backend_owned_and_tenant_scoped(client: TestClient) -> None:
    token, _ = create_session(client)
    push(client, token)
    client.post(
        f"/api/sessions/{token}/chat/custom",
        json={"raw_text": "ledger message"},
    )

    debug = client.get(f"/api/debug/marketplace?session_token={token}")

    assert debug.status_code == 200
    payload = debug.json()
    assert payload["runtime_source"] == "m2_3_sqlite"
    assert payload["snapshot"]["seller"]["seller_id"] == SELLER
    assert len(payload["snapshot"]["chat_events"]) == 1
    assert len(payload["snapshot"]["epochs"]) == 1
    assert len(payload["snapshot"]["receipts"]) == 1
