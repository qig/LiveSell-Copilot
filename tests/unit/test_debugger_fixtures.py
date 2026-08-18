from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRACE_FIXTURE = ROOT / "fixtures" / "debugger" / "reply_trace_scenarios.json"
SELLER_FIXTURE = ROOT / "fixtures" / "sellers.json"

STAGE_KEYS = [
    "ingest",
    "normalize_deduplicate",
    "route_eligibility",
    "evidence_snapshot",
    "terminal_intent",
    "broker_guardrails",
    "terminal_outcome",
]
ALLOWED_STAGE_STATES = {"simulated", "blocked", "failed", "exited", "skipped"}
DESTINATION_KEYS = {"chat_response", "copilot_inbox", "reply_receipt"}
BANNED_PAYLOAD_KEYS = {"api_key", "access_token", "password", "credential", "secret"}


def load_trace_fixture() -> dict:
    return json.loads(TRACE_FIXTURE.read_text())


def iter_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from iter_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_keys(child)


def test_trace_fixture_is_explicitly_simulated_and_agent_disconnected() -> None:
    document = load_trace_fixture()

    assert document["schema_version"] == "sidestage.debugger_projection.v1"
    assert document["synthetic"] is True
    assert document["evidence_maturity"] == "Proposed"
    assert document["runtime_source"] == "presentation_fixture"
    assert "simulated flow" in document["disclosure"].lower()
    assert "no reply agent is connected" in document["disclosure"].lower()


def test_trace_fixture_uses_exact_seven_stage_contract() -> None:
    document = load_trace_fixture()

    assert [stage["key"] for stage in document["stage_catalog"]] == STAGE_KEYS
    assert [stage["number"] for stage in document["stage_catalog"]] == list(range(1, 8))

    for scenario in document["scenarios"]:
        for event in scenario["events"]:
            assert [stage["key"] for stage in event["stages"]] == STAGE_KEYS
            assert [stage["number"] for stage in event["stages"]] == list(range(1, 8))
            assert {stage["state"] for stage in event["stages"]} <= ALLOWED_STAGE_STATES


def test_trace_identities_and_stop_states_are_consistent() -> None:
    document = load_trace_fixture()
    scenario_ids: set[str] = set()
    event_ids: set[str] = set()
    trace_ids: set[str] = set()

    for scenario in document["scenarios"]:
        assert scenario["scenario_id"] not in scenario_ids
        scenario_ids.add(scenario["scenario_id"])
        assert scenario["mode"] in {"single", "bulk"}
        assert len(scenario["events"]) == (1 if scenario["mode"] == "single" else 4)

        for event in scenario["events"]:
            assert event["event_id"] not in event_ids
            assert event["trace_id"] not in trace_ids
            event_ids.add(event["event_id"])
            trace_ids.add(event["trace_id"])

            first_stop = event["first_stop"]
            assert first_stop is not None
            stopped_stage = event["stages"][first_stop["stage"] - 1]
            assert stopped_stage["state"] == first_stop["state"]
            assert stopped_stage["reason_code"] == first_stop["reason_code"]
            assert first_stop["state"] in {"blocked", "failed", "exited"}
            assert all(
                stage["state"] == "skipped"
                for stage in event["stages"][first_stop["stage"] :]
            )


def test_trace_context_resolves_to_approved_seller_data() -> None:
    document = load_trace_fixture()
    sellers = json.loads(SELLER_FIXTURE.read_text())["sellers"]
    seller_listings = {
        seller["seller_id"]: {
            product["listing"]["listing_id"]: {
                "variants": {variant["variant_id"] for variant in product["variants"]},
                "sku": product["sku"],
            }
            for product in seller["products"]
        }
        for seller in sellers
    }

    for scenario in document["scenarios"]:
        for event in scenario["events"]:
            context = event["source_context"]
            listing = seller_listings[context["seller_id"]][context["listing_id"]]
            assert context["sku"] == listing["sku"]
            if context["variant_id"] is not None:
                assert context["variant_id"] in listing["variants"]


def test_trace_destinations_are_complete_and_payloads_are_sanitized() -> None:
    document = load_trace_fixture()

    for scenario in document["scenarios"]:
        for event in scenario["events"]:
            assert {item["key"] for item in event["destinations"]} == DESTINATION_KEYS
            assert {item["status"] for item in event["destinations"]} == {"NOT_EMITTED"}
            assert not (set(iter_keys(event)) & BANNED_PAYLOAD_KEYS)


def test_evidence_ready_messages_stop_at_the_unconnected_agent() -> None:
    document = load_trace_fixture()

    for scenario in document["scenarios"]:
        for event in scenario["events"]:
            if event["stages"][3]["state"] != "simulated":
                continue
            assert event["first_stop"] == {
                "stage": 5,
                "state": "blocked",
                "reason_code": "AGENT_NOT_CONNECTED",
                "message": "The message reached the Agent boundary, but no reply agent is connected in this build.",
            }
            assert event["stages"][4]["reason_code"] == "AGENT_NOT_CONNECTED"
            assert [stage["state"] for stage in event["stages"][5:]] == [
                "skipped",
                "skipped",
            ]


def test_reply_fixture_never_uses_green_passed_state() -> None:
    document = load_trace_fixture()

    assert all(
        stage["state"] != "passed"
        for scenario in document["scenarios"]
        for event in scenario["events"]
        for stage in event["stages"]
    )
