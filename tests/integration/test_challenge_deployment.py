from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sidestage.app import create_challenge_app
from sidestage.deployment import ChallengeUsageLimitError, ChallengeUsageLimiter
from sidestage.fixtures.loader import load_seller_fixture
from sidestage.storage.database import MarketplaceDatabase


_CHALLENGE_ENV = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "SIDESTAGE_MODEL_API_KEY",
    "SIDESTAGE_MODEL_PROVIDER",
    "SIDESTAGE_MODEL_ID",
    "SIDESTAGE_MODEL_BASE_URL",
    "SIDESTAGE_MODEL_REASONING_EFFORT",
    "SIDESTAGE_MODEL_SERVICE_TIER",
    "SIDESTAGE_WORKFLOW_STRATEGY",
    "SIDESTAGE_RUNTIME_MODEL_CATALOG_PATH",
    "SIDESTAGE_DEMO_USERNAME",
    "SIDESTAGE_DEMO_PASSWORD",
    "SIDESTAGE_DEMO_MAX_REQUESTS_PER_SESSION",
    "SIDESTAGE_DEMO_MAX_REQUESTS_PER_DAY",
    "SIDESTAGE_DATABASE_PATH",
)


def _configure_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _CHALLENGE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "deployment-key-must-never-be-reflected")
    monkeypatch.setenv("SIDESTAGE_MODEL_ID", "gpt-5.6-luna")
    monkeypatch.setenv("SIDESTAGE_MODEL_REASONING_EFFORT", "none")
    monkeypatch.setenv("SIDESTAGE_DEMO_USERNAME", "ai-fund-reviewer")
    monkeypatch.setenv("SIDESTAGE_DEMO_PASSWORD", "shared-password-must-never-be-reflected")
    monkeypatch.setenv("SIDESTAGE_DEMO_MAX_REQUESTS_PER_SESSION", "20")
    monkeypatch.setenv("SIDESTAGE_DEMO_MAX_REQUESTS_PER_DAY", "100")


def test_challenge_factory_fails_closed_for_incomplete_access_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_challenge(monkeypatch)
    monkeypatch.delenv("SIDESTAGE_DEMO_PASSWORD")

    with pytest.raises(RuntimeError, match="SIDESTAGE_DEMO_PASSWORD"):
        create_challenge_app(database_path=tmp_path / "must-not-exist.sqlite3")

    assert not (tmp_path / "must-not-exist.sqlite3").exists()


def test_challenge_factory_refuses_a_custom_openai_key_destination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_challenge(monkeypatch)
    monkeypatch.setenv("SIDESTAGE_MODEL_BASE_URL", "https://attacker.invalid/v1")

    with pytest.raises(RuntimeError, match="only sends OPENAI_API_KEY"):
        create_challenge_app(database_path=tmp_path / "must-not-exist.sqlite3")

    assert not (tmp_path / "must-not-exist.sqlite3").exists()


def test_challenge_auth_protects_static_api_debugger_and_sse_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_challenge(monkeypatch)
    application = create_challenge_app(database_path=tmp_path / "challenge.sqlite3")

    with TestClient(application) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        for path in (
            "/",
            "/app/",
            "/docs",
            "/openapi.json",
            "/api/sellers",
            "/api/debug/import-trace",
        ):
            denied = client.get(path, follow_redirects=False)
            assert denied.status_code == 401
            assert denied.headers["www-authenticate"] == 'Basic realm="SideStage challenge"'

        allowed = client.get(
            "/api/sellers",
            auth=("ai-fund-reviewer", "shared-password-must-never-be-reflected"),
        )
        assert allowed.status_code == 200
        assert len(allowed.json()["sellers"]) == 3
        assert allowed.headers["cache-control"] == "no-store"
        assert allowed.headers["x-content-type-options"] == "nosniff"
        assert allowed.headers["referrer-policy"] == "no-referrer"
        serialized = allowed.text + repr(vars(application.state))
        assert "deployment-key-must-never-be-reflected" not in serialized
        assert "shared-password-must-never-be-reflected" not in serialized

        assert client.get(
            "/docs",
            auth=("ai-fund-reviewer", "shared-password-must-never-be-reflected"),
        ).status_code == 404
        assert client.get(
            "/openapi.json",
            auth=("ai-fund-reviewer", "shared-password-must-never-be-reflected"),
        ).status_code == 404


