from __future__ import annotations

import asyncio
import json
import time

import pytest
from pydantic import SecretStr, ValidationError

from sidestage.agent_core import (
    AgentProfile,
    AgentProfileRegistry,
    AgentTask,
    CoreFailureCode,
    DeadlinePolicy,
    ModelRequestProjection,
    QueuePolicy,
    RunStatus,
    TerminalToolSchema,
    register_profile,
)
from sidestage.agent_core.core import StaticAgentCore
from sidestage.agent_core.model import (
    ModelInvocation,
    ModelResponse,
    ModelRunnerError,
    ModelTerminalCall,
    OpenAICompatibleModelConfig,
    OpenAICompatibleModelRunner,
    OpenRouterRoutingConfig,
    ScriptedModelRunner,
)


def make_profile() -> AgentProfile:
    return AgentProfile(
        adapter_id="generic.qa",
        profile_version="1.0.0",
        system_policy="Use the supplied evidence and choose exactly one terminal result.",
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "minLength": 1},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["prompt", "evidence"],
            "additionalProperties": False,
        },
        terminal_tools=(
            TerminalToolSchema(
                name="emit_answer",
                description="Return the answer.",
                parameters_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string", "minLength": 1}},
                    "required": ["answer"],
                    "additionalProperties": False,
                },
            ),
        ),
        queue_policy=QueuePolicy(capacity=4, max_concurrency=1),
        deadline_policy=DeadlinePolicy(default_timeout_ms=1_000, max_timeout_ms=5_000),
        model_config_ref="fast-primary-v1",
        max_model_input_bytes=4_096,
    )


def make_task(profile: AgentProfile, *, now: float, **updates: object) -> AgentTask:
    payload: dict[str, object] = {
        "task_id": "task-m3a2-1",
        "adapter_id": profile.adapter_id,
        "profile_version": profile.profile_version,
        "profile_digest": register_profile(profile).digest,
        "deadline_monotonic_s": now + 2.0,
        "model_input": {"prompt": "Answer this", "evidence": ["Fact A"]},
        "correlation_metadata": {
            "trace_id": "trace-m3a2-1",
            "authorization_version": 9,
            "oracle": {"expected": "emit_answer"},
        },
    }
    payload.update(updates)
    return AgentTask.model_validate(payload)


def success_response() -> ModelResponse:
    return ModelResponse(
        model_id="scripted-model-v1",
        terminal_calls=(
            ModelTerminalCall(
                tool_name="emit_answer",
                arguments_json='{"answer":"Fact A supports the answer"}',
            ),
        ),
    )


def make_core(profile: AgentProfile, runner, *, monotonic=time.monotonic) -> StaticAgentCore:
    identifiers = iter(("run-m3a2-1", "trace-generated-1", "run-m3a2-2", "trace-generated-2"))
    return StaticAgentCore(
        registry=AgentProfileRegistry((profile,)),
        model_runner=runner,
        monotonic=monotonic,
        id_factory=lambda: next(identifiers),
    )


def test_valid_task_makes_exactly_one_model_request() -> None:
    now = time.monotonic()
    profile = make_profile()
    runner = ScriptedModelRunner((success_response(),))
    core = make_core(profile, runner)

    result = asyncio.run(core.run(make_task(profile, now=now)))

    assert result.status is RunStatus.SUCCEEDED
    assert result.terminal_intent is not None
    assert result.terminal_intent.arguments.to_dict() == {
        "answer": "Fact A supports the answer"
    }
    assert len(runner.calls) == 1
    invocation = runner.calls[0]
    assert invocation.model_config_ref == profile.model_config_ref
    assert invocation.request.to_provider_dict() == {
        "system_policy": profile.system_policy,
        "input": {"prompt": "Answer this", "evidence": ["Fact A"]},
        "tools": [
            {
                "name": "emit_answer",
                "description": "Return the answer.",
                "parameters": profile.terminal_tools[0].parameters_schema.to_dict(),
            }
        ],
    }
    serialized = json.dumps(invocation.request.to_provider_dict(), sort_keys=True)
    assert "authorization_version" not in serialized
    assert "expected" not in serialized


def test_invalid_profile_input_and_expired_deadline_make_zero_model_requests() -> None:
    now = time.monotonic()
    profile = make_profile()
    runner = ScriptedModelRunner((success_response(),))
    core = make_core(profile, runner)

    unknown_profile_task = make_task(profile, now=now, adapter_id="unknown.adapter")
    invalid_input_task = make_task(
        profile,
        now=now,
        model_input={"prompt": 7, "evidence": []},
    )
    expired_task = make_task(profile, now=now, deadline_monotonic_s=now - 0.01)

    unknown_result = asyncio.run(core.run(unknown_profile_task))
    invalid_result = asyncio.run(core.run(invalid_input_task))
    expired_result = asyncio.run(core.run(expired_task))

    assert unknown_result.failure is not None
    assert unknown_result.failure.code is CoreFailureCode.INVALID_PROFILE
    assert invalid_result.failure is not None
    assert invalid_result.failure.code is CoreFailureCode.INVALID_TASK
    assert expired_result.failure is not None
    assert expired_result.failure.code is CoreFailureCode.INVALID_TASK
    assert runner.calls == ()


