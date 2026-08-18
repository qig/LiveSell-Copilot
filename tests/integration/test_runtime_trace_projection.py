from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from sidestage.app import create_app
from sidestage.trace.recorder import TraceStage
from .test_r3_safety import AERO, R3ScenarioRunner, SELLER


FIXED_TIME = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
BANNED_ARTIFACT_KEYS = {
    "api_key",
    "access_token",
    "password",
    "credential",
    "secret",
    "expected_bucket",
    "expected_route",
    "canonical_event_id",
}


def _all_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _all_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_keys(child)


def test_runtime_projection_is_persisted_complete_filterable_and_sanitized(
    tmp_path: Path,
) -> None:
    runner = R3ScenarioRunner()
    app = create_app(
        database_path=tmp_path / "runtime-traces.sqlite3",
        wall_clock=lambda: FIXED_TIME,
        model_runner=runner,
    )
    with TestClient(app) as client:
        session = client.post("/api/demo/sessions", json={"seller_id": SELLER})
        assert session.status_code == 201
        token = session.json()["session_token"]
        push = client.post(
            f"/api/sessions/{token}/actions/push",
            json={"target_listing_id": AERO, "expected_show_version": 1},
            headers={"Idempotency-Key": "push-for-runtime-trace"},
        )
        assert push.status_code == 200
        assert push.json()["receipt"]["status"] == "applied"

        answerable = client.post(
            f"/api/sessions/{token}/chat/custom",
            json={"raw_text": "How much is this pair?"},
        )
        noise = client.post(
            f"/api/sessions/{token}/chat/custom",
            json={"raw_text": "Hi"},
        )
        assert answerable.status_code == noise.status_code == 201

        response = client.get(
            "/api/debug/copilot",
            params={"session_token": token},
        )
        eligible_response = client.get(
            "/api/debug/copilot",
            params={"session_token": token, "actual_route": "eligible"},
        )
        invalid_response = client.get(
            "/api/debug/copilot",
            params={"session_token": token, "actual_route": "expected_route"},
        )

    assert response.status_code == 200
    projection = response.json()
    assert projection["schema_version"] == "sidestage.runtime_trace_projection.v1"
    assert projection["runtime_source"] == "process_customer_reply.sqlite"
    assert projection["trace_count"] == 2
    assert projection["route_counts"]["eligible"] == 1
    assert projection["route_counts"]["noise"] == 1
    assert invalid_response.status_code == 400

    eligible = next(trace for trace in projection["traces"] if trace["actual_route"] == "eligible")
    noise_trace = next(trace for trace in projection["traces"] if trace["actual_route"] == "noise")
    expected_stages = [stage.value for stage in TraceStage]
    assert [stage["stage"] for stage in eligible["stages"]] == expected_stages
    assert [stage["stage_number"] for stage in eligible["stages"]] == list(range(1, 9))
    assert eligible["complete"] is True
    assert all(stage["component_id"] for stage in eligible["stages"])
    assert all(stage["observation_id"].startswith("obs_") for stage in eligible["stages"])
    assert eligible["stages"][5]["component_id"].endswith("LivesellReplyAgent.run")
    assert eligible["stages"][5]["agent_run_id"]
    assert eligible["stages"][5]["profile_digest"].startswith("sha256:")
    assert eligible["expected_route"] is None

    artifact_kinds = {
        artifact["artifact_kind"]
        for stage in eligible["stages"]
        for artifact in stage["artifacts"]
    }
    assert artifact_kinds == {
        "routing_decision",
        "queue_admission",
        "analysis_result",
        "retrieval_result",
        "evidence_snapshot",
        "agent_run_result",
        "broker_decision",
        "publication",
            "end_to_end_latency",
            "runtime_selection",
        }
    artifact_payload = [
        artifact["payload"]
        for stage in eligible["stages"]
        for artifact in stage["artifacts"]
    ]
    assert not (set(_all_keys(artifact_payload)) & BANNED_ARTIFACT_KEYS)
    assert "OPENAI" not in json.dumps(artifact_payload)

    assert noise_trace["complete"] is True
    assert noise_trace["stages"][2]["status"] == "exited"
    assert [stage["status"] for stage in noise_trace["stages"][3:]] == ["skipped"] * 5
    eligible_projection = eligible_response.json()
    assert eligible_projection["actual_route_filter"] == "eligible"
    assert eligible_projection["trace_count"] == 1
    assert eligible_projection["traces"][0]["trace_id"] == eligible["trace_id"]

    model_inputs = [call.request.model_input.to_dict() for call in runner.calls]
    assert model_inputs
    assert not (set(_all_keys(model_inputs)) & BANNED_ARTIFACT_KEYS)
