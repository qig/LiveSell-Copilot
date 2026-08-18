from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sidestage.app import create_live_app


_MODEL_ENV = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "SIDESTAGE_MODEL_API_KEY",
    "SIDESTAGE_MODEL_PROVIDER",
    "SIDESTAGE_MODEL_ID",
    "SIDESTAGE_MODEL_BASE_URL",
    "SIDESTAGE_MODEL_REASONING_EFFORT",
    "SIDESTAGE_WORKFLOW_STRATEGY",
)


def _clear_model_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _MODEL_ENV:
        monkeypatch.delenv(name, raising=False)


def test_live_app_factory_fails_before_runtime_initialization_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_model_environment(monkeypatch)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        create_live_app(database_path=tmp_path / "must-not-exist.sqlite3")

    assert not (tmp_path / "must-not-exist.sqlite3").exists()


def test_live_app_factory_builds_one_sanitized_strict_runner_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_model_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "credential-must-not-be-recorded")
    monkeypatch.setenv("SIDESTAGE_MODEL_ID", "gpt-5.6-luna")
    monkeypatch.setenv("SIDESTAGE_MODEL_BASE_URL", "https://api.openai.com/v1/")
    monkeypatch.setenv("SIDESTAGE_MODEL_REASONING_EFFORT", "none")

    application = create_live_app(database_path=tmp_path / "live.sqlite3")
    runner = application.state.analyzer.model_runner
    config = runner.config

    assert application.state.model_runtime == {
        "mode": "live",
        "provider": "openai",
        "workflow_strategy": "two_call_draft",
        "model_id": "gpt-5.6-luna",
        "model_config_ref": "sidestage-livesell-live-v1",
        "base_url": "https://api.openai.com/v1",
        "reasoning_effort": "none",
        "request_timeout_s": 5.0,
        "strict_function_tools": True,
        "openrouter_routing": None,
    }
    assert config.model_id == "gpt-5.6-luna"
    assert config.strict_function_tools is True
    assert config.reasoning_effort == "none"
    assert "credential-must-not-be-recorded" not in repr(config)
    assert "credential-must-not-be-recorded" not in repr(application.state.model_runtime)

    with TestClient(application) as client:
        response = client.get("/api/sellers")
        assert response.status_code == 200
        assert len(response.json()["sellers"]) == 3


def test_live_app_factory_prefers_scoped_key_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_model_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-credential")
    monkeypatch.setenv("SIDESTAGE_MODEL_API_KEY", "scoped-credential")
    monkeypatch.setenv("SIDESTAGE_MODEL_ID", "gpt-5.6-luna")

    application = create_live_app(database_path=tmp_path / "scoped.sqlite3")
    config = application.state.analyzer.model_runner.config

    assert config.api_key.get_secret_value() == "scoped-credential"
    assert "scoped-credential" not in repr(config)
    assert "scoped-credential" not in repr(application.state.model_runtime)