def test_challenge_runtime_is_one_call_read_only_and_burst_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_challenge(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "supplemental-key-must-not-be-loaded")
    application = create_challenge_app(database_path=tmp_path / "challenge.sqlite3")
    assert application.state.model_runtime["mode"] == "challenge"
    assert application.state.model_runtime["provider"] == "openai"

    with TestClient(application) as client:
        client.auth = ("ai-fund-reviewer", "shared-password-must-never-be-reflected")
        created = client.post(
            "/api/demo/sessions", json={"seller_id": "sel_velocity_kicks"}
        )
        assert created.status_code == 201
        token = created.json()["session_token"]

        runtime = client.get("/api/debug/runtime", params={"session_token": token})
        assert runtime.status_code == 200
        body = runtime.json()
        assert body["runtime_mutable"] is False
        assert [item["workflow_id"] for item in body["workflows"]] == [
            "one_call_template"
        ]
        assert len(body["models"]) == 1
        assert body["models"][0]["provider"] == "openai"

        changed = client.put(
            "/api/debug/runtime",
            params={"session_token": token},
            json={
                "workflow_id": "one_call_template",
                "model_profile_id": body["active_selection"]["model_profile_id"],
                "expected_selection_version": body["active_selection"]["selection_version"],
            },
        )
        assert changed.status_code == 403
        assert changed.json()["detail"]["code"] == "challenge_runtime_read_only"

        burst = client.post(
            f"/api/sessions/{token}/chat/prepared", json={"count": 8}
        )
        assert burst.status_code == 403
        assert burst.json()["detail"]["code"] == "challenge_burst_disabled"


def test_challenge_usage_limiter_is_atomic_per_session_and_global(
    tmp_path: Path,
) -> None:
    database = MarketplaceDatabase(tmp_path / "usage.sqlite3")
    database.initialize(load_seller_fixture())
    limiter = ChallengeUsageLimiter(
        database,
        max_requests_per_session=2,
        max_requests_per_day=3,
    )
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    first = limiter.reserve("session-a", units=1, now=now)
    second = limiter.reserve("session-a", units=1, now=now)

    assert first.session_remaining == 1
    assert second.session_remaining == 0

    with pytest.raises(ChallengeUsageLimitError) as session_error:
        limiter.reserve("session-a", units=1, now=now)
    assert session_error.value.code == "session_limit_reached"

    third = limiter.reserve("session-b", units=1, now=now)
    assert third.global_remaining == 0

    with pytest.raises(ChallengeUsageLimitError) as global_error:
        limiter.reserve("session-c", units=1, now=now)
    assert global_error.value.code == "global_limit_reached"

    with database.read() as connection:
        stored = connection.execute(
            "SELECT DISTINCT session_token_digest FROM challenge_usage"
        ).fetchall()
    assert "session-a" not in {row[0] for row in stored}
    assert all(len(row[0]) == 64 for row in stored)


def test_challenge_usage_limiter_does_not_over_admit_concurrent_requests(
    tmp_path: Path,
) -> None:
    database = MarketplaceDatabase(tmp_path / "usage-concurrent.sqlite3")
    database.initialize(load_seller_fixture())
    limiter = ChallengeUsageLimiter(
        database,
        max_requests_per_session=10,
        max_requests_per_day=3,
    )
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    def attempt(index: int) -> bool:
        try:
            limiter.reserve(f"session-{index}", units=1, now=now)
        except ChallengeUsageLimitError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=10) as executor:
        admitted = list(executor.map(attempt, range(10)))

    assert admitted.count(True) == 3


def test_challenge_endpoint_rejects_before_provider_work_when_quota_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_challenge(monkeypatch)
    monkeypatch.setenv("SIDESTAGE_DEMO_MAX_REQUESTS_PER_SESSION", "0")
    monkeypatch.setenv("SIDESTAGE_DEMO_MAX_REQUESTS_PER_DAY", "0")
    application = create_challenge_app(database_path=tmp_path / "challenge.sqlite3")
    provider_called = False

    async def reject_provider_work(_invocation) -> None:
        nonlocal provider_called
        provider_called = True
        raise AssertionError("quota refusal must happen before provider work")

    monkeypatch.setattr(application.state.model_runner, "run", reject_provider_work)

    with TestClient(application) as client:
        client.auth = ("ai-fund-reviewer", "shared-password-must-never-be-reflected")
        created = client.post(
            "/api/demo/sessions", json={"seller_id": "sel_velocity_kicks"}
        )
        token = created.json()["session_token"]
        pushed = client.post(
            f"/api/sessions/{token}/actions/push",
            headers={"Idempotency-Key": "challenge-push"},
            json={
                "target_listing_id": "lst_velocity_aero_dash",
                "expected_show_version": 1,
            },
        )
        assert pushed.status_code == 200

        refused = client.post(
            f"/api/sessions/{token}/chat/custom",
            json={"raw_text": "Is US M 9 available?"},
        )
        assert refused.status_code == 429
        assert refused.json()["detail"]["code"] == "global_limit_reached"
        assert provider_called is False


def test_vercel_entrypoint_imports_with_server_only_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_challenge(monkeypatch)
    database_path = tmp_path / "vercel-preview.sqlite3"
    monkeypatch.setenv("SIDESTAGE_DATABASE_PATH", str(database_path))
    entrypoint = Path(__file__).resolve().parents[2] / "api" / "index.py"
    spec = importlib.util.spec_from_file_location("sidestage_vercel_entry", entrypoint)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with TestClient(module.app) as client:
        assert client.get("/healthz").status_code == 200
        sellers = client.get(
            "/api/sellers",
            auth=("ai-fund-reviewer", "shared-password-must-never-be-reflected"),
        )
        assert sellers.status_code == 200
        assert sellers.json()["demo_capabilities"]["challenge_mode"] is True

    assert database_path.exists()