def test_provider_error_and_cancellation_are_typed_and_never_retried() -> None:
    now = time.monotonic()
    profile = make_profile()

    error_runner = ScriptedModelRunner((ModelRunnerError("secret provider detail"),))
    error_result = asyncio.run(make_core(profile, error_runner).run(make_task(profile, now=now)))
    assert error_result.failure is not None
    assert error_result.failure.code is CoreFailureCode.PROVIDER_ERROR
    assert "secret provider detail" not in error_result.failure.message
    assert len(error_runner.calls) == 1

    cancelled_runner = ScriptedModelRunner((asyncio.CancelledError(),))
    cancelled_result = asyncio.run(
        make_core(profile, cancelled_runner).run(make_task(profile, now=time.monotonic()))
    )
    assert cancelled_result.failure is not None
    assert cancelled_result.failure.code is CoreFailureCode.CANCELLED
    assert len(cancelled_runner.calls) == 1


def test_hard_timeout_cancels_provider_and_returns_no_intent() -> None:
    class NeverReturnsRunner:
        def __init__(self) -> None:
            self.calls: list[ModelInvocation] = []
            self.cancelled = False

        async def run(self, invocation: ModelInvocation) -> ModelResponse:
            self.calls.append(invocation)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            raise AssertionError("unreachable")

    now = time.monotonic()
    profile = make_profile()
    runner = NeverReturnsRunner()
    task = make_task(profile, now=now, deadline_monotonic_s=now + 0.02)

    result = asyncio.run(make_core(profile, runner).run(task))

    assert result.failure is not None
    assert result.failure.code is CoreFailureCode.HARD_TIMEOUT
    assert result.terminal_intent is None
    assert len(runner.calls) == 1
    assert runner.cancelled is True


def test_deadline_expiring_at_dispatch_starts_zero_provider_work() -> None:
    class DispatchBoundaryClock:
        def __init__(self) -> None:
            self.reads = 0

        def __call__(self) -> float:
            self.reads += 1
            if self.reads <= 3:
                return 100.0
            return 100.2

    profile = make_profile()
    clock = DispatchBoundaryClock()
    runner = ScriptedModelRunner((success_response(),))
    task = make_task(profile, now=100.0, deadline_monotonic_s=100.1)

    result = asyncio.run(make_core(profile, runner, monotonic=clock).run(task))

    assert result.failure is not None
    assert result.failure.code is CoreFailureCode.HARD_TIMEOUT
    assert runner.calls == ()


def test_late_provider_result_is_discarded_even_if_transport_returns() -> None:
    class FakeClock:
        def __init__(self) -> None:
            self.value = 100.0

        def __call__(self) -> float:
            return self.value

    class LateRunner:
        def __init__(self, clock: FakeClock) -> None:
            self.clock = clock
            self.calls: list[ModelInvocation] = []

        async def run(self, invocation: ModelInvocation) -> ModelResponse:
            self.calls.append(invocation)
            self.clock.value = 100.2
            return success_response()

    profile = make_profile()
    clock = FakeClock()
    runner = LateRunner(clock)
    task = make_task(profile, now=clock(), deadline_monotonic_s=100.1)

    result = asyncio.run(make_core(profile, runner, monotonic=clock).run(task))

    assert result.failure is not None
    assert result.failure.code is CoreFailureCode.HARD_TIMEOUT
    assert result.terminal_intent is None
    assert len(runner.calls) == 1


def test_scripted_runner_is_deterministic_and_has_no_fallback() -> None:
    profile = make_profile()
    registered = register_profile(profile)
    now = time.monotonic()
    invocation = ModelInvocation(
        model_config_ref=profile.model_config_ref,
        request=registered.project_model_request(make_task(profile, now=now), now_monotonic_s=now),
    )
    first = success_response()
    second = ModelResponse(model_id="scripted-model-v1", text="no terminal call")
    runner = ScriptedModelRunner((first, second))

    assert asyncio.run(runner.run(invocation)) == first
    assert asyncio.run(runner.run(invocation)) == second
    try:
        asyncio.run(runner.run(invocation))
    except ModelRunnerError as exc:
        assert "exhausted" in str(exc)
    else:
        raise AssertionError("scripted runner unexpectedly invented a fallback outcome")
    assert len(runner.calls) == 3


