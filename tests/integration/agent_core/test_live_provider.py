from __future__ import annotations

import asyncio
import json
import os
import time

import pytest
from pydantic import SecretStr

from sidestage.agent_core import (
    AgentProfile,
    AgentProfileRegistry,
    AgentTask,
    DeadlinePolicy,
    QueuePolicy,
    RunStatus,
    TerminalToolSchema,
    register_profile,
)
from sidestage.agent_core.core import StaticAgentCore
from sidestage.agent_core.model import (
    OpenAICompatibleModelConfig,
    OpenAICompatibleModelRunner,
)


@pytest.mark.live_model
def test_configured_live_provider_returns_one_sanitized_terminal_outcome() -> None:
    base_url = os.environ.get("SIDESTAGE_MODEL_BASE_URL")
    api_key = os.environ.get("SIDESTAGE_MODEL_API_KEY")
    model_id = os.environ.get("SIDESTAGE_MODEL_ID")
    reasoning_effort = os.environ.get("SIDESTAGE_MODEL_REASONING_EFFORT")
    if not all((base_url, api_key, model_id)):
        pytest.skip(
            "set SIDESTAGE_MODEL_BASE_URL, SIDESTAGE_MODEL_API_KEY, and "
            "SIDESTAGE_MODEL_ID to run the live provider smoke test"
        )

    config_ref = "live-smoke-v1"
    profile = AgentProfile(
        adapter_id="generic.live_smoke",
        profile_version="1.0.0",
        system_policy=(
            "Call finish exactly once. Set answer to the lowercase word ok. "
            "Do not emit ordinary text."
        ),
        input_schema={
            "type": "object",
            "properties": {"prompt": {"type": "string"}},
            "required": ["prompt"],
            "additionalProperties": False,
        },
        terminal_tools=(
            TerminalToolSchema(
                name="finish",
                description="Finish the smoke test.",
                parameters_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string", "minLength": 1}},
                    "required": ["answer"],
                    "additionalProperties": False,
                },
            ),
        ),
        queue_policy=QueuePolicy(capacity=1, max_concurrency=1),
        deadline_policy=DeadlinePolicy(default_timeout_ms=10_000, max_timeout_ms=20_000),
        model_config_ref=config_ref,
        max_model_input_bytes=1_024,
    )
    registered = register_profile(profile)
    now = time.monotonic()
    task = AgentTask(
        task_id="live-smoke-task",
        adapter_id=profile.adapter_id,
        profile_version=profile.profile_version,
        profile_digest=registered.digest,
        deadline_monotonic_s=now + 15.0,
        model_input={"prompt": "Return the requested terminal result."},
        correlation_metadata={"trace_id": "live-smoke-trace"},
    )
    runner = OpenAICompatibleModelRunner(
        OpenAICompatibleModelConfig(
            config_ref=config_ref,
            base_url=base_url,
            api_key=SecretStr(api_key),
            model_id=model_id,
            request_timeout_s=15.0,
            reasoning_effort=reasoning_effort,
        )
    )
    identifiers = iter(("live-smoke-run", "live-smoke-generated-trace"))
    core = StaticAgentCore(
        registry=AgentProfileRegistry((profile,)),
        model_runner=runner,
        id_factory=lambda: next(identifiers),
    )

    async def run_and_close():
        try:
            return await core.run(task)
        finally:
            await runner.aclose()

    result = asyncio.run(run_and_close())

    print(
        "LIVE_SMOKE "
        + json.dumps(
            {
                "configured_model_id": model_id,
                "reported_model_id": result.model_id,
                "status": result.status.value,
                "terminal_tool": (
                    result.terminal_intent.tool_name
                    if result.terminal_intent is not None
                    else None
                ),
                "failure_code": result.failure.code.value if result.failure is not None else None,
                "latency_ms": result.latency.model_dump(),
            },
            sort_keys=True,
        )
    )

    assert result.status is RunStatus.SUCCEEDED
    assert result.terminal_intent is not None
    assert result.terminal_intent.tool_name == "finish"
    assert result.terminal_intent.arguments.to_dict()["answer"].casefold() == "ok"
    assert result.model_id
    serialized = result.model_dump_json()
    assert api_key not in serialized
    assert "effect_executed" not in serialized