def test_live_app_factory_uses_only_matching_openrouter_key_and_one_call_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_model_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-provider-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("SIDESTAGE_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("SIDESTAGE_MODEL_ID", "deepseek/deepseek-chat-v3.1")
    monkeypatch.setenv("SIDESTAGE_WORKFLOW_STRATEGY", "one_call_template")

    application = create_live_app(database_path=tmp_path / "openrouter.sqlite3")
    config = application.state.model_runner.config

    assert application.state.analyzer is None
    assert application.state.workflow_strategy == "one_call_template"
    assert config.api_key.get_secret_value() == "openrouter-key"
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.openrouter_routing is not None
    assert config.openrouter_routing.allow_fallbacks is False
    assert config.openrouter_routing.require_parameters is True
    assert application.state.model_runtime["provider"] == "openrouter"
    assert application.state.model_runtime["openrouter_routing"]["sort"] == "latency"
    assert "openrouter-key" not in repr(application.state.model_runtime)


def test_openrouter_provider_rejects_an_openai_key_mismatch_before_database_init(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_model_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-provider-key")
    monkeypatch.setenv("SIDESTAGE_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("SIDESTAGE_MODEL_ID", "deepseek/deepseek-chat-v3.1")
    database_path = tmp_path / "provider-mismatch.sqlite3"

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        create_live_app(database_path=database_path)

    assert not database_path.exists()


@pytest.mark.live_model
def test_live_app_factory_executes_the_real_two_call_r2_path(tmp_path: Path) -> None:
    api_key = os.environ.get("SIDESTAGE_MODEL_API_KEY") or os.environ.get(
        "OPENAI_API_KEY"
    )
    model_id = os.environ.get("SIDESTAGE_MODEL_ID")
    if not api_key or not model_id:
        pytest.skip("set a supported API key and SIDESTAGE_MODEL_ID for the live app smoke")

    application = create_live_app(database_path=tmp_path / "live-smoke.sqlite3")
    with TestClient(application) as client:
        session = client.post(
            "/api/demo/sessions",
            json={"seller_id": "sel_velocity_kicks"},
        )
        assert session.status_code == 201
        token = session.json()["session_token"]
        pushed = client.post(
            f"/api/sessions/{token}/actions/push",
            json={
                "target_listing_id": "lst_velocity_aero_dash",
                "expected_show_version": 1,
            },
            headers={"Idempotency-Key": "live-smoke-push"},
        )
        assert pushed.status_code == 200
        assert pushed.json()["receipt"]["status"] == "applied"

        answered = client.post(
            f"/api/sessions/{token}/chat/custom",
            json={"raw_text": "How much is the Aero Dash today?"},
        )
        assert answered.status_code == 201
        result = answered.json()["pipeline_results"][0]
        assert result["status"] == "completed", result
        assert result["broker_decision"]["outcome"] == "review"
        card = answered.json()["snapshot"]["copilot_questions"][0]
        assert card["state"] == "awaiting_review"
        assert card["suggestion"]["evidence_ids"]

        application.state.trace_sink.flush()
        projection = client.get(
            "/api/debug/copilot",
            params={"session_token": token, "actual_route": "eligible"},
        )
        assert projection.status_code == 200
        trace = projection.json()["traces"][0]
        assert trace["complete"] is True
        assert [stage["status"] for stage in trace["stages"]] == ["completed"] * 8
        assert trace["stages"][3]["analysis_call_id"]
        assert trace["stages"][5]["agent_run_id"]
        assert trace["stages"][5]["profile_digest"].startswith("sha256:")
        assert api_key not in json.dumps(projection.json())


@pytest.mark.live_model
def test_live_openrouter_factory_executes_one_template_call(tmp_path: Path) -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    model_id = os.environ.get("SIDESTAGE_MODEL_ID")
    if not api_key or not model_id:
        pytest.skip("set OPENROUTER_API_KEY and an exact SIDESTAGE_MODEL_ID")

    application = create_live_app(
        database_path=tmp_path / "openrouter-template-smoke.sqlite3",
        model_provider="openrouter",
        workflow_strategy="one_call_template",
    )
    with TestClient(application) as client:
        session = client.post(
            "/api/demo/sessions",
            json={"seller_id": "sel_velocity_kicks"},
        )
        token = session.json()["session_token"]
        pushed = client.post(
            f"/api/sessions/{token}/actions/push",
            json={
                "target_listing_id": "lst_velocity_aero_dash",
                "expected_show_version": 1,
            },
            headers={"Idempotency-Key": "openrouter-template-smoke-push"},
        )
        assert pushed.status_code == 200
        answered = client.post(
            f"/api/sessions/{token}/chat/custom",
            json={"raw_text": "How much is the Aero Dash today?"},
        )
        assert answered.status_code == 201

    result = answered.json()["pipeline_results"][0]
    assert result["status"] == "completed", result
    assert result["broker_decision"]["outcome"] == "review"
    assert result["broker_decision"]["template_id"] == "reply_current_price"
    assert result["latency"]["hard_timeout_outcome"] is False