def test_openai_compatible_runner_maps_one_http_request() -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "model": "provider-model-2026-08",
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "emit_answer",
                                        "arguments": '{"answer":"Mapped result"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
            }

    class FakeHttpClient:
        def __init__(self) -> None:
            self.requests: list[dict] = []

        async def post(self, url: str, **kwargs):
            self.requests.append({"url": url, **kwargs})
            return FakeResponse()

    profile = make_profile()
    now = time.monotonic()
    registered = register_profile(profile)
    invocation = ModelInvocation(
        model_config_ref=profile.model_config_ref,
        request=registered.project_model_request(make_task(profile, now=now), now_monotonic_s=now),
    )
    client = FakeHttpClient()
    runner = OpenAICompatibleModelRunner(
        OpenAICompatibleModelConfig(
            config_ref=profile.model_config_ref,
            base_url="https://provider.invalid/v1",
            api_key=SecretStr("credential-must-not-leak"),
            model_id="provider-model-pinned",
            request_timeout_s=3.0,
            strict_function_tools=True,
            reasoning_effort="none",
            service_tier="priority",
        ),
        http_client=client,
    )

    response = asyncio.run(runner.run(invocation))

    assert response.model_id == "provider-model-2026-08"
    assert response.terminal_calls[0].tool_name == "emit_answer"
    assert len(client.requests) == 1
    request = client.requests[0]
    assert request["url"] == "https://provider.invalid/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer credential-must-not-leak"
    assert request["json"]["model"] == "provider-model-pinned"
    assert request["json"]["tool_choice"] == "required"
    assert request["json"]["parallel_tool_calls"] is False
    assert request["json"]["stream"] is False
    assert request["json"]["reasoning_effort"] == "none"
    assert request["json"]["service_tier"] == "priority"
    assert [message["role"] for message in request["json"]["messages"]] == [
        "system",
        "user",
    ]
    assert request["json"]["tools"][0]["function"]["name"] == "emit_answer"
    assert request["json"]["tools"][0]["function"]["strict"] is True
    assert request["json"]["tools"][0]["function"]["parameters"] == {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    assert profile.terminal_tools[0].parameters_schema.to_dict()["properties"][
        "answer"
    ]["minLength"] == 1
    assert request["timeout"] == 3.0
    assert "credential-must-not-leak" not in json.dumps(request["json"])


def test_openrouter_request_disables_fallbacks_and_records_sanitized_routing_metadata() -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "id": "gen-openrouter-1",
                "model": "deepseek/deepseek-chat-v3.1",
                "provider": "DeepInfra",
                "service_tier": "default",
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-openrouter-1",
                                    "type": "function",
                                    "function": {
                                        "name": "emit_answer",
                                        "arguments": '{"answer":"Routed result"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 12,
                    "total_tokens": 112,
                    "cost": 0.0012,
                    "completion_tokens_details": {"reasoning_tokens": 3},
                    "prompt_tokens_details": {"cached_tokens": 20},
                },
                "openrouter_metadata": {
                    "requested": "deepseek/deepseek-chat-v3.1",
                    "strategy": "direct",
                    "attempt": 1,
                    "attempts": [
                        {
                            "provider": "DeepInfra",
                            "model": "deepseek/deepseek-chat-v3.1",
                            "status": 200,
                            "authorization": "must-not-be-recorded",
                        }
                    ],
                },
            }

    class FakeHttpClient:
        def __init__(self) -> None:
            self.requests: list[dict] = []

        async def post(self, url: str, **kwargs):
            self.requests.append({"url": url, **kwargs})
            return FakeResponse()

    profile = make_profile()
    now = time.monotonic()
    registered = register_profile(profile)
    invocation = ModelInvocation(
        model_config_ref=profile.model_config_ref,
        request=registered.project_model_request(
            make_task(profile, now=now),
            now_monotonic_s=now,
        ),
    )
    client = FakeHttpClient()
    runner = OpenAICompatibleModelRunner(
        OpenAICompatibleModelConfig(
            config_ref=profile.model_config_ref,
            base_url="https://openrouter.ai/api/v1",
            api_key=SecretStr("openrouter-secret"),
            model_id="deepseek/deepseek-chat-v3.1",
            request_timeout_s=3.0,
            strict_function_tools=True,
            reasoning_effort="low",
            openrouter_routing=OpenRouterRoutingConfig(),
        ),
        http_client=client,
    )

    response = asyncio.run(runner.run(invocation))

    request = client.requests[0]
    assert request["headers"]["X-OpenRouter-Metadata"] == "enabled"
    assert "parallel_tool_calls" not in request["json"]
    assert "reasoning_effort" not in request["json"]
    assert request["json"]["reasoning"] == {"effort": "low"}
    assert request["json"]["provider"] == {
        "allow_fallbacks": False,
        "require_parameters": True,
        "sort": "latency",
        "data_collection": "deny",
    }
    metadata = response.provider_metadata.to_dict()
    assert metadata["requested_model_id"] == "deepseek/deepseek-chat-v3.1"
    assert metadata["resolved_model_id"] == "deepseek/deepseek-chat-v3.1"
    assert metadata["resolved_provider"] == "DeepInfra"
    assert metadata["routing_attempts"] == [
        {
            "provider": "DeepInfra",
            "model": "deepseek/deepseek-chat-v3.1",
            "status": 200,
        }
    ]
    assert metadata["usage"] == {
        "prompt_tokens": 100,
        "completion_tokens": 12,
        "total_tokens": 112,
        "cost": 0.0012,
        "reasoning_tokens": 3,
        "cached_tokens": 20,
    }
    assert "openrouter-secret" not in json.dumps(metadata)
    assert "authorization" not in json.dumps(metadata)

    with pytest.raises(ValidationError):
        OpenRouterRoutingConfig(allow_fallbacks=True)


def test_strict_provider_projection_preserves_local_only_schema_validation() -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "model": "provider-model-pinned",
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "emit_strict",
                                        "arguments": (
                                            '{"state":"certain","tags":["one"],"value":"ok"}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
            }

    class FakeHttpClient:
        def __init__(self) -> None:
            self.requests: list[dict] = []

        async def post(self, url: str, **kwargs):
            self.requests.append({"url": url, **kwargs})
            return FakeResponse()

    local_schema = {
        "type": "object",
        "properties": {
            "state": {"type": "string", "const": "certain"},
            "tags": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "value": {"type": "string", "minLength": 1, "maxLength": 8},
        },
        "required": ["state", "tags", "value"],
        "additionalProperties": False,
    }
    invocation = ModelInvocation(
        model_config_ref="strict-subset-v1",
        request=ModelRequestProjection(
            system_policy="Choose the terminal tool.",
            model_input={"prompt": "test"},
            terminal_tools=(
                TerminalToolSchema(
                    name="emit_strict",
                    description="Emit a strict payload.",
                    parameters_schema=local_schema,
                ),
            ),
        ),
    )
    client = FakeHttpClient()
    runner = OpenAICompatibleModelRunner(
        OpenAICompatibleModelConfig(
            config_ref="strict-subset-v1",
            base_url="https://provider.invalid/v1",
            api_key=SecretStr("credential-must-not-leak"),
            model_id="provider-model-pinned",
            request_timeout_s=3.0,
            strict_function_tools=True,
        ),
        http_client=client,
    )

    asyncio.run(runner.run(invocation))

    provider_schema = client.requests[0]["json"]["tools"][0]["function"][
        "parameters"
    ]
    assert provider_schema == {
        "type": "object",
        "properties": {
            "state": {"type": "string", "enum": ["certain"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "value": {"type": "string"},
        },
        "required": ["state", "tags", "value"],
        "additionalProperties": False,
    }
    assert invocation.request.terminal_tools[0].parameters_schema.to_dict() == local_schema


def test_openai_compatible_config_rejects_credentials_in_base_url() -> None:
    with pytest.raises(ValidationError, match="embedded credentials"):
        OpenAICompatibleModelConfig(
            config_ref="unsafe-config-v1",
            base_url="https://user:password@provider.invalid/v1",
            api_key=SecretStr("separate-api-key"),
            model_id="provider-model-pinned",
            request_timeout_s=3.0,
        )


def test_openai_compatible_runner_omits_unspecified_reasoning_effort() -> None:
    config = OpenAICompatibleModelConfig(
        config_ref="default-reasoning-v1",
        base_url="https://provider.invalid/v1",
        api_key=SecretStr("credential-must-not-leak"),
        model_id="provider-model-pinned",
        request_timeout_s=3.0,
    )

    assert config.reasoning_effort is None
    assert config.service_tier is None
    assert config.strict_function_tools is False


def test_openrouter_config_rejects_openai_service_tier() -> None:
    with pytest.raises(ValidationError, match="service_tier"):
        OpenAICompatibleModelConfig(
            config_ref="invalid-openrouter-priority-v1",
            base_url="https://openrouter.ai/api/v1",
            api_key=SecretStr("credential-must-not-leak"),
            model_id="google/gemini-3.7-flash",
            request_timeout_s=3.0,
            reasoning_effort="low",
            service_tier="priority",
            openrouter_routing=OpenRouterRoutingConfig(),
        )
